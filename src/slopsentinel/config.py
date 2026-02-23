from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from slopsentinel.engine.types import Severity


class ConfigError(ValueError):
    """Raised when a SlopSentinel configuration file is invalid."""


RuleId = str
RuleGroup = str


_RULE_ID_RE = re.compile(r"^[A-Z][0-9]{2,}$")

DEFAULT_THRESHOLD = 60
DEFAULT_FAIL_ON_SLOP = False
DEFAULT_LANGUAGES: tuple[str, ...] = (
    "python",
    "typescript",
    "javascript",
    "go",
    "rust",
    "java",
    "kotlin",
    "ruby",
    "php",
)
DEFAULT_CACHE_PATH = ".slopsentinel/cache.json"
DEFAULT_HISTORY_PATH = ".slopsentinel/history.json"


# Keep this list in config (not in rules) so configuration can be resolved
# without importing the full detection engine.
DEFAULT_RULE_GROUPS: dict[RuleGroup, tuple[RuleId, ...]] = {
    # NOTE: Keep these in sync with `slopsentinel.rules.registry.builtin_rules()`.
    # Tests assert that every listed rule id exists to avoid "phantom" ids
    # (e.g. from naive `range()` expansion) silently breaking user configs.
    "claude": (
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "A07",
        "A08",
        "A09",
        "A10",
        "A11",
        "A12",
    ),
    "cursor": (
        "B01",
        "B02",
        "B03",
        "B04",
        "B05",
        "B06",
        "B07",
        "B08",
    ),
    "copilot": (
        "C01",
        "C02",
        "C03",
        "C04",
        "C05",
        "C06",
        "C07",
        "C08",
        "C09",
        "C10",
        "C11",
    ),
    "gemini": (
        "D01",
        "D02",
        "D03",
        "D04",
        "D05",
        "D06",
    ),
    "generic": (
        "E01",
        "E02",
        "E03",
        "E04",
        "E05",
        "E06",
        "E07",
        "E08",
        "E09",
        "E10",
        "E11",
        "E12",
    ),
    # Keep explicit to avoid "phantom" ids caused by naive `range()` expansion.
    "go": ("G01", "G02", "G03", "G04", "G05", "G06", "G07"),
    "rust": ("R01", "R02", "R03", "R04", "R05", "R06", "R07"),
    "java": ("J01", "J02", "J03"),
    "kotlin": ("K01", "K02", "K03"),
    "ruby": ("Y01", "Y02", "Y03"),
    "php": ("P01", "P02", "P03"),
    "crossfile": ("X01", "X02", "X03", "X04", "X05"),
}
DEFAULT_RULE_GROUPS["all"] = tuple(
    rule_id
    for group in (
        "claude",
        "cursor",
        "copilot",
        "gemini",
        "generic",
        "go",
        "rust",
        "java",
        "kotlin",
        "ruby",
        "php",
        "crossfile",
    )
    for rule_id in DEFAULT_RULE_GROUPS[group]
)


