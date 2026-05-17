"""MCP stdio server exposing warehouse tools to Claude.

Register in ~/.claude/mcp.json:
  {"mcpServers": {"bike-warehouse": {
      "command": "/Users/irb/dev/bike-warehouse/.venv/bin/python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/Users/irb/dev/bike-warehouse"
  }}}
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import predict as predict_mod
from . import reports_index, warehouse
from . import summary as summary_mod

app = Server("bike-warehouse")


def _rows_to_json(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_sql",
            description=("Execute a read-only DuckDB query against the bike "
                         "warehouse. Tables: rides, streams, thresholds, "
                         "daily_load. Returns JSON rows. Use for any "
                         "aggregate/filter the other tools don't cover."),
            inputSchema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        ),
        Tool(
            name="list_rides",
            description="List rides with optional date range and min distance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "after": {"type": "string", "description": "ISO date"},
                    "before": {"type": "string", "description": "ISO date"},
                    "min_distance_km": {"type": "number"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="get_ride",
            description="Full detail for one ride by activity_id.",
            inputSchema={
                "type": "object",
                "properties": {"activity_id": {"type": "integer"}},
                "required": ["activity_id"],
            },
        ),
        Tool(
            name="compare_rides",
            description="Side-by-side comparison of multiple rides.",
            inputSchema={
                "type": "object",
                "properties": {"activity_ids": {"type": "array",
                                                "items": {"type": "integer"}}},
                "required": ["activity_ids"],
            },
        ),
        Tool(
            name="trend",
            description=("Rolling trend of a metric. metric ∈ "
                         "{hrtss, ef, decoupling_pct, avg_speed_kmh, "
                         "avg_hr, np_est_w, vam_mph}."),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "window_days": {"type": "integer", "default": 28},
                },
                "required": ["metric"],
            },
        ),
        Tool(
            name="fitness_snapshot",
            description="CTL/ATL/TSB on a date (default today).",
            inputSchema={
                "type": "object",
                "properties": {"date": {"type": "string"}},
            },
        ),
        Tool(
            name="weekly_summary",
            description="Stats + ride list for the week ending on a date.",
            inputSchema={
                "type": "object",
                "properties": {"end_date": {"type": "string"}},
            },
        ),
        Tool(
            name="predict_ride",
            description=("Predict time/HR/load for a GPX route. "
                         "pacing ∈ {endurance, tempo, threshold}."),
            inputSchema={
                "type": "object",
                "properties": {
                    "gpx_path": {"type": "string"},
                    "pacing": {"type": "string", "default": "endurance"},
                },
                "required": ["gpx_path"],
            },
        ),
        Tool(
            name="schema",
            description="Return DuckDB schema (tables + columns) for query planning.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="search_reports",
            description=("BM25 full-text search over narrative ride reports. "
                         "Use for fuzzy queries like 'rides where I felt strong "
                         "on climbs' or 'foothill long climbs'."),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    con = warehouse.connect(readonly=True)
    try:
        if name == "query_sql":
            sql = args["sql"].strip().rstrip(";")
            low = sql.lower()
            if any(k in low for k in ("insert ", "update ", "delete ", "drop ",
                                       "create ", "alter ", "attach ")):
                return [TextContent(type="text",
                                    text="error: read-only queries only")]
            rows = _rows_to_json(con, sql)
            return [TextContent(type="text",
                                text=json.dumps(rows, indent=2, default=str))]
        if name == "list_rides":
            where = ["1=1"]
            p = []
            if args.get("after"):
                where.append("CAST(start_date_local AS DATE) >= ?")
                p.append(args["after"])
            if args.get("before"):
                where.append("CAST(start_date_local AS DATE) <= ?")
                p.append(args["before"])
            if args.get("min_distance_km"):
                where.append("distance_km >= ?")
                p.append(args["min_distance_km"])
            limit = args.get("limit", 50)
            sql = f"""SELECT activity_id, name, start_date_local, distance_km,
                             elev_gain_m, avg_hr, hrtss, decoupling_pct
                      FROM rides
                      WHERE {' AND '.join(where)}
                      ORDER BY start_date_local DESC
                      LIMIT {int(limit)}"""
            return [TextContent(type="text",
                                text=json.dumps(_rows_to_json(con, sql, p),
                                                indent=2, default=str))]
        if name == "get_ride":
            rows = _rows_to_json(con,
                "SELECT * FROM rides WHERE activity_id = ?",
                [args["activity_id"]])
            return [TextContent(type="text",
                                text=json.dumps(rows, indent=2, default=str))]
        if name == "compare_rides":
            ids = args["activity_ids"]
            ph = ",".join(["?"] * len(ids))
            rows = _rows_to_json(con,
                f"SELECT * FROM rides WHERE activity_id IN ({ph})", ids)
            return [TextContent(type="text",
                                text=json.dumps(rows, indent=2, default=str))]
        if name == "trend":
            metric = args["metric"]
            allowed = {"hrtss", "ef", "decoupling_pct", "avg_speed_kmh",
                       "avg_hr", "np_est_w", "vam_mph", "avg_watts_est"}
            if metric not in allowed:
                return [TextContent(type="text",
                                    text=f"error: metric must be one of {allowed}")]
            w = args.get("window_days", 28)
            sql = f"""
                SELECT CAST(start_date_local AS DATE) AS d, {metric} AS val,
                       avg({metric}) OVER (ORDER BY start_date_local
                            RANGE BETWEEN INTERVAL {int(w)} DAY PRECEDING
                            AND CURRENT ROW) AS rolling
                FROM rides
                WHERE {metric} IS NOT NULL
                ORDER BY start_date_local
            """
            return [TextContent(type="text",
                                text=json.dumps(_rows_to_json(con, sql),
                                                indent=2, default=str))]
        if name == "fitness_snapshot":
            d = args.get("date") or str(date.today())
            rows = _rows_to_json(con,
                "SELECT * FROM daily_load WHERE date = ?", [d])
            return [TextContent(type="text",
                                text=json.dumps(rows, indent=2, default=str))]
        if name == "weekly_summary":
            end = (date.fromisoformat(args["end_date"])
                   if args.get("end_date") else date.today())
            s = summary_mod.weekly(end)
            return [TextContent(type="text",
                                text=json.dumps(s, indent=2, default=str))]
        if name == "predict_ride":
            res = predict_mod.predict(args["gpx_path"],
                                      args.get("pacing", "endurance"))
            return [TextContent(type="text",
                                text=json.dumps(res, indent=2, default=str))]
        if name == "search_reports":
            rows = reports_index.search(args["query"], args.get("limit", 10))
            return [TextContent(type="text",
                                text=json.dumps(rows, indent=2, default=str))]
        if name == "schema":
            tables = _rows_to_json(con, """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_catalog = current_database()
                  AND table_schema = 'main'
                ORDER BY table_name, ordinal_position
            """)
            return [TextContent(type="text",
                                text=json.dumps(tables, indent=2))]
        return [TextContent(type="text", text=f"unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"error: {e}")]
    finally:
        con.close()


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
