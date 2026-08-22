# RFC 0001 — Open Score v0.1

Status: accepted for research preview. The formulas are original to this project
and do not reproduce a platform rating.

## 1. Output contract

Open Score is 0–100:

```text
OpenScore = Σ(weight_dimension × dimension_score / 100)
```

Only the final result is rounded. Seven dimensions total exactly 100 for every
strategy profile. Data confidence is a separate publication gate; critical
risk or governance flags may withdraw/cap a rating but are never hidden inside
an unexplained deduction.

## 2. Seven score dimensions

| Dimension | Meaning |
|---|---|
| Performance evidence | peer- and benchmark-relative total return, rolling excess return and statistically qualified alpha evidence |
| Downside risk | maximum drawdown, recovery, downside deviation, expected shortfall, stress and downside capture |
| Consistency | rolling hit rate, regime persistence, parameter uncertainty and style-adjusted stability |
| Manager capability | the versioned manager/team model in `MANAGER_RESEARCH.md` |
| Portfolio structure | holdings quality, concentration, factor/sector/currency/duration/credit exposure and mandate integrity |
| Implementation efficiency | fees, tracking, liquidity, capacity, premium/discount, settlement and platform restrictions |
| Governance operations | disclosure, valuation, operational continuity, conflicts and verified compliance evidence |

## 3. Category weights

| Strategy profile | Perf. | Risk | Consistency | Manager | Portfolio | Implementation | Governance | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Active equity/mixed | 24 | 18 | 12 | 24 | 10 | 7 | 5 | 100 |
| Fixed-income plus | 18 | 22 | 12 | 20 | 15 | 8 | 5 | 100 |
| Index/ETF | 10 | 15 | 10 | 5 | 20 | 35 | 5 | 100 |
| Bond | 15 | 25 | 12 | 18 | 20 | 5 | 5 | 100 |
| Money market | 12 | 25 | 18 | 8 | 22 | 10 | 5 | 100 |
| QDII active | 18 | 20 | 10 | 15 | 17 | 15 | 5 | 100 |
| QDII index | 10 | 18 | 10 | 5 | 20 | 32 | 5 | 100 |
| FOF/pension | 15 | 20 | 12 | 20 | 20 | 8 | 5 | 100 |
| Gold/commodity | 10 | 18 | 10 | 5 | 22 | 30 | 5 | 100 |
| Public REIT | 20 | 20 | 10 | 20 | 20 | 5 | 5 | 100 |

The dimension-weight source of truth is the unchanged packaged resource
`scoring-config / openfundscore-core / 0.1.0`. Metric definitions and the engine
contract are independently versioned in
`metric-catalog / openfundscore-category-metrics / 0.1.0`. Both are resolved only
through complete `(type, name, version)` selectors and both digests are recorded
on results. Sub-category metric definitions differ even when profile weights
match; a short-bond fund is never ranked in an equity bucket.

## 4. Peer scoring

1. Resolve strategy, vehicle, currency, benchmark and share-class entity.
2. Compare only within a versioned peer bucket.
3. Preserve raw values; use robust outlier controls (MAD/IQR and documented
   winsorisation only when justified).
4. Convert metric direction to 0–100 peer percentiles or calibrated monotonic
   scores. Risk, cost and tracking error are reverse-direction metrics.
5. Combine correlated metrics through a predeclared hierarchy; never award the
   same return series several times under different names.
6. Report sample size and the exact observation window; uncertainty is an optional
   annotation and is never synthesized when absent.

Downside capture is the down-market capture ratio: fund downside return in the
benchmark's down-market periods divided by benchmark downside return over those
same periods. `currency_downside_capture` applies the same contract after the
declared currency adjustment. Both use the inclusive sanity range -5 to 5. If a
window has no benchmark downside, the denominator does not exist and the metric
is missing, not zero and not automatically not-applicable.

The money-market weighted-average-maturity contract uses a 180-day sanity cap.
This is a conservative OpenFundScore project bound, not a claim of one uniform
regulatory ceiling across jurisdictions.

## 5. Missing and short data

- Missing or not-applicable data is never zero.
- Core evidence missing or conflicting can produce `insufficient`, not an
  artificially reweighted high score.
- Under 6 months: no formal performance score (money-market exceptions require
  a separate policy).
- 6–12 months: observation only.
- 12–36 months: provisional research score with reduced confidence.
- 36+ months is eligible only when the caller explicitly attests adequate regime
  coverage; without that assertion the result remains provisional.
- A short history or short manager tenure lowers confidence; it never earns a
  “clean history” bonus.
- Raw manager component scores are caller assertions. Recomputed manager/category
  totals therefore carry at most `low` manager confidence, but the confidence cap
  is not a hidden point deduction.

## 6. Double-counting controls

- Fund performance uses strategy-level results; manager performance uses actual
  tenure windows and factor/benchmark residual evidence rather than copying raw
  return again.
