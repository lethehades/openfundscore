# Contributing

## Before opening a change

- Open an issue/RFC for methodology, taxonomy or public-interface changes.
- Do not commit third-party datasets, credentials, cookies, private holdings or
  proprietary ratings.
- Document source terms and entitlements for every provider.
- Add tests before implementation and preserve point-in-time semantics.

## Local checks

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m openfundscore.cli validate-config \
  configs/scoring/v0.1.0.json
```

Method changes must include rationale, affected categories, before/after weight
sums, overlap analysis, walk-forward validation plan and versioning impact.
