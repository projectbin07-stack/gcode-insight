# Contributing

Bug reports, G-code samples that are parsed wrongly, and pull requests are welcome.

## Development setup

```console
git clone https://github.com/projectbin07-stack/gcode-insight.git
cd gcode-insight
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
```

## Checks

All four must pass; CI runs them on Ubuntu and Windows with Python 3.10 and 3.13.

```console
ruff check .
ruff format --check .
mypy
pytest --cov
```

## Guidelines

- Keep the runtime free of third-party dependencies.
- New behaviour needs a test whose expected value is derived by hand or by independent bookkeeping,
  with the derivation in a comment. Do not assert against numbers copied from the tool's own output.
- Fixtures are generated: change `tests/fixtures/generate_fixtures.py`, run it, and commit the
  regenerated files. Do not add G-code copied from third-party sources or real customer jobs. If a
  real file triggers a bug, reduce it to the few lines that matter.
- Do not state accuracy or performance figures in documentation unless you measured them and say how.
- Keep commits small with imperative messages (`Add ...`, `Fix ...`).

## Reporting a parsing problem

Include the slicer name and version, the printer/firmware flavour, the smallest excerpt of G-code
that reproduces the problem, what `gcode-insight analyze --json` reported and what you expected.
