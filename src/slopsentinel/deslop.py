from __future__ import annotations

import difflib
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from slopsentinel.languages.registry import detect_language
from slopsentinel.patterns import (
    BANNER_RE,
    COMPREHENSIVE_RE,
    LAST_UPDATE_RE,
    POLITE_RE,
    THINKING_RE,
)


@dataclass(frozen=True, slots=True)
class DeslopResult:
    path: Path
    changed: bool
    diff: str


def deslop_file(path: Path, *, backup: bool, dry_run: bool) -> DeslopResult:
    original = path.read_text(encoding="utf-8", errors="replace")
    language = detect_language(path) or ""
    updated = deslop_text(original, language=language)

    diff = _unified_diff(original, updated, path=path)
    changed = original != updated

    if changed and not dry_run:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".slopsentinel.bak")
            if not backup_path.exists():
                backup_path.write_text(original, encoding="utf-8")
        path.write_text(updated, encoding="utf-8")

    return DeslopResult(path=path, changed=changed, diff=diff)


def deslop_text(text: str, *, language: str = "") -> str:
    if language == "python":
        return _deslop_python(text)

    lines = text.splitlines(keepends=True)
    out: list[str] = []

    in_block_comment = False
    for line in lines:
        stripped = line.lstrip()
        if not stripped:
            out.append(line)
            continue

        is_comment = False
        if in_block_comment:
            is_comment = True
            if "*/" in stripped:
                in_block_comment = False
        elif stripped.startswith(("#", "//")):
            is_comment = True
        elif stripped.startswith("/*"):
            is_comment = True
            if "*/" not in stripped:
                in_block_comment = True

        if not is_comment:
            out.append(line)
            continue

        if BANNER_RE.match(line):
            continue
        if POLITE_RE.search(line):
            continue
        if COMPREHENSIVE_RE.search(line):
            continue
        if LAST_UPDATE_RE.search(line):
            continue
        if THINKING_RE.search(line):
            continue

        out.append(line)

    return "".join(out)


def _deslop_python(text: str) -> str:
    """
    Remove common AI comment artifacts from Python source.

    This is structure-aware: it removes matching `# ...` comment tokens even
    when they appear inline after code, without touching strings/docstrings.
    """

    lines = text.splitlines(keepends=True)
    removals: dict[int, tuple[int, int]] = {}

    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            row, col = tok.start
            end_row, end_col = tok.end
            if row != end_row:
                continue
            comment = tok.string
            if "slop:" in comment.lower():
                continue
            if not _comment_matches_ai_artifact(comment):
                continue
            removals[row] = (col, end_col)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Fall back to the line-based heuristic when tokenization fails.
        return deslop_text(text, language="")

    if not removals:
        return text

    out: list[str] = []
    for idx, line in enumerate(lines, start=1):
        span = removals.get(idx)
        if span is None:
            out.append(line)
            continue
        start, end = span
        if start >= len(line):
            out.append(line)
            continue
        prefix = line[:start]
        suffix = line[end:]

        # If the comment was the whole line (after indentation), drop it.
        if prefix.strip() == "" and suffix.strip() == "":
            continue

        out.append(prefix.rstrip() + suffix)

    return "".join(out)


def _comment_matches_ai_artifact(text: str) -> bool:
    if BANNER_RE.match(text):
        return True
    if POLITE_RE.search(text):
        return True
    if COMPREHENSIVE_RE.search(text):
        return True
    if LAST_UPDATE_RE.search(text):
        return True
    if THINKING_RE.search(text):
        return True
    return False


def _unified_diff(before: str, after: str, *, path: Path) -> str:
    before_lines = before.splitlines(keepends=False)
    after_lines = after.splitlines(keepends=False)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=str(path),
        tofile=str(path),
        lineterm="",
    )
    return "\n".join(diff)
