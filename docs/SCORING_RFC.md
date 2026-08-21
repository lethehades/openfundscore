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

The machine-readable source of truth is the packaged resource
`scoring-config / openfundscore-core / 0.1.0`, resolved only through the complete
`(type, name, version)` selector. Sub-category metric definitions differ even
when profile weights match; a short-bond fund is never ranked in an equity bucket.

## 4. Peer scoring

1. Resolve strategy, vehicle, currency, benchmark and share-class entity.
2. Compare only within a versioned peer bucket.
3. Preserve raw values; use robust outlier controls (MAD/IQR and documented
   winsorisation only when justified).
4. Convert metric direction to 0–100 peer percentiles or calibrated monotonic
   scores. Risk, cost and tracking error are reverse-direction metrics.
5. Combine correlated metrics through a predeclared hierarchy; never award the
   same return series several times under different names.
6. Report sample size, observation window and uncertainty.

## 5. Missing and short data

- Missing or not-applicable data is never zero.
- Core evidence missing or conflicting can produce `insufficient`, not an
  artificially reweighted high score.
- Under 6 months: no formal performance score (money-market exceptions require
  a separate policy).
- 6–12 months: observation only.
- 12–36 months: provisional research score with reduced confidence.
- 36+ months and adequate regime coverage: eligible for full research rating.
- A short history or short manager tenure lowers confidence; it never earns a
  “clean history” bonus.

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

Every score record must carry a ledger conforming to the packaged resource
`schema / score_evidence_usage / 0.1.0`. The ledger identifies each consumed
series, its lineage and evidence family, target component, source scope, usage
mode and inclusive observation window. The unified `validate_record()` boundary
caps each ledger at 1,000 entries before Schema evaluation, runs the packaged
Schema, then applies `validate_score_evidence_usage` cross-entry rules that JSON
Schema cannot express. Every evidence window ends on or before the UTC date of
the ledger `as_of` timestamp.

Fund D1–D4 may use the raw outcomes of the current fund strategy. Manager
performance, downside-control and cross-cycle scores must not reuse the same raw
current-fund series over an overlapping window; current-tenure evidence for
those manager components is residualized or orthogonalized instead. Independent
`external_career` evidence and documented `team_platform` evidence may support
the manager score. Window endpoints are inclusive, so windows sharing an
endpoint overlap. Fully duplicate ledger entries and unknown target components
are invalid.

## 7. Point-in-time validation

Backtests must use only information available at each historical decision date,
including publication lag, manager change dates, old classifications, closed or
merged funds, fees, benchmark versions and platform availability snapshots.
Walk-forward tests report future peer-relative return, drawdown, recovery,
turnover, score stability and selection breadth. Weight tuning cannot optimise
only future return; it must preserve interpretability and downside behaviour.

## 8. Separate suitability layer

Investor risk budget, monthly contribution, horizon, liquidity and platform
availability affect suitability and portfolio role, not Open Score. A high-score
fund can still be unsuitable for a low-volatility user.
