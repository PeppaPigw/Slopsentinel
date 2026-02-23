from __future__ import annotations

import os

from slopsentinel.scanner import resolve_worker_count


def test_resolve_worker_count_default_uses_cpu_times_two(monkeypatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert resolve_worker_count(None) == 8


def test_resolve_worker_count_default_is_clamped_to_max(monkeypatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    assert resolve_worker_count(None) == 32


def test_resolve_worker_count_respects_default_param(monkeypatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    assert resolve_worker_count(None, default=3) == 3

