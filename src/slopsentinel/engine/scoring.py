from __future__ import annotations

from copy import deepcopy
from typing import cast

from slopsentinel.config import ScoringConfig
from slopsentinel.engine.types import (
    AiConfidence,
    DimensionBreakdown,
    ScanSummary,
    Severity,
    Violation,
)
from slopsentinel.rules.registry import rule_meta_by_id

# Dimension budgets (max points) sum to 100 and intentionally mirror the product
# breakdown described in TaskBook/README:
# - "fingerprint" is the largest share to reflect AI-confidence signals
# - "hallucination" is heavy because broken imports/APIs are high-impact
# - "security" is smaller but still meaningful
DIMENSION_MAX = {
    "fingerprint": 35,
    "quality": 25,
    "hallucination": 20,
    "maintainability": 15,
    "security": 5,
}

# Stable presentation order for reports. Keep this independent from dict ordering.
DIMENSION_ORDER = ("fingerprint", "quality", "hallucination", "maintainability", "security")

DIMENSION_LABELS = {
    "fingerprint": "Fingerprint",
    "quality": "Quality",
    "hallucination": "Hallucination",
    "maintainability": "Maintainability",
    "security": "Security",
}

# Severity penalties are dimension-specific: hallucinations and security issues should
# crush the score quickly, while "fingerprint" style signals are lighter.
#
# These numbers are intentionally simple integers that saturate each dimension
# budget within a small number of high-severity findings, to keep CI behavior
# predictable and easy to reason about. (A future version may allow overriding
# these via configuration.)
SEVERITY_PENALTY: dict[str, dict[Severity, int]] = {
    "fingerprint": {"info": 1, "warn": 2, "error": 3},
    "quality": {"info": 1, "warn": 3, "error": 5},
    "hallucination": {"info": 4, "warn": 10, "error": 20},
    "maintainability": {"info": 1, "warn": 3, "error": 5},
    "security": {"info": 1, "warn": 3, "error": 5},
}

_SEVERITY_PENALTY_PROFILES: dict[str, dict[str, dict[Severity, int]]] = {
    "default": SEVERITY_PENALTY,
    # Stricter penalties for teams that want to block sooner on quality/security risks.
    "strict": {
        "fingerprint": {"info": 1, "warn": 3, "error": 5},
        "quality": {"info": 1, "warn": 4, "error": 7},
        "hallucination": {"info": 5, "warn": 12, "error": 20},
        "maintainability": {"info": 1, "warn": 4, "error": 7},
        "security": {"info": 2, "warn": 5, "error": 10},
    },
    # Lenient penalties for gradual adoption (focus on the most severe findings).
    "lenient": {
        "fingerprint": {"info": 0, "warn": 1, "error": 2},
        "quality": {"info": 0, "warn": 2, "error": 4},
        "hallucination": {"info": 2, "warn": 6, "error": 12},
        "maintainability": {"info": 0, "warn": 2, "error": 4},
        "security": {"info": 0, "warn": 2, "error": 4},
    },
}


def resolve_severity_penalty(scoring: ScoringConfig | None) -> dict[str, dict[Severity, int]]:
    """
    Return the effective severity penalty mapping for a run.

    The mapping is deterministic, validated by config parsing, and suitable for
    caching/fingerprinting.
    """

    profile_name = (scoring.profile if scoring is not None else "default").strip().lower() or "default"
    base = _SEVERITY_PENALTY_PROFILES.get(profile_name, SEVERITY_PENALTY)
    merged: dict[str, dict[Severity, int]] = deepcopy(base)

    if scoring is None:
        return merged

    for dim, overrides in scoring.penalties.items():
        dim_key = dim.strip().lower()
        if dim_key not in merged:
            continue
        for sev, value in overrides.items():
            sev_key = sev.strip().lower()
            if sev_key not in {"info", "warn", "error"}:
                continue
            merged[dim_key][cast(Severity, sev_key)] = int(value)

    return merged


def format_breakdown_terminal(breakdown: DimensionBreakdown) -> str:
    parts: list[str] = []
    for dim in DIMENSION_ORDER:
        label = DIMENSION_LABELS.get(dim, dim.title())
        value = getattr(breakdown, dim)
        parts.append(f"{label} {value}/{DIMENSION_MAX[dim]}")
    return " | ".join(parts)


def format_breakdown_markdown(breakdown: DimensionBreakdown) -> str:
    parts: list[str] = []
    for dim in DIMENSION_ORDER:
        value = getattr(breakdown, dim)
        parts.append(f"{dim} {value}/{DIMENSION_MAX[dim]}")
    return ", ".join(parts)


