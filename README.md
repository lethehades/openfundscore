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
- One packaged-Schema-plus-semantics validation API/CLI for manager research,
  provider records/contracts, external ratings and score evidence ledgers.
- A fail-closed, point-in-time publication gate that keeps private local research
  separate from hosted ratings and raw-data redistribution.
- A versioned complex-alternatives strategy mapping: market-neutral, long-short,
  absolute-return, derivatives-heavy and catch-all peer buckets stay explicitly
  `unrated` until comparable samples and evidence are sufficient.
- A typed Provider SDK with explicit point-in-time entitlements and fail-closed
  ingestion enforcement for rights, attribution, rate, cache and retention limits.
- Synthetic A/C/E/I, closed, merged, transformed and conflicting records only;
  no real provider data is bundled.

## M4 point-in-time walk-forward slice

- Historical universes retain closed, merged and transformed strategies and
  exclude strategies that had not yet started at each decision timestamp.
- Lifecycle, classification, benchmark, manager, fee, availability, feature and
  provider versions obey effective, publication and knowledge timestamps.
- Auditable callback or precomputed component scores feed deterministic
  walk-forward folds; future outcomes are joined only after selection.
- Explicit `revision_id`/`supersedes_revision_id` chains preserve the revision
  known in each fold and reject missing, duplicate or branching lineage.
- Score audits use `(strategy_id, audit_id, revision_id)`, so callback audit IDs
  reused across strategies remain separate; callback errors and future-known
  precomputed exclusions remain distinct fail-closed outcomes.
- Reports include stability, Jaccard turnover, breadth, coverage, wealth,
  first-loss-aware drawdown/recovery, peer-relative outcomes, uncertainty,
  pairwise-complete component correlations and no-refit leave-one-component-out
  sensitivity.
- Strict local JSON rejects duplicate keys, non-finite values, invalid Unicode,
  over-magnitude scalars, overlong identifiers/text, oversized or excessively
  nested input and redacts callback failures.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m openfundscore.cli resources list
.venv/bin/python -m openfundscore.cli resources resolve \
  --type scoring-config --name openfundscore-core --version 0.1.0
.venv/bin/python -m openfundscore.cli resources show \
  --type scoring-config --name openfundscore-core --version 0.1.0 \
  > /tmp/openfundscore-core-0.1.0.json
.venv/bin/python -m openfundscore.cli validate-config \
  /tmp/openfundscore-core-0.1.0.json
.venv/bin/python -m openfundscore.cli resources show \
  --type strategy-mapping --name complex_alternatives --version 0.1.0 \
  > /tmp/complex-alternatives-0.1.0.json
.venv/bin/python -m openfundscore.cli validate-mapping \
  /tmp/complex-alternatives-0.1.0.json
.venv/bin/python -m openfundscore.cli strategy-map market_neutral \
  --mapping-version 0.1.0
.venv/bin/python -m openfundscore.cli validate-record \
  --type provider_record --schema-version 0.1.0 \
  --evaluation-timestamp 2026-08-21T00:00:00Z provider-record.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from openfundscore.walk_forward_io import synthetic_fixture_document

Path("/tmp/openfundscore-walk-forward.json").write_text(
    json.dumps(synthetic_fixture_document(), allow_nan=False),
    encoding="utf-8",
)
PY
.venv/bin/openfundscore walk-forward /tmp/openfundscore-walk-forward.json \
  > /tmp/openfundscore-walk-forward-report.json
.venv/bin/python -m unittest discover -s tests -v
```

Packaged scoring configurations and JSON Schemas are selected by the complete
`(type, name, version)` tuple. There is no `latest` alias, implicit default or
repository-path fallback. `resources resolve` returns logical metadata rather
than an installation path; `resources show` writes the verified packaged JSON.
The research-preview `validate-config` command continues to require an explicit
configuration path and never silently switches scoring models. Contract records
must use `validate_record()` or `validate-record`, which always run both packaged
Schema and semantic validation; see [validation boundary](docs/VALIDATION.md).

## Documents

- [Project charter](docs/PROJECT_CHARTER.md)
- [Roadmap](docs/ROADMAP.md)
- [Canonical data model](docs/CANONICAL_DATA_MODEL.md)
- [Unified validation boundary](docs/VALIDATION.md)
- [Public rating and redistribution gate](docs/PUBLICATION_GATE.md)
- [Provider SDK and ingestion entitlements](docs/PROVIDER_SDK.md)
- [Point-in-time walk-forward validation](docs/WALK_FORWARD.md)
- [Fund taxonomy](docs/FUND_TAXONOMY.md)
- [Scoring RFC](docs/SCORING_RFC.md)
- [Manager research model](docs/MANAGER_RESEARCH.md)
- [Data-provider policy](docs/DATA_PROVIDER_POLICY.md)

## Licensing

Code and original documentation are Apache-2.0. This license does **not** grant
rights to redistribute third-party datasets, trademarks, proprietary ratings or
platform content. Provider-specific terms still apply.
