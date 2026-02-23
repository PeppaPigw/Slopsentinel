from __future__ import annotations

from pathlib import Path

from slopsentinel.action_sarif import _maybe_write_sarif
from slopsentinel.engine.types import DimensionBreakdown, ScanSummary


def _summary() -> ScanSummary:
    return ScanSummary(
        files_scanned=1,
        violations=(),
        score=100,
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
    )


def test_maybe_write_sarif_disabled_returns_none(tmp_path: Path) -> None:
    out = _maybe_write_sarif(
        enabled=False,
        sarif_path_spec="slopsentinel.sarif",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert out is None


def test_maybe_write_sarif_writes_inside_workspace(tmp_path: Path) -> None:
    rel = _maybe_write_sarif(
        enabled=True,
        sarif_path_spec="reports/result.sarif",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert rel == "reports/result.sarif"
    assert (tmp_path / "reports" / "result.sarif").exists()


def test_maybe_write_sarif_defaults_when_path_empty(tmp_path: Path) -> None:
    rel = _maybe_write_sarif(
        enabled=True,
        sarif_path_spec="",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert rel == "slopsentinel.sarif"
    assert (tmp_path / "slopsentinel.sarif").exists()


def test_maybe_write_sarif_refuses_outside_workspace(tmp_path: Path) -> None:
    out = _maybe_write_sarif(
        enabled=True,
        sarif_path_spec="../escape.sarif",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert out is None
    assert not (tmp_path.parent / "escape.sarif").exists()


def test_maybe_write_sarif_handles_resolve_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    def boom(self: Path) -> Path:  # noqa: ARG001
        raise OSError("boom")

    monkeypatch.setattr(Path, "resolve", boom)

    out = _maybe_write_sarif(
        enabled=True,
        sarif_path_spec="reports/result.sarif",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert out is None
    assert "Failed to resolve SARIF path" in capsys.readouterr().err


def test_maybe_write_sarif_handles_write_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    original = Path.write_text

    def boom(self: Path, *args, **kwargs):  # noqa: ANN001
        if self.name.endswith(".sarif"):
            raise OSError("boom")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)

    out = _maybe_write_sarif(
        enabled=True,
        sarif_path_spec="reports/result.sarif",
        summary=_summary(),
        project_root=tmp_path,
        workspace=tmp_path,
    )
    assert out is None
    assert "Failed to write SARIF report" in capsys.readouterr().err
