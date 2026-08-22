# Official Provider Pilots

OpenFundScore currently contains two deliberately small official-source pilots:
SEC EDGAR submissions metadata and World Bank Indicators API v2 annual
observations. They are ingestion examples, not a complete official-data
catalogue. No real third-party response or dataset is bundled in the source or
distributions.

This document describes engineering controls and conservative local-use policy.
It is not legal advice. API availability does not by itself grant copyright,
database, display, caching, redistribution, or other reuse rights. Review the
applicable provider and dataset terms for the intended use and jurisdiction.

## Shared boundary

Both adapters:

- use fixed HTTPS hosts selected by code, not caller-supplied URLs;
- issue `GET` requests without automatic redirect handling, so redirects are
  rejected as non-2xx responses and cannot cross hosts;
- accept only exact built-in finite numeric connect/read timeouts in the range
  `0 < timeout <= 60` seconds, and also bound response bytes, JSON depth,
  container width and total JSON nodes;
- materialize caller query mappings before transport with at most 64 entries.
  Every key and value must be an exact built-in string of at most 1,024
  characters and 4,096 strict UTF-8 bytes; lone surrogates and encoding errors
  fail closed. Before any percent decoding, a path must be an exact built-in
  string of at most 8,192 characters and 8,192 strict UTF-8 bytes. Path
  validation performs at most eight percent-decoding rounds and rejects a
  still-encoded ninth layer. The final encoded request target is also at most
  8,192 UTF-8 bytes;
- require JSON Content-Type with either no charset or UTF-8, then decode strict
  UTF-8 and reject duplicate object keys, NaN, Infinity and malformed JSON;
- construct `Host` internally from the fixed target and accept only `Accept`
  and `User-Agent` request headers. Each value is non-empty visible ASCII
  (`0x20` through `0x7e`) and at most 1,024 characters. Header names are unique
  case-insensitively; caller-supplied authority, framing, hop-by-hop and
  `Proxy-*` headers fail before transport. If a response declares
  `Content-Length`, its bounded ASCII decimal value must equal the exact
  response-body byte length. The default transport reads and freezes an exact
  built-in integer status before reading any response headers or body; malformed
  and non-2xx statuses fail without consuming either;
- use a local limiter with burst one and evenly space calls at five
  requests/second by default; both reject configuration above ten
  requests/second and accept only an actual `LocalRateLimiter` for clock/sleeper
  injection. An adapter reconstructs an independent limiter from the validated
  declared rate and trusted clock/sleeper callables instead of retaining the
  caller's limiter object, so later alias mutation cannot change its interval or
  state. The clock must return a finite exact built-in `int` or `float`; sleep is
  followed by bounded deadline confirmations, and ordinary injected
  clock/sleeper failures become stable redacted errors while `BaseException`
  continues to propagate;
- return stable errors that do not include response bodies, request headers,
  contact addresses or transport exception details;
- pass every emitted row through packaged `provider_record@0.2.0` validation and
  `authorize_ingestion()` before returning it;
- use `provider_contract@0.2.0` for source-scoped entitlements; published
  `provider_contract@0.1.0` remains an immutable unscoped legacy contract;
- emit explicit unit, currency, timezone, period, frequency, publication-lag,
  revision, vintage, provenance, point-in-time and rights fields; and
- default to local derived-work use: no public raw/normalized display and no raw
  redistribution.

For a live request, `fetched_at` is read from the injected clock only after the
response body has been fully read and validated. If the caller omits
`evaluation_timestamp`, that exact instant is also the evaluation boundary. If
an explicit boundary is supplied, it is validated and frozen as a built-in UTC
`datetime` before the limiter or transport is called, and
`fetched_at <= evaluation_timestamp` remains mandatory. Offline fixture parsers
require both timestamps explicitly and never read the clock. These rules prevent
a request-start timestamp or today's API view from being treated as knowledge
available earlier.

## SEC EDGAR submissions pilot

### Scope and source

- Official overview:
  <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- Fixed API host and path:
  `https://data.sec.gov/submissions/CIK##########.json`
- Access/fair-access terms recorded by the adapter:
  <https://www.sec.gov/os/accessing-edgar-data>

The caller supplies one ten-digit ASCII CIK. The adapter reads only the current
`filings.recent` columns needed for a minimal disclosure-metadata record. It
does not crawl filing documents, historical submissions files, company facts or
bulk archives.

