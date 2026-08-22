# Mainland official frozen-snapshot provider pilot

## Scope and non-claims

Mainland China does not currently have one confirmed, unified, stable public-fund
API with an open licence that this project can safely treat as a universal source.
A disclosure being visible in a browser is not evidence that automated collection
or redistribution is authorised.

This pilot therefore has **no network transport**. A user or a separately reviewed
and authorised collection layer must first obtain an original disclosure from a
CSRC, exchange, or fund-company official source and freeze it into a local JSON
bundle. `MainlandOfficialSnapshotAdapter` only reads that local bundle, validates
it, maps each disclosed field to a provider record, and authorises each record
against separately injected point-in-time entitlements.

It does not log in, read cookies, scrape a sales platform, call an official site,
resolve DNS, or imply that raw disclosure redistribution is permitted. The
Apache-2.0 licence for this code does not license third-party source documents.

## Versioned bundle contract

The packaged Draft 2020-12 schema is selected exactly as:

```text
openfundscore://schema/mainland_official_snapshot/0.1.0
```

That version identifies the frozen **input bundle**. The adapter's output uses
the current `openfundscore://schema/provider_record/0.3.0` contract. The distinct
packaged `provider_record / 0.1.0` resource remains byte-for-byte available for
explicit legacy validation and is never mutated, aliased to, or silently chosen
instead of `0.3.0`.

The root object is closed (`additionalProperties: false`) and requires:

- identity: `schema_version`, `provider_id`, and globally unique `snapshot_id`;
- source: `source_type` (`regulator`, `exchange`, or `fund_company`), `CN`, and
  an approved `official_source_url`;
- point-in-time metadata: `retrieved_at`, `published_at`, `as_of`, and
  `effective_at`, all in the strict RFC3339 profile;
- provenance: `document_sha256` as `sha256:` plus 64 lowercase hexadecimal
  digits; every field observation must bind to the same digest;
- conventions: `Asia/Shanghai`, `CNY`, and explicit NAV/weight/coverage units;
- reviewed rights: terms URL, source-evidence URL, review and expiry instants,
  rights mode, cache/derived/display/redistribution/attribution flags, and
  retention limit;
- `items`, with bounded arrays and closed nested objects.

Each item has an `item_id`, one of seven `item_type` values, a canonical
`entity_type`/`entity_id`, one or more exact identifiers, and one or more field
observations. Canonical entity IDs and external identifier values are separate
fields and are not compared with each other. Exact identifiers resolve only by
the codepoint-exact `(scheme, value, jurisdiction)` tuple: case folding, Unicode
normalization, full-width conversion, confusable-character matching, and
name/display-string matching are forbidden. Distinct reliable schemes may carry
distinct values, but a duplicate exact tuple or one tuple resolving to different
canonical identities fails closed. The resolved identity is the complete
`(entity_type, entity_id)` pair: reusing an `entity_id` under another
`entity_type` does not make an exact-tuple collision valid.
Identifier schemes are a closed Schema enum: `cn_fund_code`,
`csrc_registration_id`, `exchange_security_code`,
`fund_company_official_id`, `official_document_id`, and `official_entity_id`.

Every observation preserves its raw JSON value and all audit metadata:

```text
observation_id, field, raw_value,
as_of, published_at, fetched_at, valid_from, valid_to,
currency, unit, source_url, source_document_hash,
point_in_time_status, methodology, quality_state, conflict_group
```

The adapter emits one `provider_record@0.3.0` per observation. A daily NAV series
is therefore a sequence of small records, not one opaque array value.

## Item mapping

| Snapshot item | Provider entity | Required disclosed fields | SDK capability |
|---|---|---|---|
| `identity` | fund strategy, share class, manager, or benchmark | item-specific identity fields | `GET_PROFILE` |
| `nav` | `share_class` | chronological `nav` observations, including explicit conflicts | `GET_NAV_SERIES` |
| `report` | `report` | `report_url`, `report_document_hash` | `GET_DISCLOSURES` |
| `manager_tenure` | `manager_tenure` | manager ID, strategy ID, start, end | `GET_MANAGER_TENURES` |
| `benchmark` | `benchmark` | canonical name | `GET_BENCHMARK` |
| `holding` | `holding` | strategy ID, instrument ID, weight, coverage | `GET_HOLDINGS` |
| `corporate_action` | `corporate_action` | action type, effective time, before/after IDs | `GET_CORPORATE_ACTIONS` |

