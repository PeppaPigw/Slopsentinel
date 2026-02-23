# Plugin guide

SlopSentinel supports loading additional rules from Python modules.

Plugins are designed to be:

- local-first (no network calls)
- deterministic (stable results)
- easy to disable/suppress

This guide focuses on the current plugin mechanism: importing Python modules
listed in `pyproject.toml`.

## 1) Enable plugins in `pyproject.toml`

```toml
[tool.slopsentinel]
plugins = [
  "my_rules",            # module
  "my_rules:export_rules" # module:attribute or module:function
]
```

Supported exports:

- a module defining `RULES = [BaseRule(), ...]`
- a module defining `slopsentinel_rules() -> list[BaseRule]`
- `module:callable` where the callable returns a list/tuple of `BaseRule` instances

When a plugin fails to import or does not expose rules, SlopSentinel raises
`PluginLoadError`.

## 2) Minimal rule plugin structure

Example module layout:

```
my_rules/
  __init__.py
  rules.py
```

`my_rules/rules.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line


@dataclass(frozen=True, slots=True)
class Z01ExampleRule(BaseRule):
    meta = RuleMeta(
        rule_id="Z01",
        title="Example plugin rule",
        description="Detects an example pattern.",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []
        for idx, line in enumerate(ctx.lines, start=1):
            if "TODO" in line:
                return [
                    self._violation(
                        message="Found TODO.",
                        suggestion="Track work in an issue instead of leaving TODOs in shipped code.",
                        location=loc_from_line(ctx, line=idx),
                    )
                ]
        return []


RULES = [Z01ExampleRule()]
```

## 3) Packaging plugins

Plugins can live:

- inside your repo (simple module)
- as a separate package you install via pip

This repository includes example plugin packages under `examples/`:

- `examples/plugin-openai-slop/`
- `examples/plugin-security/`

Install an example plugin locally:

```bash
python -m pip install -e examples/plugin-openai-slop
```

Then enable it with:

```toml
[tool.slopsentinel]
plugins = ["openai_slop_rules"]
```

## 4) Testing plugins

Treat plugins like any other code:

- write unit tests for positive + negative cases
- keep rules conservative (prefer skipping over risky edits)

Both example plugins ship their own small `pytest` suites.

## 5) AutoFix and plugins

SlopSentinel’s AutoFix support is intentionally conservative and currently
targets a curated set of built-in rule IDs.

Plugin rules can participate in detection/scoring/reporting, but do not
automatically gain AutoFix support unless you contribute a fix implementation to
the core project.

