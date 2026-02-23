#!/usr/bin/env bash
set -euo pipefail

python demo/render_demo_svgs.py
echo "Wrote docs/demo.svg, docs/demo-fix.svg, docs/demo-trend.svg"

