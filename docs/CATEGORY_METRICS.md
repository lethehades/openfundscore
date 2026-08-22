# Category metric engine

## Versioned resources and migration

Category scoring uses three independently versioned package resources:

- `scoring-config / openfundscore-core / 0.1.0` owns the seven dimension weights.
- `metric-catalog / openfundscore-category-metrics / 0.1.0` owns the ten profiles,
  twelve core metrics per profile, metric weights/directions/evidence families,
  upstream formula and provenance declarations, and the normalization contract.
- `peer-admission / category-profile-buckets / 0.1.0` owns the closed mapping from
  each category profile to its allowed peer bucket.

The published scoring-config 0.1.0 bytes and SHA-256 digest are intentionally
unchanged (`e0f9f8ed58e840a078924cce2c5acae661e5a903d82402ecaf152c1ac7c85a16`).
Metric definitions and peer admission were moved to new resource types rather than
retroactively changing a released artifact. Every result records the scoring
configuration, metric-catalog and peer-admission versions and digests so a score
can be reproduced.

## Raw metric ownership and point-in-time boundary

This engine **does not compute all 120 profile-specific raw metrics**. Raw metric
calculation is upstream, and each supplied raw value is a caller assertion rather
than an externally verified fact. The catalog declares the upstream formula identifier,
data-source contract and required provenance for each metric. The engine consumes
only audited `MetricObservation` values. Each observation carries stable fund,
series, evidence and lineage identifiers, `as_of`, `published_at`,
`evaluation_timestamp`, sample size and window length. `uncertainty` is an
optional caller annotation and remains null when omitted. All
timestamps must be timezone-aware and satisfy
`as_of <= published_at <= evaluation_timestamp`.

This separation prevents a percentile engine from pretending that benchmark,
factor, holdings, liquidity, fee and governance source calculations are all the
same operation. Callers remain responsible for licensed data access, upstream
formula implementation, lineage and point-in-time snapshots.

## Formula semantic manifest

Catalog 0.1.0 embeds an independently auditable `formula_semantics` manifest that
declares contracts for 92 unique upstream formula identifiers. It does not contain
92 formula implementations: caller-owned upstream systems calculate the raw
values. Each of the 120 profile rows copies the exact
contract for its formula. Repeated formulas therefore cannot acquire different
semantics in different profiles. The generator uses an explicit formula-by-formula
table; it does not infer economics from words in a metric identifier.

Every formula contract is closed and declares:

- scoring `domain` and economic `unit`;
- inclusive `value_range.minimum` and `value_range.maximum`;
- `observation_window` kind, unit and inclusive minimum/maximum duration;
- `applicability`, upstream `formula_owner`, and audited `data_source` family.

An independent cross-field rule manifest covers the same 92 formulas. Each
formula has one explicit rule kind and a non-empty review rationale; no generic
`window_only` placeholder is accepted. The closed rule kinds are
`independent_range`, `period_sample`, `negative_day_count`,
`recovery_duration_months`, `event_duration_days`, and
`point_in_time_maturity_days`. These rules bind values to sample/window facts
that a range check alone cannot establish.

Observation windows are not all month-based rolling series. The closed kinds are
`point_in_time`, `rolling_period`, `reporting_period`, and `cumulative_period`.
A point-in-time observation uses `unit=instant` and zero bounds; period windows
use explicit month bounds. This keeps holdings/disclosure snapshots distinct
from rolling returns, annual reporting periods, and cumulative recovery events.

Representative economic contracts include:

| Formula | Unit and inclusive range | Observation window |
| --- | --- | --- |
| `recovery_months` | months, 0–1200 | cumulative, 0–1200 months |
| `ongoing_charge` | basis points, 0–1000 | reporting period, exactly 12 months |
| `rolling_goal_hit_rate` | ratio, 0–1 | rolling period, 12–60 months |
| `benchmark_coverage` | ratio, 0–1 | point in time |
| `negative_return_days` | count, 0–366 | rolling period, 1–12 months |
| `downside_capture` | down-market capture ratio, -5–5 | rolling period, 12–60 months |
| `currency_downside_capture` | currency-adjusted down-market capture ratio, -5–5 | rolling period, 12–60 months |
| `weighted_average_maturity` | days, 0–180 | point in time |

Thus a negative ongoing charge or recovery duration, a hit rate above one, a
negative count, or a value outside a formula's declared bound is invalid input;
fixtures are not allowed to widen these economic contracts. The catalog
validator checks the embedded manifest and every profile copy against the
compiled v0.1.0 table, so coordinated edits to a unit, range, window kind, source
family, or other semantic field fail closed rather than redefining a formula.

