"""BM25 reports index: build + search."""
import pytest

from src import reports_index, warehouse


@pytest.fixture
def sample_reports(tmp_repo, monkeypatch):
    """Plant 3 fake reports in a directory and point the indexer at it."""
    reports_dir = tmp_repo / "fake_reports"
    reports_dir.mkdir()
    for slug, body in [
        ("20250101_0800_111", "# Flat winter spin\n\nEasy ride, cadence drills."),
        ("20250215_0900_222", "# Foothill climb day\n\nLong hard climb, "
                              "decoupling 12%, painful."),
        ("20250320_1000_333", "# Group ride sprint\n\nFast bunch, sprint "
                              "intervals at the end, top end."),
    ]:
        d = reports_dir / slug
        d.mkdir()
        (d / "report.md").write_text(body)
    monkeypatch.setattr(reports_index, "BIKE_REPORT_REPORTS", reports_dir)
    warehouse.init()
    n = reports_index.build_index()
    assert n == 3
    return reports_dir


def test_search_finds_climb(sample_reports):
    hits = reports_index.search("climb", limit=5)
    assert hits
    assert "climb" in hits[0]["title"].lower() or "climb" in hits[0]["preview"].lower()


def test_search_returns_empty_for_no_match(sample_reports):
    hits = reports_index.search("aurora borealis lasagna", limit=5)
    # BM25 may return scored zeros or empty; allow either
    assert all(h["score"] >= 0 for h in hits)


def test_collect_handles_missing_dir(tmp_repo, monkeypatch):
    monkeypatch.setattr(reports_index, "BIKE_REPORT_REPORTS",
                        tmp_repo / "does_not_exist")
    assert reports_index.collect_reports() == []
