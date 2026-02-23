# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.0.0] - 2026-02-23

### Added

**Rules (50+ across 9 languages)**

- Claude fingerprint rules: A01–A12 (excessive comments, thinking blocks, apology comments, narrative control flow, placeholder apologies, etc.)
- Cursor fingerprint rules: B01–B08 (redundant TODOs, over-scaffolded stubs, etc.)
- Copilot fingerprint rules: C01–C11 (generic names, boilerplate patterns, etc.)
- Gemini fingerprint rules: D01–D06 (comprehensive-style comments, etc.)
- Generic AI rules: E01–E12 (unused imports, bare except, hardcoded credentials, function too long, isinstance chains, etc.)
- Go rules: G01–G07
- Rust rules: R01–R07
- Java rules: J01–J03
- Kotlin rules: K01–K03
- Ruby rules: Y01–Y03
- PHP rules: P01–P03
- Cross-file rules: X01–X05 (duplicate logic, naming inconsistency, circular imports, missing test files)

**CLI (14 commands)**

- `slop scan` — full repo scan with terminal/JSON/SARIF/HTML/Markdown output
- `slop fix` — conservative rule-level auto-fix with dry-run + diff preview
- `slop deslop` — comment-only mechanical cleanup
- `slop diff` — scan only changed lines (PR diff mode)
- `slop baseline` — generate/update baseline to suppress existing findings
- `slop trend` — score history with terminal/JSON/HTML output
- `slop watch` — incremental re-scan on file save (watchdog)
- `slop lsp` — stdio LSP server (diagnostics + hover + codeAction)
- `slop report` — generate standalone HTML/Markdown report from JSON
- `slop compare` — compare two scan results
- `slop ci` — CI-optimised scan with threshold enforcement
- `slop rules` — list/filter available rules
- `slop explain` — show rule details + examples
- `slop init` — generate starter `pyproject.toml` config

**AutoFix support for:** A03, A04, A06, A10, C09, D01, E03, E04, E06, E09, E11

**Infrastructure**

- GitHub Action with PR review comments + SARIF upload
- LSP server: hover (rule details) + codeAction (QuickFix)
- Plugin system via `tool.slopsentinel.plugins` (module imports: `module` / `module:callable`)
- File-level caching with content hash
- Baseline mechanism with v1/v2 fingerprinting
- Score history + trend tracking (HTML chart, JSON, terminal output)
- Directory overrides (longest-prefix match)
- Severity overrides per rule
- Scoring profiles: default / strict / lenient
- SARIF 2.1.0 output for GitHub Code Scanning
- JSON Schema for config (`schemas/slopsentinel-config.schema.json`)
- JSON Schema for report (`schemas/slopsentinel-report.schema.json`)
- Dockerfile for GitHub Action
- pre-commit hook support
- VS Code extension skeleton (`vscode-slopsentinel/`)
- 574 unit tests (+ integration suite), 94% coverage, mypy strict, ruff clean
- Python 3.11+, 9 languages supported

## [0.1.0] - 2026-02-01

- Initial MVP: CLI + GitHub Action
- Built-in rules for model fingerprints and generic AI anti-patterns
- Terminal / JSON / SARIF output
- PR diff scanning and line-level PR review comments

[Unreleased]: https://github.com/slopsentinel/slopsentinel/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/slopsentinel/slopsentinel/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/slopsentinel/slopsentinel/releases/tag/v0.1.0

