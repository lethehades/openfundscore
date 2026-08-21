from __future__ import annotations

import unittest

from openfundscore.publication_gate import (
    PublicationDecision,
    evaluate_publication_gate,
)
from tests.test_publication_gate import approved_request


class PublicationGateReviewRegressionTests(unittest.TestCase):
    def test_fabricated_metadata_can_never_authorize_hosted_publication(self) -> None:
        request = approved_request()
        result = evaluate_publication_gate(
            request,
            evaluation_timestamp="2026-08-21T00:00:00Z",
        )

        self.assertEqual(PublicationDecision.NO_GO, result.decision)
        self.assertFalse(result.authorizes_publication)
        self.assertIn("trusted_publication_verifier_unavailable", result.reasons)
        self.assertEqual("publication-request-1", result.request_id)
        self.assertEqual("2026-08-21T00:00:00Z", result.evaluation_timestamp)

    def test_untrusted_evidence_is_not_traversed_or_echoed(self) -> None:
        marker = "PRIVATE-UNKNOWN-FIELD-SENTINEL"
        request = approved_request()
        request[marker] = {"nested": [object()] * 20_000}
        request["legal_reviews"] = [object()] * 20_000
        request["provider_clearances"] = [object()] * 20_000

        result = evaluate_publication_gate(
            request,
            evaluation_timestamp="2026-08-21T00:00:00Z",
        )

        self.assertEqual(PublicationDecision.NO_GO, result.decision)
        self.assertNotIn(marker, str(result))
        self.assertFalse(result.authorizes_publication)


if __name__ == "__main__":
    unittest.main()
