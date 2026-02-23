# FAQ

## How is SlopSentinel different from ruff / pylint / semgrep?

SlopSentinel is intentionally **not** a general-purpose linter replacement.
It complements your existing tooling by focusing on patterns that show up
disproportionately in AI-assisted code.

- **ruff / pylint**: great for correctness, style, and Python best practices.
  SlopSentinel adds model-fingerprint heuristics, a single 0–100 score, baselines,
  and conservative auto-fixable rules that aim to reduce “slop” noise in PRs.
- **semgrep**: great for custom security and best-practice patterns across
  languages. SlopSentinel is opinionated about AI-shaped patterns and ships a
  curated rule set with built-in scoring, trend/history, and GitHub Action UX.

Many teams run: `ruff` + `mypy` + `pytest` + `slop ci`.

## Does SlopSentinel send my code anywhere?

No. SlopSentinel runs locally on your machine or CI runner.
It does not upload code and does not make network calls during scanning.

Optional features (like tree-sitter parsing for some languages) still run locally.

## Does it work on non-AI code?

Yes. Some rules are generic maintainability and hygiene checks.
The goal is not to classify authorship, but to catch patterns that correlate with
low-quality output (AI-assisted or not).

If you’re adopting SlopSentinel on a mature codebase, use a **baseline** so you
only gate on new findings.

## How do I adopt this on an existing repo without noise?

Use a baseline workflow:

1. Generate a baseline:

   ```bash
   slop baseline .
   ```

2. Commit the generated baseline file (default: `.slopsentinel-baseline.json`).
3. In CI, run `slop ci .` (baseline-aware) or `slop scan .` (if you prefer).

Baselines suppress *existing* findings so you can fix issues gradually.

## How do I suppress a false positive?

You can suppress via:

- **Inline directive**:

  ```python
  x = do_thing()  # slop: disable=E09
  ```

- **Project config** (`pyproject.toml`):

  ```toml
  [tool.slopsentinel.rules]
  disable = ["E09"]
  ```

Tip: prefer disabling the smallest scope possible (a single line or file) to keep
signal strong.

## Can I write custom rules?

Yes. SlopSentinel supports **plugins**:

```toml
[tool.slopsentinel]
plugins = ["my_rules", "my_rules:export_rules"]
```

See `CONTRIBUTING.md` for the supported plugin exports and error handling.

## What languages are supported?

Out of the box, SlopSentinel supports:

- Python
- JavaScript / TypeScript
- Go
- Rust
- Java
- Kotlin
- Ruby
- PHP

Some checks are language-specific; others are generic line-based heuristics.

## Does it support IDE integration?

Yes. SlopSentinel ships a minimal stdio LSP server:

```bash
slop lsp
```

See `docs/ide-integration.md` for editor configuration examples.

## What’s the recommended CI setup?

Two common options:

- **CLI**: use the CI wrapper (stable exit codes, baseline-aware):

  ```bash
  slop ci . --fail-under 75
  ```

- **GitHub Action**: use `slopsentinel/action` to annotate PRs and/or upload SARIF.

See `README.md` for a ready-to-copy workflow.

## How accurate is the “AI confidence” label?

It’s a heuristic label derived from fingerprint-rule hits.
It is **not** a classifier and should be interpreted as a “pattern similarity”
signal, not authorship attribution.

If you want to gate purely on risk/quality, use `--fail-under` and adjust rule
groups / severities.

