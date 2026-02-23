# ruff: noqa
# Here's a comprehensive demo module (intentionally "sloppy" to trigger rules).
# We need to ensure this is safe.
# As of my last update, this pattern works.

from __future__ import annotations

import json
import os
import random

api_token = "abc123"  # hardcoded credential-like literal (E09)


def is_positive(x: int) -> bool:
    if x > 0:
        return True
    else:
        return False


def load_config(path: str) -> dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass

    # Use os so it is *not* an unused import (we still want E03 for `random`).
    return {"home": os.path.expanduser("~")}
