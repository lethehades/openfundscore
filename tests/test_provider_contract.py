from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from openfundscore.provider_semantics import (
    ProviderRecordValidationError,
    validate_provider_record_semantics,
)
from openfundscore.resources import resolve_resource

SOURCE_TYPES = (
    "regulator",
    "exchange",
    "official_registry",
    "fund_company_or_manager",
    "custodian",
    "index_or_macro_official_source",
    "commercial_vendor",
    "distribution_platform",
    "user_import",
)
AUTHENTICATION_MODES = (
    "none",
    "api_key",
    "oauth",
    "user_session",
    "local_entitlement",
)


class ProviderContractTests(unittest.TestCase):
    def _load(self, name: str) -> dict:
        resource_name = name.removesuffix(".schema.json")
        return resolve_resource(
            resource_type="schema",
            name=resource_name,
            version="0.1.0",
        ).load_json()

    def _rights(self, mode: str) -> dict:
        profiles = {
            "unknown_blocked": {
                "cache_allowed": False,
                "derived_works_allowed": False,
                "redistribution_allowed": False,
                "attribution_required": False,
                "public_display_allowed": False,
            },
            "derived_only": {
                "cache_allowed": True,
                "derived_works_allowed": True,
                "redistribution_allowed": False,
                "attribution_required": True,
                "public_display_allowed": False,
            },
            "display_only": {
                "cache_allowed": False,
                "derived_works_allowed": False,
                "redistribution_allowed": False,
                "attribution_required": True,
                "public_display_allowed": True,
            },
            "local_entitlement": {
                "cache_allowed": True,
                "derived_works_allowed": True,
                "redistribution_allowed": False,
                "attribution_required": True,
                "public_display_allowed": False,
            },
            "open_redistributable": {
                "cache_allowed": True,
                "derived_works_allowed": True,
                "redistribution_allowed": True,
                "attribution_required": True,
                "public_display_allowed": True,
            },
        }
        return {"mode": mode, **profiles[mode]}

    def _provider_record(self, mode: str = "open_redistributable") -> dict:
        return {
            "provider_id": "provider-1",
            "provider_record_id": "provider-record-1",
            "namespace": "canonical_observation",
            "source_type": "regulator",
            "jurisdiction": "US",
            "entity_type": "manager",
            "entity_id": "manager-1",
            "field": "canonical_name",
            "value": "Example Manager",
            "as_of": "2026-08-21T00:00:00Z",
            "published_at": "2026-08-21T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "source_url": "https://example.com/manager-1",
            "source_document_hash": "sha256:synthetic-provider-record",
            "point_in_time_status": "verified",
            "quality_state": "verified",
            "rights": self._rights(mode),
        }

    def _provider_contract(self, mode: str = "open_redistributable") -> dict:
        rights = self._rights(mode)
        public_display_allowed = rights.pop("public_display_allowed")
        return {
            "provider_id": "provider-1",
            "source_type": "regulator",
            "jurisdictions": ["US"],
            "authentication_mode": "none",
            "public_display_allowed": public_display_allowed,
            "rate_limit": {
                "requests_per_period": 10,
                "period_seconds": 1,
                "burst": 20,
            },
            "rights": rights,
        }

    def test_provider_record_requires_machine_provenance_fields(self) -> None:
        schema = self._load("provider_record.schema.json")
        self.assertTrue(
            {
                "namespace",
                "source_type",
                "jurisdiction",
                "point_in_time_status",
            }.issubset(schema["required"])
        )
        validator = Draft202012Validator(schema)
        for field in (
            "namespace",
            "source_type",
            "jurisdiction",
            "point_in_time_status",
        ):
            with self.subTest(field=field):
                record = self._provider_record()
                del record[field]
                with self.assertRaises(ValidationError):
                    validator.validate(record)

    def test_external_rating_namespace_is_isolated(self) -> None:
        validator = Draft202012Validator(self._load("provider_record.schema.json"))

        canonical = self._provider_record()
        validator.validate(canonical)

        external = self._provider_record()
        external.update(
            {
                "namespace": "external_ratings",
                "entity_type": "external_rating",
                "entity_id": "rating-1",
            }
        )
        validator.validate(external)

        wrong_external = deepcopy(external)
        wrong_external["namespace"] = "canonical_observation"
        with self.assertRaises(ValidationError):
            validator.validate(wrong_external)

        wrong_canonical = deepcopy(canonical)
        wrong_canonical["namespace"] = "external_ratings"
        with self.assertRaises(ValidationError):
            validator.validate(wrong_canonical)

        unknown_namespace = deepcopy(canonical)
        unknown_namespace["namespace"] = "vendor_private"
        with self.assertRaises(ValidationError):
            validator.validate(unknown_namespace)

    def test_provider_contract_schema_is_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self._load("provider_contract.schema.json"))
        Draft202012Validator.check_schema(self._load("provider_record.schema.json"))

    def test_provider_contract_requires_machine_contract_fields(self) -> None:
        schema = self._load("provider_contract.schema.json")
        required = {
            "provider_id",
            "source_type",
            "jurisdictions",
            "authentication_mode",
            "public_display_allowed",
            "rate_limit",
            "rights",
        }
        self.assertTrue(required.issubset(schema["required"]))

        validator = Draft202012Validator(schema)
        for field in required:
            with self.subTest(field=field):
                contract = self._provider_contract()
                del contract[field]
                with self.assertRaises(ValidationError):
                    validator.validate(contract)

    def test_source_type_covers_every_provider_category(self) -> None:
        contract_validator = Draft202012Validator(
            self._load("provider_contract.schema.json")
        )
        record_validator = Draft202012Validator(
            self._load("provider_record.schema.json")
        )

        for source_type in SOURCE_TYPES:
            with self.subTest(schema="provider_contract", source_type=source_type):
                contract = self._provider_contract()
                contract["source_type"] = source_type
                contract_validator.validate(contract)
            with self.subTest(schema="provider_record", source_type=source_type):
                record = self._provider_record()
                record["source_type"] = source_type
                record_validator.validate(record)

        invalid = self._provider_contract()
        invalid["source_type"] = "social_media"
        with self.assertRaises(ValidationError):
            contract_validator.validate(invalid)

    def test_authentication_mode_describes_method_without_secrets(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))

        for mode in AUTHENTICATION_MODES:
            with self.subTest(mode=mode):
                contract = self._provider_contract()
                contract["authentication_mode"] = mode
                validator.validate(contract)

        invalid_mode = self._provider_contract()
        invalid_mode["authentication_mode"] = "hardcoded_token"
        with self.assertRaises(ValidationError):
            validator.validate(invalid_mode)

        for secret_field in ("api_key", "token", "password", "client_secret"):
            with self.subTest(secret_field=secret_field):
                leaked = self._provider_contract()
                leaked[secret_field] = "must-not-be-in-a-contract"
                with self.assertRaises(ValidationError):
                    validator.validate(leaked)

    def test_rate_limit_is_structured_and_bounded(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))
        validator.validate(self._provider_contract())

        for invalid_rate_limit in (
            "10 requests/second",
            {},
            {"requests_per_period": 0, "period_seconds": 1},
            {"requests_per_period": 10, "period_seconds": 0},
            {"requests_per_period": 10, "period_seconds": 1, "burst": 0},
        ):
            with self.subTest(rate_limit=invalid_rate_limit):
                contract = self._provider_contract()
                contract["rate_limit"] = invalid_rate_limit
                with self.assertRaises(ValidationError):
                    validator.validate(contract)

    def test_each_rights_mode_accepts_a_self_consistent_contract(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))
        for mode in (
            "unknown_blocked",
            "derived_only",
            "display_only",
            "local_entitlement",
            "open_redistributable",
        ):
            with self.subTest(mode=mode):
                validator.validate(self._provider_contract(mode))

    def test_each_rights_mode_rejects_a_contradictory_contract(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))
        contradictions = {
            "unknown_blocked": ("cache_allowed", True),
            "derived_only": ("derived_works_allowed", False),
            "display_only": ("derived_works_allowed", True),
            "local_entitlement": ("redistribution_allowed", True),
            "open_redistributable": ("redistribution_allowed", False),
        }
        for mode, (permission, invalid_value) in contradictions.items():
            with self.subTest(mode=mode, permission=permission):
                contract = self._provider_contract(mode)
                if permission == "public_display_allowed":
                    contract[permission] = invalid_value
                else:
                    contract["rights"][permission] = invalid_value
                with self.assertRaises(ValidationError):
                    validator.validate(contract)

    def test_non_open_modes_never_allow_raw_redistribution(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))
        for mode in (
            "unknown_blocked",
            "derived_only",
            "display_only",
            "local_entitlement",
        ):
            with self.subTest(mode=mode):
                contract = self._provider_contract(mode)
                contract["rights"]["redistribution_allowed"] = True
                with self.assertRaises(ValidationError):
                    validator.validate(contract)

    def test_public_display_obeys_rights_mode(self) -> None:
        validator = Draft202012Validator(self._load("provider_contract.schema.json"))

        for mode in ("unknown_blocked", "local_entitlement"):
            with self.subTest(mode=mode):
                contract = self._provider_contract(mode)
                contract["public_display_allowed"] = True
                with self.assertRaises(ValidationError):
                    validator.validate(contract)

        display_only = self._provider_contract("display_only")
        display_only["public_display_allowed"] = False
        with self.assertRaises(ValidationError):
            validator.validate(display_only)

    def test_derived_only_never_allows_public_display(self) -> None:
        contract = self._provider_contract("derived_only")
        contract["public_display_allowed"] = True
        with self.assertRaises(ValidationError):
            Draft202012Validator(self._load("provider_contract.schema.json")).validate(
                contract
            )

        record = self._provider_record("derived_only")
        record["rights"]["public_display_allowed"] = True
        with self.assertRaises(ValidationError):
            Draft202012Validator(self._load("provider_record.schema.json")).validate(
                record
            )
        with self.assertRaises(ProviderRecordValidationError):
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

    def test_provider_record_rights_modes_are_self_consistent(self) -> None:
        validator = Draft202012Validator(self._load("provider_record.schema.json"))
        for mode in (
            "unknown_blocked",
            "derived_only",
            "display_only",
            "local_entitlement",
            "open_redistributable",
        ):
            with self.subTest(mode=mode):
                validator.validate(self._provider_record(mode))

        contradictory = self._provider_record("display_only")
        contradictory["rights"]["derived_works_allowed"] = True
        with self.assertRaises(ValidationError):
            validator.validate(contradictory)

    def test_schema_only_validation_cannot_replace_provider_semantics(self) -> None:
        record = self._provider_record()
        record["published_at"] = "2026-08-22T00:00:00Z"
        record["fetched_at"] = "2026-08-21T00:00:00Z"
        Draft202012Validator(self._load("provider_record.schema.json")).validate(record)

        with self.assertRaises(ProviderRecordValidationError) as raised:
            validate_provider_record_semantics(
                record,
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.code, "chronology_violation")
        self.assertEqual(raised.exception.path, "$.published_at")


if __name__ == "__main__":
    unittest.main()
