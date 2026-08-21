from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from openfundscore.resources import (
    ResourceError,
    ResourceInfo,
    ResourceKey,
    ResourceType,
    ResolvedResource,
    _load_catalog,
    _parse_catalog,
    list_resources,
    resolve_resource,
)


class ResourceCatalogTests(unittest.TestCase):
    def test_unreadable_catalog_hides_internal_io_details(self) -> None:
        class MissingIndex:
            def read_text(self, encoding: str) -> str:
                raise FileNotFoundError("/sensitive/install/path/index.json")

        class MissingRoot:
            def joinpath(self, name: str) -> MissingIndex:
                return MissingIndex()

        with patch("openfundscore.resources.files", return_value=MissingRoot()):
            with self.assertRaises(ResourceError) as raised:
                _load_catalog()

        self.assertEqual(raised.exception.code, "catalog_unavailable")
        self.assertEqual(raised.exception.path, "$catalog")
        self.assertNotIn("sensitive", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_invalid_catalog_json_hides_parser_details(self) -> None:
        class InvalidIndex:
            def read_text(self, encoding: str) -> str:
                return "{private"

        class InvalidRoot:
            def joinpath(self, name: str) -> InvalidIndex:
                return InvalidIndex()

        with patch("openfundscore.resources.files", return_value=InvalidRoot()):
            with self.assertRaises(ResourceError) as raised:
                _load_catalog()

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")
        self.assertNotIn("private", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_catalog_rejects_non_object_roots(self) -> None:
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog(1)

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_non_array_resource_collections(self) -> None:
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": {}})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_unknown_format_versions(self) -> None:
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 2, "resources": []})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_unknown_top_level_fields(self) -> None:
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog(
                {"format_version": 1, "resources": [], "unexpected": True}
            )

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_unknown_entry_fields(self) -> None:
        entry = {
            "type": "schema",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "schema/example/0.1.0.schema.json",
            "media_type": "application/schema+json",
            "sha256": "0" * 64,
            "unexpected": True,
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": [entry]})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_malformed_sha256(self) -> None:
        entry = {
            "type": "schema",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "schema/example/0.1.0.schema.json",
            "media_type": "application/schema+json",
            "sha256": "not-a-digest",
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": [entry]})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_media_type_mismatches(self) -> None:
        entry = {
            "type": "schema",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "schema/example/0.1.0.schema.json",
            "media_type": "application/json",
            "sha256": "0" * 64,
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": [entry]})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_unknown_resource_types_with_domain_error(self) -> None:
        entry = {
            "type": "unknown",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "unknown/example/0.1.0.json",
            "media_type": "application/json",
            "sha256": "0" * 64,
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": [entry]})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_duplicate_resource_keys(self) -> None:
        entry = {
            "type": "schema",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "schema/example/0.1.0.schema.json",
            "media_type": "application/schema+json",
            "sha256": "0" * 64,
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog(
                {
                    "format_version": 1,
                    "resources": [entry, dict(entry)],
                }
            )

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_rejects_paths_not_derived_from_the_selector(self) -> None:
        entry = {
            "type": "schema",
            "name": "example",
            "version": "0.1.0",
            "internal_path": "../secret.json",
            "media_type": "application/schema+json",
            "sha256": "0" * 64,
        }
        with self.assertRaises(ResourceError) as raised:
            _parse_catalog({"format_version": 1, "resources": [entry]})

        self.assertEqual(raised.exception.code, "catalog_invalid")
        self.assertEqual(raised.exception.path, "$catalog")

    def test_catalog_lists_all_versioned_resources_in_stable_order(self) -> None:
        resources = list_resources()

        self.assertEqual(
            [
                (resource.key.resource_type.value, resource.key.name, resource.key.version)
                for resource in resources
            ],
            [
                ("schema", "external_rating", "0.1.0"),
                ("schema", "manager_research", "0.1.0"),
                ("schema", "provider_contract", "0.1.0"),
                ("schema", "provider_record", "0.1.0"),
                ("schema", "score_evidence_usage", "0.1.0"),
                ("scoring-config", "openfundscore-core", "0.1.0"),
                ("strategy-mapping", "complex_alternatives", "0.1.0"),
            ],
        )
        self.assertTrue(
            all(resource.key.resource_type in ResourceType for resource in resources)
        )

    def test_handle_constructor_rejects_non_derived_internal_paths(self) -> None:
        info = ResourceInfo(
            key=ResourceKey(
                resource_type=ResourceType.SCHEMA,
                name="provider_record",
                version="0.1.0",
            ),
            uri="openfundscore://schema/provider_record/0.1.0",
            media_type="application/schema+json",
            sha256="0" * 64,
        )
        with self.assertRaises(ResourceError) as raised:
            ResolvedResource(info=info, _internal_path="../private.json")

        self.assertEqual(raised.exception.code, "invalid_resource_handle")
        self.assertEqual(raised.exception.path, "$resource")

    def test_catalog_filters_by_resource_type(self) -> None:
        resources = list_resources(resource_type="schema")

        self.assertEqual(len(resources), 5)
        self.assertTrue(
            all(resource.key.resource_type is ResourceType.SCHEMA for resource in resources)
        )

    def test_resolves_and_reads_versioned_scoring_config(self) -> None:
        resource = resolve_resource(
            resource_type="scoring-config",
            name="openfundscore-core",
            version="0.1.0",
        )

        payload = resource.read_bytes()
        document = resource.load_json()
        self.assertEqual(document["model_id"], "openfundscore-core")
        self.assertEqual(document["model_version"], "0.1.0")
        self.assertEqual(hashlib.sha256(payload).hexdigest(), resource.info.sha256)
        self.assertEqual(
            resource.info.uri,
            "openfundscore://scoring-config/openfundscore-core/0.1.0",
        )

    def test_invalid_selectors_fail_closed_without_reflecting_values(self) -> None:
        cases = (
            ("schema", "../provider_record", "0.1.0", "$name"),
            ("schema", "provider%2frecord", "0.1.0", "$name"),
            ("schema", "provider_record", "../0.1.0", "$version"),
            ("schéma", "provider_record", "0.1.0", "$resource_type"),
        )
        for resource_type, name, version, expected_path in cases:
            with self.subTest(value=(resource_type, name, version)):
                with self.assertRaises(ResourceError) as raised:
                    resolve_resource(
                        resource_type=resource_type,
                        name=name,
                        version=version,
                    )

                self.assertEqual(raised.exception.code, "invalid_selector")
                self.assertEqual(raised.exception.path, expected_path)
                self.assertNotIn(name, str(raised.exception))
                self.assertNotIn(version, str(raised.exception))

    def test_unknown_version_never_falls_back(self) -> None:
        with self.assertRaises(ResourceError) as raised:
            resolve_resource(
                resource_type="scoring-config",
                name="openfundscore-core",
                version="0.1.1",
            )

        self.assertEqual(raised.exception.code, "resource_not_found")
        self.assertEqual(raised.exception.path, "$resource")

    def test_digest_mismatch_blocks_resource_reads(self) -> None:
        class AlteredPayload:
            def read_bytes(self) -> bytes:
                return b'{"altered":true}'

        class AlteredRoot:
            def joinpath(self, *parts: str) -> AlteredPayload:
                return AlteredPayload()

        resource = resolve_resource(
            resource_type="scoring-config",
            name="openfundscore-core",
            version="0.1.0",
        )
        with patch("openfundscore.resources.files", return_value=AlteredRoot()):
            with self.assertRaises(ResourceError) as raised:
                resource.read_bytes()

        self.assertEqual(raised.exception.code, "resource_integrity")
        self.assertEqual(raised.exception.path, "$resource")

    def test_unreadable_payload_hides_internal_io_details(self) -> None:
        class MissingPayload:
            def read_bytes(self) -> bytes:
                raise FileNotFoundError("/sensitive/install/path/resource.json")

        class MissingRoot:
            def joinpath(self, *parts: str) -> MissingPayload:
                return MissingPayload()

        resource = resolve_resource(
            resource_type="schema",
            name="provider_record",
            version="0.1.0",
        )
        with patch("openfundscore.resources.files", return_value=MissingRoot()):
            with self.assertRaises(ResourceError) as raised:
                resource.read_bytes()

        self.assertEqual(raised.exception.code, "resource_unavailable")
        self.assertEqual(raised.exception.path, "$resource")
        self.assertNotIn("sensitive", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_non_utf8_payload_uses_a_domain_format_error(self) -> None:
        resource = resolve_resource(
            resource_type="schema",
            name="provider_record",
            version="0.1.0",
        )
        with patch.object(type(resource), "read_bytes", return_value=b"\xff"):
            with self.assertRaises(ResourceError) as raised:
                resource.read_text()

        self.assertEqual(raised.exception.code, "resource_format")
        self.assertEqual(raised.exception.path, "$resource")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_invalid_json_uses_a_domain_format_error(self) -> None:
        resource = resolve_resource(
            resource_type="schema",
            name="provider_record",
            version="0.1.0",
        )
        with patch.object(type(resource), "read_text", return_value="{private"):
            with self.assertRaises(ResourceError) as raised:
                resource.load_json()

        self.assertEqual(raised.exception.code, "resource_format")
        self.assertEqual(raised.exception.path, "$resource")
        self.assertNotIn("private", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_non_object_json_uses_a_domain_format_error(self) -> None:
        resource = resolve_resource(
            resource_type="schema",
            name="provider_record",
            version="0.1.0",
        )
        with patch.object(type(resource), "read_text", return_value="[]"):
            with self.assertRaises(ResourceError) as raised:
                resource.load_json()

        self.assertEqual(raised.exception.code, "resource_format")
        self.assertEqual(raised.exception.path, "$resource")


if __name__ == "__main__":
    unittest.main()
