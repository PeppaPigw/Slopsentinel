from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.request
from hashlib import sha1
from pathlib import Path

from slopsentinel.action_markdown import _render_comment_body
from slopsentinel.engine.types import Violation
from slopsentinel.utils import safe_relpath


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


_GITHUB_GET_MAX_ATTEMPTS = 4
_GITHUB_POST_MAX_ATTEMPTS = 3
_GITHUB_RETRY_BACKOFF_BASE_SECONDS = 0.5
_GITHUB_RETRY_BACKOFF_CAP_SECONDS = 8.0


def _is_retryable_http_status(code: int) -> bool:
    return code == 429 or 500 <= code < 600


def _retry_sleep_seconds(attempt: int) -> float:
    """
    Compute an exponential backoff delay with jitter.

    attempt=0 is the first retry after the initial failure.
    """

    upper = min(_GITHUB_RETRY_BACKOFF_CAP_SECONDS, _GITHUB_RETRY_BACKOFF_BASE_SECONDS * (2**attempt))
    # "Equal jitter": sleep in [upper/2, upper]
    return float((upper / 2.0) + random.uniform(0.0, upper / 2.0))


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(_retry_sleep_seconds(attempt))


def _urlopen_json_with_retry(req: urllib.request.Request, *, timeout: int, max_attempts: int) -> object:
    """
    Read and decode JSON from a request with retries.

    This is only used for GET requests (idempotent).
    """

    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                exc.close()
            except OSError:
                pass
            if _is_retryable_http_status(int(exc.code)) and attempt < max_attempts - 1:
                _sleep_before_retry(attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            if attempt < max_attempts - 1:
                _sleep_before_retry(attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _post_pull_request_comments(
    *,
    violations: list[Violation],
    token: str,
    repository: str,
    pull_number: int,
    commit_id: str,
    project_root: Path,
) -> None:
    # Group by (path,line) to avoid spamming.
    grouped: dict[tuple[str, int], list[Violation]] = {}
    for v in violations:
        if v.location is None or v.location.path is None or v.location.start_line is None:
            continue
        path = _relpath(Path(v.location.path), project_root)
        loc_key = (path, int(v.location.start_line))
        grouped.setdefault(loc_key, []).append(v)

    if not grouped:
        return

    existing_keys = _fetch_existing_review_comment_keys(
        token=token,
        repository=repository,
        pull_number=pull_number,
    )

    max_comments = 50
    posted = 0
    for (path, line), items in sorted(grouped.items()):
        if posted >= max_comments:
            break

        comment_key = _comment_key(path=path, line=line)
        if comment_key in existing_keys:
            continue

        marker = _comment_marker(key=comment_key, path=path, line=line)
        body = _render_comment_body(items, marker=marker)
        ok = _create_review_comment(
            token=token,
            repository=repository,
            pull_number=pull_number,
            commit_id=commit_id,
            path=path,
            line=line,
            body=body,
        )
        if ok:
            posted += 1

    if posted == 0:
        return
    _eprint(f"Posted {posted} SlopSentinel PR review comment(s).")


def _fetch_existing_review_comment_keys(*, token: str, repository: str, pull_number: int) -> set[str]:
    """
    Return comment marker keys already present on the PR.

    Uses a stable per-location key so we don't re-post comments when the set of
    rule IDs for the same file/line changes between runs.
    """

    keys: set[str] = set()
    base_url = f"https://api.github.com/repos/{repository}/pulls/{pull_number}/comments"

    # Keep this simple and robust: page up to a reasonable bound without
    # implementing full Link-header pagination.
    for page in range(1, 11):
        url = f"{base_url}?per_page=100&page={page}"
        req = urllib.request.Request(
            url,
            headers=_github_headers(token),
            method="GET",
        )
        try:
            data = _urlopen_json_with_retry(req, timeout=15, max_attempts=_GITHUB_GET_MAX_ATTEMPTS)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            return keys

        if not isinstance(data, list) or not data:
            break

        for item in data:
            body = item.get("body")
            if not isinstance(body, str):
                continue
            key = _extract_marker_key(body)
            if key:
                keys.add(key)

        if len(data) < 100:
            break

    return keys


def _create_review_comment(
    *,
    token: str,
    repository: str,
    pull_number: int,
    commit_id: str,
    path: str,
    line: int,
    body: str,
) -> bool:
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_number}/comments"
    payload = {
        "body": body,
        "commit_id": commit_id,
        "path": path,
        "side": "RIGHT",
        "line": int(line),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_github_headers(token),
        method="POST",
    )

    comment_key = _comment_key(path=path, line=line)
    for attempt in range(_GITHUB_POST_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                _ = resp.read()
            return True
        except urllib.error.HTTPError as exc:
            retryable = _is_retryable_http_status(int(exc.code))
            is_last_attempt = attempt >= _GITHUB_POST_MAX_ATTEMPTS - 1
            if retryable and not is_last_attempt:
                try:
                    exc.close()
                except OSError:
                    pass

                # Avoid dupes: if the POST actually succeeded but we got a
                # retryable error response, re-check for the marker before
                # retrying.
                existing = _fetch_existing_review_comment_keys(
                    token=token,
                    repository=repository,
                    pull_number=pull_number,
                )
                if comment_key in existing:
                    return True

                _sleep_before_retry(attempt)
                continue

            try:
                msg = exc.read().decode("utf-8", errors="replace")
            except OSError:
                msg = str(exc)
            try:
                exc.close()
            except OSError:
                pass
            _eprint(f"Failed to create review comment for {path}:{line} ({exc.code}): {msg}")
            return False
        except (urllib.error.URLError, TimeoutError) as exc:
            # Don't retry network errors for POST to avoid duplicate comments.
            _eprint(f"Failed to create review comment for {path}:{line}: {exc}")
            return False

    return False


def _comment_key(*, path: str, line: int) -> str:
    digest = sha1(f"{path}\n{int(line)}".encode()).hexdigest()
    return digest[:12]


def _comment_marker(*, key: str, path: str, line: int) -> str:
    return f"<!-- slopsentinel:v1 key={key} path={path} line={int(line)} -->"


def _extract_marker_key(body: str) -> str | None:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("<!-- slopsentinel:v1 ") and line.endswith("-->"):
            # Supports both the current marker and older variants that may
            # include additional fields like `rules=...`.
            fields = _parse_marker_fields(line)
            key = fields.get("key")
            if key:
                return key
            path = fields.get("path")
            line_no = fields.get("line")
            if path and line_no:
                try:
                    return _comment_key(path=path, line=int(line_no))
                except ValueError:
                    return None
    return None


def _parse_marker_fields(marker_line: str) -> dict[str, str]:
    """
    Parse a marker line like:
      <!-- slopsentinel:v1 key=abc path=src/app.py line=12 -->
    into a dict of key -> value.

    This parser is intentionally minimal and assumes values have no spaces.
    """

    stripped = marker_line.strip()
    if stripped.startswith("<!--"):
        stripped = stripped[4:].strip()
    if stripped.endswith("-->"):
        stripped = stripped[:-3].strip()

    if not stripped.startswith("slopsentinel:v1"):
        return {}

    tokens = stripped.split()[1:]  # skip slopsentinel:v1
    out: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        if k and v:
            out[k] = v
    return out


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "slopsentinel-action",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _relpath(path: Path, root: Path) -> str:
    return safe_relpath(path, root)
