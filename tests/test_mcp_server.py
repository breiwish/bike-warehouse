"""End-to-end MCP server tool calls against synthetic warehouse."""
import asyncio
import json


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_list_tools(synth_warehouse):
    from src import mcp_server as M
    tools = _run(M.list_tools())
    names = {t.name for t in tools}
    assert {"query_sql", "list_rides", "get_ride", "trend",
            "fitness_snapshot", "weekly_summary", "predict_ride",
            "search_reports", "schema", "compare_rides"} <= names


def test_list_rides_returns_synth(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("list_rides", {"limit": 5}))
    rows = json.loads(out[0].text)
    assert len(rows) >= 1
    assert rows[0]["activity_id"] == 42


def test_query_sql_read_only(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("query_sql", {"sql": "SELECT count(*) AS n FROM rides"}))
    rows = json.loads(out[0].text)
    assert rows[0]["n"] >= 1


def test_query_sql_blocks_writes(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("query_sql",
                            {"sql": "DELETE FROM rides"}))
    assert "read-only" in out[0].text.lower()


def test_trend_rejects_unknown_metric(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("trend", {"metric": "made_up_metric"}))
    assert "error" in out[0].text.lower()


def test_trend_returns_rolling(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("trend", {"metric": "hrtss", "window_days": 7}))
    rows = json.loads(out[0].text)
    assert all("rolling" in r for r in rows)


def test_get_ride(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("get_ride", {"activity_id": 42}))
    rows = json.loads(out[0].text)
    assert rows[0]["activity_id"] == 42


def test_fitness_snapshot_today_has_row(synth_warehouse):
    from src import mcp_server as M
    out = _run(M.call_tool("fitness_snapshot", {}))
    rows = json.loads(out[0].text)
    assert len(rows) == 1
    assert "ctl" in rows[0]
