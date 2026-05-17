"""Index narrative ride reports for BM25 search.

Source: bike-report/reports/<slug>/report.md + metrics.json
Target: DuckDB table `reports` + FTS index.

Why BM25 not embeddings: short, keyword-rich text; deterministic; no torch.
Upgrade path: drop in DuckDB vss extension + sentence-transformers later.
"""
from __future__ import annotations

import re

import duckdb

from . import config as C
from . import warehouse

BIKE_REPORT_REPORTS = C.ROOT.parent / "bike-report" / "reports"

ACTIVITY_ID_RE = re.compile(r"_(\d{6,})$")


def _ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("INSTALL fts")
    con.execute("LOAD fts")
    con.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            activity_id BIGINT,
            slug        VARCHAR,
            ride_date   TIMESTAMP,
            title       VARCHAR,
            body        TEXT,
            path        VARCHAR,
            indexed_at  TIMESTAMP DEFAULT now()
        )
    """)


def _activity_id_from_slug(slug: str) -> int | None:
    m = ACTIVITY_ID_RE.search(slug)
    return int(m.group(1)) if m else None


def _date_from_slug(slug: str) -> str | None:
    # e.g. 20260508_1502_18426827907
    m = re.match(r"(\d{8})_(\d{4})", slug)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:]}:00"


def collect_reports() -> list[dict]:
    out = []
    if not BIKE_REPORT_REPORTS.exists():
        return out
    for d in sorted(BIKE_REPORT_REPORTS.iterdir()):
        md = d / "report.md"
        if not md.exists():
            continue
        body = md.read_text(errors="ignore")
        # First non-empty heading line as title
        title = next((l.lstrip("# ").strip()
                      for l in body.splitlines() if l.startswith("#")),
                     d.name)
        aid = _activity_id_from_slug(d.name)
        ride_date = _date_from_slug(d.name)
        out.append({
            "activity_id": aid,
            "slug": d.name,
            "ride_date": ride_date,
            "title": title,
            "body": body,
            "path": str(md),
        })
    return out


def build_index() -> int:
    con = warehouse.connect()
    _ensure_table(con)
    reports = collect_reports()
    con.execute("DELETE FROM reports")
    for r in reports:
        con.execute("""
            INSERT INTO reports (activity_id, slug, ride_date, title, body, path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [r["activity_id"], r["slug"], r["ride_date"],
              r["title"], r["body"], r["path"]])
    # (Re)build FTS over body+title
    con.execute("PRAGMA drop_fts_index('reports')") if _has_fts_index(con) else None
    con.execute("""
        PRAGMA create_fts_index('reports', 'slug', 'title', 'body',
                                stemmer='english', stopwords='english',
                                ignore='(\\.|[^a-z0-9])+',
                                strip_accents=1, lower=1, overwrite=1)
    """)
    con.close()
    return len(reports)


def _has_fts_index(con) -> bool:
    try:
        con.execute("SELECT 1 FROM fts_main_reports.terms LIMIT 1")
        return True
    except Exception:
        return False


def search(query: str, limit: int = 10) -> list[dict]:
    con = warehouse.connect(readonly=True)
    con.execute("LOAD fts")
    rows = con.execute(f"""
        WITH scored AS (
            SELECT *, fts_main_reports.match_bm25(slug, ?) AS score
            FROM reports
        )
        SELECT activity_id, slug, ride_date, title, score,
               substring(body, 1, 400) AS preview, path
        FROM scored
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT {int(limit)}
    """, [query]).fetchall()
    con.close()
    cols = ["activity_id", "slug", "ride_date", "title", "score", "preview", "path"]
    return [dict(zip(cols, r)) for r in rows]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        n = build_index()
        print(f"indexed {n} reports")
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        for r in search(" ".join(sys.argv[2:])):
            print(f"{r['score']:.2f}  {r['ride_date']}  {r['title']}")
            print(f"    {r['preview'][:120]}...")
    else:
        print("usage: reports_index {build|search <query>}")