Both downside-capture formulas are evaluated only over benchmark down-market
periods. The numerator is the fund's downside return (currency-adjusted for
`currency_downside_capture`) aggregated over those periods; the denominator is
the declared benchmark's downside return over the same periods. If the selected
window contains no benchmark downside, there is no denominator and the metric
must be `missing`, never zero or `not_applicable`. The -5 to 5 range is a
contract sanity bound on this ratio, not a percentage range.

Every target and peer capture row carries a closed `CaptureDenominatorAudit` with
`denominator_status`, `benchmark_downside_sample_count`, `evidence_id`,
`lineage_id` and `series_id`. An observed capture requires `present` and a positive
denominator count no greater than the metric sample; an unobserved capture requires
`absent` and zero. Non-capture metrics cannot carry this audit. Every consumed
target denominator is represented independently in the 0.2 evidence ledger with
`evidence_role=capture_denominator` and its own evidence/lineage/series identity;
it is never folded into the target's `primary` row.

The 180-day WAM ceiling is this project's conservative contract sanity cap for
the money-market profile. It is not presented as a universal statutory or
regulatory limit across jurisdictions or product types.

## Normalization

Catalog 0.1.0 requires at least five and at most 10,000 peer observations per
metric. The selected profile/bucket pair must be admitted by the exact
peer-admission resource. The canonical peer tuple is complete and closed:
`peer_id`, `metric_id`, `raw_value`, `series_id`, `source_id`, `lineage_id`,
`as_of`, `published_at`, `evaluation_timestamp`, `peer_bucket`,
`peer_bucket_version`, `category_profile`, `admission_contract_version`,
`admission_contract_sha256`, `snapshot_hash`, `document_hash`, `sample_size` and
`window_basis`, `window_months`, `window_start`, `window_end` and
`capture_denominator`. The target fund must not also occur in its peer tuple.
`peer_id`, `series_id` and `lineage_id` must each be independently unique within
one metric; identity reuse across different metrics is permitted. Both the
single-metric normalizer and complete category scorer enforce this same contract.
Results retain every tuple as `PeerAuditRecord` rows and commit them to the
`PeerSetAudit.digest`.
Calendar-month peer windows reconcile exactly to their UTC `as_of` date, and both
snapshot and document hashes must be lowercase 64-character SHA-256 values.
Those hashes are caller assertions: the engine retains and commits them but does
not fetch a preimage or infer that the peer document is externally authentic.

1. Sort finite peer raw values.
2. Calculate interpolated Q1 and Q3.
3. Winsorize to `Q1 - 1.5 × IQR` and `Q3 + 1.5 × IQR`.
4. For numerically zero IQR, use median ± `3 × 1.4826 × MAD`; exact zero
   dispersion is clamped to the median and receives a neutral score.
5. Calculate an empirical midrank percentile. Equal values receive the midpoint
   of their tied ranks.
6. Reverse lower-is-better metrics as `100 - percentile`.

Raw values are never overwritten. Results retain raw and adjusted values, bounds,
peer sample size, direction, formula version and adjustment method. The adjusted
peer rows are not repeated in output, but the declared method, bounds and source
peer tuple make the transformation reproducible.

## History stages

RFC 0001 is enforced uniformly; there is no undocumented money-market exception.

- `< 6` months: `insufficient`; performance metrics, dimension score and
  contribution are all unscored.
- `6–<12` months: `observation`; performance metrics, dimension score and
  contribution are all unscored.
- `12–<36` months: `provisional` with low confidence when otherwise complete.
- `>=36` months: `eligible` only when the caller explicitly supplies
  `adequate_regime_coverage=True`; otherwise it remains `provisional`.

An observation window cannot exceed declared fund history. Short history never
creates a contribution or a clean-history bonus.

## Missing and not applicable

`missing` and `not_applicable` are distinct states and both require `raw_value`
to be null. `all_profile_funds` metrics reject `not_applicable`; conditional
`requires_*` metrics may use it only when that declared prerequisite is absent.
Catalog 0.1.0 marks every metric core. Any core metric in either accepted state
makes its dimension and total score insufficient. The output lists missing and
not-applicable metric IDs separately and supplies stable insufficiency reasons.
There is no zero imputation and no redistribution of weight to remaining metrics.
The catalog reserves an optional-metric policy name, but 0.1.0 contains no
optional metrics; its denominator remains fixed and never reweights.

Conditional applicability is executed from a closed `ApplicabilityContext`, not
inferred from a missing value. A conditional metric may be `not_applicable` only
when its declared prerequisite is false; otherwise it must be observed or
missing. In particular, a downside-capture denominator absent because the
benchmark had no down-market periods is missing evidence, while absence of a
declared benchmark is the separate applicability fact.

