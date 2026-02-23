from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from types import MappingProxyType

from slopsentinel.rules.base import BaseRule, RuleMeta
from slopsentinel.rules.claude import builtin_claude_rules
from slopsentinel.rules.copilot import builtin_copilot_rules
from slopsentinel.rules.crossfile import builtin_crossfile_rules
from slopsentinel.rules.cursor import builtin_cursor_rules
from slopsentinel.rules.gemini import builtin_gemini_rules
from slopsentinel.rules.generic import builtin_generic_rules
from slopsentinel.rules.polyglot import builtin_polyglot_rules

_RULE_ID_RE = re.compile(r"^[A-Z][0-9]{2,}$")
_EXTRA_RULES: dict[str, BaseRule] = {}
_EXTRA_GENERATION = 0


@lru_cache(maxsize=1)
def builtin_rules() -> tuple[BaseRule, ...]:
    rules: list[BaseRule] = []
    rules.extend(builtin_claude_rules())
    rules.extend(builtin_cursor_rules())
    rules.extend(builtin_copilot_rules())
    rules.extend(builtin_gemini_rules())
    rules.extend(builtin_generic_rules())
    rules.extend(builtin_polyglot_rules())
    rules.extend(builtin_crossfile_rules())

    # Defensive: ensure no duplicate IDs.
    by_id: dict[str, BaseRule] = {}
    for rule in rules:
        rule_id = rule.meta.rule_id
        if rule_id != rule_id.strip() or rule_id != rule_id.upper():  # pragma: no cover
            raise RuntimeError(f"Rule id must be canonical uppercase without whitespace: {rule_id!r}")
        if not _RULE_ID_RE.match(rule_id):  # pragma: no cover
            raise RuntimeError(f"Rule id must match {_RULE_ID_RE.pattern}: {rule_id!r}")
        if rule_id in by_id:  # pragma: no cover
            raise RuntimeError(f"Duplicate rule id: {rule_id}")
        by_id[rule_id] = rule

    # Return stable order (A..E)
    return tuple(by_id[k] for k in sorted(by_id))


def set_extra_rules(rules: Iterable[BaseRule]) -> None:
    """
    Register extra (plugin) rules for this process.

    SlopSentinel is typically run as a CLI / GitHub Action, so process-wide
    registration is sufficient and keeps downstream code (scoring/reporters)
    able to resolve metadata for plugin rule IDs.
    """

    global _EXTRA_RULES, _EXTRA_GENERATION  # noqa: PLW0603

    by_id: dict[str, BaseRule] = {}
    builtin_ids = {r.meta.rule_id for r in builtin_rules()}
    for rule in rules:
        rule_id = rule.meta.rule_id
        if rule_id != rule_id.strip() or rule_id != rule_id.upper():
            raise RuntimeError(f"Rule id must be canonical uppercase without whitespace: {rule_id!r}")
        if not _RULE_ID_RE.match(rule_id):
            raise RuntimeError(f"Rule id must match {_RULE_ID_RE.pattern}: {rule_id!r}")
        if rule_id in builtin_ids:
            raise RuntimeError(f"Plugin rule id conflicts with built-in rule id: {rule_id}")
        if rule_id in by_id:
            raise RuntimeError(f"Duplicate plugin rule id: {rule_id}")
        by_id[rule_id] = rule

    _EXTRA_RULES = by_id
    _EXTRA_GENERATION += 1


def all_rules() -> tuple[BaseRule, ...]:
    return _all_rules(_EXTRA_GENERATION)


@lru_cache(maxsize=4)
def _all_rules(extra_generation: int) -> tuple[BaseRule, ...]:
    _ = extra_generation
    rules = list(builtin_rules())
    rules.extend(_EXTRA_RULES.values())
    by_id = {r.meta.rule_id: r for r in rules}
    return tuple(by_id[k] for k in sorted(by_id))


def rule_ids() -> set[str]:
    return {r.meta.rule_id for r in all_rules()}


def rule_meta_by_id() -> Mapping[str, RuleMeta]:
    return _rule_meta_by_id_map(_EXTRA_GENERATION)


@lru_cache(maxsize=4)
def _rule_meta_by_id_map(extra_generation: int) -> Mapping[str, RuleMeta]:
    _ = extra_generation
    return MappingProxyType({r.meta.rule_id: r.meta for r in all_rules()})


@lru_cache(maxsize=4)
def _rule_by_id_map(extra_generation: int) -> dict[str, BaseRule]:
    _ = extra_generation
    return {r.meta.rule_id: r for r in all_rules()}


def rule_by_id(rule_id: str) -> BaseRule | None:
    return _rule_by_id_map(_EXTRA_GENERATION).get(rule_id)
