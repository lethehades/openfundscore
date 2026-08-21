# Contributing

## Before opening a change

- Open an issue/RFC for methodology, taxonomy or public-interface changes.
- Do not commit third-party datasets, credentials, cookies, private holdings or
  proprietary ratings.
- Document source terms and entitlements for every provider.
- Add tests before implementation and preserve point-in-time semantics.

## Local checks

Install the project in an isolated environment so runtime format validators are
present; do not rely on a system `jsonschema` installation:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m openfundscore.cli resources show \
  --type scoring-config --name openfundscore-core --version 0.1.0 \
  > /tmp/openfundscore-core-0.1.0.json
.venv/bin/python -m openfundscore.cli validate-config \
  /tmp/openfundscore-core-0.1.0.json
```

Method changes must include rationale, affected categories, before/after weight
sums, overlap analysis, walk-forward validation plan and versioning impact.