## Python and CLI

The stable package API exports `ApplicabilityContext`, `CaptureDenominatorAudit`,
`CaptureDenominatorStatus`, `MetricObservation`, `PeerObservation`,
`ManagerScoreAudit`, `PeerAuditRecord`, `PeerSetAudit`, `MetricState`,
`MetricDirection`, `HistoryStage`, `normalize_metric`, `score_category_metrics`,
result value types and `CategoryMetricError` from `openfundscore`.

```bash
openfundscore resources show \
  --type metric-catalog --name openfundscore-category-metrics --version 0.1.0
openfundscore category-score category-score-input.json
```

`category-score` accepts one strict UTF-8 JSON file. Its closed top level requires
the profile and peer bucket/version, `peer_admission_version`, history and regime
facts, applicability context, observations, peers, the manager handoff, the 0.2
evidence ledger, scoring-config version, metric-catalog version, peer-admission
version and final precision. Observation rows include `capture_denominator`; peer
rows additionally include category and admission-contract identity/digest fields.
Observation `uncertainty` is optional; all other closed observation fields remain
required.
Duplicate object keys,
`NaN`/infinities, malformed UTF-8, unknown fields and oversized inputs fail with
a stable nonzero exit. Output JSON is deterministic (`sort_keys=True`) and
contains all three scoring-resource digests.

Output retains `peer_admission_version` and `peer_admission_sha256`, the complete
peer-set records/digests, the recomputed closed manager audit, capture provenance
and the actual evidence-ledger record ID/digest. Category confidence is `medium` only for
a complete eligible result, `low` for a complete provisional result or when the
manager audit is low-confidence, and `insufficient` otherwise. The manager
confidence cap changes confidence only; it does not subtract points from the
recomputed manager or category score.

The score call and CLI document require a complete, closed
`ManagerResearchHandoff`: the immutable raw `manager_research` input, exact
manager `as_of`, target `fund_strategy_id`, exact
`assertion_status=caller_provided`, and one caller-provided source identity row for
each of the eight manifest components. Source input is identity-only: component,
evidence, lineage, series, scope, usage mode and optional fund target. The engine
requires a matching target tenure and derives the fact digest, observation time
and exact window from the consumed structured facts in the local manager document.
That digest binds the local document facts used by the score; it does not prove
the truth or authenticity of an external source. The engine calls the sole manager scorer
again and derives its audit from that recomputation. A bare score, caller-supplied
expected summary, typed audit or legacy `manager_audit` is rejected even if its
numbers reconcile.
They also require a schema-and-semantics-valid `score_evidence_usage@0.2.0` record
as `evidence_ledger`. Version 0.2.0 binds evidence ID, observation timestamp and
exact window; the unchanged 0.1.0 Schema remains available only for explicitly
selected legacy validation and is not accepted by category scoring. Ledger identities
must match every observed fund metric and every manager component evidence ID.
Raw current-fund evidence cannot be reused across fund and manager components.
The former bare `manager_score` input is always rejected.

The ledger `as_of` and every usage `observation_as_of` are canonicalized to UTC
`Z` before digesting, while usage order and date-only window endpoints remain
unchanged. Every manager ledger row is explicitly `primary` and carries the
derived `source_facts_sha256`; fund primary and capture-denominator rows cannot
carry that manager-only field.
The component manifest allows current-fund `raw` only for tenure performance,
downside control and cross-cycle consistency and requires the exact target;
external career performance uses residualized/orthogonal modes, while descriptive
career and team/platform rows use their declared scopes. Manager component handoff
retains each component's actual caller provenance (`evidence_id`, lineage, series,
family, scope, usage, observation timestamp, `window_basis`, months and exact
endpoints).
`point_in_time`, `calendar_months` and `actual_dates` are checked by distinct
rules, and actual-date endpoints are not replaced with a synthetic calendar
window. Manager `as_of`, publication/fetch
knowledge times and PIT/period applicability must all remain internally
consistent rather than being replaced by one synthetic manager-wide window.

## Current limitations

- Research preview only; this is not investment advice or a live ranking.
- Peer-bucket construction and upstream raw formulas are outside this engine.
- Manager capability is accepted only from recomputable raw manager input and its
  exact eight-source manifest; neither a bare 0–100 value nor a precomputed audit
  is accepted.
- Raw manager component scores remain caller assertions and cap confidence at
  `low` without a score deduction. Scoring is local research only: private local
  use is `LOCAL_ONLY`, while hosted public rating remains `NO_GO`.
- Adequate regime coverage is an explicit audited caller assertion in 0.1.0, not
  inferred by this engine.
- No money-market short-history exception is implemented without an accepted,
  versioned policy resource.
