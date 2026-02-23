from __future__ import annotations

import pytest

from slopsentinel.suppressions import parse_suppressions


def test_parse_suppressions_normalizes_ids_case_insensitively() -> None:
    suppressions = parse_suppressions(
        [
            "x = 1  # slop: disable=a03,c01,ALL\n",
            "# slop: disable-next-line=e02\n",
            "y = 2\n",
        ]
    )

    assert suppressions.is_suppressed("A03", line=1)
    assert suppressions.is_suppressed("C01", line=1)
    assert suppressions.is_suppressed("E02", line=3)
    assert suppressions.is_suppressed("A99", line=1)  # ALL is a wildcard

    assert not suppressions.is_suppressed("E02", line=2)  # only next line


def test_disable_file_suppresses_rule_ids_anywhere_in_file() -> None:
    suppressions = parse_suppressions(
        [
            "# slop: disable-file=a03\n",
            "x = 1\n",
            "y = 2  # slop: disable-next-line=c01\n",
            "z = 3\n",
        ]
    )

    assert suppressions.is_suppressed("A03", line=1)
    assert suppressions.is_suppressed("A03", line=2)
    assert suppressions.is_suppressed("A03", line=999)

    # Unrelated rule only suppressed on the next line.
    assert suppressions.is_suppressed("C01", line=4)
    assert not suppressions.is_suppressed("C01", line=3)


def test_disable_file_all_is_wildcard() -> None:
    suppressions = parse_suppressions(["# slop: disable-file=all\n", "x = 1\n"])
    assert suppressions.is_suppressed("A03", line=2)
    assert suppressions.is_suppressed("Z99", line=2)


def test_suppressions_mapping_is_read_only() -> None:
    suppressions = parse_suppressions(["x = 1  # slop: disable=a01\n"])
    assert isinstance(suppressions.disabled_on_line[1], frozenset)

    with pytest.raises(TypeError):
        suppressions.disabled_on_line[1] = frozenset()


def test_is_suppressed_with_line_none_returns_false() -> None:
    suppressions = parse_suppressions(["x = 1  # slop: disable=A03\n"])
    assert suppressions.is_suppressed("A03", line=None) is False


def test_parse_suppressions_ignores_empty_tokens() -> None:
    suppressions = parse_suppressions(["x = 1  # slop: disable=,A03,\n"])
    assert suppressions.is_suppressed("A03", line=1) is True
