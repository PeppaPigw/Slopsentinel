from __future__ import annotations

from pathlib import Path

from slopsentinel.audit import audit_path
from slopsentinel.reporters.sarif import render_sarif


def test_plugin_rules_are_loaded_and_reported(tmp_path: Path, monkeypatch) -> None:
    # Create a small plugin module on disk and add it to sys.path.
    plugin = tmp_path / "my_plugin.py"
    plugin.write_text(
        """
from __future__ import annotations

from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line


@dataclass(frozen=True, slots=True)
class X99PluginRule(BaseRule):
    meta = RuleMeta(
        rule_id="X99",
        title="Plugin rule",
        description="A test plugin rule.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        return [
            self._violation(
                message="Plugin hit",
                location=loc_from_line(ctx, line=1),
            )
        ]


def slopsentinel_rules() -> list[BaseRule]:
    return [X99PluginRule()]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
plugins = ["my_plugin"]
""".lstrip(),
        encoding="utf-8",
    )

    p = tmp_path / "src" / "app.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x = 1\n", encoding="utf-8")

    result = audit_path(tmp_path)
    assert any(v.rule_id == "X99" for v in result.summary.violations)

    sarif = render_sarif(list(result.summary.violations), project_root=tmp_path)
    assert '"id": "X99"' in sarif

