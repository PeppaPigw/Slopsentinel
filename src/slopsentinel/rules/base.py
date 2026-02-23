from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.engine.types import Dimension, Location, Severity, Violation


@dataclass(frozen=True, slots=True)
class RuleMeta:
    rule_id: str
    title: str
    description: str
    default_severity: Severity
    score_dimension: Dimension
    fingerprint_model: str | None = None  # "claude" | "cursor" | "copilot" | "gemini"


class BaseRule(ABC):
    meta: RuleMeta

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        return []

    def check_file(self, ctx: FileContext) -> list[Violation]:
        return []

    def _violation(
        self,
        *,
        message: str,
        suggestion: str | None = None,
        location: Location | None = None,
        severity: Severity | None = None,
    ) -> Violation:
        return Violation(
            rule_id=self.meta.rule_id,
            severity=severity or self.meta.default_severity,
            message=message,
            suggestion=suggestion,
            dimension=self.meta.score_dimension,
            location=location,
        )


def loc_from_line(
    ctx: FileContext, *, line: int, col: int | None = 1, end_line: int | None = None, end_col: int | None = None
) -> Location:
    return Location(
        path=ctx.path,
        start_line=line,
        start_col=col,
        end_line=end_line,
        end_col=end_col,
    )

