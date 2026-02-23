from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path

from slopsentinel.cache import FileViolationCache, file_content_hash
from slopsentinel.config import RulesConfig, SlopSentinelConfig, compute_enabled_rule_ids
from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.engine.types import Severity, Violation
from slopsentinel.rules.base import BaseRule
from slopsentinel.rules.registry import all_rules


def detect(
    project: ProjectContext,
    files: Iterable[FileContext],
    *,
    changed_lines: dict[Path, set[int]] | None = None,
    workers: int | None = None,
    cache: FileViolationCache | None = None,
    on_file_done: Callable[[Path], None] | None = None,
) -> list[Violation]:
    """
    Run enabled rules over the project and file contexts.

    If `changed_lines` is provided, file-level violations are filtered to only
    include violations that land on changed lines.

    Project-level checks are skipped when `changed_lines` is provided because
    they cannot be meaningfully mapped to a specific set of changed lines.
    """

    available_rules = list(all_rules())
    available_ids = tuple(r.meta.rule_id for r in available_rules)

    # Project-level checks are controlled by the global rule configuration.
    enabled_ids_project = compute_enabled_rule_ids(project.config, available_rule_ids=available_ids)
    enabled_rules_project = [r for r in available_rules if r.meta.rule_id in enabled_ids_project]

    # File-level checks may be overridden per directory. Compute a superset of
    # rules that may be needed, then filter per-file in `_detect_file_full`.
    enabled_ids_files: set[str] = set(enabled_ids_project)
    for rules_cfg in project.config.directory_overrides.values():
        cfg = replace(project.config, rules=rules_cfg)
        enabled_ids_files.update(compute_enabled_rule_ids(cfg, available_rule_ids=available_ids))
    enabled_rules_files = [r for r in available_rules if r.meta.rule_id in enabled_ids_files]

    violations: list[Violation] = []

    # Project-level checks
    if changed_lines is None:
        for rule in enabled_rules_project:
            violations.extend(_apply_overrides(project.config, rule.meta.rule_id, rule.check_project(project)))

    # File-level checks
    file_list = list(files)
    effective_workers = workers or 1

    if effective_workers <= 1 or len(file_list) <= 1:
        for file_ctx in file_list:
            violations.extend(
                _detect_file(project.config, enabled_rules_files, file_ctx, changed_lines=changed_lines, cache=cache)
            )
            if on_file_done is not None:
                on_file_done(file_ctx.path)
        return violations

    max_workers = min(max(1, effective_workers), len(file_list))
    detect_file = partial(_detect_file, project.config, enabled_rules_files, changed_lines=changed_lines, cache=cache)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for file_ctx, file_violations in zip(file_list, executor.map(detect_file, file_list), strict=True):
            violations.extend(file_violations)
            if on_file_done is not None:
                on_file_done(file_ctx.path)

    return violations


def _detect_file(
    config: SlopSentinelConfig,
    enabled_rules: Iterable[BaseRule],
    file_ctx: FileContext,
    *,
    changed_lines: dict[Path, set[int]] | None,
    cache: FileViolationCache | None,
) -> list[Violation]:
    content_hash = file_content_hash(file_ctx.text)

    full: list[Violation] | None = None
    if cache is not None:
        full = cache.get(relative_path=file_ctx.relative_path, content_hash=content_hash)

    if full is None:
        full = _detect_file_full(config, enabled_rules, file_ctx)
        if cache is not None:
            cache.put(relative_path=file_ctx.relative_path, content_hash=content_hash, violations=full)

    if changed_lines is None:
        return full

    return [v for v in full if _is_on_changed_line(v, changed_lines)]


def _detect_file_full(
    config: SlopSentinelConfig,
    enabled_rules: Iterable[BaseRule],
    file_ctx: FileContext,
) -> list[Violation]:
    rules_list = list(enabled_rules)
    effective_cfg = _effective_config_for_file(config, relative_path=file_ctx.relative_path)
    enabled_ids = compute_enabled_rule_ids(
        effective_cfg,
        available_rule_ids=(r.meta.rule_id for r in rules_list),
    )
    violations: list[Violation] = []
    for rule in rules_list:
        if rule.meta.rule_id not in enabled_ids:
            continue
        raw = rule.check_file(file_ctx)
        adjusted = _apply_overrides(effective_cfg, rule.meta.rule_id, raw)
        for v in adjusted:
            if _is_suppressed(file_ctx, v):
                continue
            violations.append(v)
    return violations


def _effective_config_for_file(config: SlopSentinelConfig, *, relative_path: str) -> SlopSentinelConfig:
    rules_cfg = _rules_config_for_relative_path(config, relative_path=relative_path)
    if rules_cfg is config.rules:
        return config
    return replace(config, rules=rules_cfg)


def _rules_config_for_relative_path(config: SlopSentinelConfig, *, relative_path: str) -> RulesConfig:
    overrides = config.directory_overrides
    if not overrides:
        return config.rules
    rel = relative_path.replace("\\", "/")
    best_len = -1
    best = config.rules
    for prefix, rules_cfg in overrides.items():
        if rel.startswith(prefix) and len(prefix) > best_len:
            best = rules_cfg
            best_len = len(prefix)
    return best


def _apply_overrides(config: SlopSentinelConfig, rule_id: str, violations: list[Violation]) -> list[Violation]:
    override = config.rules.overrides.get(rule_id)
    severity: Severity | None
    if override is not None and override.severity is not None:
        severity = override.severity
    else:
        severity = config.rules.severity_overrides.get(rule_id)
    if severity is None:
        return violations

    adjusted: list[Violation] = []
    for v in violations:
        adjusted.append(
            Violation(
                rule_id=v.rule_id,
                severity=severity,
                message=v.message,
                suggestion=v.suggestion,
                dimension=v.dimension,
                location=v.location,
            )
        )
    return adjusted


def _is_suppressed(ctx: FileContext, violation: Violation) -> bool:
    line = violation.location.start_line if violation.location else None
    return ctx.suppressions.is_suppressed(violation.rule_id, line=line)


def _is_on_changed_line(violation: Violation, changed_lines: dict[Path, set[int]]) -> bool:
    if violation.location is None or violation.location.path is None or violation.location.start_line is None:
        return True
    path = Path(violation.location.path).resolve()
    lines = changed_lines.get(path)
    if not lines:
        return False
    return violation.location.start_line in lines
