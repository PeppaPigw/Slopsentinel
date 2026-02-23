from __future__ import annotations

import json
from pathlib import Path

from slopsentinel.audit import audit_path
from slopsentinel.engine.types import DimensionBreakdown
from slopsentinel.history import (
    HistoryEntry,
    append_history,
    load_history,
    render_trend_html,
    render_trend_json,
    render_trend_terminal,
    save_history,
)


def test_load_history_missing_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    assert load_history(path) == []


def test_append_history_writes_and_trims(tmp_path: Path) -> None:
    path = tmp_path / ".slopsentinel" / "history.json"

    entry = HistoryEntry(
        timestamp="2026-02-21T00:00:00+00:00",
        score=100,
        files_scanned=1,
        violations=0,
        breakdown=DimensionBreakdown(
            fingerprint=35,
            quality=25,
            hallucination=20,
            maintainability=15,
            security=5,
        ),
        dominant_fingerprints=(),
        git_head=None,
    )

    for _ in range(5):
        append_history(path, entry, max_entries=2)

    entries = load_history(path)
    assert len(entries) == 2

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert isinstance(raw["entries"], list)


def test_render_trend_terminal_includes_delta(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    entries = [
        HistoryEntry(
            timestamp="2026-02-21T00:00:00+00:00",
            score=90,
            files_scanned=1,
            violations=1,
            breakdown=DimensionBreakdown(fingerprint=35, quality=25, hallucination=20, maintainability=15, security=5),
            dominant_fingerprints=(),
            git_head=None,
        ),
        HistoryEntry(
            timestamp="2026-02-21T00:10:00+00:00",
            score=95,
            files_scanned=1,
            violations=0,
            breakdown=DimensionBreakdown(fingerprint=35, quality=25, hallucination=20, maintainability=15, security=5),
            dominant_fingerprints=(),
            git_head=None,
        ),
    ]
    save_history(path, entries)

    rendered = render_trend_terminal(load_history(path), last=10)
    assert "Trend: +5" in rendered


def test_render_trend_json_is_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    entries = [
        HistoryEntry(
            timestamp="2026-02-21T00:00:00+00:00",
            score=90,
            files_scanned=1,
            violations=1,
            breakdown=DimensionBreakdown(fingerprint=35, quality=25, hallucination=20, maintainability=15, security=5),
            dominant_fingerprints=(),
            git_head=None,
        )
    ]
    save_history(path, entries)
    payload = json.loads(render_trend_json(load_history(path), last=10))
    assert payload["version"] == 1
    assert isinstance(payload["entries"], list)


def test_render_trend_html_contains_svg(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    entries = [
        HistoryEntry(
            timestamp="2026-02-21T00:00:00+00:00",
            score=90,
            files_scanned=1,
            violations=1,
            breakdown=DimensionBreakdown(fingerprint=35, quality=25, hallucination=20, maintainability=15, security=5),
            dominant_fingerprints=(),
            git_head=None,
        )
    ]
    save_history(path, entries)
    html_text = render_trend_html(load_history(path), last=10)
    assert "<svg" in html_text


def test_audit_records_history_when_enabled(tmp_path: Path, monkeypatch) -> None:
    # Avoid picking up user env worker count, keep deterministic.
    monkeypatch.delenv("SLOPSENTINEL_WORKERS", raising=False)

    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.slopsentinel]",
                'languages = ["python"]',
                "",
                "[tool.slopsentinel.rules]",
                'enable = ["A03"]',
                "",
                "[tool.slopsentinel.history]",
                "enabled = true",
                'path = ".slopsentinel/history.json"',
                "max-entries = 50",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.py").write_text("# We need to ensure this is closed\nx = 1\n", encoding="utf-8")

    audit_path(tmp_path)
    history_path = tmp_path / ".slopsentinel" / "history.json"
    assert history_path.exists()
    assert len(load_history(history_path)) == 1

    audit_path(tmp_path)
    assert len(load_history(history_path)) == 2
