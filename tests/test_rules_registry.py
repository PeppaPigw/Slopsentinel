from __future__ import annotations

from dataclasses import dataclass

from slopsentinel.rules.base import BaseRule, RuleMeta
from slopsentinel.rules.registry import rule_by_id, rule_meta_by_id, set_extra_rules


@dataclass(frozen=True, slots=True)
class _PluginRule(BaseRule):
    meta = RuleMeta(
        rule_id="Z99",
        title="Plugin rule",
        description="plugin",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model=None,
    )


def test_rule_registry_caches_invalidate_when_plugins_change() -> None:
    assert rule_by_id("Z99") is None
    assert "Z99" not in rule_meta_by_id()

    set_extra_rules([_PluginRule()])
    assert rule_by_id("Z99") is not None
    assert "Z99" in rule_meta_by_id()

    set_extra_rules([])
    assert rule_by_id("Z99") is None
    assert "Z99" not in rule_meta_by_id()

