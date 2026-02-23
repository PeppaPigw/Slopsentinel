from __future__ import annotations

import json
from pathlib import Path

from slopsentinel.engine.types import DimensionBreakdown
from slopsentinel.history import HistoryEntry, load_history, render_trend_html


def _entry(*, score: int, ts: str = "2026-02-21T00:00:00+00:00") -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts,
        score=score,
        files_scanned=1,
        violations=0,
        breakdown=DimensionBreakdown(fingerprint=35, quality=25, hallucination=20, maintainability=15, security=5),
        dominant_fingerprints=(),
        git_head=None,
    )


def test_load_history_returns_empty_for_invalid_shapes(tmp_path: Path) -> None:
    path = tmp_path / "history.json"

    # Invalid JSON.
    path.write_text("{", encoding="utf-8")
    assert load_history(path) == []

    # Wrong top-level type.
    path.write_text("[]", encoding="utf-8")
    assert load_history(path) == []

    # Wrong version.
    path.write_text(json.dumps({"version": 999, "entries": []}), encoding="utf-8")
    assert load_history(path) == []

    # Entries not a list.
    path.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
    assert load_history(path) == []


def test_load_history_skips_bad_entries_and_parses_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    payload = {
        "version": 1,
        "entries": [
            123,
            # breakdown isn't a dict -> _parse_entry raises -> skipped.
            {"timestamp": "t", "score": 1, "files_scanned": 1, "violations": 0, "breakdown": []},
            {
                "timestamp": "t",
                "score": 90,
                "files_scanned": 1,
                "violations": 0,
                "breakdown": {"fingerprint": 1, "quality": 1, "hallucination": 1, "maintainability": 1, "security": 1},
                "ai_confidence": 123,
                "violation_density": "nope",
                "violation_clustering": [],
                "git_head": 456,
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    entries = load_history(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.ai_confidence is None
    assert e.violation_density is None
    assert e.violation_clustering is None
    assert e.git_head is None


def test_render_trend_html_renders_polyline_with_two_entries() -> None:
    html_text = render_trend_html([_entry(score=90), _entry(score=95, ts="2026-02-21T00:10:00+00:00")], last=10)
    assert "<svg" in html_text
    assert "<polyline" in html_text

