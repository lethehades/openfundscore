# Project Charter

## Mission

Build a reproducible, explainable and extensible fund-research engine that can
run locally for individuals and organisations. Version 1 targets all major
Chinese public-fund strategies and funds available through Chinese platforms,
including products whose underlying assets and reference data are overseas.

## Users

- individual investors comparing candidates or reviewing holdings;
- researchers conducting point-in-time fund studies;
- advisers or institutions using their own licensed data;
- Hermes Agent users invoking the engine through a future Skill;
- developers adding jurisdiction-specific providers and metrics.

## Outputs

Every scored report must keep these fields separate:

1. taxonomy and intended portfolio role;
2. Open Score (0–100) and seven component scores;
3. risk flags and stress observations;
4. data confidence and unresolved conflicts;
5. manager/team status and evidence date;
6. share-class costs and platform implementation state;
7. investor suitability, which never changes fund quality;
8. reasons, formulas, source timestamps and model version.

## Non-goals

- copying Alipay, Morningstar or any other platform's formula;
- republishing proprietary datasets or reverse-engineering closed ratings;
- guaranteeing returns or principal;
- generating a universal cross-category winner;
- automated subscription, redemption or rebalancing;
- collecting private account credentials, cookies or unrelated personal data;
- publishing unverified allegations about fund managers.

## Release boundary

Until jurisdiction-specific legal review is complete, the public repository
ships code, contracts, synthetic examples and local-result tooling. It does not
host a live real-fund leaderboard. Chinese public publication must account for
the *Interim Measures for the Administration of Securities Investment Fund
Evaluation Business*, including category separation, minimum history, method
disclosure and publication requirements:
https://www.gov.cn/zhengce/2021-12/16/content_5724599.htm

## Governance

- Method changes require an RFC, version bump, migration note and walk-forward
  validation.
- Data providers declare rights, freshness, point-in-time support and fields.
- External ratings are stored in a separate namespace and cannot silently enter
  Open Score.
- Conflicts of interest and sponsored relationships must be disclosed.
- Results state that historical evaluation is not a forecast or trade advice.
