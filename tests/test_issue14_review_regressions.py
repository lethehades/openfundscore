from __future__ import annotations

import io
import unittest
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema.exceptions import ValidationError

from openfundscore.cli import _MAX_RECORD_BYTES, _load_record_document, main
from openfundscore.evidence_usage import (
    EvidenceUsageValidationError,
    validate_score_evidence_usage,
)
from openfundscore.validation import RecordValidationError, validate_record
from tests.test_record_validation import (
    external_rating,
    manager_record,
    provider_contract,
    provider_record,
    score_evidence_usage,
)


class Issue14ReviewRegressionTests(unittest.TestCase):
    def test_document_loader_reads_at_most_limit_plus_one_byte(self) -> None:
        stream = Mock()
        stream.read.return_value = b"x" * (_MAX_RECORD_BYTES + 1)
        context = Mock()
        context.__enter__ = Mock(return_value=stream)
        context.__exit__ = Mock(return_value=False)
        with (
            patch.object(Path, "open", return_value=context) as open_file,
            self.assertRaises(RecordValidationError) as raised,
        ):
            _load_record_document(
                "private-marker",
                record_type="provider_record",
                schema_version="0.1.0",
            )
        open_file.assert_called_once_with("rb")
        stream.read.assert_called_once_with(_MAX_RECORD_BYTES + 1)
        self.assertEqual("document_too_large", raised.exception.code)
        self.assertNotIn("private-marker", str(raised.exception))

    def test_argument_errors_use_one_redacted_stable_line(self) -> None:
        cases = (
            (
                "invalid-choice",
                [
                    "validate-record",
                    "--type",
                    "private-marker",
                    "--schema-version",
                    "0.1.0",
                    "private-marker.json",
                ],
            ),
            (
                "unknown-option",
                [
                    "validate-record",
                    "--private-marker",
                    "value",
                ],
            ),
            (
                "missing-required",
                ["validate-record", "private-marker.json"],
            ),
        )
        for label, arguments in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    main(arguments)
                self.assertEqual(2, raised.exception.code)
                self.assertEqual("", stdout.getvalue())
                self.assertEqual(
                    "openfundscore: error: argument_error at $arguments: "
                    "command arguments are invalid\n",
                    stderr.getvalue(),
                )
                self.assertNotIn("private-marker", stderr.getvalue())
                self.assertNotIn("usage:", stderr.getvalue())

    def test_provider_and_external_rating_reject_future_knowledge(self) -> None:
        provider_cases = (
            ("as_of", "2026-08-22T00:00:00Z", "future_as_of", "$.as_of"),
            (
                "fetched_at",
                "2026-08-22T00:00:00Z",
                "chronology_violation",
                "$.fetched_at",
            ),
        )
        for field, value, expected_code, expected_path in provider_cases:
            with self.subTest(record="provider", field=field):
                document = provider_record()
                document[field] = value
                with self.assertRaises(RecordValidationError) as raised:
                    validate_record(
                        "provider_record",
                        document,
                        schema_version="0.1.0",
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual(expected_code, raised.exception.code)
                self.assertEqual(expected_path, raised.exception.path)

        rating_cases = (
            ("fetched_at", "2026-08-22T00:00:00Z", "$.fetched_at"),
            ("published_at", "2026-08-22T00:00:00Z", "$.published_at"),
        )
        for field, value, expected_path in rating_cases:
            with self.subTest(record="external_rating", field=field):
                document = external_rating()
                document["published_at"] = "2026-08-20T12:00:00Z"
                document[field] = value
                with self.assertRaises(RecordValidationError) as raised:
                    validate_record(
                        "external_rating",
                        document,
                        schema_version="0.1.0",
                        evaluation_timestamp="2026-08-21T00:00:00Z",
                    )
                self.assertEqual("chronology_violation", raised.exception.code)
                self.assertEqual(expected_path, raised.exception.path)

    def test_manager_research_rejects_reversed_and_future_dates(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        employment = manager_record()
        employment["employment_history"] = [
            {
                "organisation": "Example",
                "role": "Manager",
                "start_date": "2025-01-01",
                "end_date": "2024-01-01",
                "evidence_ids": [],
            }
        ]
        cases.append(("employment", employment, "$.employment_history[0].start_date"))

        tenure = manager_record()
        tenure["tenures"] = [
            {
                "tenure_id": "tenure-1",
                "fund_strategy_id": "strategy-1",
                "start_date": "2025-01-01",
                "end_date": "2024-01-01",
                "role": "lead",
                "attribution_mode": "individual",
                "co_manager_ids": [],
                "evidence_ids": [],
            }
        ]
        cases.append(("tenure", tenure, "$.tenures[0].start_date"))

        performance = manager_record()
        performance["performance_evidence"] = [
            {
                "tenure_id": "tenure-1",
                "window_start": "2025-01-01",
                "window_end": "2024-01-01",
                "metric_id": "return",
                "value": 1,
                "confidence": "medium",
            }
        ]
        cases.append(
            (
                "performance",
                performance,
                "$.performance_evidence[0].window_start",
            )
        )

        evidence = manager_record()
        evidence["evidence"] = [
            {
                "evidence_id": "evidence-1",
                "tier": "A",
                "source_url": "https://example.com/evidence",
                "published_at": "2099-01-01T00:00:00Z",
                "fetched_at": "2026-08-20T00:00:00Z",
                "fact_excerpt": "public professional fact",
            }
        ]
        cases.append(("evidence", evidence, "$.evidence[0].published_at"))

        for label, document, expected_path in cases:
            with self.subTest(label=label):
                with self.assertRaises(RecordValidationError) as raised:
                    validate_record(
                        "manager_research",
                        document,
                        schema_version="0.1.0",
                    )
                self.assertEqual("semantic", raised.exception.stage)
                self.assertEqual(expected_path, raised.exception.path)

    def test_evidence_windows_end_no_later_than_ledger_as_of(self) -> None:
        document = score_evidence_usage()
        document["usage"][0]["window_end"] = "2099-12-31"
        with self.assertRaises(RecordValidationError) as raised:
            validate_record(
                "score_evidence_usage",
                document,
                schema_version="0.1.0",
            )
        self.assertEqual("semantic", raised.exception.stage)
        self.assertEqual("$.usage[0].window_end", raised.exception.path)

    def test_date_only_windows_use_the_utc_date_of_as_of(self) -> None:
        usage = score_evidence_usage()
        usage["as_of"] = "2026-08-21T00:30:00+02:00"
        usage["usage"][0]["window_end"] = "2026-08-21"
        with self.assertRaises(RecordValidationError) as evidence_error:
            validate_record(
                "score_evidence_usage",
                usage,
                schema_version="0.1.0",
            )
        self.assertEqual("$.usage[0].window_end", evidence_error.exception.path)

        manager = manager_record()
        manager["as_of"] = "2026-08-21T00:30:00+02:00"
        manager["performance_evidence"] = [
            {
                "tenure_id": "tenure-utc",
                "window_start": "2026-08-20",
                "window_end": "2026-08-21",
                "metric_id": "information_ratio",
                "value": None,
                "missing_reason": "insufficient_history",
                "confidence": "low",
            }
        ]
        with self.assertRaises(RecordValidationError) as manager_error:
            validate_record(
                "manager_research",
                manager,
                schema_version="0.1.0",
            )
        self.assertEqual(
            "$.performance_evidence[0].window_end",
            manager_error.exception.path,
        )

    def test_display_only_requires_attribution_for_contract_and_record(self) -> None:
        contract = provider_contract()
        contract["public_display_allowed"] = True
        contract["rights"] = {
            "mode": "display_only",
            "cache_allowed": False,
            "derived_works_allowed": False,
            "redistribution_allowed": False,
            "attribution_required": False,
        }
        with self.assertRaises(RecordValidationError) as contract_error:
            validate_record(
                "provider_contract",
                contract,
                schema_version="0.1.0",
            )
        self.assertEqual("rights_mismatch", contract_error.exception.code)
        self.assertEqual(
            "$.rights.attribution_required",
            contract_error.exception.path,
        )

        record = provider_record()
        record["rights"] = {
            "mode": "display_only",
            "cache_allowed": False,
            "derived_works_allowed": False,
            "redistribution_allowed": False,
            "attribution_required": False,
            "public_display_allowed": True,
        }
        with self.assertRaises(RecordValidationError) as record_error:
            validate_record(
                "provider_record",
                record,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("rights_mismatch", record_error.exception.code)
        self.assertEqual("$.rights.attribution_required", record_error.exception.path)

    def test_usage_count_is_bounded_before_schema_and_direct_semantics(self) -> None:
        document = score_evidence_usage()
        template = document["usage"][0]
        document["usage"] = []
        for index in range(1001):
            usage = deepcopy(template)
            usage["lineage_id"] = f"lineage-{index}"
            usage["series_id"] = f"series-{index}"
            document["usage"].append(usage)

        with self.assertRaises(RecordValidationError) as unified:
            validate_record(
                "score_evidence_usage",
                document,
                schema_version="0.1.0",
            )
        self.assertEqual("record_too_complex", unified.exception.code)
        self.assertEqual("$.usage", unified.exception.path)

        with self.assertRaises(EvidenceUsageValidationError):
            validate_score_evidence_usage(document)

    def test_schema_validation_stops_after_first_error(self) -> None:
        first_error = ValidationError(
            "private-marker",
            validator="required",
            validator_value=("manager_id",),
            instance={},
            path=deque(),
        )

        def errors():
            yield first_error
            raise AssertionError("schema error iterator was over-consumed")

        validator = Mock()
        validator.iter_errors.return_value = errors()
        validator_class = Mock(return_value=validator)
        validator_class.check_schema.return_value = None
        with (
            patch(
                "openfundscore.validation.Draft202012Validator",
                validator_class,
            ),
            self.assertRaises(RecordValidationError) as raised,
        ):
            validate_record(
                "manager_research",
                manager_record(),
                schema_version="0.1.0",
            )
        self.assertEqual("schema_required", raised.exception.code)
        self.assertEqual("$.manager_id", raised.exception.path)


if __name__ == "__main__":
    unittest.main()
