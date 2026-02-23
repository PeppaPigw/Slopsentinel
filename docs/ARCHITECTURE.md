# Architecture

SlopSentinel is designed to be **local-first**, deterministic, and safe to run
in CI without network access.

## Design goals

- **Local-first**: scanning never uploads code and does not require API keys.
- **Deterministic**: given the same inputs, results should be stable.
- **CI-safe**: runs on untrusted PR code; conservative defaults.
- **Fast enough**: parallel file evaluation + file-level caching.
- **Actionable**: line-level findings, clear suggestions, and conservative auto-fixes.

Non-goals:

- Replacing `ruff`, `pylint`, `mypy`, `semgrep`, or a real security audit.
- Doing whole-program type inference or semantic refactors.
- “AI vs human” authorship classification (SlopSentinel reports heuristic signals).

## High-level flow

1. **Target resolution** (`scanner.prepare_target`)
   - Detects project root (git root when available)
   - Loads configuration from `pyproject.toml`
2. **File discovery** (`scanner.discover_files`)
   - Filters by enabled languages/extensions
   - Applies ignore patterns
3. **Context build**
   - `ProjectContext`: immutable project-level view
   - `FileContext`: immutable per-file view (text, lines, suppressions, ASTs)
4. **Rule execution** (`engine.detection.detect`)
   - Project-level rules first (`check_project`)
   - File-level rules next (`check_file`)
   - Applies severity overrides + suppressions
   - Supports parallel file evaluation via thread pool
5. **Optional post-processing**
   - **Baseline** filtering (full scans only)
   - **Cache** read/write (file-level)
   - **History** append (full scans only)
6. **Scoring + reporting**
   - `engine.scoring.summarize` produces `ScanSummary`
   - Reporters render terminal/JSON/SARIF/HTML/GitHub annotations

## System diagram (bird’s eye view)

```
             ┌──────────────────────────────────────────────┐
             │                    CLI                        │
             │  scan / diff / fix / baseline / trend / lsp   │
             └───────────────┬──────────────────────────────┘
                             │
                             v
┌──────────────────────────────────────────────┐
│                 scanner.py                   │
│  - project root detection                     │
│  - config load (pyproject.toml)               │
│  - file discovery + language detection        │
│  - build ProjectContext + FileContext         │
└───────────────┬──────────────────────────────┘
                │ contexts
                v
┌──────────────────────────────────────────────┐
│              engine/detection.py             │
│  - resolve enabled rules (global + overrides) │
│  - run check_project + check_file             │
│  - apply suppressions + severity overrides    │
│  - changed-lines filtering for diff scans     │
│  - file-level cache integration               │
└───────────────┬──────────────────────────────┘
                │ violations
                v
┌──────────────────────────────────────────────┐
│              engine/scoring.py               │
│  - per-dimension penalties + profiles         │
│  - density/clustering structure signals       │
│  - ai_confidence label                        │
└───────────────┬──────────────────────────────┘
                │ ScanSummary
                v
┌──────────────────────────────────────────────┐
│                reporters/*                   │
│  terminal / json / sarif / html / github      │
└──────────────────────────────────────────────┘
```

## Core data types

### Context objects

SlopSentinel builds immutable context objects for rule execution:

- `ProjectContext` (`src/slopsentinel/engine/context.py`)
  - `project_root`, `scan_path`, `files`, `config`
- `FileContext`
  - `path`, `relative_path`, `language`
  - `text`, `lines` (used by most rules)
  - `suppressions` (parsed from inline directives)
  - `python_ast` (only for Python files, best-effort)
  - `syntax_tree` (tree-sitter, when enabled and available)

### Findings and summaries

- `Violation` (`src/slopsentinel/engine/types.py`)
  - `rule_id`, `severity`, `dimension`, `message`, `suggestion`, `location`
- `ScanSummary` (same module)
  - overall `score` (0–100)
  - per-dimension breakdown + structure signals
  - list of violations

## File discovery and language detection

`scanner.discover_files()` walks the scan path and applies:

- skip directories (`DEFAULT_SKIP_DIRS`)
- allowed extensions based on enabled languages (`languages/registry.py`)
- ignore patterns from config (`config.path_is_ignored`)

Language detection is extension-based (by design): fast and deterministic.

## Rules: structure and execution

### Rule interface

Rules are `BaseRule` subclasses (`src/slopsentinel/rules/base.py`) with:

- `meta: RuleMeta` (id/title/description/severity/dimension)
- `check_project(ProjectContext) -> list[Violation]`
- `check_file(FileContext) -> list[Violation]`

Rules should:

- avoid network access
- be fast and deterministic
- return stable locations when possible (`Violation.location.start_line`)

### Rule registry

SlopSentinel keeps rule discovery centralized:

- built-in rules live under `src/slopsentinel/rules/`
- `rules/registry.py` exposes:
  - `builtin_rules()` (built-ins)
  - `all_rules()` (built-ins + plugin rules)

### Configuration: enabling/disabling rules

Rule selection is controlled by `SlopSentinelConfig` (`src/slopsentinel/config.py`):

