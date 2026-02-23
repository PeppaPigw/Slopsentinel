from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Suppressions:
    """
    Line-level rule suppressions extracted from in-file directives.

    Supported directives (case-insensitive):
    - `slop: disable-file=A03,C01` (suppresses violations anywhere in the file)
    - `slop: disable=A03,C01` (suppresses violations on that same line)
    - `slop: disable-next-line=C01` (suppresses violations on the next line)
    """

    disabled_in_file: frozenset[str]
    disabled_on_line: Mapping[int, frozenset[str]]

    def is_suppressed(self, rule_id: str, *, line: int | None) -> bool:
        normalized_id = rule_id.upper()
        if "all" in self.disabled_in_file or normalized_id in self.disabled_in_file:
            return True
        if line is None:
            return False
        disabled = self.disabled_on_line.get(line)
        if not disabled:
            return False
        return "all" in disabled or normalized_id in disabled


_DISABLE_FILE_RE = re.compile(r"slop:\s*disable[-_]?file\s*=\s*(?P<ids>[a-z0-9_,\-\s]+)", re.IGNORECASE)
_DISABLE_RE = re.compile(r"slop:\s*disable\s*=\s*(?P<ids>[a-z0-9_,\-\s]+)", re.IGNORECASE)
_DISABLE_NEXT_RE = re.compile(r"slop:\s*disable-next-line\s*=\s*(?P<ids>[a-z0-9_,\-\s]+)", re.IGNORECASE)


def parse_suppressions(lines: Sequence[str]) -> Suppressions:
    disabled_in_file: set[str] = set()
    disabled_on_line: dict[int, set[str]] = {}

    for idx, line in enumerate(lines, start=1):
        match_file = _DISABLE_FILE_RE.search(line)
        if match_file:
            disabled_in_file.update(_parse_ids(match_file.group("ids")))

        match = _DISABLE_RE.search(line)
        if match:
            disabled_on_line.setdefault(idx, set()).update(_parse_ids(match.group("ids")))

        match_next = _DISABLE_NEXT_RE.search(line)
        if match_next:
            target = idx + 1
            disabled_on_line.setdefault(target, set()).update(_parse_ids(match_next.group("ids")))

    frozen = {line: frozenset(ids) for line, ids in disabled_on_line.items()}
    return Suppressions(disabled_in_file=frozenset(sorted(disabled_in_file)), disabled_on_line=MappingProxyType(frozen))


def _parse_ids(value: str) -> set[str]:
    ids = set()
    for token in re.split(r"[,\s]+", value.strip()):
        if not token:
            continue
        normalized = token.strip()
        if not normalized:
            continue
        if normalized.lower() == "all":
            ids.add("all")
        else:
            ids.add(normalized.upper())
    return ids