SEC requests require an explicit, non-default, printable User-Agent containing
an application identity and a syntactically valid, contactable email address.
Single-label hosts, IP literals, invalid DNS names, the IANA special-use
`.invalid`, `.test`, `.example`, and `.localhost` namespaces, and `example.com`,
`example.org`, `example.net` (including their subdomains) are rejected. No
library default is sent. The adapter defaults to five requests/second and never
permits more than ten requests/second locally; operators remain responsible for
current SEC policy and lower shared limits where appropriate.

### Field mapping and chronology

| SEC field | Provider record field |
| --- | --- |
| requested/payload CIK | `entity_id = sec:cik:<10-digit CIK>` |
| accession number | `provider_record_id`, value, archive URL |
| company name, form, report date, primary document | structured `value` |
| filing date | `period` and `value.filing_date` |
| acceptance date/time | `as_of` and `published_at` in UTC |
| response bytes | `source_document_hash` SHA-256 |
| post-response clock | UTC `fetched_at` and response vintage |

`filingDate` is interpreted as an America/New_York calendar date. The acceptance
timestamp must use the SEC pilot's explicit extended RFC3339 UTC profile:
ASCII `YYYY-MM-DDTHH:MM:SS[.fraction]Z`, with one to six fractional digits when
present. Basic dates/times, Unicode digits, spaces, lowercase separators and
numeric offsets are rejected rather than normalized. The timestamp is normalized
to UTC, and a filing date later than the acceptance instant's Eastern date is
rejected. CIK, accession, column lengths, dates and primary-document path segments
are validated before archive URLs are built. `filingDate` and non-empty
`reportDate` use strict ASCII `YYYY-MM-DD` calendar dates. A report date later
than its filing date is rejected; this deliberately conservative ordering also
rejects remote future values such as `9999-12-31`.

The `America/New_York` timezone is resolved lazily only when SEC rows are parsed.
Missing local IANA timezone data therefore does not prevent resource or other
non-SEC CLI commands from running. An SEC parse that needs the missing timezone
fails deterministically with the redacted `invalid_sec_payload` provider error;
local tzdb exception details are not exposed.

The current submissions response is only a current snapshot. SEC metadata can
be amended, and this pilot does not possess historical response vintages. The
record therefore says `provider_claimed`, not OpenFundScore `verified`, and does
not backfill the current response into an earlier evaluation.

### Rights posture

The pilot records SEC access terms, attribution required, 30-day local retention
and cache support, and authorizes local derived work only. Public display and
redistribution are false. This is intentionally more restrictive than an
assumption that government-hosted or publicly accessible material is freely
redistributable. Reassess the terms and the specific intended use before
changing these flags.

## World Bank Indicators API v2 pilot

### Scope and source

- Official developer information:
  <https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information>
- Fixed API host/path shape:
  `https://api.worldbank.org/v2/country/<ISO2>/indicator/<indicator>`
- Dataset terms recorded by the adapter:
  <https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets>

The adapter is constructed with an explicit non-empty allowlist of assigned
ISO 3166-1 two-letter country codes and the single reviewed World Bank source
`2`, whose API dataset label is exactly `World Development Indicators`. A call
supplies one allowlisted country, one bounded indicator identifier, source `2`, a page size at
most 1,000, an explicit maximum of at most ten pages, and an explicit record
maximum from 1 to 10,000. `max_pages` defaults to one and `max_records` defaults
to 1,000. Source `1`, source `9999`, every other source, and a constructor scope
other than `2` fail before transport. It is not a bulk downloader, and there is
no live-fetch CLI command.

### Field mapping and chronology

| World Bank field | Provider record field |
| --- | --- |
| source, country, indicator, year | stable IDs and `period` |
| indicator/country labels, ISO3, value, decimal | structured `value`; ISO3 must equal the bundled ISO 3166-1 mapping for the requested/row ISO2 |
| unit | `unit`; `currency=USD` only when the returned unit explicitly contains `US$` |
| annual year | UTC annual `[valid_from, valid_to)` interval |
| metadata `lastupdated` | date-granularity `vintage` |
| response bytes | per-page `source_document_hash` SHA-256 |
| post-response clock | UTC `fetched_at` and conservative `published_at` proxy |

Records use `entity_type=macro_observation` and are authorized under
`GET_MACRO_SERIES`. The API exposes the current view, not a historical vintage
as of the observation year. `lastupdated` has date-only granularity and does not
provide an observation publication timestamp, so exact publication lag is
explicitly unknown. `published_at=fetched_at` is a conservative knowledge-time
proxy, not a claim about original release time. Records are
`not_point_in_time`; observations may be revised.

