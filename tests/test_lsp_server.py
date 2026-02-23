from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from slopsentinel.lsp import _read_lsp_message, _send_lsp_message, run_stdio_server


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


def test_read_lsp_message_parses_framed_json(monkeypatch) -> None:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootPath": "/tmp"}}
    monkeypatch.setattr(sys, "stdin", _DummyStdin(_frame(msg)))
    parsed = _read_lsp_message()
    assert parsed is not None
    assert parsed.get("method") == "initialize"
    assert parsed.get("id") == 1


def test_send_lsp_message_writes_content_length(monkeypatch) -> None:
    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", out)
    _send_lsp_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    raw = out.buffer.getvalue()
    assert raw.startswith(b"Content-Length: ")
    assert b"\r\n\r\n" in raw
    assert b"\"ok\":true" in raw.lower()


def test_stdio_server_initialize_and_diagnostics(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
plugins = ["this_plugin_does_not_exist"]
""".lstrip(),
        encoding="utf-8",
    )

    doc_path = tmp_path / "src" / "example.py"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("x = 1\n", encoding="utf-8")

    root_uri = tmp_path.as_uri()
    doc_uri = doc_path.as_uri()

    stream = b"".join(
        [
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootUri": root_uri}}),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {"textDocument": {"uri": doc_uri, "text": "# We need to ensure this is safe\nx = 1\n"}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": doc_uri},
                        "contentChanges": [{"text": "# We need to ensure this is still safe\nx = 1\n"}],
                    },
                }
            ),
            _frame({"jsonrpc": "2.0", "method": "textDocument/didSave", "params": {"textDocument": {"uri": doc_uri}}}),
            _frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )

    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdin", _DummyStdin(stream))
    monkeypatch.setattr(sys, "stdout", out)

    run_stdio_server()

    raw = out.buffer.getvalue()
    assert b"publishDiagnostics" in raw
    assert b"A03" in raw
    assert doc_uri.encode("utf-8") in raw


def test_stdio_server_hover_and_code_action(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.slopsentinel]\n", encoding="utf-8")

    doc_path = tmp_path / "example.py"
    doc_path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    root_uri = tmp_path.as_uri()
    doc_uri = doc_path.as_uri()

    stream = b"".join(
        [
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootUri": root_uri}}),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {"textDocument": {"uri": doc_uri, "text": "# We need to ensure this is safe\nx = 1\n"}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "textDocument/hover",
                    "params": {"textDocument": {"uri": doc_uri}, "position": {"line": 0, "character": 2}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "textDocument/codeAction",
                    "params": {
                        "textDocument": {"uri": doc_uri},
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                        "context": {"diagnostics": [{"code": "A03"}]},
                    },
                }
            ),
            _frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )

    out = _DummyStdout()
    monkeypatch.setattr(sys, "stdin", _DummyStdin(stream))
    monkeypatch.setattr(sys, "stdout", out)

    run_stdio_server()

    messages = _unframe_all(out.buffer.getvalue())
    init_res = next(m for m in messages if m.get("id") == 1)
    caps = init_res.get("result", {}).get("capabilities", {})
    assert caps.get("hoverProvider") is True
    assert caps.get("codeActionProvider") is True

    hover_res = next(m for m in messages if m.get("id") == 3)
    hover = hover_res.get("result")
    assert isinstance(hover, dict)
    contents = hover.get("contents", {})
    assert isinstance(contents, dict)
    assert "A03" in str(contents.get("value", ""))

    ca_res = next(m for m in messages if m.get("id") == 4)
    actions = ca_res.get("result")
    assert isinstance(actions, list)
    assert any(isinstance(a, dict) and a.get("kind") == "quickfix" for a in actions)
    quickfix = next(a for a in actions if isinstance(a, dict) and a.get("kind") == "quickfix")
    new_text = (
        quickfix.get("edit", {})
        .get("changes", {})
        .get(doc_uri, [{}])[0]
        .get("newText", "")
    )
    assert "We need to ensure" not in new_text
    assert "x = 1" in new_text
