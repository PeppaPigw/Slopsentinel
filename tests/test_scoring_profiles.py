from __future__ import annotations

from slopsentinel.config import ScoringConfig
from slopsentinel.engine.scoring import summarize
from slopsentinel.engine.types import Location, Violation


def test_scoring_profiles_change_score() -> None:
    violations = [
        Violation(
            rule_id="E99",
            severity="warn",
            message="x",
            dimension="quality",
            suggestion=None,
            location=Location(path=None, start_line=None, start_col=None),
        )
        for _ in range(3)
    ]

    default = summarize(files_scanned=1, violations=violations)
    strict = summarize(files_scanned=1, violations=violations, scoring=ScoringConfig(profile="strict"))
    lenient = summarize(files_scanned=1, violations=violations, scoring=ScoringConfig(profile="lenient"))

    assert strict.score <= default.score
    assert lenient.score >= default.score


def test_scoring_penalty_overrides_are_applied() -> None:
    v = Violation(
        rule_id="E99",
        severity="warn",
        message="x",
        dimension="quality",
        suggestion=None,
        location=None,
    )
    default = summarize(files_scanned=1, violations=[v, v])
    harsh = summarize(files_scanned=1, violations=[v, v], scoring=ScoringConfig(profile="default", penalties={"quality": {"warn": 10}}))
    assert harsh.score < default.score
