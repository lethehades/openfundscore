# Data Provider Policy

## Principle

Providers supply observations; OpenFundScore defines metrics and weights.
Alipay/Ant Fortune is a candidate sales-platform provider boundary, not an
implemented adapter, identity system, methodology owner or sole source. As of
`2026-08-22T00:22:00Z`, no confirmed public per-fund API, field-level
authorization, or automated adapter is recorded; per-fund collection remains
`unknown_blocked`.

## Priority order

1. regulator, exchange, official registry and legally filed disclosure;
2. fund manager/company, custodian, administrator and official prospectus/report;
3. benchmark administrator, central bank and statistical agency;
4. licensed commercial data under the user's entitlement;
5. sales/distribution platforms such as Alipay and Eastmoney;
6. reputable reporting for qualitative discovery;
7. user import, requiring explicit provenance and confirmation.

Priority does not erase conflicts. Every record retains source, as-of date,
publication time, retrieval time, units, currency, methodology and rights.

## Initial source catalogue

### Mainland China and Chinese distribution

- CSRC and AMAC: registration, rules, institutions, personnel and official
  evaluation/compliance context.
- Exchanges and fund-company disclosures: listed funds, REITs, announcements,
  holdings, reports, benchmark and manager changes.
- Alipay/Ant Fortune, Eastmoney/Tiantian, banks and brokers: platform mapping,
  displayed fees, limits and current availability where access is authorised.
- Commercial connectors (Wind, Choice, CNI and others): optional local plugins;
  no licensed dataset is bundled or redistributed.

### Overseas regulatory and official sources

- US SEC EDGAR APIs and investment-management filings:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- ESMA databases/registers and national competent-authority repositories:
  https://www.esma.europa.eu/publications-and-data/databases-and-registers
- UK FCA Financial Services Register (access and reuse terms must be checked):
  https://register.fca.org.uk/
- Hong Kong SFC authorised product list, including unit trusts, ETFs and REITs:
  https://apps.sfc.hk/productlistWeb/searchProduct/UTMF.do
- Singapore MAS OPERA collective-investment-scheme records:
  https://eservices.mas.gov.sg/opera/
- Other planned official adapters include Japan EDINET, Canada SEDAR+, ASIC,
  and jurisdictional regulator/fund registries after field and licence review.

### Benchmarks, macro and reference data

- Index administrators and exchanges under their licence terms.
- FRED/ALFRED for macro series and vintage-aware observations:
  https://fred.stlouisfed.org/docs/api/fred/
- World Bank developer APIs for documented international indicators:
  https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information
- IMF, BIS, OECD and central-bank data only with an explicit series definition,
  publication lag and revision policy.
- OpenFIGI/ISIN or licensed security masters for identity mapping; names alone
  are never sufficient identifiers.

### International commercial/financial platforms

Morningstar, LSEG/Lipper, Bloomberg, FactSet, S&P Capital IQ, MSCI/FTSE/S&P
index data, Yahoo Finance and similar sources are connectors only when their
terms permit the requested use. Proprietary ratings remain under
`external_ratings` and never enter Open Score by default.

## Provider contract

A provider declares capabilities such as:

```text
list_funds, get_profile, get_share_classes, get_nav_series,
get_benchmark, get_manager_tenures, get_holdings, get_fees,
get_purchase_status, get_disclosures, get_external_ratings,
get_entitlements
```

`get_entitlements` must state authentication mode, caching, derived-work rights,
public display, redistribution, retention, rate limit and attribution.

## Rights modes

- `open_redistributable`: raw data may be redistributed under named terms.
- `derived_only`: calculate locally; do not publicly display or publish raw or
  normalized rows.
- `local_entitlement`: user supplies an authorised key/file; keep results local.
- `display_only`: show limited fields with attribution; no bulk storage/export.
- `unknown_blocked`: do not ingest until reviewed.

A public webpage is not automatically open data. Robots rules, rate limits,
terms, copyright, database rights and account restrictions must all be checked.
Robots is not authorization. A missing, unavailable, reset, HTML, or otherwise
unverified robots response must remain `unverified_unavailable`; it must not be
translated into invented `Allow` or `Disallow` rules.

