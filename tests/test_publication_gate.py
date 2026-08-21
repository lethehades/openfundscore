from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any, cast

from openfundscore.publication_gate import (
    PublicationDecision,
    PublicationGateError,
    evaluate_publication_gate,
)


def approved_request() -> dict[str, Any]:
    """Fabricated complete-looking metadata used to prove it cannot authorize."""
    return {
        "request_id": "publication-request-1",
        "publication_mode": "hosted_public_rating",
        "jurisdictions": ["CN"],
        "legal_reviews": [
            {
                "review_id": "review-1",
                "jurisdiction": "CN",
                "reviewer_organization": "Example Counsel",
                "reviewer_role": "qualified_external_counsel",
                "completed_at": "2026-08-20T00:00:00Z",
                "expires_at": "2027-08-20T00:00:00Z",
                "outcome": "approved",
                "scope": ["fund_evaluation_publication"],
                "required_controls": ["geo_restrict_cn"],
                "artifact_sha256": "a" * 64,
            }
        ],
        "provider_clearances": [
            {
                "provider_id": "provider-1",
                "contract_version": "0.1.0",
                "reviewed_at": "2026-08-20T00:00:00Z",
                "expires_at": "2027-08-20T00:00:00Z",
                "public_display_allowed": True,
                "derived_works_allowed": True,
                "raw_redistribution_allowed": True,
                "attribution_required": True,
                "attribution_plan_present": True,
                "database_rights_assessed": True,
                "license_artifact_sha256": "b" * 64,
            }
        ],
        "controls": {
            "methodology_disclosed": True,
            "conflicts_disclosed": True,
            "personnel_data_policy_present": True,
            "retention_policy_present": True,
            "complaints_process_present": True,
            "human_approval_required": True,
            "raw_provider_data_in_output": False,
            "required_controls_implemented": ["geo_restrict_cn"],
            "release_approval": {
                "approved_by_role": "authorized_release_officer",
                "approved_at": "2026-08-20T00:00:00Z",
                "artifact_sha256": "c" * 64,
            },
        },
    }


class PublicationGateTests(unittest.TestCase):
    def test_complete_looking_assertions_are_always_no_go(self) -> None:
        request = approved_request()
        snapshot = deepcopy(request)

        result = evaluate_publication_gate(
            request,
            evaluation_timestamp="2026-08-21T00:00:00Z",
        )

        self.assertIs(PublicationDecision.NO_GO, result.decision)
        self.assertFalse(result.authorizes_publication)
        self.assertEqual(
            (
                "jurisdiction_review_not_obtained",
                "not_authorized_for_publication",
                "publication_manifest_not_verified",
                "trusted_publication_verifier_unavailable",
            ),
            result.reason_codes,
        )
        self.assertEqual(("CN",), result.jurisdictions)
        self.assertEqual("publication-request-1", result.request_id)
        self.assertEqual(request, snapshot)
        self.assertFalse(hasattr(PublicationDecision, "GO"))

    def test_local_private_research_is_local_only(self) -> None:
        request = approved_request()
        request["publication_mode"] = "local_private_research"

        result = evaluate_publication_gate(
            request,
            evaluation_timestamp="2026-08-21T00:00:00Z",
        )

        self.assertIs(PublicationDecision.LOCAL_ONLY, result.decision)
        self.assertEqual(("not_authorized_for_publication",), result.reasons)
        self.assertFalse(result.authorizes_publication)

    def test_evidence_assertions_are_never_interpreted_as_authority(self) -> None:
        request = approved_request()
        request["legal_reviews"] = [object()] * 20_000
        request["provider_clearances"] = [object()] * 20_000
        request["controls"] = object()

        result = evaluate_publication_gate(
            request,
            evaluation_timestamp="2026-08-21T00:00:00Z",
        )

        self.assertIs(PublicationDecision.NO_GO, result.decision)

    def test_malformed_boundary_inputs_use_stable_redacted_errors(self) -> None:
        marker = "PRIVATE-INPUT-SENTINEL"
        cases: tuple[tuple[object, object, str], ...] = (
            ([], "2026-08-21T00:00:00Z", "$"),
            (
                {"request_id": marker, "publication_mode": "bad"},
                "2026-08-21T00:00:00Z",
                "$.publication_mode",
            ),
            (
                {
                    "request_id": "line1\nINJECTED: go",
                    "publication_mode": "hosted_public_rating",
                },
                "2026-08-21T00:00:00Z",
                "$.request_id",
            ),
            (
                {"request_id": "", "publication_mode": "hosted_public_rating"},
                "2026-08-21T00:00:00Z",
                "$.request_id",
            ),
            (
                {
                    "request_id": "request-1",
                    "publication_mode": "hosted_public_rating",
                    "jurisdictions": ["ZZZ"],
                },
                "2026-08-21T00:00:00Z",
                "$.jurisdictions[*]",
            ),
            (
                {
                    "request_id": "request-1",
                    "publication_mode": "hosted_public_rating",
                },
                marker,
                "$evaluation_timestamp",
            ),
        )
        for request, timestamp, path in cases:
            with self.subTest(path=path):
                with self.assertRaises(PublicationGateError) as raised:
                    evaluate_publication_gate(
                        cast(Any, request),
                        evaluation_timestamp=cast(Any, timestamp),
                    )
                self.assertEqual("invalid_publication_request", raised.exception.code)
                self.assertEqual(path, raised.exception.path)
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_counts_and_identifiers_are_bounded(self) -> None:
        too_many_fields = {
            "request_id": "request-1",
            "publication_mode": "hosted_public_rating",
            **{f"field_{index}": True for index in range(31)},
        }
        with self.assertRaises(PublicationGateError) as top:
            evaluate_publication_gate(
                too_many_fields,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("$", top.exception.path)

        request = approved_request()
        request["jurisdictions"] = ["CN"] * 33
        with self.assertRaises(PublicationGateError) as jurisdictions:
            evaluate_publication_gate(
                request,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("$.jurisdictions", jurisdictions.exception.path)

    def test_public_package_exports_publication_gate(self) -> None:
        import openfundscore

        self.assertIs(
            evaluate_publication_gate, openfundscore.evaluate_publication_gate
        )
        self.assertIs(PublicationDecision, openfundscore.PublicationDecision)
        self.assertIs(PublicationGateError, openfundscore.PublicationGateError)


if __name__ == "__main__":
    unittest.main()
