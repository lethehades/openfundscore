from __future__ import annotations

import unittest
from copy import deepcopy
from typing import cast

from openfundscore.provider_semantics import (
    ProviderRecordValidationError,
    validate_provider_record_semantics,
)


class ProviderSemanticsTests(unittest.TestCase):
    def _record(self) -> dict:
        return {
            "provider_id": "provider-1",
            "provider_record_id": "provider-record-1",
            "namespace": "canonical_observation",
            "source_type": "regulator",
            "jurisdiction": "CN",
            "entity_type": "benchmark",
            "entity_id": "benchmark-1",
            "field": "level",
            "value": 1000,
            "as_of": "2026-08-20T00:00:00Z",
            "published_at": "2026-08-20T01:00:00Z",
            "fetched_at": "2026-08-20T02:00:00Z",
            "valid_from": None,
            "valid_to": None,
            "source_url": "https://example.com/benchmark-1",
            "source_document_hash": "sha256:synthetic",
            "methodology": None,
            "point_in_time_status": "verified",
            "quality_state": "verified",
            "rights": {
                "mode": "open_redistributable",
                "cache_allowed": True,
                "derived_works_allowed": True,
                "redistribution_allowed": True,
                "attribution_required": True,
                "public_display_allowed": True,
            },
        }

    def test_publication_after_fetch_is_rejected_with_a_stable_path(self) -> None:
        record = self._record()
        record["published_at"] = "2026-08-20T03:00:00Z"
        snapshot = deepcopy(record)

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "chronology_violation")
        self.assertEqual(raised.exception.path, "$.published_at")
        self.assertEqual(record, snapshot)

    def test_future_as_of_is_rejected_against_the_explicit_evaluation_time(
        self,
    ) -> None:
        record = self._record()
        record["as_of"] = "2026-08-21T00:00:00.000001Z"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "future_as_of")
        self.assertEqual(raised.exception.path, "$.as_of")

    def test_reversed_validity_interval_is_rejected(self) -> None:
        record = self._record()
        record["valid_from"] = "2026-09-01T00:00:00Z"
        record["valid_to"] = "2026-08-31T23:59:59.999999Z"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "chronology_violation")
        self.assertEqual(raised.exception.path, "$.valid_from")

    def test_verified_point_in_time_requires_identity_and_content_hash(self) -> None:
        for field in ("provider_record_id", "source_document_hash"):
            for absent_value in (None, "", "   "):
                with self.subTest(field=field, absent_value=absent_value):
                    record = self._record()
                    if absent_value is None:
                        record.pop(field)
                    else:
                        record[field] = absent_value

                    with self.assertRaises(ProviderRecordValidationError) as raised:
                        validate_provider_record_semantics(
                            record,
                            evaluation_timestamp="2026-08-21T00:00:00Z",
                        )

                    self.assertEqual(raised.exception.code, "missing_provenance")
                    self.assertEqual(raised.exception.path, f"$.{field}")

    def test_reconstructed_records_require_methodology_and_lower_quality(self) -> None:
        missing_method = self._record()
        missing_method["point_in_time_status"] = "reconstructed"
        missing_method["quality_state"] = "unverified"
        missing_method["methodology"] = None
        with self.assertRaises(ProviderRecordValidationError) as missing:
            validate_provider_record_semantics(
                missing_method,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(missing.exception.code, "missing_methodology")
        self.assertEqual(missing.exception.path, "$.methodology")

        inflated = self._record()
        inflated["point_in_time_status"] = "reconstructed"
        inflated["methodology"] = "Rebuilt from archived public disclosures"
        with self.assertRaises(ProviderRecordValidationError) as quality:
            validate_provider_record_semantics(
                inflated,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(quality.exception.code, "incompatible_quality")
        self.assertEqual(quality.exception.path, "$.quality_state")

        accepted = self._record()
        accepted["point_in_time_status"] = "reconstructed"
        accepted["quality_state"] = "unverified"
        accepted["methodology"] = "Rebuilt from archived public disclosures"
        snapshot = deepcopy(accepted)
        self.assertIsNone(
            validate_provider_record_semantics(
                accepted,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )
        self.assertEqual(accepted, snapshot)

    def test_not_point_in_time_records_require_methodology_and_lower_quality(
        self,
    ) -> None:
        for field, value, expected_path in (
            ("methodology", None, "$.methodology"),
            ("quality_state", "verified", "$.quality_state"),
        ):
            with self.subTest(field=field):
                record = self._record()
                record["point_in_time_status"] = "not_point_in_time"
                record["quality_state"] = "unverified"
                record["methodology"] = (
                    "Current-state source without historical vintages"
                )
                record[field] = value
                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual(raised.exception.path, expected_path)

        accepted = self._record()
        accepted["point_in_time_status"] = "not_point_in_time"
        accepted["quality_state"] = "unverified"
        accepted["methodology"] = "Current-state source without historical vintages"
        snapshot = deepcopy(accepted)
        self.assertIsNone(
            validate_provider_record_semantics(
                accepted,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )
        self.assertEqual(accepted, snapshot)

    def test_unknown_point_in_time_status_requires_lower_quality_only(self) -> None:
        inflated = self._record()
        inflated["point_in_time_status"] = "unknown"
        inflated["methodology"] = None
        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                inflated,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(raised.exception.code, "incompatible_quality")
        self.assertEqual(raised.exception.path, "$.quality_state")

        accepted = self._record()
        accepted["point_in_time_status"] = "unknown"
        accepted["quality_state"] = "unverified"
        accepted["methodology"] = None
        self.assertIsNone(
            validate_provider_record_semantics(
                accepted,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )

    def test_semantic_enums_fail_closed_without_schema_validation(self) -> None:
        for field, invalid_value in (
            ("point_in_time_status", True),
            ("point_in_time_status", "retroactive_guess"),
            ("quality_state", True),
            ("quality_state", "excellent"),
        ):
            with self.subTest(field=field, invalid_value=invalid_value):
                record = self._record()
                record[field] = invalid_value
                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual(raised.exception.code, "invalid_enum")
                self.assertEqual(raised.exception.path, f"$.{field}")

    def test_rights_reviewed_at_must_be_an_offset_aware_rfc3339_timestamp(self) -> None:
        record = self._record()
        record["rights"]["reviewed_at"] = "2026-08-21T00:00:00"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "invalid_rfc3339")
        self.assertEqual(raised.exception.path, "$.rights.reviewed_at")

    def test_rights_valid_until_must_cover_the_evaluation_instant(self) -> None:
        record = self._record()
        record["rights"]["valid_until"] = "2026-08-20T23:59:59.999999Z"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T08:00:00+08:00",
            )

        self.assertEqual(raised.exception.code, "expired_rights")
        self.assertEqual(raised.exception.path, "$.rights.valid_until")
        self.assertNotIn("2026-08-20", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_rights_valid_until_accepts_the_exact_evaluation_instant(self) -> None:
        record = self._record()
        record["rights"]["valid_until"] = "2026-08-21T08:00:00+08:00"
        snapshot = deepcopy(record)

        self.assertIsNone(
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )
        self.assertEqual(record, snapshot)

    def test_rights_valid_until_must_be_representable_in_utc(self) -> None:
        for value in (
            "0001-01-01T00:00:00+23:59",
            "9999-12-31T23:59:59-23:59",
        ):
            with self.subTest(value=value):
                record = self._record()
                record["rights"]["valid_until"] = value

                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )

                self.assertEqual(raised.exception.code, "invalid_rfc3339")
                self.assertEqual(raised.exception.path, "$.rights.valid_until")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_non_mapping_boundaries_fail_with_domain_errors(self) -> None:
        with self.assertRaises(ProviderRecordValidationError) as root:
            validate_provider_record_semantics(
                [],
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(root.exception.code, "invalid_type")
        self.assertEqual(root.exception.path, "$")

        missing_rights = self._record()
        missing_rights.pop("rights")
        with self.assertRaises(ProviderRecordValidationError) as missing:
            validate_provider_record_semantics(
                missing_rights,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(missing.exception.code, "missing_field")
        self.assertEqual(missing.exception.path, "$.rights")

        record = self._record()
        record["rights"] = []
        with self.assertRaises(ProviderRecordValidationError) as rights:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual(rights.exception.code, "invalid_type")
        self.assertEqual(rights.exception.path, "$.rights")

    def test_timestamp_boundaries_compare_instants_and_allow_future_effective_data(
        self,
    ) -> None:
        record = self._record()
        record["as_of"] = "2026-08-21T08:00:00+08:00"
        record["published_at"] = "2026-08-20T09:00:00+08:00"
        record["fetched_at"] = "2026-08-21T00:00:00Z"
        record["valid_from"] = "2026-09-01T00:00:00Z"
        record["valid_to"] = "2026-09-01T00:00:00+00:00"
        record["rights"]["reviewed_at"] = "2026-08-20T08:00:00+08:00"

        self.assertIsNone(
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )

    def test_malformed_timestamps_fail_closed_at_their_paths(self) -> None:
        cases = (
            ("as_of", True, "$.as_of"),
            ("published_at", "2026-08-20", "$.published_at"),
            ("fetched_at", "2026-08-20 02:00:00Z", "$.fetched_at"),
            ("valid_from", 123, "$.valid_from"),
            ("valid_to", "2026-09-01T00:00:00", "$.valid_to"),
        )
        for field, value, expected_path in cases:
            with self.subTest(field=field):
                record = self._record()
                record[field] = value
                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual(raised.exception.path, expected_path)

        with self.assertRaises(ProviderRecordValidationError) as evaluation:
            validate_provider_record_semantics(
                self._record(),
                evaluation_timestamp=cast(str, True),
            )
        self.assertEqual(evaluation.exception.path, "$evaluation_timestamp")

    def test_provider_claimed_remains_distinct_from_verified(self) -> None:
        record = self._record()
        record["point_in_time_status"] = "provider_claimed"
        record.pop("provider_record_id")
        record.pop("source_document_hash")
        snapshot = deepcopy(record)

        self.assertIsNone(
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )
        self.assertEqual(record, snapshot)
        self.assertEqual(record["point_in_time_status"], "provider_claimed")

    def test_errors_do_not_embed_provider_payload_values(self) -> None:
        record = self._record()
        record["value"] = "PRIVATE-PAYLOAD-SENTINEL"
        record["published_at"] = "not-a-time"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertNotIn("PRIVATE-PAYLOAD-SENTINEL", str(raised.exception))

    def test_invalid_calendar_timestamp_hides_parser_exception_chain(self) -> None:
        record = self._record()
        record["published_at"] = "2026-02-30T00:00:00Z"

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "invalid_rfc3339")
        self.assertEqual(raised.exception.path, "$.published_at")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_unicode_digits_are_rejected_without_parser_payload_context(self) -> None:
        provider_value = "٢٠٢٦-٠٨-٢٠T٠٠:٠٠:٠٠+00:00"
        record = self._record()
        record["published_at"] = provider_value

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "invalid_rfc3339")
        self.assertEqual(raised.exception.path, "$.published_at")
        self.assertNotIn(provider_value, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_submicrosecond_timestamps_are_rejected_instead_of_truncated(self) -> None:
        cases = (
            (
                "as_of",
                "2026-08-21T00:00:00.0000001Z",
                "2026-08-21T00:00:00.000000Z",
                "$.as_of",
            ),
            (
                "published_at",
                "2026-08-20T02:00:00.0000001Z",
                "2026-08-21T00:00:00Z",
                "$.published_at",
            ),
            (
                "valid_from",
                "2026-09-01T00:00:00.0000001Z",
                "2026-08-21T00:00:00Z",
                "$.valid_from",
            ),
        )
        for field, value, evaluation_timestamp, expected_path in cases:
            with self.subTest(field=field):
                record = self._record()
                record[field] = value
                if field == "published_at":
                    record["fetched_at"] = "2026-08-20T02:00:00.0000000Z"
                if field == "valid_from":
                    record["valid_to"] = "2026-09-01T00:00:00.0000000Z"
                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp=evaluation_timestamp,
                    )
                self.assertEqual(raised.exception.code, "invalid_rfc3339")
                self.assertEqual(raised.exception.path, expected_path)

    def test_timestamp_profile_rejects_lowercase_separators_and_leap_seconds(
        self,
    ) -> None:
        for value in (
            "2026-08-20t00:00:00z",
            "2016-12-31T23:59:60Z",
            "2026-08-20T00:00:00+00:99",
            "2026-08-20T00:00:00+23:60",
            "2026-08-20T00:00:00-00:00",
        ):
            with self.subTest(value=value):
                record = self._record()
                record["as_of"] = value
                with self.assertRaises(ProviderRecordValidationError) as raised:
                    validate_provider_record_semantics(
                        record,
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual(raised.exception.code, "invalid_rfc3339")
                self.assertEqual(raised.exception.path, "$.as_of")


if __name__ == "__main__":
    unittest.main()
