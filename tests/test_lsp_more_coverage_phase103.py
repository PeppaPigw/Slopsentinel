from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from slopsentinel.engine.types import Location, Violation
from slopsentinel.lsp import (
    _collect_violations,
    _find_violation_at_position,
    _range_for_violation,
    _read_lsp_message,
    run_stdio_server,
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


def test_read_lsp_message_skips_blank_and_malformed_header_lines(monkeypatch) -> None:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    body = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    stream = b"".join(
        [
            b" \r\n",  # whitespace-only header line (ignored)
            b"NoColon\r\n",  # invalid header line (ignored)
            f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"),
            body,
        ]
    )
    monkeypatch.setattr(sys, "stdin", _DummyStdin(stream))
    parsed = _read_lsp_message()
    assert parsed is not None
    assert parsed.get("method") == "initialize"


def test_violations_to_diagnostics_uses_explicit_end_range(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    v = Violation(
        rule_id="E11",
        severity="warn",
        message="x",
        dimension="quality",
        location=Location(path=path, start_line=1, start_col=2, end_line=1, end_col=4),
    )
    diags = violations_to_diagnostics([v], text="abcd\n")
    assert diags[0]["range"]["end"]["character"] == 3  # end_col=4 => 0-based 3


def test_range_for_violation_out_of_bounds_uses_character_fallback(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    v = Violation(rule_id="A03", severity="warn", message="x", dimension="quality", location=Location(path=path, start_line=99, start_col=5))
    rng = _range_for_violation(v, text="x\n")
    assert rng is not None
    assert rng["end"]["character"] == 5  # col0=4 -> fallback end=5


def test_find_violation_at_position_skips_violations_with_no_range(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    good = Violation(rule_id="E11", severity="warn", message="x", dimension="quality", location=Location(path=path, start_line=1, start_col=1))
    bad = Violation(rule_id="E11", severity="warn", message="x", dimension="quality", location=None)
    picked = _find_violation_at_position([bad, good], text="x\n", line0=0, character0=0)
    assert picked is good


def test_collect_violations_returns_empty_for_unknown_language(tmp_path: Path) -> None:
    from slopsentinel.lsp import _Document

    unknown_path = tmp_path / "x.unknown"
    doc = _Document(uri=unknown_path.as_uri(), path=unknown_path, text="x = 1\n")
    assert _collect_violations(doc, project_root=tmp_path) == []


def test_stdio_server_covers_additional_error_branches(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.slopsentinel]\n", encoding="utf-8")

    doc_path = tmp_path / "example.py"
    doc_path.write_text("x = 1\n", encoding="utf-8")
    doc_uri = doc_path.as_uri()

    stream = b"".join(
        [
            # initialize with no root info -> defaults to cwd
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            # hover for unopened doc -> null result
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/hover",
                    "params": {"textDocument": {"uri": doc_uri}, "position": {"line": 0, "character": 0}},
                }
            ),
            # codeAction with invalid diagnostics payload -> empty actions
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "textDocument/codeAction",
                    "params": {"textDocument": {"uri": doc_uri}, "context": {"diagnostics": {}}},
                }
            ),
            # didOpen invalid payload -> ignored
            _frame({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": 123, "text": "x\n"}}}),
            # didChange empty changes -> ignored
            _frame({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {"textDocument": {"uri": doc_uri}, "contentChanges": []}}),
            # didChange non-str change text -> ignored
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {"textDocument": {"uri": doc_uri}, "contentChanges": [{"text": 123}]} ,
                }
            ),
            # didChange with bad scheme triggers uri_to_path ValueError -> ignored
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {"textDocument": {"uri": "http://example.com/nope.py"}, "contentChanges": [{"text": "x\n"}]},
                }
            ),
            # didSave with non-str uri -> ignored
            _frame({"jsonrpc": "2.0", "method": "textDocument/didSave", "params": {"textDocument": {"uri": None}}}),
            _frame({"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )

    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdin", _DummyStdin(stream))
    monkeypatch.setattr(sys, "stdout", out)

    run_stdio_server()

    messages = _unframe_all(out.buffer.getvalue())
    assert any(m.get("id") == 1 for m in messages)
    assert next(m for m in messages if m.get("id") == 2).get("result") is None
    assert next(m for m in messages if m.get("id") == 3).get("result") == []
