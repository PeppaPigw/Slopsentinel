from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import pytest

from slopsentinel.engine.types import Location, Violation
from slopsentinel.lsp import (
    _find_violation_at_position,
    _full_document_edit,
    _hover_for_violation,
    _range_for_violation,
    _read_lsp_message,
    run_stdio_server,
    uri_to_path,
    violations_to_diagnostics,
)


def _frame(payload: dict[str, object]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class _DummyStdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = BytesIO(data)


class _DummyStdout:
    def __init__(self) -> None:
        self.buffer = BytesIO()


def _unframe_all(data: bytes) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    cursor = 0
    while cursor < len(data):
        header_end = data.find(b"\r\n\r\n", cursor)
        if header_end == -1:
            break
        header = data[cursor:header_end].decode("ascii", errors="replace")
        length = None
        for line in header.splitlines():
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = None
                break
        if length is None:
            break
        body_start = header_end + 4
        body_end = body_start + length
        if body_end > len(data):
            break
        payload = json.loads(data[body_start:body_end].decode("utf-8", errors="replace"))
        if isinstance(payload, dict):
            out.append(payload)
        cursor = body_end
    return out


def test_read_lsp_message_returns_none_on_eof(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b""))
    assert _read_lsp_message() is None


def test_read_lsp_message_handles_missing_length_and_invalid_json(monkeypatch) -> None:
    # Missing Content-Length.
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b"X: 1\r\n\r\n{}"))
    assert _read_lsp_message() is None

    # Invalid Content-Length.
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b"Content-Length: nope\r\n\r\n{}"))
    assert _read_lsp_message() is None

    # Invalid JSON.
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b"Content-Length: 1\r\n\r\n{"))
    assert _read_lsp_message() is None

    # Non-dict JSON payload.
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b"Content-Length: 2\r\n\r\n[]"))
    assert _read_lsp_message() is None


def test_uri_to_path_rejects_non_file_scheme() -> None:
    with pytest.raises(ValueError):
        uri_to_path("http://example.com/x.py")


def test_violations_to_diagnostics_covers_severity_and_end_col_fallback(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    text = "x = 1\n"
    violations = [
        Violation(rule_id="E01", severity="error", message="e", dimension="quality", location=Location(path=path, start_line=1, start_col=1)),
        Violation(rule_id="E02", severity="warn", message="w", dimension="quality", location=Location(path=path, start_line=1, start_col=1)),
        Violation(rule_id="E03", severity="info", message="i", dimension="quality", location=Location(path=path, start_line=1, start_col=1)),
        Violation(rule_id="E04", severity="warn", message="skip", dimension="quality", location=None),
        # start_line out of bounds triggers end_col = col0 + 1 path.
        Violation(rule_id="E05", severity="warn", message="oob", dimension="quality", location=Location(path=path, start_line=99, start_col=5)),
    ]

    diags = violations_to_diagnostics(violations, text=text)
    assert {d["code"] for d in diags} == {"E01", "E02", "E03", "E05"}

    sev_by_code = {d["code"]: d["severity"] for d in diags}
    assert sev_by_code["E01"] == 1
    assert sev_by_code["E02"] == 2
    assert sev_by_code["E03"] == 3
    assert diags[-1]["range"]["end"]["character"] == 5  # start_col=5 -> col0=4 -> end=5


def test_find_violation_prefers_smallest_enclosing_range(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    text = "abcdef\n"
    big = Violation(
        rule_id="A03",
        severity="info",
        message="big",
        dimension="fingerprint",
        location=Location(path=path, start_line=1, start_col=1, end_line=1, end_col=7),
    )
    small = Violation(
        rule_id="E11",
        severity="warn",
        message="small",
        dimension="quality",
        location=Location(path=path, start_line=1, start_col=2, end_line=1, end_col=3),
    )
    picked = _find_violation_at_position([big, small], text=text, line0=0, character0=1)
    assert picked is small

    # Out-of-range position -> no match.
    assert _find_violation_at_position([big], text=text, line0=10, character0=0) is None


def test_hover_for_violation_returns_none_when_meta_missing(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    v = Violation(rule_id="ZZZ", severity="info", message="x", dimension="quality", location=Location(path=path, start_line=1, start_col=1))
    assert _hover_for_violation(v) is None


def test_full_document_edit_end_line_counts_lines() -> None:
    edit = _full_document_edit("file:///tmp/x.py", old_text="a\nb\nc\n", new_text="new\n")
    change = edit["changes"]["file:///tmp/x.py"][0]
    assert change["range"]["end"]["line"] == 3


def test_range_for_violation_returns_none_when_location_missing(tmp_path: Path) -> None:
    v = Violation(rule_id="A03", severity="info", message="x", dimension="fingerprint", location=None)
    assert _range_for_violation(v, text="x") is None


def test_stdio_server_exercises_more_branches(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.slopsentinel]\n", encoding="utf-8")

    doc_path = tmp_path / "example.py"
    doc_path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    doc_uri = doc_path.as_uri()

    bad_uri = "http://example.com/nope.py"

    stream = b"".join(
        [
            # initialize via workspaceFolders path (not rootUri/rootPath)
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"workspaceFolders": [{"path": str(tmp_path)}]}}),
            # didOpen with bad uri scheme -> ignored
            _frame({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": bad_uri, "text": "x=1\n"}}}),
            # didChange before didOpen should create a document.
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {"textDocument": {"uri": doc_uri}, "contentChanges": [{"text": "# We need to ensure this is safe\nx = 1\n"}]},
                }
            ),
            # hover with invalid position payload -> null result
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/hover",
                    "params": {"textDocument": {"uri": doc_uri}, "position": {"line": "0", "character": 0}},
                }
            ),
            # didSave for unknown uri -> ignored
            _frame({"jsonrpc": "2.0", "method": "textDocument/didSave", "params": {"textDocument": {"uri": (tmp_path / 'missing.py').as_uri()}}}),
            _frame({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )

    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdin", _DummyStdin(stream))
    monkeypatch.setattr(sys, "stdout", out)

    run_stdio_server()

    messages = _unframe_all(out.buffer.getvalue())
    assert any(m.get("method") == "textDocument/publishDiagnostics" for m in messages)
    hover = next(m for m in messages if m.get("id") == 2)
    assert hover.get("result") is None


def test_stdio_server_returns_cleanly_when_no_messages(monkeypatch) -> None:
    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdin", _DummyStdin(b""))
    monkeypatch.setattr(sys, "stdout", out)
    run_stdio_server()
    assert out.buffer.getvalue() == b""

