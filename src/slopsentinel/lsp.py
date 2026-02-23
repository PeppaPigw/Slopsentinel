from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from slopsentinel.autofix import apply_fixes, supported_rule_ids
from slopsentinel.config import load_config
from slopsentinel.engine.context import ProjectContext
from slopsentinel.engine.detection import detect
from slopsentinel.engine.types import Violation
from slopsentinel.rules.examples import EXAMPLES
from slopsentinel.rules.plugins import PluginLoadError, load_plugin_rules
from slopsentinel.rules.registry import rule_meta_by_id, set_extra_rules
from slopsentinel.scanner import build_file_context_from_text


def _read_lsp_message() -> dict[str, Any] | None:
    """
    Read a single JSON-RPC message from stdin.

    LSP uses a `Content-Length: N` header framing protocol.
    """

    stdin = sys.stdin.buffer
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if not decoded:
            continue
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    raw_len = headers.get("content-length")
    if raw_len is None:
        return None
    try:
        length = int(raw_len)
    except ValueError:
        return None

    body = stdin.read(length)
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


def _send_lsp_message(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    sys.stdout.buffer.flush()


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Unsupported URI scheme: {parsed.scheme!r}")
    path = unquote(parsed.path)
    return Path(path)


def _severity_to_lsp(severity: str) -> int:
    # LSP DiagnosticSeverity: 1=Error, 2=Warning, 3=Information, 4=Hint
    if severity == "error":
        return 1
    if severity == "warn":
        return 2
    return 3


def violations_to_diagnostics(violations: list[Violation], *, text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    for v in violations:
        if v.location is None or v.location.start_line is None:
            continue

        line0 = max(0, int(v.location.start_line) - 1)
        col0 = max(0, int(v.location.start_col or 1) - 1)

        if v.location.end_line is not None:
            end_line0 = max(0, int(v.location.end_line) - 1)
            end_col0 = max(0, int(v.location.end_col or 1) - 1)
        else:
            end_line0 = line0
            if 0 <= line0 < len(lines):
                end_col0 = len(lines[line0])
            else:
                end_col0 = col0 + 1

        msg = v.message
        if v.suggestion:
            msg = f"{msg}\nSuggestion: {v.suggestion}"

        out.append(
            {
                "range": {
                    "start": {"line": line0, "character": col0},
                    "end": {"line": end_line0, "character": end_col0},
                },
                "severity": _severity_to_lsp(v.severity),
                "code": v.rule_id,
                "source": "slopsentinel",
                "message": msg,
            }
        )
    return out


@dataclass
class _Document:
    uri: str
    path: Path
    text: str
    violations: list[Violation] = field(default_factory=list)


def _collect_violations(doc: _Document, *, project_root: Path) -> list[Violation]:
    config = load_config(project_root)
    try:
        plugin_rules = load_plugin_rules(config.plugins)
    except PluginLoadError:
        plugin_rules = []
    set_extra_rules(plugin_rules)

    project = ProjectContext(project_root=project_root, scan_path=project_root, files=(doc.path,), config=config)
    file_ctx = build_file_context_from_text(project, doc.path, doc.text)
    if file_ctx is None:
        return []

    all_violations = detect(project, [file_ctx], workers=1, cache=None)
    return [
        v
        for v in all_violations
        if v.location is not None
        and v.location.path is not None
        and Path(v.location.path).resolve() == doc.path.resolve()
    ]


def _diagnose_document(doc: _Document, *, project_root: Path) -> list[dict[str, Any]]:
    violations = _collect_violations(doc, project_root=project_root)
    doc.violations = violations
    return violations_to_diagnostics(violations, text=doc.text)


def _range_for_violation(v: Violation, *, text: str) -> dict[str, Any] | None:
    if v.location is None or v.location.start_line is None:
        return None

    lines = text.splitlines()
    line0 = max(0, int(v.location.start_line) - 1)
    col0 = max(0, int(v.location.start_col or 1) - 1)

    if v.location.end_line is not None:
        end_line0 = max(0, int(v.location.end_line) - 1)
        end_col0 = max(0, int(v.location.end_col or 1) - 1)
    else:
        end_line0 = line0
        if 0 <= line0 < len(lines):
            end_col0 = len(lines[line0])
        else:
            end_col0 = col0 + 1

    return {
        "start": {"line": line0, "character": col0},
        "end": {"line": end_line0, "character": end_col0},
    }


def _find_violation_at_position(
    violations: list[Violation],
    *,
    text: str,
    line0: int,
    character0: int,
) -> Violation | None:
    best: tuple[int, int, Violation] | None = None
    for v in violations:
        rng = _range_for_violation(v, text=text)
        if rng is None:
            continue
        start = rng["start"]
        end = rng["end"]
        start_line = int(start["line"])
        start_char = int(start["character"])
        end_line = int(end["line"])
        end_char = int(end["character"])

        before_start = (line0, character0) < (start_line, start_char)
        after_end = (line0, character0) > (end_line, end_char)
        if before_start or after_end:
            continue

        # Prefer the smallest enclosing range.
        size = (end_line - start_line, end_char - start_char)
        if best is None or size < (best[0], best[1]):
            best = (size[0], size[1], v)

    return best[2] if best is not None else None


def _hover_for_violation(v: Violation) -> dict[str, Any] | None:
    meta = rule_meta_by_id().get(v.rule_id)
    if meta is None:
        return None

    lines: list[str] = []
    lines.append(f"**{meta.rule_id}: {meta.title}**")
    lines.append("")
    lines.append(f"- Severity: `{v.severity}`")
    lines.append(f"- Dimension: `{meta.score_dimension}`")
    if meta.fingerprint_model:
        lines.append(f"- Model: `{meta.fingerprint_model}`")
    lines.append("")
    lines.append(meta.description.strip())

    example = EXAMPLES.get(meta.rule_id)
    if example is not None:
        lines.append("")
        if example.notes:
            lines.append(example.notes.strip())
            lines.append("")
        lines.append("Bad:")
        lines.append(f"```{example.language}")
        lines.append(example.bad.rstrip("\n"))
        lines.append("```")
        if example.good is not None:
            lines.append("")
            lines.append("Good:")
            lines.append(f"```{example.language}")
            lines.append(example.good.rstrip("\n"))
            lines.append("```")

    value = "\n".join(lines).strip() + "\n"
    return {"contents": {"kind": "markdown", "value": value}}


def _full_document_edit(uri: str, *, old_text: str, new_text: str) -> dict[str, Any]:
    lines = old_text.splitlines()
    # Replace the full document. Most LSP clients accept end=(len(lines),0).
    end_line = len(lines)
    return {
        "changes": {
            uri: [
                {
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": end_line, "character": 0}},
                    "newText": new_text,
                }
            ]
        }
    }


def run_stdio_server() -> None:
    """
    Run a minimal Language Server Protocol (LSP) server over stdio.

    This is intentionally dependency-free (no `pygls`), supporting a small
    subset of LSP sufficient for real-time diagnostics:
    - initialize/shutdown/exit
    - textDocument/didOpen, didChange (full sync), didSave
    - textDocument/publishDiagnostics
    """

    project_root: Path | None = None
    docs: dict[str, _Document] = {}

    while True:
        msg = _read_lsp_message()
        if msg is None:
            return

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            root_uri = params.get("rootUri")
            root_path = params.get("rootPath")
            workspace_folders = params.get("workspaceFolders") or []
            candidate: str | None = root_uri or root_path
            if candidate is None and workspace_folders:
                first = workspace_folders[0]
                if isinstance(first, dict):
                    candidate = first.get("uri") or first.get("path")

            if isinstance(candidate, str) and candidate.startswith("file:"):
                try:
                    project_root = uri_to_path(candidate)
                except ValueError:
                    project_root = None
            elif isinstance(candidate, str) and candidate:
                project_root = Path(candidate)

            if project_root is None:
                project_root = Path.cwd()

            result = {
                "capabilities": {
                    "textDocumentSync": 1,  # Full sync
                    "hoverProvider": True,
                    "codeActionProvider": True,
                }
            }
            _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": result})
            continue

        if method == "shutdown":
            _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
            continue

        if method == "exit":
            return

        if method == "textDocument/hover":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            pos = params.get("position") or {}
            line0 = pos.get("line")
            character0 = pos.get("character")
            if not isinstance(uri, str) or not isinstance(line0, int) or not isinstance(character0, int):
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
                continue
            doc = docs.get(uri)
            if doc is None:
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
                continue
            if not doc.violations:
                doc.violations = _collect_violations(doc, project_root=project_root or Path.cwd())

            violation = _find_violation_at_position(doc.violations, text=doc.text, line0=line0, character0=character0)
            if violation is None:
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
                continue
            hover = _hover_for_violation(violation)
            if hover is None:
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
                continue
            rng = _range_for_violation(violation, text=doc.text)
            if rng is not None:
                hover["range"] = rng
            _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": hover})
            continue

        if method == "textDocument/codeAction":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            ctx = params.get("context") or {}
            diags = ctx.get("diagnostics") or []
            if not isinstance(uri, str) or not isinstance(diags, list):
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": []})
                continue
            doc = docs.get(uri)
            if doc is None:
                _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": []})
                continue
            if not doc.violations:
                doc.violations = _collect_violations(doc, project_root=project_root or Path.cwd())

            diag_codes: set[str] = set()
            for diag in diags:
                if not isinstance(diag, dict):
                    continue
                code = diag.get("code")
                if isinstance(code, str):
                    diag_codes.add(code)

            fixable_ids = supported_rule_ids()
            requested_fixable = sorted(diag_codes.intersection(fixable_ids))

            actions: list[dict[str, Any]] = []
            if requested_fixable:
                relevant = [v for v in doc.violations if v.rule_id in requested_fixable]
                new_text = apply_fixes(doc.path, doc.text, relevant)
                if new_text != doc.text:
                    actions.append(
                        {
                            "title": "SlopSentinel: Apply safe fixes",
                            "kind": "quickfix",
                            "isPreferred": True,
                            "edit": _full_document_edit(uri, old_text=doc.text, new_text=new_text),
                        }
                    )

            # Offer a generic action for clients that support it (even when no
            # SlopSentinel-specific quickfix is available).
            actions.append({"title": "Organize Imports", "kind": "source.organizeImports"})

            _send_lsp_message({"jsonrpc": "2.0", "id": msg_id, "result": actions})
            continue

        if method in {"textDocument/didOpen", "textDocument/didChange", "textDocument/didSave"}:
            if project_root is None:
                project_root = Path.cwd()

            if method == "textDocument/didOpen":
                td = params.get("textDocument") or {}
                uri = td.get("uri")
                text = td.get("text")
                if not isinstance(uri, str) or not isinstance(text, str):
                    continue
                try:
                    path = uri_to_path(uri)
                except ValueError:
                    continue
                docs[uri] = _Document(uri=uri, path=path, text=text)

            elif method == "textDocument/didChange":
                td = params.get("textDocument") or {}
                uri = td.get("uri")
                changes = params.get("contentChanges") or []
                if not isinstance(uri, str) or not changes:
                    continue
                change0 = changes[0]
                text = change0.get("text") if isinstance(change0, dict) else None
                if not isinstance(text, str):
                    continue
                existing = docs.get(uri)
                if existing is None:
                    try:
                        path = uri_to_path(uri)
                    except ValueError:
                        continue
                    existing = _Document(uri=uri, path=path, text=text)
                existing.text = text
                docs[uri] = existing

            else:  # didSave
                td = params.get("textDocument") or {}
                uri = td.get("uri")
                if not isinstance(uri, str):
                    continue
                if uri not in docs:
                    continue

            doc = docs.get(uri) if isinstance(uri, str) else None
            if doc is None:
                continue
            diagnostics = _diagnose_document(doc, project_root=project_root)
            _send_lsp_message(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": doc.uri,
                        "diagnostics": diagnostics,
                    },
                }
            )
            continue

        # Unknown method / notification: ignore.
