from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor


def test_tree_sitter_parser_is_thread_local(monkeypatch) -> None:
    import slopsentinel.engine.tree_sitter as ts

    class DummyParser:
        def __init__(self) -> None:
            self.language = None

        def set_language(self, language: object) -> None:
            self.language = language

        def parse(self, _source: bytes) -> int:
            return id(self)

    monkeypatch.setattr(ts, "_TREE_SITTER_AVAILABLE", True)
    monkeypatch.setattr(ts, "Parser", DummyParser)
    monkeypatch.setattr(ts, "get_language", lambda _name: object())

    ts._get_language.cache_clear()
    if hasattr(ts._PARSER_LOCAL, "parsers"):
        ts._PARSER_LOCAL.parsers.clear()

    # Same thread should reuse the same Parser instance.
    assert ts.parse("python", "x = 1") == ts.parse("python", "x = 2")

    barrier = threading.Barrier(2)

    def worker() -> int:
        barrier.wait()
        return int(ts.parse("python", "x = 1"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = list(executor.map(lambda _: worker(), range(2)))

    assert a != b
