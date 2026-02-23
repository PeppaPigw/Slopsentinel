from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError

from slopsentinel.action_github import (
    _GITHUB_GET_MAX_ATTEMPTS,
    _comment_key,
    _comment_marker,
    _create_review_comment,
    _fetch_existing_review_comment_keys,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _http_error(*, url: str, code: int, body: bytes = b"error") -> HTTPError:
    return HTTPError(url, code, "error", hdrs=None, fp=io.BytesIO(body))


def test_fetch_existing_review_comment_keys_retries_then_succeeds(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments?per_page=100&page=1"
    key = _comment_key(path="src/app.py", line=1)
    marker = _comment_marker(key=key, path="src/app.py", line=1)
    payload: list[dict[str, Any]] = [{"body": f"hello\n\n{marker}\n"}]
    body = json.dumps(payload).encode("utf-8")

    results: list[object] = [
        _http_error(url=url, code=500, body=b"boom"),
        _FakeResponse(body),
    ]
    calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append((req.get_method(), req.full_url))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda s: sleep_calls.append(float(s)))
    monkeypatch.setattr("slopsentinel.action_github.random.uniform", lambda _a, _b: 0.0)

    keys = _fetch_existing_review_comment_keys(token="t", repository="o/r", pull_number=1)
    assert key in keys
    assert calls == [("GET", url), ("GET", url)]
    assert len(sleep_calls) == 1


def test_fetch_existing_review_comment_keys_stops_after_max_attempts(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments?per_page=100&page=1"

    results: list[object] = [_http_error(url=url, code=500, body=b"boom")] * _GITHUB_GET_MAX_ATTEMPTS
    calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append((req.get_method(), req.full_url))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda s: sleep_calls.append(float(s)))
    monkeypatch.setattr("slopsentinel.action_github.random.uniform", lambda _a, _b: 0.0)

    keys = _fetch_existing_review_comment_keys(token="t", repository="o/r", pull_number=1)
    assert keys == set()
    assert len(calls) == _GITHUB_GET_MAX_ATTEMPTS
    assert len(sleep_calls) == _GITHUB_GET_MAX_ATTEMPTS - 1


def test_create_review_comment_retries_on_http_5xx(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments"
    results: list[object] = [
        _http_error(url=url, code=502, body=b"bad gateway"),
        _FakeResponse(b'{"ok":true}'),
    ]
    calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []
    existing_calls: list[tuple[str, str, int]] = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append((req.get_method(), req.full_url))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def fake_fetch_existing_review_comment_keys(*, token: str, repository: str, pull_number: int):
        existing_calls.append((token, repository, pull_number))
        return set()

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "slopsentinel.action_github._fetch_existing_review_comment_keys", fake_fetch_existing_review_comment_keys
    )
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda s: sleep_calls.append(float(s)))
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
    assert calls == [("POST", url), ("POST", url)]
    assert len(sleep_calls) == 1
    assert existing_calls == [("t", "o/r", 1)]


def test_create_review_comment_does_not_retry_on_http_4xx(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments"
    results: list[object] = [_http_error(url=url, code=400, body=b"bad request")]
    calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append((req.get_method(), req.full_url))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda s: sleep_calls.append(float(s)))
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
    assert calls == [("POST", url)]
    assert sleep_calls == []


def test_create_review_comment_does_not_retry_on_network_error(monkeypatch) -> None:
    url = "https://api.github.com/repos/o/r/pulls/1/comments"
    results: list[object] = [URLError("network down")]
    calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []

    def fake_urlopen(req, *args, **kwargs):
        calls.append((req.get_method(), req.full_url))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("slopsentinel.action_github.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("slopsentinel.action_github.time.sleep", lambda s: sleep_calls.append(float(s)))
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
    assert calls == [("POST", url)]
    assert sleep_calls == []

