# Public Rating and Redistribution Gate

## Current decision: NO_GO

OpenFundScore is deliverable as a **local private research tool**. It is not
authorised to host public real-fund ratings, rankings, or redistributed provider
data. The package contains no jurisdiction-specific legal opinion, provider
licence, authenticated counsel identity, release-officer identity, signed
approval registry, revocation service, or deployment verifier.

`evaluate_publication_gate()` therefore has no `GO` outcome:

- `local_private_research` returns `LOCAL_ONLY`;
- `hosted_public_rating` returns `NO_GO`;
- caller-supplied roles, hashes, legal-review objects, provider-clearance objects
  and control booleans are not traversed and can never grant authority.

This is deliberate. A hexadecimal digest proves neither who approved an artifact
nor what the artifact says. Self-declared jurisdiction, provider coverage,
output composition and controls cannot safely authorise publication.

## Python API

```python
from openfundscore import evaluate_publication_gate

result = evaluate_publication_gate(
    {
        "request_id": "local-report-2026-08-21",
        "publication_mode": "local_private_research",
        "jurisdictions": ["CN"],
    },
    evaluation_timestamp="2026-08-21T00:00:00Z",
)

assert result.decision.value == "local_only"
assert result.authorizes_publication is False
```

The result records the request ID, explicit evaluation timestamp, jurisdictions
and stable reason codes. It never reads the system clock. Request IDs must be
bounded, nonblank and printable; top-level field count and jurisdiction count are
bounded. Arbitrary nested approval assertions are ignored rather than trusted or
reflected in errors.

## Preconditions for a future public GO

A future public-publication interface must be separately versioned and reviewed.
At minimum it must verify, rather than accept caller assertions about:

1. an immutable publication manifest and output digest;
2. the complete target audience, distribution channels and legal jurisdictions;
3. every represented provider, contract version and output field;
4. raw-data versus derived-output classification;
5. authenticated, qualified counsel and release officers;
6. signed artifact contents, supersession, contradiction and revocation state;
7. provider licences, database rights, attribution and redistribution rights;
8. methodology, conflicts, personnel-data, retention and complaints controls;
9. deployment configuration and implementation evidence; and
10. a trusted current-release timestamp.

A professional, jurisdiction-appropriate legal review must then approve the
actual manifest and deployment. Code cannot supply that review or regulatory
status.

## Scope boundary

The present gate is not a licence, legal opinion, regulatory filing, investment
recommendation or proof of provider rights. Local reports must remain local and
must not be presented as public rankings, forecasts, trading signals or an
authorised public fund-evaluation service.
