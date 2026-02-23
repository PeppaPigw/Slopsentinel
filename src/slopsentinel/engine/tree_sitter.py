from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, cast

from slopsentinel.engine.context import SyntaxTree


class _ParserLike(Protocol):
    def set_language(self, language: object) -> None: ...

    def parse(self, source: bytes) -> object: ...

_parser_cls: type[_ParserLike] | None
_get_language_func: Callable[[str], object] | None

try:  # pragma: no cover
    from tree_sitter import Parser as _TreeSitterParser
    from tree_sitter_languages import get_language as _tree_sitter_get_language
except (ImportError, OSError):  # pragma: no cover
    _parser_cls = None
    _get_language_func = None
else:  # pragma: no cover (depends on installed grammars)
    # mypy treats optional dependency imports as `Any` (ignored). Cast to the
    # minimal protocol we rely on.
    _parser_cls = cast(type[_ParserLike], _TreeSitterParser)
    _get_language_func = cast(Callable[[str], object], _tree_sitter_get_language)

_TREE_SITTER_AVAILABLE = _parser_cls is not None and _get_language_func is not None

# Expose these for tests and for light monkeypatching in downstream tooling.
# They are intentionally optional to support running without tree-sitter deps.
Parser: type[_ParserLike] | None = _parser_cls
get_language: Callable[[str], object] | None = _get_language_func


class TreeSitterError(RuntimeError):
    """Raised when tree-sitter cannot load a language or parse source."""


@lru_cache(maxsize=32)
def _get_language(language: str) -> object:
    if not _TREE_SITTER_AVAILABLE:  # pragma: no cover
        raise TreeSitterError(
            "tree-sitter dependencies are not installed. Install `slopsentinel[treesitter]` (or add "
            "`tree-sitter` + `tree-sitter-languages`) to enable multi-language AST parsing."
        )
    try:
        assert get_language is not None
        return get_language(language)
    except (AttributeError, KeyError, ValueError, RuntimeError) as exc:  # pragma: no cover (depends on installed grammars)
        raise TreeSitterError(f"tree-sitter language not available: {language!r}") from exc


_PARSER_LOCAL = threading.local()


def _get_parser(language: str) -> _ParserLike:
    """
    Return a per-thread Parser instance for the requested language.

    tree-sitter Parser objects are not thread-safe; sharing a single cached
    Parser across threads can lead to crashes or corrupted parse output.
    """

    if not _TREE_SITTER_AVAILABLE:  # pragma: no cover
        raise TreeSitterError(
            "tree-sitter dependencies are not installed. Install `slopsentinel[treesitter]` (or add "
            "`tree-sitter` + `tree-sitter-languages`) to enable multi-language AST parsing."
        )

    parsers: dict[str, _ParserLike] | None = getattr(_PARSER_LOCAL, "parsers", None)
    if parsers is None:
        parsers = {}
        _PARSER_LOCAL.parsers = parsers

    parser = parsers.get(language)
    if parser is not None:
        return parser

    lang = _get_language(language)
    assert Parser is not None
    parser = Parser()
    parser.set_language(lang)
    parsers[language] = parser
    return parser


def parse(language: str, source: str) -> SyntaxTree | None:
    """
    Parse source code with tree-sitter.

    Returns a Tree or None if parsing fails unexpectedly.
    """

    if not _TREE_SITTER_AVAILABLE:
        return None
    try:
        parser = _get_parser(language)
        tree = parser.parse(source.encode("utf-8", errors="replace"))
        return cast(SyntaxTree, tree)
    except (TreeSitterError, ValueError, TypeError, RuntimeError):
        return None


def is_available() -> bool:
    return _TREE_SITTER_AVAILABLE
