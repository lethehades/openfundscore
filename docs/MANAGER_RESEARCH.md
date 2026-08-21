# Fund Manager and Investment Team Research Model

This model covers public professional evidence only. It excludes private life,
family, contact details, rumours, political profiling and unrelated social-media
content. Prestigious education is descriptive evidence, not a scoring shortcut.
Sensitive-text detection uses a normalized scan-only view with Unicode format,
control and combining characters removed, so invisible characters cannot hide
contact details; the stored public source text itself is not rewritten. The guard
also recognizes grouped Chinese mobile/identity numbers and common email-dot or
`[at]`/`(at)` obfuscation, while excluding ordinary phone-meeting prose and
unseparated ten-digit public values from the North American phone pattern in
professional prose. Source URLs retain a stricter compact-number check because a
phone number embedded in a URL is contact disclosure rather than an analytical
value. Both dictionary-style manager records and typed canonical evidence use
the same bounded recursive URL-decoding validator. It is a conservative
pattern-based boundary, not a claim of exhaustive DLP; callers must still
exclude contact data at ingestion.

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
- structured research-platform capacity, team and decision-process evidence;
- a timestamped compliance assessment, including an explicit insufficient state;
- verified compliance events with jurisdiction, status and source;
- evidence objects with URL/document, publication date, as-of date, retrieval
  time, quoted fact and confidence tier.

## Attribution rules

1. Attribute only dates when the manager actually held the role.
2. Separate legacy holdings and transition periods after appointment/departure.
3. Preserve benchmark and mandate versions in force at that date.
4. For co-management, default to team attribution. Do not give every manager
   100% credit for the same observation. A documented role-weighted decision
   uses `attribution_share` in (0, 1); unresolved roles remain unscored until
   attribution is resolved.
   A team observation is divided equally across the subject and listed
   co-managers; a role-weighted observation uses its explicit share. The scoring
   API averages each uniquely cited tenure factor and applies it only to the
   tenure-attributed-performance component, returning the factors in
   `tenure_attribution` for audit. Every performance observation has a unique
   `observation_id`; the output maps the observations, windows, metrics and
   only the component-qualified evidence IDs actually used. Observations with
   `confidence=insufficient` or a missing numeric `value` cannot support a
   numeric performance component. One factor-residual evidence object, or the same
   window/metric/residual observation under a different ID, cannot be reused
   across tenures. Identifier and measure-name fields reject Unicode controls,
   combining or spacing characters and compatibility variants, preventing
   visually identical IDs or metrics from bypassing uniqueness and attribution
   signatures. A numeric score is rejected when attribution remains unresolved.
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
Each quantitative style block is a timestamped, closed snapshot containing
named numeric measures and optional methodology. Measure names must be unique,
the timestamp cannot be after the manager record's `as_of`, and change points
carry an effective date, a `known_at` timestamp and evidence references.
Evidence used by a quantitative snapshot must already have been published and
fetched by that snapshot timestamp. Change-point evidence must have been
published and fetched by `known_at`; compliance-assessment evidence must
likewise be available by `reviewed_at`. Later evidence cannot backfill a
historical claim.

## Workload and platform burden

Measure concurrent strategy count, product count, total assets, number of
materially different mandates, co-manager coverage, new launches, redemptions,
team turnover and company investment-platform continuity. Do not use raw product
count alone: multiple share classes and clone portfolios are deduplicated.
Reported AUM uses a non-empty three-letter uppercase currency code.
Empty or Unicode-invisible-only organisation, role or team-coverage strings are
not research facts, and an `unknown` succession status alone cannot support a
numeric platform score. Domain fact text must contain at least one Unicode
letter or number.

## Evidence tiers

- A: regulator, court/disciplinary decision, audited/official fund disclosure.
- B: fund-company report, official biography, signed interview/transcript.
- C: reputable financial reporting with named sources.
- D: aggregator/community content; discovery only, never sole evidence for a
  compliance deduction or biographical fact.

Conflicting evidence remains visible. Serious unresolved conflicts lower data
confidence and can block publication; they are not silently converted into a
negative score.

Each evidence object may declare `supports_components`. Every numeric component
must cite at least one evidence object that explicitly names that component.
Every numeric component must share the same evidence object with its matching
structured research fact: performance observations, style, workload,
employment/tenure history, research platform or compliance assessment. One
evidence object must therefore be both cited by the component and its domain
block and explicitly name the component in `supports_components`; two unrelated
objects cannot split those duties. Self-declaring support without the matching
structured fact is insufficient.
For numeric or high-confidence compliance scores, the same assessment evidence
must also declare compliance support and have Tier A, B or C. An unrelated
higher-tier reference cannot upgrade Tier D assessment evidence. The
`no_verified_events` assessment state cannot coexist with a `final_verified`
event in the same record.
Evidence and compliance-event identifiers, every evidence-reference list and
every component-support list are unique. Cross-cycle scores require at least two
different regimes backed by non-overlapping windows, not two labels placed on
the same observation period.

## Machine validation boundary

Validation is deliberately split into two mandatory layers, in this order:

1. The explicitly selected packaged resource
   `schema / manager_research / 0.1.0` validates document structure, required
   fields, closed objects, primitive types, ranges and enumerations.
2. `openfundscore.validate_record` dispatches the manager semantic checks after
   Schema success: sensitive-private-text exclusion, resolution of every nested
   `evidence_ids` reference against top-level `evidence`, the A/B/C evidence-tier
   minimum for scored or high-confidence `compliance_integrity`, ordered
   employment/tenure/performance ranges (date-only fields compare against the UTC
   date of `as_of`), and evidence retrieval no later than the record `as_of`.
   Scored tenure performance requires cited factor-residual evidence; scored
   downside control requires a cited downside metric; scored cross-cycle
   consistency requires evidence from at least two regimes; and scored style,
   workload, career, platform and compliance components require the same
   semantically matched evidence in their respective structured blocks.

`openfundscore.score_manager_research(record)` first rebuilds the caller-owned
mapping into one bounded, finite snapshot containing only exact built-in JSON
values. Unified validation and scoring consume that same snapshot, so overridden
mapping/list/scalar methods cannot present one identity or component value to the
Schema and another to the scorer. It then loads the manifest-verified
`openfundscore-core / 0.1.0` manager weights. The result includes the manager and
`as_of` identities, model version, component weights, per-component evidence IDs
and contributions, tenure-attribution factors, aggregate confidence and final
score. Numeric scores and `insufficient` confidence are mutually exclusive.
Missing or `insufficient` components never become zero and are never silently
reweighted: the aggregate status is `insufficient` and its score is `null`.
The canonical boundary rejects cycles, depth above 512 and total node counts
above 10,000 so hostile records cannot create unbounded traversal work.

Passing the JSON Schema alone is not sufficient. Callers use the unified API or
CLI so both layers always run and failures carry stable paths:

```bash
openfundscore validate-record \
  --type manager_research --schema-version 0.1.0 manager-research.json
```
