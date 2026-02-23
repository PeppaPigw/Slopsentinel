from __future__ import annotations

import logging
import sys


def configure_logging(*, verbose: bool, quiet: bool) -> None:
    """
    Configure process-wide logging defaults for CLI/CI usage.

    - Default: INFO
    - --verbose: DEBUG
    - --quiet: WARNING

    Logging is written to stderr so it does not corrupt machine-readable stdout
    outputs (JSON/SARIF/HTML).
    """

    if verbose and quiet:
        # CLI argument validation normally prevents this, but keep the helper
        # safe for programmatic callers.
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    fmt = "SlopSentinel: %(message)s"
    if verbose:
        fmt = "SlopSentinel [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(level=level, format=fmt, stream=sys.stderr, force=True)