NAV values must be finite, non-boolean, non-negative CNY-per-share values. Their
canonical UTC revision instants must be non-decreasing. Distinct revisions remain
strictly chronological; multiple different values at one canonical instant are
retained only as one explicit conflict group, ordered deterministically by
`observation_id`. Silent, mixed, empty-group, or different-group collisions fail
closed. Exact duplicates also fail closed. Holding weight and coverage units must
match the bundle declaration; exact instruments cannot repeat within a fund
snapshot; aggregate weights cannot exceed coverage or the unit maximum.
Snapshot, conflict, duplicate, profile-revision, and holding-aggregate keys use
the parsed UTC instant, not the raw RFC3339 spelling. Consequently `Z`, `+08:00`,
and `-05:00` representations of one instant cannot create separate groups.
Manager-tenure start/end values use exactly ten ASCII digits and separators in
`YYYY-MM-DD` form and must be real Gregorian calendar dates; basic dates, week
dates, date-times, Unicode digits, and invalid leap days fail closed. Manager
tenure windows cannot reverse. Corporate actions are limited to
`closed`, `merged`, and `transformed`; closure has no successor, while merger and
transformation require a distinct after-ID. Corporate-action observations are
grouped into complete revisions by canonical UTC `as_of`. Within each revision,
every `valid_from` must equal that revision's one disclosed `effective_at`; a
later true `as_of` revision may correct the effective instant, but an equivalent
offset spelling cannot create a second revision. Future, current, and expired
validity are evaluated per preserved observation. A future effective instant is
retained and emitted with `effective_status: future`, never marked current.
Report URLs and hashes are validated independently for every revision.

The root must satisfy `published_at <= retrieved_at <= evaluation_timestamp` and
`as_of <= retrieved_at`. Every observation must independently satisfy
`as_of <= published_at <= fetched_at <= root retrieved_at` and an ordered validity
interval. Each observation revision at a distinct parsed `as_of` instant must
contain the complete closed field profile for its item; a different RFC3339
offset spelling of the same instant is not a revision. A valid later instant
cannot hide an invalid or incomplete earlier revision.

Duplicate field knowledge at the same `as_of` is accepted only when every
duplicate is explicitly marked `quality_state: conflict` with the same non-empty
conflict group. Every conflicting value is still checked independently before
grouping. Original RFC3339 strings remain unchanged in emitted audit records,
and canonical grouping does not alter provider-record IDs or identifier
codepoints. All records are retained; there is no last-write-wins path.

## Source-host policy

All source, report, terms, and evidence URLs must use HTTPS and a public DNS host.
Userinfo, fragments, IP literals, localhost names, malformed names, and lookalike
suffixes are rejected.

Reviewed built-in source rules are deliberately narrow:

- regulator: `csrc.gov.cn` and its subdomains;
- exchange: `sse.com.cn`, `szse.cn`, and their subdomains.

A fund-company hostname has no suffix wildcard. The caller must inject an exact
host together with the exact source-evidence URL used by the bundle:

```bash
--fund-company-host 'fund.example.cn=https://fund.example.cn/terms-review'
```

This mechanism records a technical review input; it is not a legal conclusion.
Sales-platform source types and external-rating items are outside this adapter
and are rejected.

## Explicit entitlement declaration

The CLI requires a separate, closed local entitlement JSON document. Omitting it
is not allowed. Its `evaluated_at` must equal the CLI evaluation instant, its
provider/source/jurisdiction must match the bundle, and it must contain every
requested capability. Mainland adapters require explicit, non-null
`rights_reviewed_at` and `valid_until` values even though the public
`ProviderEntitlements` SDK permits open-ended `valid_until=None` for other
providers. Rights booleans, mode, URLs, and retention days must match exactly.
`reviewed_at` and `valid_until` are compared as parsed UTC instants, so equivalent
`Z`, `+08:00`, and `-05:00` spellings match. A syntactically valid RFC3339 value
that cannot be represented after UTC normalization fails closed as
`invalid_timestamp`. Every emitted Mainland
`provider_record@0.3.0` preserves the bundle's original `reviewed_at` and
`valid_until` strings independently; an equivalent entitlement spelling is not
substituted into the audit record.

Minimal shape (values are synthetic examples only):

```json
{
  "schema_version": "0.1.0",
  "provider_id": "mainland-official-pilot",
  "evaluated_at": "2026-08-21T00:00:00Z",
  "valid_until": "2026-09-01T00:00:00Z",
  "source_type": "regulator",
  "jurisdictions": ["CN"],
  "authentication_mode": "local_entitlement",
  "capabilities": [
    "get_benchmark",
    "get_corporate_actions",
    "get_disclosures",
    "get_entitlements",
    "get_holdings",
    "get_manager_tenures",
    "get_nav_series",
    "get_profile"
  ],
  "rights": {
    "mode": "local_entitlement",
    "cache_allowed": true,
    "cache_ttl_seconds": 86400,
    "derived_works_allowed": true,
    "public_display_allowed": false,
    "redistribution_allowed": false,
    "retention_days": 30,
    "attribution_required": true,
    "terms_url": "https://www.csrc.gov.cn/synthetic/terms",
    "reviewed_at": "2026-08-20T00:00:00Z"
  },
  "rate_limit": {
    "requests_per_period": 1000,
    "period_seconds": 86400,
    "burst": null
  }
}
```

