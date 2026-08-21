# OpenFundScore

OpenFundScore is an open, auditable and category-aware research framework for
public funds. It separates **fund quality**, **data confidence**, **risk flags**,
**platform availability** and **investor suitability** instead of turning all
questions into one leaderboard.

> Status: research preview. The repository does not publish a live ranking,
> predict returns, guarantee principal, or execute trades.

## Design principles

- The core score is OpenFundScore's own 100-point methodology.
- Alipay/Ant Fortune, Eastmoney and overseas platforms are data providers only;
  their proprietary ratings never define the core score.
- Funds are classified before comparison; unlike categories are never ranked
  together.
- A strategy entity is scored once; A/C/E/I share classes are selected later by
  fees, holding period and availability.
- Fund-manager evidence uses actual tenure windows and public professional or
  regulatory records only.
- Missing data is not zero. Confidence is a separate publication gate.
- Point-in-time data, publication lag and survivorship controls are mandatory
  for backtests.

## Implemented in v0.1

- Ten category-aware, versioned 100-point weight profiles.
- A detailed 100-point manager/team model.
- Deterministic JSON configuration validation.
- Global data-provider, taxonomy and research contracts.
- CI tests that reject broken totals and confidence leakage.

## M1 canonical-data slice

- Immutable, effective-dated fund strategy, share class, benchmark, manager,
  manager-tenure, holding-snapshot and evidence records.
- Exact-identifier resolution that never merges entities by name alone.
- Append-only SQLite storage with point-in-time knowledge cutoffs,
  conflict-preserving joins and deterministic JSON round trips.
- Fail-closed provider-record chronology semantics with explicit evaluation times,
  provenance requirements and preserved lower-confidence observations.
- Synthetic A/C/E/I, closed, merged, transformed and conflicting records only;
  no real provider data is bundled.

```bash
PYTHONPATH=src python3 -m openfundscore.cli validate-config \
  configs/scoring/v0.1.0.json
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The research-preview CLI intentionally requires an explicit configuration path.
The versioned default currently lives in the repository rather than being
silently selected from package data.

## Documents

- [Project charter](docs/PROJECT_CHARTER.md)
- [Roadmap](docs/ROADMAP.md)
- [Canonical data model](docs/CANONICAL_DATA_MODEL.md)
- [Fund taxonomy](docs/FUND_TAXONOMY.md)
- [Scoring RFC](docs/SCORING_RFC.md)
- [Manager research model](docs/MANAGER_RESEARCH.md)
- [Data-provider policy](docs/DATA_PROVIDER_POLICY.md)

## Licensing

Code and original documentation are Apache-2.0. This license does **not** grant
rights to redistribute third-party datasets, trademarks, proprietary ratings or
platform content. Provider-specific terms still apply.
