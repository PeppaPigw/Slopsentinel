# Quickstart (5 minutes)

This guide is a slightly more detailed version of `README.md`.
It’s designed to be copy/pasteable and safe to try on an existing repo.

## 1) Install

```bash
pip install slopsentinel
```

You’ll get two equivalent entrypoints:

- `slopsentinel`
- `slop` (short alias)

## 2) Run a scan

From your repo root:

```bash
slop scan .
```

Want a machine-readable report?

```bash
slop scan . --format json > slopsentinel.json
slop scan . --format sarif > slopsentinel.sarif
slop scan . --format html > slopsentinel.html
slop scan . --format markdown > slopsentinel.md
```

## 3) Preview conservative auto-fixes

SlopSentinel can apply **conservative, rule-level** fixes (no cross-file edits).
Start with a dry-run:

```bash
slop fix . --dry-run
```

If the diff looks good:

```bash
slop fix . --backup
```

## 4) Adopt on an existing repo (baseline workflow)

If you have an established codebase, avoid noisy “fix everything at once” rollouts.
Generate a baseline so CI only cares about *new* findings:

```bash
slop baseline .
```

Commit the generated baseline file (default: `.slopsentinel-baseline.json`).

Then use the CI-friendly wrapper:

```bash
slop ci . --fail-under 75
```

## 5) Add CI gating

### GitHub Actions (recommended)

Example `.github/workflows/slopsentinel.yml`:

```yaml
name: SlopSentinel
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  security-events: write

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: slopsentinel
        uses: slopsentinel/action@v1
        with:
          github-token: ${{ github.token }}
          threshold: 60
          comment: true
          sarif: true
          sarif-path: slopsentinel.sarif
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: ${{ steps.slopsentinel.outputs.sarif_path }}
```

### Generic CI

Run:

```bash
slop ci . --fail-under 75 --format terminal
```

Exit codes are stable:

- `0`: pass
- `1`: score below threshold / policy failure
- `2`: configuration error

## 6) Track score over time (trend/history)

Enable history recording in `pyproject.toml`:

```toml
[tool.slopsentinel.history]
enabled = true
```

After scans, render the last few runs:

```bash
slop trend --format terminal
slop trend --format json
slop trend --format html > trend.html
```

## 7) Watch mode (incremental re-scan)

If you install optional watch support:

```bash
pip install "slopsentinel[watch]"
```

Run:

```bash
slop watch src/ --profile strict
```

## 8) IDE integration (LSP)

Run the LSP server:

```bash
slop lsp
```

See `docs/ide-integration.md` for Neovim / VS Code / Emacs examples.

## 9) Configuration overview

Minimal `pyproject.toml`:

```toml
[tool.slopsentinel]
threshold = 60
fail-on-slop = false
languages = ["python", "typescript", "javascript", "go", "rust", "java", "kotlin", "ruby", "php"]
baseline = ".slopsentinel-baseline.json"

[tool.slopsentinel.rules]
enable = "all"
disable = []
severity_overrides = { "A03" = "warning", "C01" = "info" }
```

More docs:

- `docs/RULES.md`: full rule reference + examples
- `docs/scoring.md`: how the 0–100 score is computed
- `docs/ARCHITECTURE.md`: engine / rules / reporters overview

