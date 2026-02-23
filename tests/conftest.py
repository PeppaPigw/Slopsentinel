from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.registry import set_extra_rules


@pytest.fixture()
def project_ctx(tmp_path: Path) -> ProjectContext:
    return ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(),
        config=SlopSentinelConfig(),
    )


@pytest.fixture(autouse=True)
def _reset_rule_registry_plugins() -> None:
    set_extra_rules([])
