# Custom reporter (example)

SlopSentinel already ships several built-in output formats (`terminal`, `json`,
`sarif`, `html`, `markdown`, `github`).

This example shows how to build a custom output layer by consuming the JSON scan
report schema.

## Example: custom Markdown summary

Generate a JSON scan report:

```bash
slop scan . --format json > slopsentinel.json
```

Render a custom Markdown summary:

```bash
python examples/custom-reporter/custom_markdown.py slopsentinel.json > summary.md
```

