# Roadmap

## M0 — Foundation (complete)

- public repository and Apache-2.0 code licence;
- project, taxonomy, scoring, manager and provider contracts;
- ten category-aware 100-point profiles;
- configuration validator, schemas, tests and CI.

Exit gate: independent specification and quality review; CI green on `main`.

## M1 — Canonical entities and local storage (current)

- `fund_strategy`, `share_class`, `benchmark`, `manager`, `manager_tenure`,
  `holding_snapshot`, `provider_record` and `evidence` models;
- effective-date and publication-time semantics;
- synthetic multi-category fixtures including closed/merged/changed funds;
- entity resolution without relying on names alone.

Exit gate: deterministic round trips and conflict-preserving joins.

## M2 — Provider SDK and official-source pilots

- provider capability/entitlement interface;
- Mainland official disclosure pilot;
- SEC/ESMA/SFC/MAS and macro/reference pilots where terms allow;
- local user import and licensed-commercial plugin boundary;
- Alipay/Ant Fortune adapter only after public-field and terms review.

Exit gate: no credentials or restricted raw data in repository; every record has
provenance, rights, as-of/publication/retrieval timestamps and quality state.

## M3 — Metric and manager-attribution engines

- return, drawdown, recovery, downside, tracking and cost metrics;
- category-specific portfolio metrics;
- exact manager tenure windows, co-management and transition attribution;
- style fingerprints, workload/capacity and verified compliance evidence;
- confidence and risk flags separated from Open Score.

Exit gate: fixed examples, adversarial edge cases and no duplicate contribution.

## M4 — Point-in-time calibration and backtesting

- historical universe including closed, merged and transformed funds;
- publication lag, benchmark/classification/manager versions and data revisions;
- walk-forward validation, sensitivity and component-correlation analysis;
- score stability, turnover, drawdown and future peer outcome diagnostics.

Exit gate: methodology report documents failures and uncertainty, not just the
best backtest.

## M5 — Local reports and comparison workflow

- single-fund and multi-fund local reports;
- share-class fee/holding-period selection;
- overlap, role, risk-budget and stress reports;
- platform availability checked at execution time;
- suitability remains separate from fund quality.

Exit gate: reports reproduce from frozen input snapshots.

## M6 — Hermes Skill

- a concise `SKILL.md` that orchestrates the tested Python package;
- no large formulas or scraping logic embedded in prompts;
- explicit provider, privacy, confidence, compliance and human-trade gates;
- examples for personal and general users.

Exit gate: Skill integration tests and the same result as direct CLI/package use.

## M7 — Publication and legal gate

Before any hosted real-fund leaderboard, obtain jurisdiction-appropriate review
for fund-evaluation publication, provider licences, database rights, retention,
attribution and conflicts. Code release does not imply permission to redistribute
data or publicly market ratings.

The package's point-in-time publication gate does not trust, interpret or record
caller-supplied reviews, provider clearances, control assertions or human-release
roles. It can only record an explicit hosted `NO_GO` or private `LOCAL_ONLY`
decision until future authenticated infrastructure verifies immutable approval
artifacts and their publication-manifest binding. The repository ships with no
such infrastructure or artifacts. Private local research remains available
subject to entitlements. See
[PUBLICATION_GATE.md](PUBLICATION_GATE.md).
