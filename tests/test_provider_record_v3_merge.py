from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "src/openfundscore/_resources/schema/provider_record"
PUBLISHED_V2_SHA256 = "36a25071c7622a6252a51c559c3adae49855a3b2e1bf954ce62c5a8b71c47f5f"


def mainland_record() -> dict[str, object]:
    return {
        "provider_id": "mainland-official-frozen-snapshot",
        "namespace": "canonical_observation",
        "source_type": "regulator",
        "jurisdiction": "CN",
        "entity_type": "report",
        "entity_id": "report-1",
        "exact_identifiers": [
            {
                "scheme": "official_document_id",
                "value": "report-1",
                "jurisdiction": "CN",
            }
        ],
        "field": "report_url",
        "value": "https://example.invalid/report-1",
        "as_of": "2026-08-20T00:00:00Z",
        "published_at": "2026-08-20T00:00:00Z",
        "fetched_at": "2026-08-21T00:00:00Z",
        "source_url": "https://example.invalid/report-1",
        "point_in_time_status": "verified",
        "quality_state": "verified",
        "rights": {
            "mode": "local_entitlement",
            "cache_allowed": True,
            "derived_works_allowed": True,
            "redistribution_allowed": False,
            "attribution_required": True,
            "public_display_allowed": False,
            "valid_until": "2026-08-31T00:00:00Z",
        },
        "effective_status": "current",
    }


class ProviderRecordV3MergeTests(unittest.TestCase):
    def test_published_provider_record_v2_bytes_are_immutable(self) -> None:
        payload = (SCHEMA_DIR / "0.2.0.schema.json").read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), PUBLISHED_V2_SHA256)

    def test_published_v2_rejects_mainland_record_but_v3_accepts_it(self) -> None:
        record = mainland_record()
        v2 = json.loads((SCHEMA_DIR / "0.2.0.schema.json").read_text())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(v2).validate(record)

        v3 = json.loads((SCHEMA_DIR / "0.3.0.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(v3)
        jsonschema.Draft202012Validator(v3).validate(record)
        self.assertNotEqual(v2["$id"], v3["$id"])


if __name__ == "__main__":
    unittest.main()
