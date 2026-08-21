# Canonical data model v0.2

This module is the first local-storage slice of M1. It defines immutable,
effective-dated entities without collecting real provider data or calculating a
fund score.

## Public records

`openfundscore.canonical` exposes seven top-level record types:

| Record | Stable identity and ownership |
|---|---|
| `FundStrategy` | Mandate, strategy profile, lifecycle and primary benchmark shared by all economically equivalent share classes. |
| `ShareClass` | Fees, dealing currency, distribution and subscription/redemption state for A/C/E/I/R or other classes. |
| `Benchmark` | Exact contractual or analytical benchmark identity. |
| `Manager` | Public professional identity only; private-person attributes are outside this model. |
| `ManagerTenure` | Exact manager-to-strategy responsibility window and explicit team/role attribution. |
| `HoldingSnapshot` | Integer-basis-point positions owned by `fund_strategy_id`, never copied to each share class. |
| `Evidence` | Public source fact or content hash supporting a canonical subject. Manager and tenure source URLs and excerpts reuse the manager-research sensitive-content guard. |

Nested value objects are `ExternalIdentifier`, `FeeSchedule`,
`HoldingPosition`, and `FundLifecycleEvent`.

Every top-level record carries:

- an immutable `record_id` for this exact version;
- a stable entity ID such as `fund_strategy_id` or `share_class_id`;
- `as_of`, `published_at`, `fetched_at`, `valid_from`, and optional `valid_to`;
- `source_provider_id`, `quality_state`, and optional `conflict_group`.

All datetimes must be timezone-aware and serialize as UTC with exactly six
fractional-second digits, so SQLite lexical ordering matches chronological
ordering. Validity is interpreted as the half-open interval
`[valid_from, valid_to)`. The record contract requires
`published_at <= fetched_at`; the broader provider chronology and verified-state
rules remain tracked in Issue #13.

## Strategy and share-class separation

A/C/E/I share classes point to one `fund_strategy_id`. They cannot own mandate,
manager-tenure or holding fields because those fields do not exist on
`ShareClass`. Fees are encoded as integer basis points in `FeeSchedule`; holding
weights use integer basis points in `HoldingPosition`. This avoids float drift and
prevents duplicate strategy evidence from being created per share class.

## Lifecycle

`FundLifecycleEvent` is append-only:

- `closed` records the effective closure;
- `merged` requires a different `successor_strategy_id`;
- `transformed` creates a new effective-dated `FundStrategy` record while
  retaining the same stable strategy ID when the legal strategy continues.

Old versions are never deleted or rewritten. A `closed`, `merged`, or
`transformed` status record must start exactly at its matching event time; the
preceding version remains active until that boundary. This prevents future
closure or merger states from being backfilled into earlier history and
preserves the complete universe for later point-in-time backtests.

## Entity resolution

`resolve_external_identifier()` compares exact
`(scheme, value, jurisdiction)` identifiers and returns stable entity keys.
Canonical names are deliberately ignored. Same-name funds are therefore not
merged automatically, while renamed versions with the same exact identifier can
resolve to the same strategy ID.

## Deterministic local storage

`openfundscore.storage.CanonicalStore` uses Python's standard-library `sqlite3`.
It is a local, single-writer store rather than a network service or ORM.

- `put(record)` appends an immutable record. Replaying identical content is a
  no-op; reusing a `record_id` for different content raises
  `RecordIdentityConflict`.
- `query_versions(..., effective_at, knowledge_cutoff)` returns every candidate
  effective at the requested time and fetched by the knowledge cutoff.
- `resolve_share_class()` returns every linked strategy candidate and every
  conflict group; it never silently picks a winner.
- `dump_json()` and `load_json()` provide deterministic, byte-stable round trips.

The store keeps conflicting provider records side by side. Conflict resolution
is a later explicit policy decision, not a last-write-wins side effect.

## Synthetic fixture

`synthetic_canonical_records(fetched_at=...)` has an explicit clock and contains
no network or private data. It includes:

- one strategy with A/C/E/I share classes;
- a benchmark, public synthetic manager, tenure and holding snapshot;
- closed, merged and transformed strategy histories;
- two provider candidates in one conflict group;
- public synthetic evidence records.

## Non-goals

This slice does not implement real providers, NAV histories, metric calculation,
manager-performance attribution, ratings, rankings, suitability, trading, an
HTTP service or a multi-user database. It does not authorize collection or
redistribution of any third-party data.