Every row must repeat the requested indicator and ISO2 country, and its ISO3
must exactly match the adapter's complete 249-entry ISO 3166-1 alpha mapping;
missing or contradictory codes fail closed (for example, `US` with `CHN`). Every
page must agree on page count, total, source and `lastupdated`. Requested
page/per-page metadata must match, page count must stay within the caller's
limits, total rows must stay within `max_records`, final row count must equal
`total`, and record IDs must be unique. A change between pages or
duplicate/revised identity fails the whole call rather than silently selecting a
value.

### Rights posture

World Bank terms and licences can vary by dataset/source. The pilot does not
apply a blanket CC-BY claim. Its reviewed decision is closed to source `2` and
the exact `World Development Indicators` dataset label. The entitlement and
every emitted record carry both identifiers, and `authorize_ingestion()` checks
both exact values in addition to the provider identity. The conservative result
is local `derived_only`: attribution required, cache and local derived work
allowed for at most 30 days, and public display and redistribution false. No
other World Bank source inherits this decision; an unreviewed source is rejected
before a request rather than receiving these rights. API accessibility is not
treated as legal permission. A deployment with stricter terms must use
`unknown_blocked` or a separately reviewed adapter decision rather than
weakening these defaults.

## Offline API and CLI

Python:

```python
from datetime import UTC, datetime
from openfundscore import SecEdgarSubmissionsAdapter, WorldBankIndicatorsAdapter

cutoff = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
sec_records = SecEdgarSubmissionsAdapter(
    user_agent="YourApplication compliance@yourdomain.org"
).parse_submissions_fixture(
    sec_bytes,
    cik="0000320193",
    fetched_at=cutoff,
    evaluation_timestamp=cutoff,
)

world_bank_records = WorldBankIndicatorsAdapter(
    countries=frozenset({"US"})
).parse_page_fixture(
    world_bank_bytes,
    country="US",
    indicator="NY.GDP.MKTP.CD",
    source=2,
    page=1,
    per_page=1,
    fetched_at=cutoff,
    evaluation_timestamp=cutoff,
)
```

CLI fixture parsing is bounded to 2 MiB and has no network path:

```text
openfundscore provider-fixture sec --cik 0000320193 \
  --schema-version 0.2.0 \
  --user-agent "YourApplication compliance@yourdomain.org" \
  --fetched-at 2026-08-21T12:30:00Z \
  --evaluation-timestamp 2026-08-21T12:30:00Z sec-fixture.json

openfundscore provider-fixture world-bank --country US \
  --schema-version 0.2.0 \
  --indicator NY.GDP.MKTP.CD --source 2 --page 1 --per-page 1 \
  --fetched-at 2026-08-21T12:30:00Z \
  --evaluation-timestamp 2026-08-21T12:30:00Z world-bank-fixture.json
```

The SEC fixture command requires a User-Agent only to exercise the same adapter
constructor; parsing remains offline and the value is neither sent nor printed.
Fixture files are caller-provided and are not included in this repository.

## Explicitly not covered

No live adapter or coverage is claimed for ESMA, Hong Kong SFC, Singapore MAS,
FRED/ALFRED, FCA, EDINET, SEDAR+, ASIC, IMF, BIS, OECD, central banks, commercial
vendors, sales platforms, filing documents, SEC bulk archives or World Bank
bulk datasets. Catalogue links elsewhere in the documentation are research
priorities, not implemented connectors. Adding any source requires separate
field mapping, point-in-time/revision analysis, security review, data-rights
review, tests and a conservative entitlement decision.

The named Issue #4 candidates remain unimplemented for concrete review gaps,
not because this project claims that their data is unavailable:

- **ESMA, Hong Kong SFC and Singapore MAS:** the catalogue or search links have
  not yet been narrowed to a stable machine endpoint and response contract, and
  no source-specific field, chronology, revision or reuse-rights decision has
  completed review. Browser accessibility is not an API or redistribution grant.
- **FRED/ALFRED:** the API-key lifecycle is not implemented, series-level rights
  can differ, and the mapping between current FRED values, ALFRED vintages,
  release dates and OpenFundScore knowledge time has not completed review.

Consequently there is no entitlement, rights, point-in-time, live-fetch or
current-coverage claim for those sources. The two implemented pilots are also
limited: SEC submissions are a current metadata snapshot, and World Bank
Indicators are a current revisable view with date-only `lastupdated`; neither is
a complete historical point-in-time archive.
