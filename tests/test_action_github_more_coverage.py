from __future__ import annotations

import io
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from slopsentinel.action_github import (
    _comment_key,
    _create_review_comment,
    _extract_marker_key,
    _fetch_existing_review_comment_keys,
    _parse_marker_fields,
    _post_pull_request_comments,
    _urlopen_json_with_retry,
)
from slopsentinel.engine.types import Location, Violation


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _BadCloseHTTPError(HTTPError):
    def close(self) -> None:  # pragma: no cover - trivial behavior; exercised via coverage in callers
        raise OSError("close failed")


class _BadReadHTTPError(HTTPError):
    def read(self, amt: int | None = None) -> bytes:  # type: ignore[override]
        raise OSError("read failed")

    def close(self) -> None:  # pragma: no cover - trivial behavior; exercised via coverage in callers
        raise OSError("close failed")


def _http_error(*, url: str, code: int, body: bytes = b"error") -> HTTPError:
    return HTTPError(url, code, "error", hdrs=None, fp=io.BytesIO(body))


def test_urlopen_json_with_retry_handles_errors_and_unreachable_guard(monkeypatch) -> None:
    req = urllib.request.Request("https://example.invalid", method="GET")

    bad_close = _BadCloseHTTPError(req.full_url, 500, "err", hdrs=None, fp=io.BytesIO(b"boom"))

    def fake_urlopen(_req, *args, **kwargs):
        raise bad_close

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(HTTPError):
        _urlopen_json_with_retry(req, timeout=1, max_attempts=1)

    # Network errors retry and then re-raise.
    calls: list[int] = []

    def fake_urlopen2(_req, *args, **kwargs):
        calls.append(1)
        raise URLError("network down")

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen2)
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda _s: None)
    monkeypatch.setattr("slopsentinel.action_github.random.uniform", lambda _a, _b: 0.0)

    with pytest.raises(URLError):
        _urlopen_json_with_retry(req, timeout=1, max_attempts=2)
    assert len(calls) == 2

    # max_attempts=0 hits the defensive "unreachable" guard.
    with pytest.raises(RuntimeError):
        _urlopen_json_with_retry(req, timeout=1, max_attempts=0)


def test_fetch_existing_review_comment_keys_breaks_on_non_list_and_skips_non_str_bodies(monkeypatch) -> None:
    def fake_urlopen_json(*_a, **_k):
        return {"not": "a list"}

    monkeypatch.setattr("slopsentinel.action_github._urlopen_json_with_retry", fake_urlopen_json)
    keys = _fetch_existing_review_comment_keys(token="t", repository="o/r", pull_number=1)
    assert keys == set()

    def fake_urlopen_json2(*_a, **_k):
        return [{"body": None}, {"body": 123}]

    monkeypatch.setattr("slopsentinel.action_github._urlopen_json_with_retry", fake_urlopen_json2)
    keys2 = _fetch_existing_review_comment_keys(token="t", repository="o/r", pull_number=1)
    assert keys2 == set()


