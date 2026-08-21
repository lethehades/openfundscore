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

The initial Schema version is `0.1.0`. There is no `latest` alias, implicit
version selection or repository-path fallback.

## Python API

```python
from openfundscore import RecordType, validate_record

validate_record(
    RecordType.PROVIDER_RECORD,
    document,
    schema_version="0.1.0",
    evaluation_timestamp="2026-08-21T00:00:00Z",
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
  --schema-version 0.1.0 \
  --evaluation-timestamp 2026-08-21T00:00:00Z \
  provider-record.json
```

A valid document prints one line:

```text
valid: provider_record@0.1.0 (schema+semantics)
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
  ledger `as_of` UTC date, duplicate entries, window order and indexed raw
  current-fund evidence-reuse detection across fund and manager components.

The boundary performs no collection, network access, ranking, forecasting or
trading. It validates local records only.
