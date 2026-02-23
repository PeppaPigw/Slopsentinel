from __future__ import annotations

from pathlib import Path

from slopsentinel.audit import audit_path


def test_audit_parallel_matches_serial(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.slopsentinel]",
                'languages = ["python"]',
                "",
                "[tool.slopsentinel.rules]",
                'enable = ["A03", "C03", "C07"]',
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    content = "\n".join(
        [
            "# We need to ensure this is closed",
            "import slopsentinel_nonexistent_pkg_12345",
            'print("DEBUG: hello")',
            "",
        ]
    )

    for name in ("alpha.py", "beta.py", "gamma.py", "delta.py"):
        (src / name).write_text(content, encoding="utf-8")

    monkeypatch.setenv("SLOPSENTINEL_WORKERS", "1")
    serial = audit_path(tmp_path)

    monkeypatch.setenv("SLOPSENTINEL_WORKERS", "4")
    parallel = audit_path(tmp_path)

    assert serial.summary == parallel.summary

