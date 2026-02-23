from __future__ import annotations

from pathlib import Path

from openai_slop_rules.rules import O01OpenAIHardcodedApiKey, O02OpenAILegacyChatCompletion

from slopsentinel.engine.context import FileContext
from slopsentinel.suppressions import parse_suppressions


def _ctx(*, text: str) -> FileContext:
    if not text.endswith("\n"):
        text += "\n"
    lines = tuple(text.splitlines(keepends=True))
    return FileContext(
        project_root=Path("."),
        path=Path("example.py"),
        relative_path="example.py",
        language="python",
        text=text,
        lines=lines,
        suppressions=parse_suppressions(lines),
    )


def test_o01_hardcoded_api_key_triggers() -> None:
    ctx = _ctx(text='import openai\nopenai.api_key = "sk-test-123"\n')
    violations = O01OpenAIHardcodedApiKey().check_file(ctx)
    assert [v.rule_id for v in violations] == ["O01"]


def test_o01_env_var_does_not_trigger() -> None:
    ctx = _ctx(text='import os\napi_key = os.environ.get("OPENAI_API_KEY", "")\n')
    violations = O01OpenAIHardcodedApiKey().check_file(ctx)
    assert violations == []


def test_o02_legacy_chatcompletion_triggers() -> None:
    ctx = _ctx(text="import openai\nopenai.ChatCompletion.create(model='gpt-3.5-turbo')\n")
    violations = O02OpenAILegacyChatCompletion().check_file(ctx)
    assert [v.rule_id for v in violations] == ["O02"]
