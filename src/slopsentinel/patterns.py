from __future__ import annotations

import re

# Shared patterns used across detection rules and mechanical "deslop" transforms.
# Keep these centralized so detection and cleanup stay consistent when patterns evolve.

POLITE_RE = re.compile(
    r"\b(?:"
    r"we\s+need\s+to|"
    r"let['’]s|"
    r"we\s+should|"
    r"as\s+you\s+can\s+see|"
    r"note\s+that|"
    r"it['’]s\s+worth\s+noting|"
    r"it\s+is\s+worth\s+noting|"
    r"keep\s+in\s+mind|"
    r"feel\s+free\s+to|"
    r"don['’]t\s+hesitate\s+to|"
    r"please\s+note"
    r")\b",
    re.IGNORECASE,
)
THINKING_RE = re.compile(r"</?thinking>", re.IGNORECASE)
# Match common "banner" comments like:
#   # --------------------------
#   # ====== Configuration ======
#   // ----- Section -----
BANNER_RE = re.compile(r"^\s*(#|//)\s*(?:[=\-]{10,}|[=\-]{3,}\s*\S.*\s*[=\-]{3,})\s*$")

COMPREHENSIVE_RE = re.compile(r"here['’]s a comprehensive", re.IGNORECASE)
LAST_UPDATE_RE = re.compile(r"\bas of my last update\b", re.IGNORECASE)
