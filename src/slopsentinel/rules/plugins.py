from __future__ import annotations

import importlib
from collections.abc import Iterable
from types import ModuleType
from typing import Any

from slopsentinel.rules.base import BaseRule


class PluginLoadError(RuntimeError):
    """Raised when a configured plugin cannot be imported or doesn't expose rules."""


def load_plugin_rules(plugin_specs: tuple[str, ...]) -> list[BaseRule]:
    rules: list[BaseRule] = []
    for raw_spec in plugin_specs:
        spec = raw_spec.strip()
        if not spec:
            continue
        rules.extend(_load_one(spec))
    return rules


def _load_one(spec: str) -> list[BaseRule]:
    module_name, sep, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        raise PluginLoadError(f"Failed to import plugin module {module_name!r}: {exc}") from exc

    if sep:
        try:
            obj: Any = getattr(module, attr)
        except AttributeError as exc:
            raise PluginLoadError(f"Plugin module {module_name!r} has no attribute {attr!r}") from exc
    else:
        obj = module
    extracted = _extract_rules(obj)
    return list(extracted)


def _extract_rules(obj: Any) -> Iterable[BaseRule]:
    if isinstance(obj, ModuleType):
        if hasattr(obj, "slopsentinel_rules"):
            return _extract_rules(obj.slopsentinel_rules)
        if hasattr(obj, "RULES"):
            return _extract_rules(obj.RULES)
        raise PluginLoadError("Plugin module must define `slopsentinel_rules()` or `RULES`.")

    if callable(obj):
        produced = obj()
        return _extract_rules(produced)

    if isinstance(obj, list | tuple):
        out: list[BaseRule] = []
        for item in obj:
            if not isinstance(item, BaseRule):
                raise PluginLoadError(f"Plugin rules must be BaseRule instances, got: {type(item).__name__}")
            out.append(item)
        return out

    raise PluginLoadError(f"Unsupported plugin export type: {type(obj).__name__}")
