from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from slopsentinel.baseline import BaselineError, filter_violations, load_baseline
from slopsentinel.cache import FileViolationCache, config_fingerprint
from slopsentinel.config import RulesConfig, compute_enabled_rule_ids
from slopsentinel.engine.detection import detect
from slopsentinel.engine.scoring import summarize
from slopsentinel.engine.types import ScanSummary
from slopsentinel.rules.plugins import PluginLoadError, load_plugin_rules
from slopsentinel.rules.registry import all_rules, set_extra_rules
from slopsentinel.scanner import (
    ScanTarget,
    build_file_contexts,
    build_project_context,
    discover_files,
    prepare_target,
    worker_count_from_env,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditResult:
    target: ScanTarget
    files: tuple[Path, ...]
    summary: ScanSummary


@dataclass(frozen=True, slots=True)
class AuditCallbacks:
    on_context_built: Callable[[Path], None] | None = None
    on_file_contexts_ready: Callable[[int], None] | None = None
    on_file_scanned: Callable[[Path], None] | None = None


def audit_path(
    scan_path: Path,
    *,
    changed_lines: dict[Path, set[int]] | None = None,
    apply_baseline: bool = True,
    record_history: bool = True,
    callbacks: AuditCallbacks | None = None,
) -> AuditResult:
    target = prepare_target(scan_path)
    files = discover_files(target)
    return audit_files(
        target,
        files=files,
        changed_lines=changed_lines,
        apply_baseline=apply_baseline,
        record_history=record_history,
        callbacks=callbacks,
    )


def audit_changed_files(
    scan_path: Path,
    changed_lines: dict[Path, set[int]],
    *,
    apply_baseline: bool = True,
    record_history: bool = True,
    callbacks: AuditCallbacks | None = None,
) -> AuditResult:
    target = prepare_target(scan_path)
    files = sorted(changed_lines.keys())
    # Keep only files that are under scan_path and supported by language/ignore rules.
    discovered = set(discover_files(target))
    files = [p for p in files if p in discovered]
    return audit_files(
        target,
        files=files,
        changed_lines=changed_lines,
        apply_baseline=apply_baseline,
        record_history=record_history,
        callbacks=callbacks,
    )


def audit_files(
    target: ScanTarget,
    *,
    files: list[Path],
    changed_lines: dict[Path, set[int]] | None = None,
    apply_baseline: bool = True,
    record_history: bool = True,
    callbacks: AuditCallbacks | None = None,
) -> AuditResult:
    project = build_project_context(target, files)
    workers = worker_count_from_env()
    file_contexts = build_file_contexts(
        project,
        files,
        workers=workers,
        on_path_done=callbacks.on_context_built if callbacks else None,
    )
    if callbacks is not None and callbacks.on_file_contexts_ready is not None:
        callbacks.on_file_contexts_ready(len(file_contexts))

    try:
        plugin_rules = load_plugin_rules(target.config.plugins)
    except PluginLoadError as exc:
        raise RuntimeError(f"Failed to load SlopSentinel plugins: {exc}") from exc
    set_extra_rules(plugin_rules)

    available_ids = {r.meta.rule_id for r in all_rules()}
    unknown_override_ids = set(target.config.rules.overrides).union(target.config.rules.severity_overrides)
    for rules_cfg in target.config.directory_overrides.values():
        unknown_override_ids.update(rules_cfg.overrides)
        unknown_override_ids.update(rules_cfg.severity_overrides)
    unknown_override_ids -= available_ids
    for rule_id in sorted(unknown_override_ids):
        logger.warning("unknown rule id in rules overrides: %s", rule_id)

    cache: FileViolationCache | None = None
    cache_cfg = target.config.cache
    if cache_cfg.enabled:
        cache_path = _resolve_project_file(target.project_root, cache_cfg.path)
        if cache_path is None:
            logger.warning("refusing cache path outside project root: %r", cache_cfg.path)
        else:
            enabled_ids = compute_enabled_rule_ids(target.config, available_rule_ids=available_ids)
            for rules_cfg in target.config.directory_overrides.values():
                enabled_ids.update(
                    compute_enabled_rule_ids(replace(target.config, rules=rules_cfg), available_rule_ids=available_ids)
                )

            def effective_severity_overrides(rules_cfg: RulesConfig) -> dict[str, str]:
                out: dict[str, str] = {}
                all_ids = set(rules_cfg.overrides).union(rules_cfg.severity_overrides)
                for rule_id in sorted(all_ids):
                    override = rules_cfg.overrides.get(rule_id)
                    severity = override.severity if override is not None and override.severity is not None else None
                    if severity is None:
                        severity = rules_cfg.severity_overrides.get(rule_id)
                    if severity is None:
                        continue
                    out[rule_id] = str(severity)
                return out

            overrides: dict[str, str] = {}
            overrides.update(effective_severity_overrides(target.config.rules))
            for prefix, rules_cfg in sorted(target.config.directory_overrides.items()):
                overrides[f"dir:{prefix}:enable"] = (
                    rules_cfg.enable if isinstance(rules_cfg.enable, str) else ",".join(rules_cfg.enable)
                )
                overrides[f"dir:{prefix}:disable"] = ",".join(sorted(rules_cfg.disable))
                for rule_id, sev in sorted(effective_severity_overrides(rules_cfg).items()):
                    overrides[f"dir:{prefix}:severity:{rule_id}"] = sev
            fingerprint = config_fingerprint(
                enabled_rule_ids=enabled_ids,
                overrides=overrides,
                plugins=target.config.plugins,
            )
            cache = FileViolationCache.load(cache_path, fingerprint=fingerprint, project_root=target.project_root)

    violations = detect(
        project,
        file_contexts,
        changed_lines=changed_lines,
        workers=workers,
        cache=cache,
        on_file_done=callbacks.on_file_scanned if callbacks else None,
    )
    if cache is not None:
        hits, misses = cache.stats()
        logger.debug("cache: %d hits, %d misses", hits, misses)
    if cache is not None:
        try:
            cache.save()
        except OSError as exc:  # pragma: no cover
            logger.warning("failed to save cache (%s): %s", cache.path, exc)

    # Baselines are intended for full-repo scans; diff-based scans already focus
    # on new/changed lines and should not typically be suppressed by baseline.
    baseline_spec = target.config.baseline
    if apply_baseline and changed_lines is None and baseline_spec:
        baseline_path = _resolve_project_file(target.project_root, baseline_spec)
        if baseline_path is None:
            logger.warning("refusing baseline path outside project root: %r", baseline_spec)
        elif baseline_path.exists():
            try:
                baseline = load_baseline(baseline_path)
                violations = filter_violations(violations, baseline, project_root=target.project_root)
            except BaselineError as exc:
                logger.warning("failed to load baseline (%s): %s", baseline_path, exc)

    summary = summarize(files_scanned=len(file_contexts), violations=violations, scoring=target.config.scoring)

    history_cfg = target.config.history
    if record_history and history_cfg.enabled and changed_lines is None:
        history_path = _resolve_project_file(target.project_root, history_cfg.path)
        if history_path is None:
            logger.warning("refusing history path outside project root: %r", history_cfg.path)
        else:
            from slopsentinel.history import append_history, record_entry

            try:
                entry = record_entry(summary, project_root=target.project_root)
                append_history(history_path, entry, max_entries=history_cfg.max_entries)
            except OSError as exc:  # pragma: no cover
                logger.warning("failed to write history (%s): %s", history_path, exc)

    return AuditResult(
        target=target,
        files=tuple(files),
        summary=summary,
    )


def _resolve_project_file(project_root: Path, spec: str) -> Path | None:
    raw = Path(spec)
    candidate = raw if raw.is_absolute() else (project_root / raw)
    try:
        root = project_root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(root)
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None