def summarize(files_scanned: int, violations: list[Violation], *, scoring: ScoringConfig | None = None) -> ScanSummary:
    effective_penalties = resolve_severity_penalty(scoring)
    density, clustering = compute_density_and_clustering(files_scanned, violations)
    breakdown = compute_breakdown(violations, density=density, clustering=clustering, severity_penalty=effective_penalties)
    score = sum(getattr(breakdown, dim) for dim in DIMENSION_ORDER)
    dominant = compute_dominant_fingerprints(violations)
    confidence = compute_ai_confidence(violations, density=density, clustering=clustering)
    return ScanSummary(
        files_scanned=files_scanned,
        violations=tuple(violations),
        score=int(score),
        breakdown=breakdown,
        dominant_fingerprints=dominant,
        ai_confidence=confidence,
        violation_density=float(density),
        violation_clustering=float(clustering),
        scoring_profile=(scoring.profile if scoring is not None else "default"),
    )


def compute_breakdown(
    violations: list[Violation],
    *,
    density: float,
    clustering: float,
    severity_penalty: dict[str, dict[Severity, int]] = SEVERITY_PENALTY,
) -> DimensionBreakdown:
    penalties = {k: 0 for k in DIMENSION_MAX}

    for v in violations:
        dim = v.dimension
        if dim not in penalties:
            continue
        penalties[dim] += severity_penalty[dim][v.severity]

    def score_for(dim: str) -> int:
        max_points = DIMENSION_MAX[dim]
        penalty = min(max_points, penalties[dim])
        return max_points - penalty

    breakdown = DimensionBreakdown(
        fingerprint=score_for("fingerprint"),
        quality=score_for("quality"),
        hallucination=score_for("hallucination"),
        maintainability=score_for("maintainability"),
        security=score_for("security"),
    )

    # Incorporate structure signals (density + clustering) as a small,
    # deterministic quality adjustment. We keep the dimension sum at 100 by
    # subtracting from "quality" only (bounded), so reports remain consistent.
    structure_penalty = _structure_penalty(density=density, clustering=clustering, total=len(violations))
    if structure_penalty <= 0:
        return breakdown
    return DimensionBreakdown(
        fingerprint=breakdown.fingerprint,
        quality=max(0, breakdown.quality - structure_penalty),
        hallucination=breakdown.hallucination,
        maintainability=breakdown.maintainability,
        security=breakdown.security,
    )


def compute_dominant_fingerprints(violations: list[Violation]) -> tuple[str, ...]:
    meta = rule_meta_by_id()
    counts: dict[str, int] = {}
    for v in violations:
        m = meta.get(v.rule_id)
        model = m.fingerprint_model if m else None
        if not model:
            continue
        counts[model] = counts.get(model, 0) + 1

    if not counts:
        return ()

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(model for model, _ in ordered[:2])


def compute_density_and_clustering(files_scanned: int, violations: list[Violation]) -> tuple[float, float]:
    """
    Return (density, clustering) signals for the run.

    - density: violations per scanned file (including repo-level findings)
    - clustering: fraction of file-level violations concentrated in the worst file
    """

    total = len(violations)
    density = float(total) / float(max(1, files_scanned))

    by_file: dict[str, int] = {}
    file_total = 0
    for v in violations:
        if v.location is None or v.location.path is None:
            continue
        file_total += 1
        key = str(v.location.path)
        by_file[key] = by_file.get(key, 0) + 1

    max_in_one = max(by_file.values(), default=0)
    clustering = float(max_in_one) / float(file_total) if file_total else 0.0

    # Keep stable for equality comparisons and JSON output.
    return round(density, 3), round(clustering, 3)


def compute_ai_confidence(violations: list[Violation], *, density: float, clustering: float) -> AiConfidence:
    """
    Return a conservative AI-confidence label based on fingerprint rules.

    This intentionally does not claim authorship; it is a heuristic for how
    strong AI-like signals are in the analyzed code.
    """

    meta = rule_meta_by_id()
    model_hits = 0
    models: set[str] = set()
    for v in violations:
        m = meta.get(v.rule_id)
        if m and m.fingerprint_model:
            model_hits += 1
            models.add(m.fingerprint_model)

    if model_hits >= 8 or (model_hits >= 4 and len(models) >= 2):
        return "high"
    if model_hits >= 3:
        return "medium"
    # Allow density/clustering to bump borderline cases without being noisy.
    if model_hits >= 2 and len(models) >= 2 and (density >= 2.0 or clustering >= 0.6):
        return "medium"
    return "low"


def _structure_penalty(*, density: float, clustering: float, total: int) -> int:
    """
    Compute a small penalty that reflects how "slop" findings concentrate.

    This is bounded and deliberately simple so CI behavior stays predictable.
    """

    if total <= 0:
        return 0

    penalty = 0
    if density > 2.0:
        # One point per extra violation/file beyond 2.0, up to 6.
        penalty += min(6, int(density - 2.0))

    if total >= 10 and clustering > 0.6:
        # Up to 4 points when findings concentrate heavily.
        penalty += min(4, int((clustering - 0.6) * 10.0))

    return max(0, min(10, penalty))
