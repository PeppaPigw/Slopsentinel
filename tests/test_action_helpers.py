from __future__ import annotations

from slopsentinel.action import _as_bool, _as_int
from slopsentinel.action_github import _comment_key, _comment_marker, _extract_marker_key


def test_comment_marker_roundtrip() -> None:
    key = _comment_key(path="src/app.py", line=123)
    marker = _comment_marker(key=key, path="src/app.py", line=123)
    body = f"hello\n\n{marker}\n"
    assert _extract_marker_key(body) == key


def test_extract_marker_none_when_missing() -> None:
    assert _extract_marker_key("no marker here") is None


def test_extract_marker_key_backwards_compatible() -> None:
    body = "hello\n\n<!-- slopsentinel:v1 path=src/app.py line=123 rules=A03,C03 -->\n"
    assert _extract_marker_key(body) == _comment_key(path="src/app.py", line=123)


def test_as_bool_parsing() -> None:
    assert _as_bool("true", default=False) is True
    assert _as_bool("1", default=False) is True
    assert _as_bool("false", default=True) is False
    assert _as_bool("0", default=True) is False
    assert _as_bool("maybe", default=True) is True


def test_as_int_parsing() -> None:
    assert _as_int("42", default=0) == 42
    assert _as_int("nope", default=7) == 7
