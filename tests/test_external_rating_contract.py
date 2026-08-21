from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from openfundscore.resources import resolve_resource


RIGHTS_DISPLAY_STATUS = {
    "open_redistributable": "allowed",
    "derived_only": "blocked",
    "local_entitlement": "local_only",
    "display_only": "allowed",
    "unknown_blocked": "unknown",
}


class ExternalRatingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = resolve_resource(
            resource_type="schema",
            name="external_rating",
            version="0.1.0",
        ).load_json()
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def _rating(self) -> dict:
        return {
            "external_rating_id": "rating-1",
            "provider_id": "provider-1",
            "subject_type": "manager",
            "subject_id": "manager-1",
            "rating_type": "stars",
            "value": 5,
            "scale": "1-5",
            "as_of": "2026-08-21T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "source_url": "https://example.com/rating-1",
            "affects_open_score": False,
            "rights_mode": "open_redistributable",
            "display_status": "allowed",
        }

    def test_display_status_is_required(self) -> None:
        rating = self._rating()
        del rating["display_status"]

        with self.assertRaises(ValidationError):
            self.validator.validate(rating)

    def test_each_rights_mode_accepts_only_its_display_status(self) -> None:
        for rights_mode, expected_status in RIGHTS_DISPLAY_STATUS.items():
            with self.subTest(rights_mode=rights_mode, status=expected_status):
                rating = self._rating()
                rating.update(
                    {"rights_mode": rights_mode, "display_status": expected_status}
                )
                self.validator.validate(rating)

            for drifted_status in set(RIGHTS_DISPLAY_STATUS.values()) - {expected_status}:
                with self.subTest(
                    rights_mode=rights_mode, drifted_status=drifted_status
                ):
                    rating = deepcopy(self._rating())
                    rating.update(
                        {
                            "rights_mode": rights_mode,
                            "display_status": drifted_status,
                        }
                    )
                    with self.assertRaises(ValidationError):
                        self.validator.validate(rating)


if __name__ == "__main__":
    unittest.main()