### Ant Fortune boundary (Issue #9)

The versioned `platform-boundary / ant_fortune / 0.1.0` resource inventories
fund/share-class identifiers and names; subscription, redemption-tier,
sales-service, ongoing, management and custody fee candidates; purchase amount
limits; subscription, redemption and sale availability; and external platform
ratings. Every per-fund row independently records observation/access,
authorization, official evidence and review time, terms, robots, rate limit,
cache TTL, retention, derived/display/redistribution/attribution rights,
provenance, pending evidence and re-evaluation triggers.

The only verified official entries are <https://www.antfortune.com/> and
<https://open.alipay.com/>. They establish brand/entry facts only, not per-fund
fields or a public API. All per-fund uses are `unknown_blocked`: no ingestion,
cache, derived work, display, redistribution, or automatic adapter. Ratings are
fixed to `external_ratings` and cannot affect Open Score. See
[Ant Fortune public-data boundary](ANT_FORTUNE_BOUNDARY.md). This policy is not
legal advice.

## Security and privacy

- Never request/store Alipay password, payment PIN, SMS code, session cookie or
  unrelated account data.
- No bypass of login, CAPTCHA, anti-bot or platform controls.
- API keys are user-local environment/secrets, never committed or logged.
- Personal holdings and suitability profiles are local by default and isolated
  per user.
- Manager research is limited to relevant public professional evidence.

## Point-in-time and quality

Every observation follows the explicitly selected packaged resource
`schema / provider_record / 0.1.0`. Providers must
state whether historical retrieval is truly point-in-time. Today's manager,
classification, benchmark or availability cannot be backfilled into a past
simulation. Missing, stale and conflicting states remain distinct.

JSON Schema validation is structural and is not sufficient on its own. After
schema validation, local ingestion must call the unified
`openfundscore.validate_record()` boundary with record type `provider_record`,
Schema version `0.1.0` and an explicit RFC3339 `evaluation_timestamp`. The
boundary always runs Schema and semantics in order, is deterministic, does not
read the clock, and never rewrites or drops a record.

The timestamp profile is a deterministic RFC3339 subset using ASCII digits:
uppercase `T`, uppercase `Z` or a known numeric `±HH:MM` offset (`00`–`23`
hours and `00`–`59` minutes), and zero to six fractional-second digits.
Lowercase `t`/`z`, non-ASCII digits, leap-second `:60`, sub-microsecond
precision, malformed offsets and RFC3339's unknown-local-offset marker `-00:00`
are rejected rather than normalized or truncated.

The semantic contract enforces:

- timestamps in that offset-aware profile for observation, publication, retrieval,
  validity and optional rights-review times;
- `published_at <= fetched_at <= evaluation_timestamp`, and
  `as_of <= fetched_at`, preventing future knowledge from entering a current or
  historical evaluation;
- `valid_from <= valid_to` when both endpoints exist;
- `as_of <= evaluation_timestamp`, preserving the explicit evaluation boundary;
- future-effective facts through a future `valid_from` while retaining a
  non-future `as_of`;
- both a non-empty `provider_record_id` and `source_document_hash` for
  `point_in_time_status = verified`;
- a documented methodology and non-verified quality state for reconstructed and
  explicitly not-point-in-time records;
- a non-verified quality state for records whose point-in-time status is unknown.

`provider_claimed` remains a separate chronology assertion and is never promoted
to `verified` by validation. `quality_state` describes observation quality, so it
remains a separate axis from chronology confidence. A validity interval with
equal endpoints is accepted for compatibility with the canonical model but is an
empty half-open interval `[valid_from, valid_to)` and will not match any instant.

## Typed ingestion enforcement

Schema and semantic validity do not grant a right to use data. Provider adapters
must expose typed capabilities and an exact-time `get_entitlements()` snapshot,
then pass each record through `openfundscore.provider_sdk.authorize_ingestion()`
before persistence or downstream use. The boundary independently enforces
provider identity, capability, rights mode, attribution readiness, provider-bound
rate limits, cache TTL, display, derived-work, redistribution and retention.
Unknown rights block ingestion. See [Provider SDK](PROVIDER_SDK.md).
