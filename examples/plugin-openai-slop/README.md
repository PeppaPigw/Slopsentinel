# slopsentinel-openai-slop (example plugin)

This is an **example** SlopSentinel plugin package.

It demonstrates how to ship additional rules in a separate Python distribution,
then load them via `pyproject.toml`.

## Install locally (editable)

From the repo root:

```bash
python -m pip install -e examples/plugin-openai-slop
```

## Enable in a project

In your project’s `pyproject.toml`:

```toml
[tool.slopsentinel]
plugins = ["openai_slop_rules"]
```

Then run:

```bash
slop scan .
```

## Run this plugin’s tests

```bash
python -m pytest examples/plugin-openai-slop/tests
```

