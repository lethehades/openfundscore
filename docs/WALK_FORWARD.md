# Point-in-time walk-forward validation

OpenFundScore's walk-forward harness is a deterministic, local research tool. It
freezes every decision from information that was knowable at that decision time,
then joins future outcomes only after selection. It does not place trades, publish
a live rating, predict returns or guarantee principal or performance.

## Point-in-time contract

A fold has ordered training, validation, decision and outcome windows. Its
`embargo_seconds` must fit entirely between `decision_at` and `outcome_start`, and
outcome windows may not overlap.

A strategy enters a fold universe only when `inception_at <= decision_at`.
Closed, merged and transformed strategies remain in the historical universe for
survivorship control. They are eligible while their point-in-time lifecycle is
active and become retained-but-ineligible only when a terminal lifecycle record
was both published and known by the decision and was effective at that decision.

Each lifecycle record has independent `effective_from`/`effective_to`,
`published_at` and `knowledge_at` fields. Resolution first excludes records with
`published_at > decision_at` or `knowledge_at > decision_at`, then applies the
effective interval. A terminal event may therefore be published before its future
effective date without terminating the strategy early. Conversely, a closure
that was effective in the past but published later cannot leak into an earlier
decision. Missing or ambiguous lifecycle state fails closed. Reports retain the
known lifecycle records, including known future-effective events, in
`audit_lifecycle`.

Classification, benchmark, manager, fee, availability and optional feature
snapshots use the same publication and knowledge cutoffs plus their effective
intervals. Each domain must resolve uniquely. Required text values must be
non-empty strings, fees must be finite and non-negative, and availability must be
a Boolean. Conflicts, missing values, unknown values and unavailable strategies
fail closed. All matching point-in-time snapshots—including records involved in
a conflict—remain in the fold audit trail.

This controls publication lag and basic revision leakage only when callers supply
true historical versions. Latest-only data, silently revised histories or a
current constituent list are not point-in-time data.

### Revision and supersession chains

Lifecycle, snapshot and precomputed-score revisions are explicit rather than
latest-write-wins. Records are grouped by one economic identity: lifecycle by
effective interval within a strategy, snapshots by strategy/domain/effective
interval, and precomputed scores by strategy/effective interval. Every group must
have exactly one root revision and one complete, acyclic, unbranched
`revision_id` -> `supersedes_revision_id` chain. Revision IDs must be unique in
the group. A child may only supersede a present direct parent, may not be
published before its parent, and must have a strictly later `knowledge_at`.
Missing parents, duplicate IDs, multiple roots, forks, cycles and attempts to
supersede a future or equally-known revision fail closed with a stable revision
error.

For example, an economic record can have `revision_id="r1"`, effective from
2020-01-01 and known on 2020-12-20. A correction with the same effective interval
can later declare `revision_id="r2"`, `supersedes_revision_id="r1"` and become
known on 2021-02-20. A January fold resolves `r1`; a March fold resolves `r2`.
The later publication does not rewrite the January decision. Omitting `r1` from
the supplied history, supplying two children of `r1`, or supplying an unlinked
second root is rejected rather than resolved by input order.

## Score boundary and provenance

Use exactly one score source:

- a callback returning `ScoreResult | None`; or
- versioned `PrecomputedScore` records.

A plain `float` is rejected. Boolean, NaN and infinite scores are rejected
stably. A score contains a finite total, named additive component contributions,
component/model versions, provider ID, provider snapshot ID/version and
score/publication/knowledge timestamps. Complete contributions must sum to the
total. The provider identity must equal the uniquely resolved provider snapshot,
and score timestamps cannot predate the input snapshot's as-of, publication or
knowledge timestamps. Scores not known by the decision are excluded.

Every retained score audit is bound to its strategy. `FoldReport.audit_score_ids`
uses the stable key `(strategy_id, audit_id, revision_id)`, and that key is
run-global: reuse is allowed only when every immutable audit contract field is
identical. Every corresponding `score_audit_trail` item carries the same
`strategy_id`, audit/revision lineage, model/provider versions, timestamps and
components. A callback may reuse an `audit_id` for different strategies without
merging their audits because the harness binds each returned immutable
`ScoreResult` to the `ScoringView` strategy.
Within one strategy, repeated or branching precomputed revisions still fail
closed; identity is never inferred from input order.

`ScoringView` contains only the fold, decision timestamp, strategy ID and resolved
point-in-time snapshots. It has no future-outcome field. Callback exceptions are
converted to a fixed redacted error; `KeyboardInterrupt` and `SystemExit` still
propagate, and no partial report is returned or printed.

Future knowledge has deliberately different handling at the two score boundaries.
A precomputed record with future `published_at`, `knowledge_at`, `score_as_of` or
effective interval is not visible to that fold and produces a structured
`score_missing` failure when no older revision is eligible. A callback executes at
the decision boundary: returning `None` likewise records `score_missing`, but
raising an exception aborts with redacted `score_callback_failed`, and returning a
score whose timestamps are after the decision aborts with
`score_not_point_in_time`. These callback contract errors are not silently treated
as absent precomputed history.

## Diagnostics and formulas

### Component coverage and correlation

For each component, the report includes total observations, finite observations,
missing observations, component versions and complete/partial status.

For components `x` and `y`, Pearson correlation is calculated on their
pairwise-complete observations:

```text
r(x,y) = sum((x_i-x_bar)(y_i-y_bar))
         / sqrt(sum((x_i-x_bar)^2) * sum((y_i-y_bar)^2))
```

Inputs are scaled before the calculation to avoid overflow without changing
Pearson correlation. Every pair reports `sample_size`. Fewer than two pairs are
`insufficient_sample`; zero variation is `constant_component`; neither condition
is represented as a fabricated zero correlation.

### Leave-one-component-out sensitivity

For each named additive component `c`, the no-refit perturbation is:

```text
perturbed_score_i = baseline_score_i - contribution_(i,c)
```

No model is retrained, no parameter is tuned and no future outcome is read. The
fold serializes baseline and perturbed ranks, baseline and perturbed selections,
selected-set Jaccard distance, Spearman rank correlation across all eligible
strategies, and the change in selected mean score. Incomplete component coverage
is reported rather than imputed. Summary values average only estimated fold
scenarios.

### Stability, turnover, breadth and coverage

- score stability: Spearman rank correlation between consecutive folds on the
  overlapping eligible strategies;
- selection turnover: Jaccard distance
  `1 - |A intersect B| / |A union B|`;
- breadth: selected counts by point-in-time classification;
- coverage: eligible scored strategies divided by the point-in-time universe,
  including retained terminal strategies in the denominator.

Statuses explicitly distinguish no prior fold, insufficient overlap and
insufficient variation.

### Future outcomes, wealth, drawdown and recovery

Selections are frozen before matching future outcomes. Selected strategy returns
are equal-weighted by period. Peer-relative return is each selected strategy's
compounded simple return minus its matched peer's compounded simple return.
Missing outcomes produce partial or insufficient status rather than imputation.

Wealth begins at `1.0`:

```text
W_0 = 1
W_t = W_(t-1) * (1 + r_t)
drawdown_t = W_t / max(W_0, ..., W_t) - 1
maximum drawdown = min(drawdown_t)
```

Including `W_0` means a first-period loss is not missed. Recovery periods are
counted from the maximum-drawdown trough until wealth regains the associated prior
peak. Input returns are finite simple returns in `[-1, 1]`, series length is
bounded, and non-finite wealth is rejected.

Uncertainty is a descriptive 95% normal approximation for the arithmetic mean:

```text
mean +/- 1.96 * sample_standard_deviation / sqrt(n)
```

It requires at least two observations. It is not a forecast interval and can be
unreliable for small, dependent or non-normal samples.

## Strict JSON and resource limits

Schema version `0.1.0` is exact: unknown or missing fields fail closed. The CLI
accepts at most 8 MiB of strict UTF-8 JSON and rejects duplicate object keys,
NaN/Infinity constants, invalid Unicode, excessive depth or width and malformed
JSON. API collections and nested lifecycle/component/outcome content have bounded
per-container and cumulative sizes; outcome series are limited to 256 periods.
Reports reject every non-finite number before JSON serialization.

Identifiers are non-empty and limited to 256 characters. Scalar snapshot, score
and component inputs must be finite, non-Boolean numbers with absolute magnitude
at most `1e308`; derivations that overflow fail with `calculation_overflow`.
General snapshot text is limited to 4,096 characters, while identifier-like
classification/benchmark/manager values must also be non-empty. Fees are limited
to `[0, 100000]` basis points and simple outcome returns to `[-1, 1]`. The API and
CLI use the same dataclass validation, so a huge JSON integer is rejected rather
than converted to infinity or emitted in a report.

These limits are denial-of-service boundaries, not claims that every accepted
input is economically meaningful.

## CLI example

Generate the deterministic synthetic input and run it locally:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from openfundscore.walk_forward_io import synthetic_fixture_document

Path("/tmp/openfundscore-walk-forward.json").write_text(
    json.dumps(
        synthetic_fixture_document(),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
openfundscore walk-forward /tmp/openfundscore-walk-forward.json \
  > /tmp/openfundscore-walk-forward-report.json
```

The command performs no network access. The synthetic fixture includes historical
classification/benchmark/manager/fee/provider versions and active, closed,
merged and transformed strategies.

## Python API example

```python
from openfundscore import run_walk_forward
from openfundscore.walk_forward_fixtures import synthetic_walk_forward_fixture

fixture = synthetic_walk_forward_fixture()
report = run_walk_forward(
    fixture.config,
    candidates=fixture.candidates,
    snapshots=fixture.snapshots,
    outcomes=fixture.outcomes,
    precomputed_scores=fixture.precomputed_scores,
)
assert report.summary.disclaimer == "research_only_not_a_return_guarantee"
```

For non-synthetic use, construct the exported immutable API types explicitly and
preserve frozen source snapshots outside the report.

## Biases, uncertainty and non-goals

The harness cannot repair an incomplete historical universe, missing delisted
funds, incorrect merger links, stale provider timestamps, publication dates
reconstructed after the fact, unrecorded data revisions, benchmark backfills,
fee omissions, manager-tenure errors or unavailable peer outcomes. Such defects
can still create survivorship, look-ahead, selection and revision bias.

Correlation is descriptive rather than causal. Leave-one-component-out analysis
is local sensitivity, not proof of robustness. Repeated model selection,
transaction costs, liquidity, taxes, capacity, multiple testing and regime change
remain outside this harness unless independently modeled and documented.

The output is research-only. It is not personalized suitability advice, an order,
a live recommendation or a promise of future return.
