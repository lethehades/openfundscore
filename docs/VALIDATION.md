# Unified contract-record validation

OpenFundScore exposes one local, fail-closed boundary for all packaged contract
records. Structural validation alone is never reported as success.

## Supported record types

Every call selects an exact record type and packaged Schema version:

- `manager_research`
- `provider_record`
- `provider_contract`
- `external_rating`
- `score_evidence_usage`

Every record type retains Schema `0.1.0`. `provider_record` additionally
publishes immutable `0.2.0` for SEC/World Bank fields including
`macro_observation`, and `0.3.0` as the closed union used by Mainland snapshots
for exact identifiers, Mainland entity types and `rights.valid_until`.
`score_evidence_usage` additionally publishes `0.2.0`, which requires consumed
`evidence_id`, `observation_as_of`, `window_basis`, `window_months` and inclusive
window endpoints for category scoring. Manager primary rows additionally require
`source_facts_sha256`; fund primary and capture-denominator rows forbid that
manager-only field. Published 0.1.0 and provider-record 0.2.0 bytes remain
unchanged for explicit legacy validation. There is no `latest` alias, implicit
version selection, downgrade or repository-path fallback.

## Python API

```python
from openfundscore import RecordType, validate_record

validate_record(
    RecordType.PROVIDER_RECORD,
    document,
    schema_version="0.2.0",
    evaluation_timestamp="2026-08-21T00:00:00Z",
)

# Category-score ledgers use the explicit 0.2.0 contract.
validate_record(
    RecordType.SCORE_EVIDENCE_USAGE,
    evidence_ledger,
    schema_version="0.2.0",
)
```

`validate_record()` returns `None` only after both stages pass:

1. the exact packaged Draft 2020-12 JSON Schema, with active `date`,
   `date-time` and `uri` format checking;
2. the registered cross-field semantic validator.

`provider_record` and `external_rating` require an explicit RFC3339
`evaluation_timestamp`. Validation never reads the wall clock. Other types do
not require this argument.

Failures raise `RecordValidationError`. Stable attributes are:

- `record_type`
- `schema_version`
- `stage` (`schema`, `semantic` or `document`)
- `code`
- `path`

Messages do not include record values, local file paths or parser exception
chains.

## CLI

```bash
openfundscore validate-record \
  --type provider_record \
  --schema-version 0.2.0 \
  --evaluation-timestamp 2026-08-21T00:00:00Z \
  provider-record.json

openfundscore validate-record \
  --type score_evidence_usage \
  --schema-version 0.2.0 \
  score-evidence-usage.json
```

A valid document prints one line:

```text
valid: provider_record@0.2.0 (schema+semantics)
```

Invalid invocations and all document, Schema or semantic failures return exit
code `2`, write no success output and emit one concise, redacted error on stderr.
Document loading uses one bounded read of at most 8 MiB plus one sentinel byte;
the CLI rejects larger files, invalid UTF-8, malformed or excessively nested
JSON, duplicate object keys and non-finite `NaN`/`Infinity` values.

## Semantic mapping

- `manager_research`: public-professional privacy boundary, evidence-reference
  resolution, compliance evidence tiers, range ordering and evidence/as-of
  chronology.
- `provider_record`: strict RFC3339 profile, `published <= fetched <= evaluation`
  and `as_of <= fetched` chronology, point-in-time provenance, rights and
  quality-state combinations.
- `provider_contract`: rights-mode and permission consistency, including required
  attribution for `display_only`.
- `external_rating`: publication/retrieval/evaluation chronology, Open Score
  isolation and display-rights status.
- `score_evidence_usage`: at most 1,000 entries, windows ending no later than the
  ledger `as_of` canonical UTC date, duplicate entries, window order and indexed raw
  current-fund evidence-reuse detection across fund and manager components.
  Version 0.2.0 also structurally requires `evidence_id`, `observation_as_of`,
  `window_basis` and `window_months`; the ledger digest canonicalizes ledger and
  observation instants to UTC `Z`, so offset-equivalent instants produce the same
  digest while usage order and date-only windows remain unchanged. `point_in_time`, `calendar_months` and
  `actual_dates` are validated separately; actual-date windows retain their real
  endpoints. Manager usage entries must all declare `evidence_role=primary` and
  match the component-specific caller provenance and window recomputed from the
  raw `ManagerResearchHandoff`. Each manager row carries the digest of its consumed
  structured facts in that local manager document. The digest detects local
  document changes; it is not proof that an external claim is true. Observed capture denominators require their own
  `evidence_role=capture_denominator` ledger row and positive downside sample count.
  Version
  0.1.0 remains accepted only when explicitly selected.

Category metric validation additionally checks 92 declared upstream-formula
contracts and 92 cross-field rule entries; it does not calculate those upstream
formulas. Checks include the -5 to 5 down-market capture-ratio
contracts and the project's conservative 180-day WAM sanity cap. A capture
window with no benchmark downside is represented as `missing`. Applicability is
validated separately from evidence availability against the closed prerequisite
context.

`category-score` has a separate closed JSON boundary. It requires the raw manager
handoff (`manager_research`, exact `as_of`, target strategy and eight-source
identity manifest) with exact `assertion_status=caller_provided`. Caller source
input is limited to component/evidence/lineage/series/scope/mode/fund identity;
the target tenure, fact digest, observation time and window are checked or derived
from the manager document. The boundary recomputes the manager result and rejects bare scores,
expected summaries, typed audits and legacy `manager_audit` inputs. Observation
`uncertainty` is the sole optional observation annotation. Peer rows require exact
window basis/months/endpoints plus peer-admission identity and 64-character
snapshot/document hashes; unknown fields still fail closed.
Within each metric, `peer_id`, `series_id` and `lineage_id` are each independently
unique in both normalization and complete scoring. The same identities may be
reused by a different metric. Manager derivation validates the complete manager
Schema and semantics before reading tenure or nested fact fields. Manager handoff
domain failures at the `category-score` boundary return exit code 2 with one
redacted stderr line and no traceback.
Those peer hashes and all raw metric/manager scores remain caller assertions;
validation retains and cross-checks them but does not retrieve external preimages
or independently verify the asserted economics. Caller-provided manager inputs cap
confidence at `low` without a score deduction.

The boundary performs no collection, network access, ranking, forecasting or
trading. It validates local records only. Publication remains `LOCAL_ONLY` for
private local research and `NO_GO` for hosted public ratings.
