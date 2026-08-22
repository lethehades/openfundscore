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
- Fund-manager evidence uses actual target-tenure windows and public professional
  or regulatory records only. Raw manager component scores are explicit caller
  assertions, not facts independently verified by this package.
- Missing data is not zero. Confidence is a separate publication gate: caller
  manager assertions cap confidence at `low` but do not create a hidden score
  deduction.
- Point-in-time data, publication lag and survivorship controls are mandatory
  for backtests.

## Implemented in v0.1

- Ten category-aware, versioned 100-point weight profiles.
- A separately versioned 120-row metric catalog that declares validation contracts
  for 92 unique **upstream** formula identifiers. The category engine does not
  implement those 92 source calculations; it validates their audited outputs with
  an explicit 92-entry cross-field manifest, robust peer midranks, point-in-time
  audit fields and closed capture-denominator provenance.
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
- A no-network Mainland official frozen-snapshot provider pilot for regulator,
  exchange and explicitly approved exact-host fund-company disclosures; all seven
  disclosure classes map to separately validated and authorised provider records.
- Two bounded official-source pilots: SEC EDGAR submissions metadata and World
  Bank annual indicator observations. Both use fixed HTTPS hosts, conservative
  local derived-only rights and offline fixture API/CLI paths; no provider data
  is bundled and no coverage is claimed for other official sources.
- Synthetic A/C/E/I, closed, merged, transformed and conflicting records only;
  no real provider data is bundled.

### Ant Fortune boundary

The packaged Ant Fortune boundary is fail closed: it records no authorized per-fund API,
no automated adapter, and no login or cookie access. Current legal
permission, terms, and robots implications are uncertain and are not claimed as
authorization. Platform ratings are external only and never enter Open Score.
See the [Ant Fortune public-data boundary](docs/ANT_FORTUNE_BOUNDARY.md).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m openfundscore.cli resources list
.venv/bin/python -m openfundscore.cli resources resolve \
  --type scoring-config --name openfundscore-core --version 0.1.0
.venv/bin/python -m openfundscore.cli resources resolve \
  --type metric-catalog --name openfundscore-category-metrics --version 0.1.0
.venv/bin/python -m openfundscore.cli resources resolve \
  --type peer-admission --name category-profile-buckets --version 0.1.0
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
  --type provider_record --schema-version 0.2.0 \
  --evaluation-timestamp 2026-08-21T00:00:00Z provider-record.json
.venv/bin/python -m openfundscore.cli platform-boundary validate --boundary-version 0.1.0
.venv/bin/python -m openfundscore.cli platform-boundary check platform_rating \
  --access-mode automated --use open_score --boundary-version 0.1.0
.venv/bin/python -m openfundscore.cli provider mainland-parse snapshot.json \
  --entitlements reviewed-entitlements.json \
  --evaluation-timestamp 2026-08-21T00:00:00Z
.venv/bin/python -m openfundscore.cli validate-record \
  --type score_evidence_usage --schema-version 0.2.0 evidence-ledger.json
.venv/bin/python -m openfundscore.cli category-score category-score-input.json
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
New provider records, including records emitted by the Mainland snapshot adapter,
use `schema / provider_record / 0.3.0`. The packaged `0.1.0` provider-record
Schema remains available byte-for-byte for explicit legacy validation; versions
are never selected implicitly or rewritten in place.

Category scoring combines the unchanged scoring-config 0.1.0 weights with the
independent metric-catalog 0.1.0 resource. It consumes audited upstream raw
metrics rather than claiming to calculate every source metric; missing and NA
core data remain distinct and never trigger reweighting. See
[category metric engine](docs/CATEGORY_METRICS.md).
Category scoring requires the exact peer-admission 0.1.0 contract, a closed
`ManagerResearchHandoff` containing raw manager input plus eight real caller-owned
identity rows and exact `assertion_status=caller_provided`, complete PIT peer tuples
and an explicit
`score_evidence_usage@0.2.0` ledger. The engine recomputes the manager result from
that handoff; a caller-supplied expected summary, typed audit or legacy
`manager_audit` cannot authorize a score. Results retain the peer-admission version
and digest. The published 0.1.0 evidence Schema remains byte-compatible for
explicitly selected legacy validation; it is not accepted as an implicit
category-engine downgrade.
Ledger digests are calculated after canonicalizing the ledger `as_of` and every
usage `observation_as_of` instant to UTC `Z`; equivalent offsets therefore commit
to the same instant. Manager component evidence
retains component-specific provenance, requires a tenure for the target strategy,
and declares `window_basis` as
`point_in_time`, `calendar_months` or `actual_dates`; actual-date endpoints are
preserved rather than reverse-clamped to synthetic calendar windows. The fact
digest and observation/window fields are derived from the consumed structured
facts in that local manager document. This binding detects local document changes;
it does not prove that the document or its external-source claims are true. Category
confidence is `medium` only for a complete eligible result, `low` for a complete
provisional result or a low-confidence manager audit, and `insufficient` otherwise.
Conditional metric applicability comes only from explicit prerequisite facts.
Downside capture is a -5 to 5 down-market capture ratio and is missing when the
benchmark has no downside denominator. Target and peer capture rows carry the
closed denominator status, downside sample count, evidence, lineage and series
identities. Each consumed target denominator is a separate 0.2 ledger row with
`evidence_role=capture_denominator`; ordinary fund and all eight manager rows use
`evidence_role=primary`. Peer audit rows preserve exact window
basis/months/start/end and both 64-character snapshot/document hashes. Observation
`uncertainty` is an optional annotation, not invented when a caller omits it. The
peer hashes are caller assertions retained and committed for audit; OpenFundScore
does not fetch their preimages or treat a hash as proof of external truth. The
180-day money-market WAM ceiling is a conservative project sanity cap, not a
universal regulatory rule.

This remains local research only: the publication gate returns `LOCAL_ONLY` for
private local research and `NO_GO` for hosted public ratings. A successful local
score or digest does not authorize publication or redistribution.

Built wheels and sdists contain the same seventeen `_resources` payloads: fifteen
indexed logical resources plus `index.json` and the resource package `__init__.py`.

## Documents

- [Project charter](docs/PROJECT_CHARTER.md)
- [Roadmap](docs/ROADMAP.md)
- [Canonical data model](docs/CANONICAL_DATA_MODEL.md)
- [Unified validation boundary](docs/VALIDATION.md)
- [Public rating and redistribution gate](docs/PUBLICATION_GATE.md)
- [Provider SDK and ingestion entitlements](docs/PROVIDER_SDK.md)
- [Ant Fortune public-data boundary](docs/ANT_FORTUNE_BOUNDARY.md)
- [Mainland official frozen-snapshot provider pilot](docs/MAINLAND_OFFICIAL_SNAPSHOT.md)
- [Official provider pilots: SEC EDGAR and World Bank](docs/OFFICIAL_PROVIDERS.md)
- [Fund taxonomy](docs/FUND_TAXONOMY.md)
- [Scoring RFC](docs/SCORING_RFC.md)
- [Category metric engine](docs/CATEGORY_METRICS.md)
- [Manager research model](docs/MANAGER_RESEARCH.md)
- [Data-provider policy](docs/DATA_PROVIDER_POLICY.md)

## Licensing

Code and original documentation are Apache-2.0. This license does **not** grant
rights to redistribute third-party datasets, trademarks, proprietary ratings or
platform content. Provider-specific terms still apply.