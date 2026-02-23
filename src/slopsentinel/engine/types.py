from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["info", "warn", "error"]
Dimension = Literal["fingerprint", "quality", "hallucination", "maintainability", "security"]
AiConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class Location:
    path: Path | None = None
    start_line: int | None = None  # 1-based
    start_col: int | None = None  # 1-based
    end_line: int | None = None  # 1-based
    end_col: int | None = None  # 1-based


@dataclass(frozen=True, slots=True)
class Violation:
    rule_id: str
    severity: Severity
    message: str
    dimension: Dimension
    suggestion: str | None = None
    location: Location | None = None


@dataclass(frozen=True, slots=True)
class RuleStats:
    rule_id: str
    count: int


@dataclass(frozen=True, slots=True)
class DimensionBreakdown:
    fingerprint: int
    quality: int
    hallucination: int
    maintainability: int
    security: int


@dataclass(frozen=True, slots=True)
class ScanSummary:
    files_scanned: int
    violations: tuple[Violation, ...]
    score: int
    breakdown: DimensionBreakdown
    dominant_fingerprints: tuple[str, ...] = ()
    ai_confidence: AiConfidence = "low"
    violation_density: float = 0.0
    violation_clustering: float = 0.0
    scoring_profile: str = "default"
