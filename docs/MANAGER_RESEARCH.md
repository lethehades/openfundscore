# Fund Manager and Investment Team Research Model

This model covers public professional evidence only. It excludes private life,
family, contact details, rumours, political profiling and unrelated social-media
content. Prestigious education is descriptive evidence, not a scoring shortcut.

## Manager score (100)

| Component | Weight | Evidence |
|---|---:|---|
| Tenure-attributed performance | 25 | benchmark/peer-relative results during exact tenures, factor residuals, transition windows and co-manager context |
| Downside control | 15 | tenure drawdown, expected shortfall, downside capture, recovery and stress periods |
| Cross-cycle consistency | 15 | rolling outcomes across bull, bear, rate, credit, style and liquidity regimes |
| Style discipline | 15 | holdings-based style, factor exposure, sector/currency/duration/credit bets, concentration and turnover stability |
| Career track record | 10 | prior comparable mandates with overlap-adjusted evidence and no stitched “manager NAV” fiction |
| Workload and capacity | 8 | concurrent products, distinct strategies, total assets, launches, team sharing and capacity risk |
| Research platform and team | 7 | analyst resources, succession, decision process, organisational stability and documented role |
| Compliance and integrity | 5 | verified regulator/company disclosures, sanctions, corrections and conflicts; unresolved allegations are not scored as facts |

For passive funds, named-manager skill receives low top-level weight and the
model is adapted to the index-replication/operations team. For public REITs,
operator and asset-management evidence replaces ordinary security-selection
assumptions.

## Required entities

- canonical manager identity and source-specific IDs;
- employer and role history with effective dates;
- fund/strategy tenure, role, co-managers and mandate state;
- professional qualifications and public official biography;
- holdings snapshots and calculated style exposures;
- verified compliance events with jurisdiction, status and source;
- evidence objects with URL/document, publication date, as-of date, retrieval
  time, quoted fact and confidence tier.

## Attribution rules

1. Attribute only dates when the manager actually held the role.
2. Separate legacy holdings and transition periods after appointment/departure.
3. Preserve benchmark and mandate versions in force at that date.
4. For co-management, default to team attribution. Do not give every manager
   100% credit for the same observation. A documented role-weighted decision
   uses `attribution_share` in [0, 1]; unresolved roles remain team-attributed.
5. Similar funds run from one model portfolio count as correlated evidence.
6. Previous funds are comparable only after strategy, currency and regime
   matching; otherwise they are background, not performance proof.
7. Factor beta, sector concentration or duration bets are reported separately
   from residual skill.

## Style fingerprint

Depending on mandate, calculate and timestamp:

- equity size/value/quality/momentum/low-volatility exposures;
- sector, country, currency and single-name active weights;
- active share, tracking error, cash level, turnover and concentration;
- bond duration, curve, credit quality, spread, leverage and convertible usage;
- market timing proxies and participation in rising/falling markets;
- change points around team, mandate, capacity and employer transitions.

A style change is not automatically bad. Undisclosed or unstable drift relative
to mandate is the risk; an explained adaptive decision is reported with evidence.

## Workload and platform burden

Measure concurrent strategy count, product count, total assets, number of
materially different mandates, co-manager coverage, new launches, redemptions,
team turnover and company investment-platform continuity. Do not use raw product
count alone: multiple share classes and clone portfolios are deduplicated.

## Evidence tiers

- A: regulator, court/disciplinary decision, audited/official fund disclosure.
- B: fund-company report, official biography, signed interview/transcript.
- C: reputable financial reporting with named sources.
- D: aggregator/community content; discovery only, never sole evidence for a
  compliance deduction or biographical fact.

Conflicting evidence remains visible. Serious unresolved conflicts lower data
confidence and can block publication; they are not silently converted into a
negative score.

## Machine validation boundary

Validation is deliberately split into two mandatory layers, in this order:

1. The explicitly selected packaged resource
   `schema / manager_research / 0.1.0` validates document structure, required
   fields, closed objects, primitive types, ranges and enumerations.
2. `openfundscore.manager_research.validate_manager_research` validates semantic
   content that JSON Schema does not own: sensitive-private-text exclusion,
   resolution of every nested `evidence_ids` reference against top-level
   `evidence`, and the A/B/C evidence-tier minimum for scored or high-confidence
   `compliance_integrity`.

Passing the JSON Schema alone is not sufficient. Callers must run both layers;
semantic errors include the failing JSON path. The machine checks can be run with:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_manager_schema tests.test_manager_semantics -v
```