def test_post_pull_request_comments_groups_and_posts(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    v1 = Violation(
        rule_id="A03",
        severity="info",
        message="m1",
        dimension="fingerprint",
        location=Location(path=project_root / "src" / "a.py", start_line=10, start_col=1, end_line=10, end_col=1),
    )
    v2 = Violation(
        rule_id="A06",
        severity="warn",
        message="m2",
        dimension="fingerprint",
        location=Location(path=project_root / "src" / "a.py", start_line=10, start_col=1, end_line=10, end_col=1),
    )
    v3 = Violation(
        rule_id="A10",
        severity="info",
        message="m3",
        dimension="fingerprint",
        location=Location(path=project_root / "src" / "a.py", start_line=11, start_col=1, end_line=11, end_col=1),
    )
    skipped = Violation(
        rule_id="A03",
        severity="info",
        message="no loc",
        dimension="fingerprint",
        location=None,
    )

    existing_key = _comment_key(path="src/a.py", line=11)
    monkeypatch.setattr("slopsentinel.action_github._fetch_existing_review_comment_keys", lambda **_k: {existing_key})

    created: list[tuple[str, int]] = []

    def fake_create_review_comment(*, path: str, line: int, **_k) -> bool:
        created.append((path, int(line)))
        return True

    monkeypatch.setattr("slopsentinel.action_github._create_review_comment", fake_create_review_comment)

    printed: list[str] = []
    monkeypatch.setattr("slopsentinel.action_github._eprint", lambda msg: printed.append(msg))

    _post_pull_request_comments(
        violations=[skipped, v1, v2, v3],
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        project_root=project_root,
    )

    # Only the non-existing location should be posted (line 10).
    assert created == [("src/a.py", 10)]
    assert printed and "Posted 1" in printed[0]


def test_post_pull_request_comments_returns_early_when_nothing_posted(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    v = Violation(
        rule_id="A03",
        severity="info",
        message="m1",
        dimension="fingerprint",
        location=Location(path=project_root / "src" / "a.py", start_line=10, start_col=1, end_line=10, end_col=1),
    )
    # Force skip: existing key already present.
    existing_key = _comment_key(path="src/a.py", line=10)
    monkeypatch.setattr("slopsentinel.action_github._fetch_existing_review_comment_keys", lambda **_k: {existing_key})
    monkeypatch.setattr("slopsentinel.action_github._create_review_comment", lambda **_k: True)

    printed: list[str] = []
    monkeypatch.setattr("slopsentinel.action_github._eprint", lambda msg: printed.append(msg))

    _post_pull_request_comments(
        violations=[v],
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        project_root=project_root,
    )
    assert printed == []


def test_post_pull_request_comments_returns_when_no_grouped_items(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    v = Violation(
        rule_id="A03",
        severity="info",
        message="no loc",
        dimension="fingerprint",
        location=None,
    )

    def fail_fetch(**_k):
        raise AssertionError("should not fetch existing keys when nothing is grouped")

    monkeypatch.setattr("slopsentinel.action_github._fetch_existing_review_comment_keys", fail_fetch)

    _post_pull_request_comments(
        violations=[v],
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        project_root=project_root,
    )


def test_post_pull_request_comments_caps_to_max_comments(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    violations: list[Violation] = []
    for i in range(1, 61):
        violations.append(
            Violation(
                rule_id="A03",
                severity="info",
                message="m",
                dimension="fingerprint",
                location=Location(
                    path=project_root / "src" / "a.py",
                    start_line=i,
                    start_col=1,
                    end_line=i,
                    end_col=1,
                ),
            )
        )

    monkeypatch.setattr("slopsentinel.action_github._fetch_existing_review_comment_keys", lambda **_k: set())
    posted: list[tuple[str, int]] = []

    def fake_create_review_comment(*, path: str, line: int, **_k) -> bool:
        posted.append((path, int(line)))
        return True

    monkeypatch.setattr("slopsentinel.action_github._create_review_comment", fake_create_review_comment)
    monkeypatch.setattr("slopsentinel.action_github._eprint", lambda _msg: None)

    _post_pull_request_comments(
        violations=violations,
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        project_root=project_root,
    )

    assert len(posted) == 50


def test_create_review_comment_returns_true_when_marker_already_exists_after_retryable_error(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments"
    err = _BadCloseHTTPError(url, 502, "bad gateway", hdrs=None, fp=io.BytesIO(b"boom"))
    results: list[object] = [err]

    def fake_urlopen(req, *args, **kwargs):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    key = _comment_key(path="src/app.py", line=12)

    def fake_fetch_existing_review_comment_keys(*, token: str, repository: str, pull_number: int):
        return {key}

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "slopsentinel.action_github._fetch_existing_review_comment_keys", fake_fetch_existing_review_comment_keys
    )
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda _s: None)
    monkeypatch.setattr("slopsentinel.action_github.random.uniform", lambda _a, _b: 0.0)

    ok = _create_review_comment(
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        path="src/app.py",
        line=12,
        body="hi",
    )
    assert ok is True


def test_create_review_comment_formats_error_message_on_read_failure(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments"
    err = _BadReadHTTPError(url, 400, "bad request", hdrs=None, fp=io.BytesIO(b"boom"))

    def fake_urlopen(req, *args, **kwargs):
        raise err

    printed: list[str] = []
    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("slopsentinel.action_github._eprint", lambda msg: printed.append(msg))
    monkeypatch.setattr("slopsentinel.action_github.random.uniform", lambda _a, _b: 0.0)

    ok = _create_review_comment(
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        path="src/app.py",
        line=12,
        body="hi",
    )
    assert ok is False
    assert printed and "Failed to create review comment" in printed[0]


def test_create_review_comment_returns_false_when_no_attempts(monkeypatch) -> None:
    monkeypatch.setattr("slopsentinel.action_github._GITHUB_POST_MAX_ATTEMPTS", 0)
    ok = _create_review_comment(
        token="t",
        repository="o/r",
        pull_number=1,
        commit_id="deadbeef",
        path="src/app.py",
        line=12,
        body="hi",
    )
    assert ok is False


def test_marker_parsing_handles_invalid_line_numbers_and_malformed_fields() -> None:
    body = "<!-- slopsentinel:v1 path=src/app.py line=notint -->"
    assert _extract_marker_key(body) is None

    assert _parse_marker_fields("<!-- not-a-marker -->") == {}
    assert _parse_marker_fields("<!-- slopsentinel:v1 key=abc weirdtoken -->") == {"key": "abc"}
