from __future__ import annotations

import re
from collections.abc import Iterable

from slopsentinel.engine.context import FileContext

_LINE_COMMENT_PREFIXES = (
    "#",  # Python
    "//",  # JS/TS/Go/Rust
)
_BLOCK_COMMENT_START = "/*"
_BLOCK_COMMENT_END = "*/"


def is_comment_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    return stripped.startswith(_LINE_COMMENT_PREFIXES) or stripped.startswith(_BLOCK_COMMENT_START)


def iter_comment_lines(ctx: FileContext) -> Iterable[tuple[int, str]]:
    """
    Yield comment lines with basic block-comment support.

    This intentionally only treats lines as comments when the comment delimiter
    appears at the start of the line (after whitespace). It is designed for
    low-noise heuristics, not for full lexical parsing.
    """

    in_block_comment = False
    for idx, line in enumerate(ctx.lines, start=1):
        stripped = line.lstrip()
        if not stripped:
            continue

        if in_block_comment:
            yield idx, line
            if _BLOCK_COMMENT_END in stripped:
                in_block_comment = False
            continue

        if stripped.startswith(_LINE_COMMENT_PREFIXES):
            yield idx, line
            continue

        if stripped.startswith(_BLOCK_COMMENT_START):
            yield idx, line
            if _BLOCK_COMMENT_END not in stripped:
                in_block_comment = True
            continue


def iter_code_lines(ctx: FileContext) -> Iterable[tuple[int, str]]:
    """
    Yield non-empty code lines with basic block-comment support.

    Lines that are part of a leading `/* ... */` block are treated as comments.
    """

    in_block_comment = False
    for idx, line in enumerate(ctx.lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        lstripped = line.lstrip()
        if in_block_comment:
            if _BLOCK_COMMENT_END in lstripped:
                in_block_comment = False
            continue

        if lstripped.startswith(_LINE_COMMENT_PREFIXES):
            continue
        if lstripped.startswith(_BLOCK_COMMENT_START):
            if _BLOCK_COMMENT_END not in lstripped:
                in_block_comment = True
            continue

        yield idx, line


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]{3,}", text.lower())


def consecutive_runs(values: list[int]) -> list[tuple[int, int]]:
    """
    Return (start_index, length) for each run of consecutive integers in `values`.
    """

    if not values:
        return []
    runs: list[tuple[int, int]] = []
    start = values[0]
    prev = values[0]
    length = 1
    for v in values[1:]:
        if v == prev + 1:
            length += 1
        else:
            runs.append((start, length))
            start = v
            length = 1
        prev = v
    runs.append((start, length))
    return runs
