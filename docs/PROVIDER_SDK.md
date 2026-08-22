# Provider SDK and Ingestion Entitlements

The Provider SDK is the typed boundary between provider-specific adapters and
OpenFundScore. Adapter capabilities describe what code can call; entitlements
describe what the current contract permits at one caller-supplied point in time.
Neither implies the other.

## Public API

Import from `openfundscore.provider_sdk`:

- `ProviderAdapter` and `ProviderCapability`;
- `ProviderEntitlements`, `RightsMode`, `AuthenticationMode`, `SourceType`;
- `RateLimit` and provider-bound `RateLimitBudget`;
- `IngestionRequest`, `DataUse`, `authorize_ingestion()`;
- `IngestionAuthorization`, `IngestionDenied`, `ProviderContractError`.

Every adapter implements:

```python
def get_entitlements(
    *, evaluation_timestamp: datetime
) -> ProviderEntitlements:
    ...
```

The returned snapshot must use that exact timezone-aware timestamp. The caller
also passes an explicit packaged provider-record Schema version to
`authorize_ingestion()`; there is no implicit latest version and no system-clock
fallback. `GET_ENTITLEMENTS` is the metadata lookup capability required on an
adapter and its snapshot; it is rejected as an `IngestionRequest` data-fetch
capability.

## Enforcement order

`authorize_ingestion()` fails closed and does not mutate the input record. It:

1. validates the provider record with packaged Schema plus provider semantics;
2. obtains a typed, redacted entitlement snapshot;
3. binds adapter identity, capability and evaluation instant to that snapshot;
4. binds the requested capability to the record's entity-type data plane;
5. binds the record's provider, source, jurisdiction and rights metadata to it;
6. blocks unknown rights and every ungranted cache, derived, display or
   redistribution use;
7. requires attribution readiness before attributed uses;
8. enforces a provider-bound rate-limit window, total and burst budget;
9. enforces explicit cache TTL and retention bounds; and
10. returns deterministic expiry, retention and remaining-budget metadata.

Provider exceptions and malformed snapshots become stable redacted
`IngestionDenied` errors. Payloads, credentials, provider exception text and
private contract values are not copied into public errors.
Typed entitlement objects and their nested rate limits are reconstructed and
revalidated at this boundary, so a forged or post-construction-mutated dataclass
does not inherit trust from its Python type. Timestamp awareness is checked on
the original snapshot before UTC normalization, so a naive value cannot be
healed through the host's local timezone. Requests and rate-budget snapshots
are reconstructed and revalidated for the same reason.
Security-sensitive strings and frozen sets must have exact built-in runtime
types. Subclasses with forged equality, iteration or membership behavior are
rejected rather than treated as typed contract values.
Optional `source_ids` and `dataset_ids` form one closed resource scope: they
must be declared together and, when present, each must be a non-empty exact
built-in `frozenset[str]` containing at most 256 unique values. Each value is a
non-empty exact built-in string of at most 256 characters. The entitlement is
reconstructed and both immutable exact built-in frozensets are revalidated at
the authorization boundary, so forged or damaged entitlement state cannot
change the authorization scope. The record must contain `value.source.id` and
`value.source.dataset` and both must match exactly. Provider identity is checked
independently before these fields, so a different provider cannot reuse another
adapter's scope. Source-scoped authorization explicitly requires
`provider_record@0.2.0`; legacy unscoped records continue to validate and
authorize with `provider_record@0.1.0`. The packaged
`provider_contract@0.2.0` JSON contract exposes the paired arrays with
`dependentRequired`, uniqueness, the same 256-item cardinality and 256-character
string bounds; semantic validation independently rechecks the pair and values.
Published `provider_contract@0.1.0` remains byte-for-byte immutable and does not
expose these fields.
Provider identifiers are capped at 256 characters and terms URLs at 2,048
characters in both typed and JSON contracts.

Capability-to-record binding is explicit: fund listing covers fund strategies
and share classes; profile covers fund strategies, share classes, managers,
benchmarks, issuers and platform listings; share-class, NAV, benchmark,
manager-tenure and holding calls cover their matching entity types; fees cover
fund strategies and share classes; purchase status covers share classes and
platform listings; disclosures cover canonical entities; and external ratings
cover only the isolated `external_rating` namespace. `GET_MACRO_SERIES` covers
only `macro_observation`. A broad adapter capability therefore cannot authorize
an unrelated record such as a holding fetched under `GET_PROFILE`.

## Rate-limit state

`RateLimitBudget` is an input from the local ingestion coordinator. Its
`period_started_at` must be a whole-second UTC window boundary aligned to the
Unix epoch modulo the entitlement's `period_seconds`; overlapping caller-chosen
windows are rejected. In a concurrent importer it must come from an atomic
provider-specific meter. The SDK validates provider identity and alignment but
cannot prove a caller's counter is truthful. Persist and increment the counter
transactionally before performing network work. Rate periods and cache TTLs are
capped at 365 days; retention is capped at 36,500 days to bound hostile
integers. Any calendar addition that would still exceed Python's supported
datetime range is converted to a stable fail-closed denial rather than leaking
an `OverflowError`. UTC normalization of extreme offset-aware timestamps is
subject to the same stable denial boundary.
All equality, validity, rate-window, cache-expiry and retention calculations use
canonical UTC instants. Local wall-clock folds or gaps cannot extend a policy
window or make two different instants compare equal.
Per-period and burst allowances are capped at 1,000,000,000, an individual
request at 1,000,000 operations, and a supplied counter at 1,000,000,000.
Provider records are also subject to bounded container width, total JSON-node
count, 65,536 bytes per string and 1,000,000 aggregate string bytes before
schema traversal. Provider-contract Schema mirrors the SDK maxima for rate
allowances, periods and retention. These are defensive implementation ceilings,
not provider-advertised quotas.
Strings that cannot be encoded as strict UTF-8, including lone surrogates from
escaped JSON, are rejected through the same stable redacted validation boundary.

## Adapter and data boundary

This module performs no network access and stores no credentials. Official,
commercial and user-import adapters live outside the entitlement core and must:

- keep secrets in local environment or OS secret storage;
- validate every external response before constructing a provider record;
- return only redacted entitlement metadata;
- document terms at a well-formed public DNS HTTPS URL, rights-review timestamp,
  attribution and retention;
- use `unknown_blocked` when rights are not established; and
- pass `authorize_ingestion()` before local persistence or downstream use.

A capability is not permission. A successful authorization is limited to the
specific record, operation set, Schema version, evaluation instant and budget
provided. It is not a licence, legal opinion, data subscription or public
publication approval.

The two current fixed-host pilot adapters, their field mappings, live-fetch
clock boundary, offline fixture API/CLI, conservative rights posture and
explicitly uncovered sources are documented in
[Official Provider Pilots](OFFICIAL_PROVIDERS.md). The pilots live outside this
entitlement core and do not change its fail-closed rules.

At that official-adapter boundary, query mappings are materialized to at most 64
entries; each exact built-in string key/value is limited to 1,024 characters and
4,096 strict UTF-8 bytes, and the final encoded target to 8,192 UTF-8 bytes.
Allowed request-header values are non-empty visible ASCII and at most 1,024
characters. Exact built-in finite connect/read timeouts must satisfy
`0 < timeout <= 60` seconds. Injected local limiters are defensively reconstructed
as independent instances after validation. SEC Eastern time is resolved lazily:
missing tzdb does not break resource CLI commands and produces a stable redacted
`invalid_sec_payload` only when SEC row parsing requires that timezone.
