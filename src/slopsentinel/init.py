from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from slopsentinel.languages.registry import LANGUAGES, detect_language

_DEFAULT_INIT_LANGUAGES: Final[tuple[str, ...]] = tuple(spec.name for spec in LANGUAGES)


def detect_project_languages(project_dir: Path) -> tuple[str, ...]:
    """
    Best-effort project language detection for `slopsentinel init`.

    This scans file extensions and skips common build/venv/vendor directories to
    keep it fast and dependency-free.
    """

    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
    }

    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(project_dir, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        base = Path(dirpath)
        for filename in filenames:
            lang = detect_language(base / filename)
            if lang is not None:
                found.add(lang)

    if not found:
        return _DEFAULT_INIT_LANGUAGES

    order = [spec.name for spec in LANGUAGES]
    return tuple(lang for lang in order if lang in found)


def _pyproject_snippet(*, languages: tuple[str, ...], scoring_profile: str) -> str:
    langs = ", ".join(f"\"{lang}\"" for lang in languages)
    return f"""\

[tool.slopsentinel]
threshold = 60
fail-on-slop = false
languages = [{langs}]
baseline = ".slopsentinel-baseline.json" # optional
plugins = []                             # optional

[tool.slopsentinel.rules]
enable = "all"
disable = []

[tool.slopsentinel.scoring]
profile = "{scoring_profile}"

[tool.slopsentinel.ignore]
paths = ["tests/", "scripts/", "*.generated.*"]

[tool.slopsentinel.cache]
enabled = false
path = ".slopsentinel/cache.json"

[tool.slopsentinel.history]
enabled = false
path = ".slopsentinel/history.json"
max-entries = 200
"""

_GITHUB_WORKFLOW_YML: Final[str] = """\
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
          fail-on-slop: false
          rules: "all"
          sarif: true
          sarif-path: slopsentinel.sarif
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: ${{ steps.slopsentinel.outputs.sarif_path }}
"""

_PRE_COMMIT_CONFIG_YAML: Final[str] = """\
repos:
  - repo: local
    hooks:
      - id: slopsentinel
        name: SlopSentinel
        entry: slopsentinel diff --staged
        language: system
        pass_filenames: false
"""

_PRE_COMMIT_INSERTION_BLOCK: Final[str] = """\
  - repo: local
    hooks:
      - id: slopsentinel
        name: SlopSentinel
        entry: slopsentinel diff --staged
        language: system
        pass_filenames: false
"""


class InitError(RuntimeError):
    """Raised when `slopsentinel init` cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class InitOptions:
    project_dir: Path
    ci: str | None = None
    pre_commit: bool = False
    languages: tuple[str, ...] | None = None
    scoring_profile: str = "default"


@dataclass(frozen=True, slots=True)
class InitResult:
    changed_files: tuple[Path, ...] = ()
    messages: tuple[str, ...] = ()


def init_project(options: InitOptions) -> InitResult:
    """
    Initialize a repository with SlopSentinel config and optional integrations.

    Idempotency rules:
    - Never overwrite existing files.
    - If config/hook/workflow already exists, skip that part.
    - If a file exists but cannot be parsed safely, do not modify it.
    """

    project_dir = options.project_dir
    changed_files: list[Path] = []
    messages: list[str] = []

    pyproject = project_dir / "pyproject.toml"
    languages = options.languages if options.languages is not None else detect_project_languages(project_dir)
    snippet = _pyproject_snippet(languages=languages, scoring_profile=options.scoring_profile)
    changed = _ensure_pyproject_config(pyproject, messages, snippet=snippet)
    if changed:
        changed_files.append(pyproject)

    if options.ci is not None:
        ci_normalized = options.ci.strip().lower()
        if ci_normalized == "github":
            workflow_path = project_dir / ".github" / "workflows" / "slopsentinel.yml"
            changed = _ensure_github_workflow(workflow_path, messages)
            if changed:
                changed_files.append(workflow_path)
        else:
            raise InitError(f"Unsupported CI provider: {options.ci!r} (supported: github).")

    if options.pre_commit:
        precommit_path = project_dir / ".pre-commit-config.yaml"
        changed = _ensure_pre_commit_config(precommit_path, messages)
        if changed:
            changed_files.append(precommit_path)

    if not changed_files:
        messages.append("No changes needed (already initialized).")

    return InitResult(changed_files=tuple(changed_files), messages=tuple(messages))


def _ensure_pyproject_config(pyproject_path: Path, messages: list[str], *, snippet: str) -> bool:
    if pyproject_path.exists():
        existing = pyproject_path.read_text(encoding="utf-8")

        try:
            tomllib.loads(existing)
        except tomllib.TOMLDecodeError as exc:
            messages.append(f"Skipped `pyproject.toml` (invalid TOML: {exc}).")
            return False

        if _has_tool_slopsentinel(existing):
            messages.append("Found existing `[tool.slopsentinel]` in `pyproject.toml`; leaving unchanged.")
            return False

        new_text = existing
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += snippet
        pyproject_path.write_text(new_text, encoding="utf-8")
        messages.append("Appended minimal `[tool.slopsentinel]` config to `pyproject.toml`.")
        return True

    pyproject_path.write_text(snippet.lstrip("\n"), encoding="utf-8")
    messages.append("Created `pyproject.toml` with minimal `[tool.slopsentinel]` config.")
    return True


def _ensure_github_workflow(workflow_path: Path, messages: list[str]) -> bool:
    if workflow_path.exists():
        messages.append(f"Found existing workflow at `{workflow_path}`; leaving unchanged.")
        return False

    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(_GITHUB_WORKFLOW_YML, encoding="utf-8")
    messages.append(f"Created GitHub Actions workflow `{workflow_path}`.")
    return True


def _ensure_pre_commit_config(precommit_path: Path, messages: list[str]) -> bool:
    if not precommit_path.exists():
        precommit_path.write_text(_PRE_COMMIT_CONFIG_YAML, encoding="utf-8")
        messages.append("Created `.pre-commit-config.yaml` with a local SlopSentinel hook.")
        return True

    existing = precommit_path.read_text(encoding="utf-8")
    if _precommit_contains_slopsentinel(existing):
        messages.append("Found existing SlopSentinel hook in `.pre-commit-config.yaml`; leaving unchanged.")
        return False

    updated = _insert_into_precommit_repos(existing)
    if updated is None:
        messages.append("Skipped `.pre-commit-config.yaml` (could not safely insert into `repos:`).")
        return False

    precommit_path.write_text(updated, encoding="utf-8")
    messages.append("Patched `.pre-commit-config.yaml` to add a local SlopSentinel hook.")
    return True


def _has_tool_slopsentinel(pyproject_text: str) -> bool:
    # Conservative check: avoid parsing/rewriting; just look for the table header.
    for line in pyproject_text.splitlines():
        if line.strip() == "[tool.slopsentinel]":
            return True
    return False


def _precommit_contains_slopsentinel(precommit_text: str) -> bool:
    # Best-effort search. Avoid YAML parsing to keep this safe and dependency-free.
    lowered = precommit_text.lower()
    return "id: slopsentinel" in lowered or "id:  slopsentinel" in lowered or "\n- id: slopsentinel" in lowered


def _insert_into_precommit_repos(precommit_text: str) -> str | None:
    """
    Insert `_PRE_COMMIT_INSERTION_BLOCK` as the last item under the top-level `repos:` key.

    This is a minimal, line-based edit to preserve user formatting and comments.
    Returns updated text or None if insertion cannot be done safely.
    """

    lines = precommit_text.splitlines(keepends=True)

    repos_line_index = None
    for i, line in enumerate(lines):
        if line.strip() == "repos:":
            repos_line_index = i
            break

    if repos_line_index is None:
        return None

    # Find the end of the `repos:` block: first non-empty/comment line with indent 0 after repos.
    insertion_index = len(lines)
    for j in range(repos_line_index + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if not lines[j].startswith(" "):  # indent 0 -> new top-level key
            insertion_index = j
            break

    block = _PRE_COMMIT_INSERTION_BLOCK
    if not precommit_text.endswith("\n"):
        block = "\n" + block
    else:
        # Ensure a blank line between existing content and insertion if we're appending at EOF.
        if insertion_index == len(lines) and lines and lines[-1].strip() != "":
            block = "\n" + block

    updated_lines = lines[:insertion_index] + [block] + lines[insertion_index:]
    return "".join(updated_lines)
