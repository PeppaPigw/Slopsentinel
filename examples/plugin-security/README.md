# slopsentinel-plugin-security (example plugin)

This is an **example** SlopSentinel plugin package with a few security-flavored
heuristics.

These rules are deliberately small and conservative (regex/line-based) to show
the plugin mechanics, not to replace dedicated security tooling.

## Install locally (editable)

```bash
python -m pip install -e examples/plugin-security
```

## Enable in a project

```toml
[tool.slopsentinel]
plugins = ["slopsentinel_plugin_security"]
```

## Run this plugin’s tests

```bash
python -m pytest examples/plugin-security/tests
```

