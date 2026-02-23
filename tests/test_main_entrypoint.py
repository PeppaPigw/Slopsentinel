from __future__ import annotations

import runpy
import sys

import slopsentinel.__main__ as main_mod
import slopsentinel.cli as cli_mod


def test_main_calls_cli_app(monkeypatch) -> None:
    called = {"count": 0}

    def fake_app() -> None:
        called["count"] += 1

    monkeypatch.setattr(main_mod, "app", fake_app)
    main_mod.main()
    assert called["count"] == 1


def test_module_main_guard_invokes_main(monkeypatch) -> None:
    called = {"count": 0}

    def fake_app() -> None:
        called["count"] += 1

    monkeypatch.setattr(cli_mod, "app", fake_app)
    monkeypatch.delitem(sys.modules, "slopsentinel.__main__", raising=False)
    runpy.run_module("slopsentinel.__main__", run_name="__main__")
    assert called["count"] == 1