`unknown_blocked`, missing review/terms, a future review, expired validity,
rights mismatch, source mismatch, and missing capability all fail closed. Public
visibility alone never creates an entitlement. The recommended raw-disclosure
mode is local entitlement with public display and redistribution disabled.

## CLI

```bash
openfundscore provider mainland-parse frozen-snapshot.json \
  --entitlements reviewed-entitlements.json \
  --evaluation-timestamp 2026-08-21T00:00:00Z
```

Successful stdout is one deterministic compact JSON array of provider records.
Diagnostics go to stderr and do not echo input paths or payload values. No network
request is made. The Python API is exported from the package top level:

```python
from openfundscore import (
    MainlandOfficialSnapshotAdapter,
    SnapshotValidationError,
    load_mainland_entitlements,
)

records = MainlandOfficialSnapshotAdapter(
    entitlements=typed_entitlements,
    fund_company_hosts={"fund.example.cn": "https://fund.example.cn/review"},
).parse(snapshot_bytes, evaluation_timestamp=evaluation_timestamp)
```

Bytes and `Path` are preferred trust boundaries. A `Mapping` is accepted for
programmatic use only after a bounded defensive deep copy.

## Authorised acquisition checklist

1. Identify the official regulator, exchange, or fund-company document and exact
   public HTTPS URL; do not substitute a sales-platform mirror.
2. Record retrieval, publication, as-of, and effective instants separately.
3. Preserve the original bytes outside this adapter and compute SHA-256 locally.
4. Review source terms and collection/retention/derived/display/redistribution
   rights; record the exact terms and source-evidence URLs and review instant.
5. Build the frozen bundle without normalising away raw values or conflicts.
6. Create a separate entitlement declaration for the chosen evaluation instant.
7. Run the offline CLI and retain bundle, entitlement, output, and digest as one
   audit set. Re-review rights before expiry.

## Security and resource bounds

The parser enforces strict UTF-8 JSON, duplicate-key rejection, an 8 MiB file/body
limit, bounded nodes/containers/depth/string bytes, at most 1,000 items and 1,000
observations per item, finite JSON numbers, non-boolean financial numerics, cycle
rejection, defensive handling of unusual Mapping/Sequence implementations, and
stable redacted errors. Input mappings are never mutated. Every mapped record is
first passed to `validate_record()` and then to `authorize_ingestion()`.

## Synthetic fixture

`openfundscore.fixtures.synthetic_mainland_snapshot_bundle()` returns a fresh,
deterministic, wholly synthetic bundle. It covers all seven item types, A/C share
classes, closure, merger, transformation, conflict preservation, and publication
lag. Its names, identifiers, values, hashes, and `/synthetic/` URLs are test data;
it contains no copied third-party dataset or private person information.

## Limits

- This pilot does not discover documents, verify live website availability, or
  judge whether a human rights review is legally sufficient.
- It does not provide a current inventory of every fund-company official domain.
- It does not make raw disclosures redistributable and does not publish them.
- Exact identifiers must already be present in the authorised frozen snapshot;
  there is no fuzzy matching or name-based entity merge.
- A future authorised transport can supply the same versioned bundle boundary,
  but transport implementation and entitlement review remain separate work.

## TDD execution evidence for Issue #3

The implementation used vertical RED → GREEN slices. Commands were run with an
external QA environment (`/tmp/openfundscore-issue3-qa`), never a repository-local
venv.

| Slice | RED observed | GREEN observed |
|---|---|---|
| schema, adapter, seven mappings | import failed because `openfundscore.mainland_official` did not exist | 3 focused tests passed |
| digest binding | altered observation digest was accepted; a later sabotage run deleting the exact digest check made the regression test fail again | focused digest test and 11 adapter tests passed; after restoration the sabotage target passed |
| offline CLI | argparse rejected `provider` as an invalid command | both focused CLI tests passed |
| packaged synthetic fixture | fixture import failed | lifecycle/A-C/conflict fixture test passed |
| holding reconciliation | excess aggregate weight and unit mismatch were accepted | focused reconciliation test and adapter suite passed |
| hostile structural value | unhashable holding ID escaped as `TypeError` | focused test passed with stable `invalid_holding` |

The final quality-gate results are reported with the change, rather than encoded
as claims that future runs will necessarily remain green.