- A/C/E/I classes are one strategy observation, not independent confirmations.
- Co-managed periods are attributed to a team unless documented role evidence
  supports a narrower claim.
- Portfolio concentration cannot be penalised again through several aliases.
- During calibration, component correlations and marginal contribution are
  published; highly redundant metrics are removed or capped.

### 6.1 Machine-enforced evidence usage ledger

Every category score must carry a ledger conforming to the packaged resource
`schema / score_evidence_usage / 0.2.0`. In addition to series, lineage, evidence
family, target component, source scope, usage mode and inclusive observation
window, 0.2.0 requires the exact `evidence_id`, `observation_as_of`,
`window_basis` and `window_months` consumed by the engine. `point_in_time` is a
zero-month UTC observation date, `calendar_months` uses the exact reverse-clamped
calendar window, and `actual_dates` preserves the real supplied endpoints. The
published 0.1.0 Schema remains
byte-for-byte available for validation of legacy standalone records, but category
scoring does not silently downgrade to it. The unified `validate_record()` boundary
caps each ledger at 1,000 entries before Schema evaluation, runs the packaged
Schema, then applies `validate_score_evidence_usage` cross-entry rules that JSON
Schema cannot express. Every evidence window ends on or before the UTC date of
the ledger `as_of` timestamp. Before hashing, the ledger `as_of` and every usage
`observation_as_of` are normalized to canonical UTC `Z`; usage order and date-only
window fields are preserved, so offset-equivalent instants produce the same digest.

Fund D1–D4 may use the raw outcomes of the current fund strategy. Manager
performance, downside-control and cross-cycle scores must not reuse the same raw
current-fund series over an overlapping window; current-tenure evidence for
those manager components is residualized or orthogonalized instead. Independent
`external_career` evidence and documented `team_platform` evidence may support
the manager score. Each manager component retains its own evidence identity,
lineage, series, source scope, knowledge time and applicable PIT or period
window; a manager-wide synthetic provenance window is not accepted. Window
endpoints are inclusive, so windows sharing an
endpoint overlap. Fully duplicate ledger entries and unknown target components
are invalid.

Manager values enter category scoring only through a `ManagerResearchHandoff`
containing the immutable raw manager input and eight caller-owned source rows. The
category engine recomputes the manager audit; bare scores, expected summaries and
legacy audits are rejected. The closed component manifest permits current-fund raw
sources only for tenure performance, downside control and cross-cycle consistency;
all eight resulting manager ledger rows explicitly use `evidence_role=primary`.
Each manager row also requires `source_facts_sha256`, derived from the local
manager document facts consumed for that component. Fund primary and capture
denominator rows cannot carry it. This digest detects changes to the local fact
subset; it does not prove an external claim true.
Each observed capture denominator is an additional independent row with
`evidence_role=capture_denominator` and a positive downside sample count, never an
attribute smuggled into the primary row.

## 7. Point-in-time validation

Backtests must use only information available at each historical decision date,
including publication lag, manager change dates, old classifications, closed or
merged funds, fees, benchmark versions and platform availability snapshots.
Walk-forward tests report future peer-relative return, drawdown, recovery,
turnover, score stability and selection breadth. Weight tuning cannot optimise
only future return; it must preserve interpretability and downside behaviour.

The category engine consumes already calculated, audited raw observations. It
does not itself calculate all benchmark, factor, holdings, fee, liquidity and
governance metrics. Upstream formula identifiers, data-source ownership and
provenance requirements are declared by the metric catalog; see
`CATEGORY_METRICS.md`.

Peer audit input binds `window_basis`, `window_months`, inclusive start/end dates,
the peer-admission version/digest, and lowercase 64-character snapshot and document
hashes. These fields are retained in the output and committed to each peer-set
digest; changing a PIT time, window endpoint or hash changes or invalidates the
audit rather than silently preserving the old set. The snapshot and document
hashes themselves are caller assertions; retaining them is not verification of
their preimages or external authenticity.

The catalog declares validation contracts for 92 unique upstream formula
identifiers, and its independent cross-field manifest has 92 corresponding
entries. This is validation coverage of caller-computed raw observations, not a
claim that the category engine implements 92 source formulas. Every identifier has
an explicit rule kind and review
rationale; placeholder-only validation is rejected. Conditional applicability
is driven by closed prerequisite facts. A false prerequisite may justify
`not_applicable`; unavailable evidence for an otherwise applicable formula is
`missing` and never causes weight redistribution.

## 8. Separate suitability layer

Investor risk budget, monthly contribution, horizon, liquidity and platform
availability affect suitability and portfolio role, not Open Score. A high-score
fund can still be unsuitable for a low-volatility user.

All scoring described here is local research. The publication gate returns
`LOCAL_ONLY` for private local research and `NO_GO` for hosted public ratings;
neither a score nor a canonical digest authorizes publication.