def _normalize_group(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _validate_str_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ConfigError(f"`{field_name}` must be a list of strings.")
    return tuple(v.strip() for v in value)


def _normalize_rule_id(value: str) -> str:
    # Rule IDs are case-insensitive in UX, but canonicalized internally.
    return value.strip().upper()


def _validate_severity(value: Any, *, field_name: str) -> Severity:
    if not isinstance(value, str):
        raise ConfigError(f"`{field_name}` must be a string.")
    normalized = value.strip().lower()
    if normalized == "warning":
        normalized = "warn"
    if normalized not in {"info", "warn", "error"}:
        raise ConfigError(f"`{field_name}` must be one of: info, warn, error.")
    return cast(Severity, normalized)


@dataclass(frozen=True, slots=True)
class RuleOverride:
    severity: Severity | None = None


@dataclass(frozen=True, slots=True)
class RulesConfig:
    enable: str | tuple[str, ...] = "all"
    disable: tuple[str, ...] = ()
    overrides: Mapping[RuleId, RuleOverride] = field(default_factory=lambda: MappingProxyType({}))
    severity_overrides: Mapping[RuleId, Severity] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class RulesConfigPatch:
    """
    Partial rules configuration used for directory overrides.

    Fields set to None mean "inherit from base config".
    """

    enable: str | tuple[str, ...] | None = None
    disable: tuple[str, ...] | None = None
    overrides: Mapping[RuleId, RuleOverride] | None = None
    severity_overrides: Mapping[RuleId, Severity] | None = None


@dataclass(frozen=True, slots=True)
class CacheConfig:
    enabled: bool = False
    path: str = DEFAULT_CACHE_PATH


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    enabled: bool = False
    path: str = DEFAULT_HISTORY_PATH
    max_entries: int = 200


_SCORING_PROFILES = {"default", "strict", "lenient"}
_SCORING_DIMS = {"fingerprint", "quality", "hallucination", "maintainability", "security"}
_SCORING_SEVERITIES = {"info", "warn", "error"}


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """
    Scoring configuration.

    `profile` selects a built-in severity penalty mapping. `penalties` allows
    overriding per-dimension severity penalties in a safe, deterministic way.
    """

    profile: str = "default"
    penalties: Mapping[str, Mapping[str, int]] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class IgnoreConfig:
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SlopSentinelConfig:
    threshold: int = DEFAULT_THRESHOLD
    fail_on_slop: bool = DEFAULT_FAIL_ON_SLOP
    languages: tuple[str, ...] = DEFAULT_LANGUAGES
    rules: RulesConfig = field(default_factory=RulesConfig)
    directory_overrides: Mapping[str, RulesConfig] = field(default_factory=lambda: MappingProxyType({}))
    ignore: IgnoreConfig = field(default_factory=IgnoreConfig)
    baseline: str | None = None
    cache: CacheConfig = field(default_factory=CacheConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    plugins: tuple[str, ...] = ()


def load_config(project_dir: Path | str = ".") -> SlopSentinelConfig:
    """
    Load SlopSentinel configuration from `pyproject.toml` within `project_dir`.

    If no file / no `[tool.slopsentinel]` table exists, returns defaults.
    """

    project_dir_path = Path(project_dir)
    pyproject_path = project_dir_path / "pyproject.toml"
    if not pyproject_path.exists():
        return SlopSentinelConfig()

    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover (rare)
        raise ConfigError(f"Invalid TOML in {pyproject_path}: {exc}") from exc

    tool_table = data.get("tool", {})
    if not isinstance(tool_table, dict):
        return SlopSentinelConfig()

    slopsentinel_table = tool_table.get("slopsentinel", {})
    if not isinstance(slopsentinel_table, dict) or not slopsentinel_table:
        return SlopSentinelConfig()

    return _parse_slopsentinel_table(slopsentinel_table)


def _parse_slopsentinel_table(slopsentinel_table: dict[str, Any]) -> SlopSentinelConfig:
    threshold = slopsentinel_table.get("threshold", DEFAULT_THRESHOLD)
    if not isinstance(threshold, int):
        raise ConfigError("`tool.slopsentinel.threshold` must be an integer.")
    if not (0 <= threshold <= 100):
        raise ConfigError("`tool.slopsentinel.threshold` must be between 0 and 100.")

    fail_on_slop = slopsentinel_table.get("fail-on-slop", slopsentinel_table.get("fail_on_slop", DEFAULT_FAIL_ON_SLOP))
    if not isinstance(fail_on_slop, bool):
        raise ConfigError("`tool.slopsentinel.fail-on-slop` must be a boolean.")

    languages_value = slopsentinel_table.get("languages", list(DEFAULT_LANGUAGES))
    if not isinstance(languages_value, list) or any(not isinstance(v, str) for v in languages_value):
        raise ConfigError("`tool.slopsentinel.languages` must be a list of strings.")
    languages = tuple(languages_value)

    rules = _parse_rules_config(slopsentinel_table.get("rules", {}))
    directory_overrides = _parse_directory_overrides(slopsentinel_table.get("overrides", {}), base_rules=rules)
    ignore = _parse_ignore_config(slopsentinel_table.get("ignore", {}))
    baseline = _parse_baseline_path(slopsentinel_table.get("baseline"))
    cache = _parse_cache_config(slopsentinel_table.get("cache", {}))
    history = _parse_history_config(slopsentinel_table.get("history", {}))
    scoring = _parse_scoring_config(slopsentinel_table.get("scoring", {}))
    plugins = _validate_str_list(slopsentinel_table.get("plugins", []), field_name="tool.slopsentinel.plugins")

    return SlopSentinelConfig(
        threshold=threshold,
        fail_on_slop=fail_on_slop,
        languages=languages,
        rules=rules,
        directory_overrides=directory_overrides,
        ignore=ignore,
        baseline=baseline,
        cache=cache,
        history=history,
        scoring=scoring,
        plugins=plugins,
    )


def _parse_rules_config(value: Any) -> RulesConfig:
    if value is None:
        return RulesConfig()
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.rules` must be a table.")

    enable: str | tuple[str, ...]
    enable_raw = value.get("enable", "all")
    if isinstance(enable_raw, str):
        stripped = enable_raw.strip()
        if "," in stripped or ";" in stripped:
            enable = _split_rule_tokens(stripped)
        else:
            enable = stripped or "all"
    elif isinstance(enable_raw, list) and all(isinstance(v, str) for v in enable_raw):
        enable = _split_rule_list(enable_raw)
    else:
        raise ConfigError("`tool.slopsentinel.rules.enable` must be a string or a list of strings.")

    disable_raw = _validate_str_list(value.get("disable", []), field_name="tool.slopsentinel.rules.disable")
    disable = _split_rule_list(disable_raw)

    _validate_rule_spec(enable, field_name="tool.slopsentinel.rules.enable")
    _validate_rule_tokens(disable, field_name="tool.slopsentinel.rules.disable")

    sev_overrides_raw = value.get("severity_overrides", value.get("severity-overrides"))
    severity_overrides: dict[RuleId, Severity] = {}
    if sev_overrides_raw is not None:
        if not isinstance(sev_overrides_raw, dict):
            raise ConfigError("`tool.slopsentinel.rules.severity_overrides` must be a table.")
        for raw_rule_id, raw_severity in sev_overrides_raw.items():
            normalized_rule_id = _normalize_rule_id(str(raw_rule_id))
            if not _RULE_ID_RE.match(normalized_rule_id):
                raise ConfigError(
                    f"`tool.slopsentinel.rules.severity_overrides.{raw_rule_id}` is invalid; expected a rule id like A03."
                )
            severity_overrides[normalized_rule_id] = _validate_severity(
                raw_severity,
                field_name=f"tool.slopsentinel.rules.severity_overrides.{raw_rule_id}",
            )

    overrides: dict[RuleId, RuleOverride] = {}
    for key, sub in value.items():
        if key in {"enable", "disable", "severity_overrides", "severity-overrides"}:
            continue
        if not isinstance(sub, dict):
            continue
        normalized_key = _normalize_rule_id(str(key))
        if not _RULE_ID_RE.match(normalized_key):
            raise ConfigError(f"`tool.slopsentinel.rules.{key}` is invalid; expected a rule id like A03.")
        severity = sub.get("severity")
        override = RuleOverride(
            severity=_validate_severity(severity, field_name=f"tool.slopsentinel.rules.{key}.severity")
            if severity is not None
            else None,
        )
        overrides[normalized_key] = override

    return RulesConfig(
        enable=enable,
        disable=disable,
        overrides=MappingProxyType(overrides),
        severity_overrides=MappingProxyType(severity_overrides),
    )


def _parse_rules_config_patch(value: Any, *, field_name: str) -> RulesConfigPatch:
    if value is None:
        return RulesConfigPatch()
    if not isinstance(value, dict):
        raise ConfigError(f"`{field_name}` must be a table.")

    enable: str | tuple[str, ...] | None = None
    if "enable" in value:
        enable_raw = value.get("enable")
        if isinstance(enable_raw, str):
            stripped = enable_raw.strip()
            if "," in stripped or ";" in stripped:
                enable = _split_rule_tokens(stripped)
            else:
                enable = stripped or "all"
        elif isinstance(enable_raw, list) and all(isinstance(v, str) for v in enable_raw):
            enable = _split_rule_list(enable_raw)
        else:
            raise ConfigError(f"`{field_name}.enable` must be a string or a list of strings.")
        _validate_rule_spec(enable, field_name=f"{field_name}.enable")

    disable: tuple[str, ...] | None = None
    if "disable" in value:
        disable_raw = _validate_str_list(value.get("disable", []), field_name=f"{field_name}.disable")
        disable = _split_rule_list(disable_raw)
        _validate_rule_tokens(disable, field_name=f"{field_name}.disable")

    severity_overrides: dict[RuleId, Severity] | None = None
    if "severity_overrides" in value or "severity-overrides" in value:
        sev_overrides_raw = value.get("severity_overrides", value.get("severity-overrides"))
        severity_overrides = {}
        if sev_overrides_raw is not None:
            if not isinstance(sev_overrides_raw, dict):
                raise ConfigError(f"`{field_name}.severity_overrides` must be a table.")
            for raw_rule_id, raw_severity in sev_overrides_raw.items():
                normalized_rule_id = _normalize_rule_id(str(raw_rule_id))
                if not _RULE_ID_RE.match(normalized_rule_id):
                    raise ConfigError(
                        f"`{field_name}.severity_overrides.{raw_rule_id}` is invalid; expected a rule id like A03."
                    )
                severity_overrides[normalized_rule_id] = _validate_severity(
                    raw_severity,
                    field_name=f"{field_name}.severity_overrides.{raw_rule_id}",
                )

    overrides: dict[RuleId, RuleOverride] = {}
    for key, sub in value.items():
        if key in {"enable", "disable", "severity_overrides", "severity-overrides"}:
            continue
        if not isinstance(sub, dict):
            continue
        normalized_key = _normalize_rule_id(str(key))
        if not _RULE_ID_RE.match(normalized_key):
            raise ConfigError(f"`{field_name}.{key}` is invalid; expected a rule id like A03.")
        severity = sub.get("severity")
        override = RuleOverride(
            severity=_validate_severity(severity, field_name=f"{field_name}.{key}.severity") if severity is not None else None,
        )
        overrides[normalized_key] = override

    return RulesConfigPatch(
        enable=enable,
        disable=disable,
        overrides=MappingProxyType(overrides) if overrides else None,
        severity_overrides=MappingProxyType(severity_overrides) if severity_overrides is not None else None,
    )


def _apply_rules_patch(*, base: RulesConfig, patch: RulesConfigPatch) -> RulesConfig:
    enable = patch.enable if patch.enable is not None else base.enable
    disable = patch.disable if patch.disable is not None else base.disable

    overrides: dict[RuleId, RuleOverride] = dict(base.overrides)
    if patch.overrides is not None:
        overrides.update(patch.overrides)

    severity_overrides: dict[RuleId, Severity] = dict(base.severity_overrides)
    if patch.severity_overrides is not None:
        severity_overrides.update(patch.severity_overrides)

    return RulesConfig(
        enable=enable,
        disable=disable,
        overrides=MappingProxyType(overrides),
        severity_overrides=MappingProxyType(severity_overrides),
    )


def _normalize_override_prefix(value: str, *, field_name: str) -> str:
    prefix = value.strip().replace("\\", "/")
    if prefix.startswith("./"):
        prefix = prefix[2:]
    if prefix.startswith("/"):
        raise ConfigError(f"`{field_name}` must be a relative path prefix (no leading '/').")
    if not prefix:
        raise ConfigError(f"`{field_name}` must not be empty.")
    if ".." in Path(prefix).parts:
        raise ConfigError(f"`{field_name}` must not contain '..' segments.")
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


def _parse_directory_overrides(value: Any, *, base_rules: RulesConfig) -> Mapping[str, RulesConfig]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.overrides` must be a table.")

    out: dict[str, RulesConfig] = {}
    for raw_prefix, raw_table in value.items():
        if not isinstance(raw_prefix, str):
            raise ConfigError("`tool.slopsentinel.overrides` keys must be strings.")
        field_name = f"tool.slopsentinel.overrides.{raw_prefix}"
        if not isinstance(raw_table, dict):
            raise ConfigError(f"`{field_name}` must be a table.")
        rules_table = raw_table.get("rules")
        if rules_table is None:
            # Allow future override fields; skip entries without a rules patch.
            continue

        normalized_prefix = _normalize_override_prefix(raw_prefix, field_name=field_name)
        if normalized_prefix in out:
            raise ConfigError(f"`{field_name}` duplicates another override prefix after normalization: {normalized_prefix!r}.")

        patch = _parse_rules_config_patch(rules_table, field_name=f"{field_name}.rules")
        out[normalized_prefix] = _apply_rules_patch(base=base_rules, patch=patch)

    return MappingProxyType(out)


def _split_rule_tokens(value: str) -> tuple[str, ...]:
    parts = []
    for raw in value.replace(";", ",").split(","):
        token = raw.strip()
        if token:
            parts.append(token)
    return tuple(parts)


def _split_rule_list(values: Iterable[str]) -> tuple[str, ...]:
    parts: list[str] = []
    for raw in values:
        parts.extend(_split_rule_tokens(raw))
    return tuple(parts)


def _validate_rule_spec(enable: str | tuple[str, ...], *, field_name: str) -> None:
    if isinstance(enable, str):
        _validate_rule_tokens((enable,), field_name=field_name)
    else:
        _validate_rule_tokens(enable, field_name=field_name)


def _validate_rule_tokens(tokens: Iterable[str], *, field_name: str) -> None:
    for token in tokens:
        stripped = token.strip()
        if not stripped:
            continue
        normalized_group = _normalize_group(stripped)
        if normalized_group == "all" or normalized_group in DEFAULT_RULE_GROUPS:
            continue

        normalized_id = _normalize_rule_id(stripped)
        if _RULE_ID_RE.match(normalized_id):
            continue

        groups = ", ".join(sorted(DEFAULT_RULE_GROUPS))
        raise ConfigError(
            f"`{field_name}` contains unknown rule group or invalid rule id: {token!r}. "
            f"Valid groups: {groups}. Valid ids look like A03/E10."
        )


def _parse_ignore_config(value: Any) -> IgnoreConfig:
    if value is None:
        return IgnoreConfig()
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.ignore` must be a table.")
    paths = _validate_str_list(value.get("paths", []), field_name="tool.slopsentinel.ignore.paths")
    return IgnoreConfig(paths=paths)


def _parse_baseline_path(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("`tool.slopsentinel.baseline` must be a string path.")
    path = value.strip()
    return path or None


def _parse_cache_config(value: Any) -> CacheConfig:
    if value is None:
        return CacheConfig()
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.cache` must be a table.")

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("`tool.slopsentinel.cache.enabled` must be a boolean.")

    path = value.get("path", DEFAULT_CACHE_PATH)
    if not isinstance(path, str):
        raise ConfigError("`tool.slopsentinel.cache.path` must be a string path.")
    path = path.strip() or DEFAULT_CACHE_PATH

    return CacheConfig(enabled=enabled, path=path)


def _parse_history_config(value: Any) -> HistoryConfig:
    if value is None:
        return HistoryConfig()
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.history` must be a table.")

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("`tool.slopsentinel.history.enabled` must be a boolean.")

    path = value.get("path", DEFAULT_HISTORY_PATH)
    if not isinstance(path, str):
        raise ConfigError("`tool.slopsentinel.history.path` must be a string path.")
    path = path.strip() or DEFAULT_HISTORY_PATH

    max_entries = value.get("max-entries", value.get("max_entries", 200))
    if not isinstance(max_entries, int):
        raise ConfigError("`tool.slopsentinel.history.max-entries` must be an integer.")
    if max_entries <= 0:
        raise ConfigError("`tool.slopsentinel.history.max-entries` must be > 0.")

    return HistoryConfig(enabled=enabled, path=path, max_entries=max_entries)


def _parse_scoring_config(value: Any) -> ScoringConfig:
    if value is None:
        return ScoringConfig()
    if not isinstance(value, dict):
        raise ConfigError("`tool.slopsentinel.scoring` must be a table.")

    profile_raw = value.get("profile", "default")
    if not isinstance(profile_raw, str):
        raise ConfigError("`tool.slopsentinel.scoring.profile` must be a string.")
    profile = profile_raw.strip().lower() or "default"
    if profile not in _SCORING_PROFILES:
        valid = ", ".join(sorted(_SCORING_PROFILES))
        raise ConfigError(f"`tool.slopsentinel.scoring.profile` must be one of: {valid}.")

    penalties_raw = value.get("penalties", value.get("severity-penalty", value.get("severity_penalty")))
    penalties: dict[str, Mapping[str, int]] = {}
    if penalties_raw is not None:
        if not isinstance(penalties_raw, dict):
            raise ConfigError("`tool.slopsentinel.scoring.penalties` must be a table.")
        for dim_key, dim_table in penalties_raw.items():
            dim = str(dim_key).strip().lower()
            if dim not in _SCORING_DIMS:
                valid_dims = ", ".join(sorted(_SCORING_DIMS))
                raise ConfigError(f"`tool.slopsentinel.scoring.penalties` contains unknown dimension: {dim_key!r}. ({valid_dims})")
            if not isinstance(dim_table, dict):
                raise ConfigError(f"`tool.slopsentinel.scoring.penalties.{dim}` must be a table.")
            dim_penalties: dict[str, int] = {}
            for severity_key, raw_value in dim_table.items():
                sev = str(severity_key).strip().lower()
                if sev not in _SCORING_SEVERITIES:
                    valid_sev = ", ".join(sorted(_SCORING_SEVERITIES))
                    raise ConfigError(
                        f"`tool.slopsentinel.scoring.penalties.{dim}` contains unknown severity: {severity_key!r}. ({valid_sev})"
                    )
                if not isinstance(raw_value, int) or raw_value < 0:
                    raise ConfigError(f"`tool.slopsentinel.scoring.penalties.{dim}.{sev}` must be an integer >= 0.")
                dim_penalties[sev] = int(raw_value)
            penalties[dim] = MappingProxyType(dim_penalties)

    return ScoringConfig(profile=profile, penalties=MappingProxyType(penalties))


def compute_enabled_rule_ids(
    config: SlopSentinelConfig,
    *,
    available_rule_ids: Iterable[RuleId] | None = None,
) -> set[RuleId]:
    """
    Resolve the final enabled rules set from `rules.enable` + `rules.disable`.

    - `enable = "all"` enables all known built-in rules.
    - `enable = ["claude", "generic"]` enables group(s) and/or explicit IDs.
    - `disable = ["A02"]` disables specific IDs (or groups).

    If `available_rule_ids` is provided, the result is intersected with it.
    """

    available: set[RuleId] | None = set(available_rule_ids) if available_rule_ids is not None else None

    enable_spec = config.rules.enable
    enable_tokens: tuple[str, ...]
    if isinstance(enable_spec, str):
        enable_tokens = (enable_spec,)
    else:
        enable_tokens = enable_spec

    enabled: set[RuleId] = set()
    for token in enable_tokens:
        stripped = token.strip()
        normalized_group = _normalize_group(stripped)
        if normalized_group == "all":
            enabled.update(available if available is not None else DEFAULT_RULE_GROUPS["all"])
        elif normalized_group in DEFAULT_RULE_GROUPS:
            enabled.update(DEFAULT_RULE_GROUPS[normalized_group])
        else:
            enabled.add(_normalize_rule_id(stripped))

    for token in config.rules.disable:
        stripped = token.strip()
        normalized_group = _normalize_group(stripped)
        if normalized_group == "all":
            enabled.difference_update(available if available is not None else DEFAULT_RULE_GROUPS["all"])
        elif normalized_group in DEFAULT_RULE_GROUPS:
            enabled.difference_update(DEFAULT_RULE_GROUPS[normalized_group])
        else:
            enabled.discard(_normalize_rule_id(stripped))

    if available is not None:
        enabled.intersection_update(available)

    return enabled


def path_is_ignored(path: Path, *, project_root: Path, ignore_patterns: Iterable[str]) -> bool:
    """
    Return True if `path` matches any ignore patterns.

    Patterns are evaluated against the POSIX-style relative path from `project_root`.

    Supported patterns:
    - Directory prefixes: "tests/" matches "tests/..." anywhere under root.
    - Globs without slashes: "*.generated.*" matches basenames.
    - Globs with slashes: "src/**/generated/*.py" matches full relative paths.
    """

    import fnmatch

    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError, RuntimeError):
        # If the path isn't under root (or can't be resolved), don't ignore it implicitly.
        return False

    rel_posix = relative.as_posix()
    basename = relative.name

    for raw_pattern in ignore_patterns:
        pattern = raw_pattern.strip().replace("\\", "/")
        if not pattern:
            continue
        if pattern.startswith("./"):
            pattern = pattern[2:]

        if pattern.endswith("/"):
            if rel_posix.startswith(pattern):
                return True
            continue

        if "/" in pattern:
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
        else:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(rel_posix, pattern):
                return True

    return False
