# Contributing

Thanks for helping improve SlopSentinel.

## Development setup

SlopSentinel is a normal Python package. A virtualenv is the simplest path:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Optional: tree-sitter support (multi-language AST parsing):

```bash
.venv/bin/python -m pip install -e ".[dev,treesitter]"
```

If you prefer Hatch, you can install it and use the scripts in `pyproject.toml`
(see the "Hatch scripts" section below).

Optional: `pre-commit`

```bash
pip install pre-commit
pre-commit install
```

## Quality checks

```bash
ruff check .
mypy src/slopsentinel

# Some environments have global pytest plugins that can crash collection.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest

# Optional: run integration tests (git required)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -m integration
```

CI runs:

- `ruff check .`
- `mypy src/slopsentinel`
- `pytest --cov=slopsentinel --cov-fail-under=90` (unit tests only)
- `pytest -m integration` (integration tests)

## Running benchmarks

Benchmarks are intentionally not part of `pytest` collection. Run them as scripts:

```bash
python tests/bench/bench_scan.py
python tests/bench/bench_rules.py
```

See `docs/performance.md` for details and interpretation guidance.

## Architecture overview

Key modules:

- `src/slopsentinel/scanner.py`: project root detection + file discovery + context building
- `src/slopsentinel/engine/`: detection + scoring
- `src/slopsentinel/rules/`: built-in rules (A/B/C/D/E + polyglot + cross-file)
- `src/slopsentinel/reporters/`: terminal/json/html/sarif/github formatters
- `src/slopsentinel/autofix.py`: conservative rule-level auto-fixes
- `src/slopsentinel/baseline.py`: baselines for gradual adoption
- `src/slopsentinel/cache.py`: file-level result cache
- `src/slopsentinel/history.py`: score history + trend reporting
- `src/slopsentinel/lsp.py`: minimal stdio LSP server (diagnostics + quickfix)

## Adding or changing rules

This repo intentionally keeps rules:

- deterministic (no network)
- conservative by default (easy to suppress, easy to explain)
- fast (avoid expensive per-file work unless it’s cached)

1. Implement the rule (usually as a `BaseRule` subclass) in the appropriate module under `src/slopsentinel/rules/`.
2. Register it in the module’s `builtin_*_rules()` list so `builtin_rules()` discovers it.
3. Add or update examples in `src/slopsentinel/rules/examples.py` (used by `slopsentinel explain` and LSP hover).
4. Update `DEFAULT_RULE_GROUPS` in `src/slopsentinel/config.py` if the rule should be enabled by a default group.
5. Add tests under `tests/test_rules_*.py` (and ideally at least one negative test).
6. Update `CHANGELOG.md` (keep changes user-facing and scannable).

Rule authoring guidelines:

- Keep heuristics deterministic and fast (avoid network and heavy dependencies).
- Prefer conservative checks that are easy to suppress (`slop: disable=...`) and explain.
- Include actionable suggestions.

### Adding a new rule (tutorial)

1) Pick a group module under `src/slopsentinel/rules/` (or create one).

2) Add a `BaseRule` subclass:

```python
from __future__ import annotations

from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line


@dataclass(frozen=True, slots=True)
class E99ExampleRule(BaseRule):
    meta = RuleMeta(
        rule_id="E99",
        title="Example rule",
        description="Detects an example pattern.",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python":
            return []
        if "TODO" in ctx.text:
            return [
                self._violation(
                    message="Found TODO.",
                    suggestion="Track work in an issue instead of leaving TODOs in shipped code.",
                    location=loc_from_line(ctx, line=1),
                )
            ]
        return []
```

3) Register it in that module’s `builtin_*_rules()` so it’s discoverable.

4) Add an entry to `src/slopsentinel/rules/examples.py` so `slop explain E99` and LSP hover can show good/bad snippets.

5) Add tests:

- a positive test (pattern triggers)
- at least one negative test (legit code does not trigger)

6) If this should be enabled by default, add it to the appropriate group in `src/slopsentinel/config.py` (`DEFAULT_RULE_GROUPS`).

7) Add a short entry to `CHANGELOG.md`.

## Plugins (custom rules)

SlopSentinel supports loading rules from Python modules via `plugins = [...]` in `pyproject.toml`:

```toml
[tool.slopsentinel]
plugins = ["my_rules", "my_rules:export_rules"]
```

Supported plugin exports:

- A module attribute `RULES = [BaseRule(), ...]`
- A module function `slopsentinel_rules() -> list[BaseRule]`
- Or `module:callable` where the callable returns a list/tuple of `BaseRule` instances

When a plugin cannot be loaded, SlopSentinel raises `PluginLoadError` (see `src/slopsentinel/rules/plugins.py`).

## Adding AutoFix support (tutorial)

AutoFix is intentionally conservative: it should be safe to run in CI on untrusted code.

High-level flow:

1) Ensure the rule has stable locations (`Violation.location.start_line`) for the edit you want.
2) Add the rule id to `_FIXABLE_RULE_IDS` in `src/slopsentinel/autofix.py`.
3) Implement the edit plan in one of:
   - `_plan_removals(...)` for line deletions
   - `_plan_replacements(...)` for line replacements / insertions
4) Add tests that exercise:
   - the happy path
   - skip paths (syntax errors, name conflicts, unsafe contexts)
5) If applicable, ensure LSP QuickFix support stays correct (code actions call `apply_fixes()`).

Design guidelines:

- Avoid cross-file edits.
- Avoid edits that require semantic type info.
- Prefer single-line edits and stable insertion points.
- If safety is unclear: **skip** (no fix) rather than guessing.

## Conventional commits

Recommended commit prefixes:

- `feat:` new user-visible behavior
- `fix:` bug fix
- `test:` tests only
- `docs:` documentation only
- `chore:` internal maintenance (no behavior change)

## PR checklist

- `ruff check .` passes
- `mypy src/slopsentinel` passes
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest` passes
- (Optional) `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -m integration` passes
- `CHANGELOG.md` updated (when user-facing)

## Release process

See `RELEASING.md`.

## Hatch scripts (optional)

If you use Hatch, you can run:

```bash
hatch run lint
hatch run typecheck
hatch run test
hatch run bench
```
