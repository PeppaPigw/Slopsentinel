from __future__ import annotations

from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line


@dataclass(frozen=True, slots=True)
class S01PythonShellTrue(BaseRule):
    meta = RuleMeta(
        rule_id="S01",
        title="subprocess with shell=True",
        description="Detects `shell=True` usage which is often unsafe in AI-generated code.",
        default_severity="warn",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []
        out: list[Violation] = []
        for idx, line in enumerate(ctx.lines, start=1):
            if "shell=True" not in line:
                continue
            out.append(
                self._violation(
                    message="Found `shell=True` in subprocess call.",
                    suggestion="Avoid `shell=True` unless strictly necessary; pass args as a list.",
                    location=loc_from_line(ctx, line=idx, col=line.index("shell=True") + 1),
                )
            )
        return out


@dataclass(frozen=True, slots=True)
class S02YamlLoadUnsafe(BaseRule):
    meta = RuleMeta(
        rule_id="S02",
        title="yaml.load without safe loader",
        description="Detects `yaml.load(...)` calls without an explicit safe loader.",
        default_severity="warn",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []
        out: list[Violation] = []
        for idx, line in enumerate(ctx.lines, start=1):
            if "yaml.load(" not in line:
                continue
            if "Loader=" in line or "SafeLoader" in line or "safe_load" in line:
                continue
            out.append(
                self._violation(
                    message="Found `yaml.load(...)` without a safe loader.",
                    suggestion="Use `yaml.safe_load(...)` or an explicit safe Loader.",
                    location=loc_from_line(ctx, line=idx, col=line.index("yaml.load(") + 1),
                )
            )
        return out


@dataclass(frozen=True, slots=True)
class S03JavaScriptEval(BaseRule):
    meta = RuleMeta(
        rule_id="S03",
        title="eval() usage",
        description="Detects JavaScript/TypeScript `eval(...)` usage.",
        default_severity="error",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language not in {"javascript", "typescript"}:
            return []
        out: list[Violation] = []
        for idx, line in enumerate(ctx.lines, start=1):
            if "eval(" not in line:
                continue
            out.append(
                self._violation(
                    message="Found `eval(...)` usage.",
                    suggestion="Avoid `eval`; use safer parsing/dispatch patterns instead.",
                    location=loc_from_line(ctx, line=idx, col=line.index("eval(") + 1),
                )
            )
        return out


def slopsentinel_rules() -> list[BaseRule]:
    return [S01PythonShellTrue(), S02YamlLoadUnsafe(), S03JavaScriptEval()]


RULES = slopsentinel_rules()