- rule groups (`DEFAULT_RULE_GROUPS`)
- rules config:
  - enable/disable sets
  - per-rule overrides (including severity)
  - `severity_overrides` shorthand map
- directory overrides (`[tool.slopsentinel.overrides."path/"]`)

The detection engine computes:

- enabled rule ids for project-level checks
- a superset of enabled rule ids for file-level checks (because directory overrides
  can enable additional rules in subtrees)

### Suppressions

Inline directives are parsed by `suppressions.parse_suppressions()`:

- `slop: disable-file=A03,C01`
- `slop: disable=A03,C01`
- `slop: disable-next-line=C01`

Suppressions are applied after rule execution so the rule logic stays simple.

## Diff scanning

Diff scanning (`slop diff`) focuses on changed lines:

1. Use `gitdiff.py` to compute a mapping of changed line numbers.
2. Run file-level rules (optionally cached).
3. Filter violations to those landing on changed lines.

Project-level rules are skipped for diff scans because they can’t be reliably
mapped to line changes.

## Cache

`FileViolationCache` (`src/slopsentinel/cache.py`) stores full per-file
violations keyed by:

- `relative_path`
- file content hash (`file_content_hash()`)
- a config fingerprint (enabled rules + overrides + plugins + tool version)

Cache goals:

- preserve determinism (content-hash based keys)
- avoid recomputation (especially AST/tree-sitter work)
- keep diff scans fast (compute full results once, filter after)

## Baselines

Baselines suppress *existing* findings in full-repo scans, enabling gradual
adoption.

- Generation: `slop baseline .` (`src/slopsentinel/baseline.py`)
- Application: baseline filtering is applied after detection (full scans only).

Baseline formats:

- **v1**: `(rule_id, path, line)` matching (simple but line numbers drift)
- **v2**: fingerprint-based matching (more resilient to drift)

Diff scans intentionally do not apply the baseline by default.

## Scoring

The scoring model lives in `src/slopsentinel/engine/scoring.py`.

Key ideas:

- one bounded 0–100 score
- five dimensions (fingerprint / quality / hallucination / maintainability / security)
- severity penalties are dimension-specific and profile-driven
- a small structure penalty uses density + clustering to discourage “one file full
  of slop” patterns

For full details see `docs/scoring.md`.

## Reporters and formats

Reporters live under `src/slopsentinel/reporters/`:

- `terminal`: human-friendly Rich output
- `json`: stable machine format + JSON Schema metadata
- `sarif`: GitHub Code Scanning compatible output
- `html`: standalone HTML report (stdlib only)
- `markdown`: Markdown summary/table output
- `github`: GitHub Actions-style annotations (`::error file=...`)

The `slop report` command lets you re-render a saved JSON report into a
different output format.

## AutoFix framework

AutoFix is intentionally conservative (safe to run in CI on untrusted code).

High-level flow (`src/slopsentinel/autofix.py`):

1. Plan edits for a subset of fixable rule ids.
2. Merge edits safely (skip conflicting edits).
3. Apply changes to files (or render diffs in `--dry-run`).

Edits are represented as:

- `LineRemoval`: delete a line range
- `LineReplacement`: replace/insert text at a specific line

When safety checks fail (syntax errors, conflicts, ambiguous edits), the fix is
skipped rather than guessed.

## LSP server

The LSP implementation (`src/slopsentinel/lsp.py`) is a minimal stdio server:

- reads JSON-RPC messages from stdin
- supports:
  - diagnostics
  - hover (rule metadata + examples when available)
  - code actions (QuickFix edits powered by AutoFix planning)

See `docs/ide-integration.md` for client configuration examples.

## Watch mode

Watch mode (`slop watch`) lives in `src/slopsentinel/watch.py` and provides an
incremental “re-scan on file change” loop.

It uses `watchdog` when installed (`pip install "slopsentinel[watch]"`) and
reuses the same scanning + caching pipeline.

## Plugins

Plugins add rule objects from external modules:

- Config: `tool.slopsentinel.plugins = ["module", "module:callable"]`
- Loader: `src/slopsentinel/rules/plugins.py`

Plugins integrate with scoring/reporting because they register normal `BaseRule`
instances with `RuleMeta` metadata.

See `docs/plugin-guide.md` and the example plugins under `examples/`.

## Plugins

Plugins are loaded from `tool.slopsentinel.plugins`. At runtime:

- `rules/plugins.py` loads rule objects from modules / callables
- `rules/registry.set_extra_rules` registers them process-wide
- Reporters and scoring can resolve plugin metadata via the registry

## Cache

The file cache stores **full per-file violations** keyed by:

- `relative_path`
- file content hash
- config fingerprint (enabled rules + overrides + plugins + tool version)

This enables deterministic results even when running `diff` scans (filtering to
changed lines is applied after reading full cached results).

## Baseline

Baselines suppress existing findings for full scans. The current format is:

- v1: `(rule_id, path, line)` matching
- v2: fingerprint-based matching for line-number drift resilience

`diff` scans intentionally do not apply the baseline by default.
