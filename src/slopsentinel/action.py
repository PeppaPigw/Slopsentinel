from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from slopsentinel.action_github import _post_pull_request_comments
from slopsentinel.action_markdown import _write_step_summary
from slopsentinel.action_sarif import _maybe_write_sarif
from slopsentinel.audit import audit_files
from slopsentinel.engine.types import ScanSummary
from slopsentinel.git import GitError, git_check_call, git_check_output
from slopsentinel.gitdiff import changed_lines_between
from slopsentinel.reporters.github import render_github_annotations
from slopsentinel.scanner import ScanTarget, discover_files, prepare_target


def main() -> None:
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(workspace)

    threshold = _as_int(_get_input("threshold", "60"), default=60)
    comment = _as_bool(_get_input("comment", "true"), default=True)
    fail_on_slop = _as_bool(_get_input("fail-on-slop", _get_input("fail_on_slop", "false")), default=False)
    rules_spec = _get_input("rules", "all").strip()
    sarif_enabled = _as_bool(_get_input("sarif", "true"), default=True)
    sarif_path_spec = _get_input("sarif-path", "slopsentinel.sarif").strip()

    target = prepare_target(workspace)
    target = _override_target(target, threshold=threshold, fail_on_slop=fail_on_slop, rules_spec=rules_spec)

    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    event = _load_event(event_path)

    pull_request: dict[str, Any] | None = None
    if isinstance(event, dict):
        pr = event.get("pull_request")
        if isinstance(pr, dict):
            pull_request = cast(dict[str, Any], pr)

    is_pull_request = pull_request is not None
    if pull_request is not None:
        pr = pull_request
        pull_number = int(pr["number"])
        base_sha = str(cast(dict[str, Any], pr["base"])["sha"])
        head_sha = str(cast(dict[str, Any], pr["head"])["sha"])

        _ensure_git_object(base_sha)
        _ensure_git_object(head_sha)

        changed = changed_lines_between(base_sha, head_sha, cwd=workspace, scope=workspace)
        files = sorted(changed.keys())
        discovered = set(discover_files(target))
        files = [p for p in files if p in discovered]
        result = audit_files(target, files=files, changed_lines=changed)
    else:
        files = discover_files(target)
        result = audit_files(target, files=files)
        pull_number = None
        base_sha = None
        head_sha = os.environ.get("GITHUB_SHA") or ""

    sarif_path = _maybe_write_sarif(
        enabled=sarif_enabled,
        sarif_path_spec=sarif_path_spec,
        summary=result.summary,
        project_root=result.target.project_root,
        workspace=workspace,
    )

    _write_outputs(result.summary, sarif_path=sarif_path)
    _write_step_summary(result.summary)

    # Always emit GitHub Actions annotations so users see findings in the check UI.
    print(render_github_annotations(list(result.summary.violations), project_root=result.target.project_root))

    if comment and is_pull_request:
        token = _get_input("github-token", "").strip() or os.environ.get("GITHUB_TOKEN") or os.environ.get("INPUT_GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if token and repo and pull_number and head_sha:
            _post_pull_request_comments(
                violations=list(result.summary.violations),
                token=token,
                repository=repo,
                pull_number=pull_number,
                commit_id=head_sha,
                project_root=result.target.project_root,
            )
        else:
            _eprint("PR commenting requested, but required env is missing (GITHUB_TOKEN/GITHUB_REPOSITORY/PR context).")

    if result.summary.score < threshold and fail_on_slop:
        _eprint(f"Score {result.summary.score} is below threshold {threshold}.")
        raise SystemExit(1)


def _override_target(target: ScanTarget, *, threshold: int, fail_on_slop: bool, rules_spec: str) -> ScanTarget:
    """
    Apply action inputs to the loaded config without mutating the original dataclass instances.
    """

    cfg = target.config
    enable: str | tuple[str, ...]
    if rules_spec.lower() == "all":
        enable = "all"
    else:
        enable = tuple([t.strip() for t in rules_spec.replace(";", ",").split(",") if t.strip()])
        if not enable:
            enable = "all"

    new_cfg = replace(
        cfg,
        threshold=threshold,
        fail_on_slop=fail_on_slop,
        rules=replace(
            cfg.rules,
            enable=enable,
        ),
    )
    return replace(target, config=new_cfg)


def _write_outputs(summary: ScanSummary, *, sarif_path: str | None) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    p = Path(out_path)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"score={summary.score}\n")
        f.write(f"files_scanned={summary.files_scanned}\n")
        if sarif_path:
            f.write(f"sarif_path={sarif_path}\n")


def _ensure_git_object(sha: str) -> None:
    if _git_has_object(sha):
        return
    remote = _git_remote()
    if not remote:
        return
    try:
        git_check_call(["fetch", "--no-tags", "--depth=1", remote, sha], cwd=Path("."))
    except GitError:
        return


def _git_has_object(sha: str) -> bool:
    try:
        git_check_call(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=Path("."))
        return True
    except GitError:
        return False


def _git_remote() -> str | None:
    try:
        out = git_check_output(["remote"], cwd=Path(".")).splitlines()
    except GitError:
        return None
    if "origin" in out:
        return "origin"
    return out[0] if out else None


def _load_event(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.is_dir():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    return cast(dict[str, Any], data)


def _get_input(name: str, default: str) -> str:
    candidates = {
        f"INPUT_{name.upper()}",
        f"INPUT_{name.upper().replace('-', '_')}",
        f"INPUT_{name.lower()}",
        f"INPUT_{name.lower().replace('-', '_')}",
    }
    for key in candidates:
        value = os.environ.get(key)
        if value is not None:
            return value
    return default


def _as_bool(value: str, *, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_int(value: str, *, default: int) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return default


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
