from __future__ import annotations

import re
from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line


@dataclass(frozen=True, slots=True)
class O01OpenAIHardcodedApiKey(BaseRule):
    meta = RuleMeta(
        rule_id="O01",
        title="OpenAI API key hardcoded",
        description="Detects likely OpenAI `api_key` assignments with string literals.",
        default_severity="error",
        score_dimension="security",
        fingerprint_model=None,
    )

    _PATTERN = re.compile(r"""(?x)\b(api_key|openai\.api_key)\s*=\s*(['"])(?P<value>[^'"]+)\2""")

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []

        out: list[Violation] = []
        for idx, line in enumerate(ctx.lines, start=1):
            if "os.environ" in line or "getenv(" in line:
                continue
            match = self._PATTERN.search(line)
            if not match:
                continue
            value = match.group("value").strip()
            if not value:
                continue
            out.append(
                self._violation(
                    message="Possible OpenAI API key hardcoded in source.",
                    suggestion='Use an environment variable (e.g. `os.environ.get("OPENAI_API_KEY", "")`).',
                    location=loc_from_line(ctx, line=idx, col=(match.start() + 1)),
                )
            )
        return out


@dataclass(frozen=True, slots=True)
class O02OpenAILegacyChatCompletion(BaseRule):
    meta = RuleMeta(
        rule_id="O02",
        title="Legacy openai.ChatCompletion usage",
        description="Detects legacy `openai.ChatCompletion.create(...)` style calls (older OpenAI Python SDK).",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    _NEEDLE = "openai.ChatCompletion.create"

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []

        out: list[Violation] = []
        for idx, line in enumerate(ctx.lines, start=1):
            if self._NEEDLE not in line:
                continue
            out.append(
                self._violation(
                    message="Found legacy `openai.ChatCompletion.create(...)` call.",
                    suggestion="Consider migrating to the newer client-based OpenAI SDK patterns.",
                    location=loc_from_line(ctx, line=idx, col=line.index(self._NEEDLE) + 1),
                )
            )
        return out


def slopsentinel_rules() -> list[BaseRule]:
    return [O01OpenAIHardcodedApiKey(), O02OpenAILegacyChatCompletion()]


RULES = slopsentinel_rules()

