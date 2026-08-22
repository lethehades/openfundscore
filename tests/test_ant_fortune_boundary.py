from __future__ import annotations

import unittest


class AntFortuneBoundaryTests(unittest.TestCase):
    def test_readme_documents_the_minimal_ant_fortune_boundary(self) -> None:
        from pathlib import Path

        readme = (
            Path(__file__).parents[1].joinpath("README.md").read_text(encoding="utf-8")
        )

        required_fragments = (
            "[Ant Fortune public-data boundary](docs/ANT_FORTUNE_BOUNDARY.md)",
            "platform-boundary validate --boundary-version 0.1.0",
            "platform-boundary check platform_rating",
            "no authorized per-fund API",
            "no automated adapter",
            "no login or cookie access",
            "external only and never enter Open Score",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)

    def test_packaged_boundary_blocks_all_per_fund_fields_without_authorization(
        self,
    ) -> None:
        from openfundscore.ant_fortune_boundary import load_ant_fortune_boundary

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")

        self.assertEqual(boundary["boundary_id"], "ant_fortune_public_data_boundary")
        self.assertEqual(boundary["boundary_version"], "0.1.0")
        self.assertFalse(boundary["automated_adapter_available"])
        fields = {item["field_id"]: item for item in boundary["fields"]}
        self.assertEqual(len(fields), 15)
        for field_id in set(fields) - {"platform_brand_entry"}:
            self.assertEqual(
                fields[field_id]["authorization_status"], "unknown_blocked"
            )
            self.assertFalse(fields[field_id]["automated_ingestion_allowed"])
        self.assertEqual(
            fields["platform_brand_entry"]["authorization_status"],
            "marketing_fact_only",
        )
        self.assertFalse(fields["platform_brand_entry"]["open_score_eligible"])

    def test_cli_validates_a_local_boundary_document_without_network(self) -> None:
        import json
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from pathlib import Path

        from openfundscore.ant_fortune_boundary import load_ant_fortune_boundary
        from openfundscore.cli import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "boundary.json"
            path.write_text(
                json.dumps(load_ant_fortune_boundary(boundary_version="0.1.0")),
                encoding="utf-8",
            )
            output = StringIO()
            error = StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                exit_code = main(
                    [
                        "platform-boundary",
                        "validate",
                        str(path),
                        "--boundary-version",
                        "0.1.0",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(error.getvalue(), "")
        self.assertRegex(
            output.getvalue(),
            r"^valid: ant_fortune@0\.1\.0; sha256=[0-9a-f]{64}\n$",
        )

    def test_validator_returns_an_immutable_auditable_boundary_decision(self) -> None:
        from dataclasses import FrozenInstanceError

        from openfundscore.ant_fortune_boundary import (
            BoundaryConclusion,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )
        from openfundscore.resources import resolve_resource

        resource = resolve_resource(
            resource_type="platform-boundary",
            name="ant_fortune",
            version="0.1.0",
        )
        decision = validate_ant_fortune_boundary(
            load_ant_fortune_boundary(boundary_version="0.1.0"),
            expected_version="0.1.0",
            resource_sha256=resource.info.sha256,
        )

        self.assertEqual(
            decision.conclusion, BoundaryConclusion.BLOCKED_PENDING_AUTHORIZATION
        )
        self.assertEqual(decision.resource_sha256, resource.info.sha256)
        self.assertEqual(decision.reviewed_at, "2026-08-22T00:22:00Z")
        self.assertEqual(len(decision.fields), 15)
        self.assertTrue(
            {
                "documented_public_api",
                "login_session",
                "private_account",
                "unauthenticated_official_page",
                "user_authorized_export",
                "login",
                "cookie",
                "session",
                "automated",
            }.issubset({mode.access_mode for mode in decision.access_modes})
        )
        with self.assertRaises(FrozenInstanceError):
            decision.conclusion = BoundaryConclusion.MARKETING_FACT_ONLY  # type: ignore[misc]

    def test_boundary_decision_retains_the_complete_audit_inventory(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        decision = validate_ant_fortune_boundary(
            load_ant_fortune_boundary(boundary_version="0.1.0"),
            expected_version="0.1.0",
            resource_sha256="0" * 64,
        )

        self.assertTrue(hasattr(decision, "sources"))
        self.assertEqual(
            {source.source_id for source in decision.sources},
            {"ant_fortune_official_entry", "alipay_open_platform_entry"},
        )
        self.assertIn("automated_adapter", decision.prohibited_collection)
        self.assertEqual(len(decision.reassessment_conditions), 4)
        self.assertEqual(len(decision.unresolved_items), 3)

    def test_validator_rejects_unknown_fields_with_stable_redacted_error(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        boundary["private-marker"] = "do-not-echo"

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "unknown_field")
        self.assertEqual(raised.exception.path, "$")
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertNotIn("do-not-echo", str(raised.exception))

    def test_validator_rejects_hostile_mapping_without_leaking_its_exception(
        self,
    ) -> None:
        from collections.abc import Mapping

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            validate_ant_fortune_boundary,
        )

        class HostileMapping(Mapping[str, object]):
            def __getitem__(self, key: str) -> object:
                raise RuntimeError("private-marker")

            def __iter__(self):
                raise RuntimeError("private-marker")

            def __len__(self) -> int:
                raise RuntimeError("private-marker")

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                HostileMapping(),
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid_document")
        self.assertEqual(raised.exception.path, "$")
        self.assertNotIn("private-marker", str(raised.exception))

    def test_format_version_rejects_bool_pseudo_integer(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        boundary["format_version"] = True

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid_integer")
        self.assertEqual(raised.exception.path, "$.format_version")

    def test_validator_rejects_integer_boolean_impersonators(self) -> None:
        from copy import deepcopy
        from typing import Any

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cases = (
            (("access_modes", 0, "public_by_default"), 0),
            (("access_modes", 1, "public_by_default"), 0.0),
            (("fields", 0, "robots_is_authorization"), 0),
            (("fields", 0, "open_score_eligible"), 0.0),
            (("fields", 0, "automated_ingestion_allowed"), 0),
            (("fields", -1, "robots_is_authorization"), 0.0),
        )
        for path, value in cases:
            with self.subTest(path=path, value=value):
                boundary = deepcopy(original)
                target: Any = boundary
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_boolean")

    def test_copy_errors_never_include_untrusted_mapping_keys(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            validate_ant_fortune_boundary,
        )

        hostile_documents = (
            {"private-marker": object()},
            {"safe": {"private-marker": object()}},
        )
        for document in hostile_documents:
            with self.subTest(document_depth=len(document)):
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        document,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_document")
                self.assertNotIn("private-marker", raised.exception.path)
                self.assertNotIn("private-marker", str(raised.exception))

    def test_field_api_redacts_unexpected_access_mode_exceptions(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryUse,
            BoundaryValidationError,
            decide_ant_fortune_field,
        )

        class HostileAccessMode:
            def __eq__(self, other: object) -> bool:
                raise RuntimeError("private-marker")

        with self.assertRaises(BoundaryValidationError) as raised:
            decide_ant_fortune_field(
                "subscription_fee",
                access_mode=HostileAccessMode(),  # type: ignore[arg-type]
                requested_uses=frozenset({BoundaryUse.CACHE}),
                boundary_version="0.1.0",
            )
        self.assertEqual(raised.exception.code, "invalid_selector")
        self.assertEqual(raised.exception.path, "$access_mode")
        self.assertNotIn("private-marker", str(raised.exception))

    def test_validator_rejects_unknown_access_and_rights_enums(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cases = (
            ("access", ("access_modes", 0, "access_mode"), "unknown_access"),
            ("rights", ("fields", 0, "derived_status"), "invalid_enum"),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                boundary = deepcopy(original)
                target = boundary
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_enum")

    def test_validator_rejects_duplicate_field_identifiers(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        boundary["fields"].append(deepcopy(boundary["fields"][0]))

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "duplicate_field")
        self.assertEqual(raised.exception.path, "$.fields")

    def test_validator_rejects_non_public_https_source_urls(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        for url in (
            "http://www.antfortune.com/",
            "https://localhost/private",
            "https://127.0.0.1/private",
            "https://user:pass@example.com/private",
        ):
            with self.subTest(url=url):
                boundary = deepcopy(original)
                boundary["sources"][0]["url"] = url
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_url")
                self.assertEqual(raised.exception.path, "$.sources[0].url")
                self.assertNotIn(url, str(raised.exception))

    def test_validator_rejects_invisible_audit_text_without_echoing_it(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        marker = "private-marker\u200b"
        boundary["sources"][0]["observation"] = marker

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid_string")
        self.assertEqual(raised.exception.path, "$.sources[0].observation")
        self.assertNotIn(marker, str(raised.exception))

    def test_validator_rejects_overlong_or_unicode_confusable_identifiers(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cases = (
            (("boundary_id",), "ant_fortunе_boundary", "$.boundary_id"),
            (("fields", 0, "field_id"), "a" * 129, "$.fields[0].field_id"),
            (("sources", 0, "source_id"), "../source", "$.sources[0].source_id"),
        )
        for path, value, expected_path in cases:
            with self.subTest(path=expected_path):
                boundary = deepcopy(original)
                target = boundary
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_identifier")
                self.assertEqual(raised.exception.path, expected_path)
                self.assertNotIn(value, str(raised.exception))

    def test_validator_rejects_non_finite_cyclic_and_overdeep_json(self) -> None:
        import math
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cyclic: list[object] = []
        cyclic.append(cyclic)
        deep: object = "leaf"
        for _ in range(80):
            deep = [deep]
        cases = (
            ("nan", [math.nan]),
            ("inf", [math.inf]),
            ("cycle", cyclic),
            ("depth", deep),
        )
        for label, hostile in cases:
            with self.subTest(label=label):
                boundary = deepcopy(original)
                boundary["unresolved_items"] = hostile
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_document")

    def test_validator_rejects_oversized_width_nodes_and_scalars(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        hostile_values = (
            ["item"] * 1_001,
            [["item"] * 10 for _ in range(1_000)],
            ["private-marker" + ("x" * 65_537)],
        )
        for index, hostile in enumerate(hostile_values):
            with self.subTest(index=index):
                boundary = deepcopy(original)
                boundary["unresolved_items"] = hostile
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_document")
                self.assertNotIn("private-marker", str(raised.exception))

    def test_validator_rejects_duplicate_keys_from_a_custom_mapping(self) -> None:
        from collections.abc import Mapping
        from typing import Any

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            validate_ant_fortune_boundary,
        )

        class DuplicateMapping(Mapping[str, object]):
            def __getitem__(self, key: str) -> object:
                raise RuntimeError("private-marker")

            def __iter__(self):
                return iter(("duplicate", "duplicate"))

            def __len__(self) -> int:
                return 2

            def items(self) -> Any:
                return (("duplicate", 1), ("duplicate", 2))

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                DuplicateMapping(),
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "duplicate_key")
        self.assertNotIn("private-marker", str(raised.exception))

    def test_copy_bounds_and_redacts_hostile_container_entries(self) -> None:
        from collections.abc import Mapping, Sequence
        from typing import Any

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            validate_ant_fortune_boundary,
        )

        class HostileEntry:
            def __iter__(self):
                raise RuntimeError("private-marker")

        class EntryMapping(Mapping[str, object]):
            def __init__(self, entries: object, declared_size: int = 1) -> None:
                self.entries = entries
                self.declared_size = declared_size

            def __getitem__(self, key: str) -> object:
                raise KeyError(key)

            def __iter__(self):
                return iter(())

            def __len__(self) -> int:
                return self.declared_size

            def items(self) -> Any:
                return self.entries

        class CountedItems:
            def __init__(self) -> None:
                self.calls = 0

            def __iter__(self):
                for index in range(1_002):
                    self.calls += 1
                    yield (f"key-{index}", index)

        class OversizedSequence(Sequence[object]):
            def __init__(self) -> None:
                self.calls = 0

            def __len__(self) -> int:
                return 1_001

            def __getitem__(self, index: int) -> object:  # type: ignore[override]
                self.calls += 1
                return index

        hostile_mappings = (
            EntryMapping((HostileEntry(),)),
            EntryMapping((("a", 1, 2),)),
        )
        for index, mapping in enumerate(hostile_mappings):
            with self.subTest(mapping=index):
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        mapping,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "invalid_document")
                self.assertNotIn("private-marker", str(raised.exception))

        counted = CountedItems()
        with self.assertRaises(BoundaryValidationError):
            validate_ant_fortune_boundary(
                EntryMapping(counted),
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )
        self.assertLessEqual(counted.calls, 2)

        oversized = OversizedSequence()
        with self.assertRaises(BoundaryValidationError):
            validate_ant_fortune_boundary(
                oversized,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )
        self.assertEqual(oversized.calls, 0)

    def test_validator_rejects_unknown_nested_fields(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cases = (
            ("access", "access_modes"),
            ("source", "sources"),
            ("field", "fields"),
        )
        for label, collection in cases:
            with self.subTest(label=label):
                boundary = deepcopy(original)
                boundary[collection][0]["private-marker"] = True
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "unknown_field")
                self.assertNotIn("private-marker", str(raised.exception))

    def test_access_modes_and_external_rating_are_fail_closed(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        access_by_name = {
            item["access_mode"]: index
            for index, item in enumerate(original["access_modes"])
        }
        rating_index = next(
            index
            for index, item in enumerate(original["fields"])
            if item["field_id"] == "platform_rating"
        )
        mutations = (
            (
                "login",
                lambda document: document["access_modes"][
                    access_by_name["login_session"]
                ].__setitem__("project_collection", "boundary_review_only"),
            ),
            (
                "private",
                lambda document: document["access_modes"][
                    access_by_name["private_account"]
                ].__setitem__("project_collection", "local_import_only"),
            ),
            (
                "export-public",
                lambda document: document["access_modes"][
                    access_by_name["user_authorized_export"]
                ].__setitem__("public_by_default", True),
            ),
            (
                "rating-namespace",
                lambda document: document["fields"][rating_index].__setitem__(
                    "namespace", "provider_observation"
                ),
            ),
            (
                "rating-score",
                lambda document: document["fields"][rating_index].__setitem__(
                    "open_score_eligible", True
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                boundary = deepcopy(original)
                mutate(boundary)
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "policy_violation")

    def test_field_api_returns_immutable_auditable_fail_closed_decisions(self) -> None:
        from dataclasses import FrozenInstanceError

        from openfundscore.ant_fortune_boundary import (
            AccessMode,
            BoundaryConclusion,
            BoundaryUse,
            decide_ant_fortune_field,
        )

        decision = decide_ant_fortune_field(
            "subscription_fee",
            access_mode=AccessMode.UNAUTHENTICATED_OFFICIAL_PAGE,
            requested_uses=frozenset({BoundaryUse.CACHE, BoundaryUse.DISPLAY}),
            boundary_version="0.1.0",
        )
        self.assertEqual(
            decision.authorization_status,
            BoundaryConclusion.UNKNOWN_BLOCKED,
        )
        self.assertEqual(decision.reason_code, "field_authorization_missing")
        self.assertFalse(decision.publication_allowed)
        self.assertFalse(decision.affects_open_score)
        self.assertRegex(decision.resource_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            dict(decision.use_decisions),
            {"cache": "unknown_blocked", "display": "unknown_blocked"},
        )
        with self.assertRaises(FrozenInstanceError):
            decision.publication_allowed = True  # type: ignore[misc]

        rating = decide_ant_fortune_field(
            "platform_rating",
            access_mode="user_authorized_export",
            requested_uses=frozenset({BoundaryUse.DERIVED}),
            boundary_version="0.1.0",
        )
        self.assertEqual(rating.namespace, "external_ratings")
        self.assertEqual(rating.reason_code, "local_authorization_required")
        self.assertFalse(rating.affects_open_score)

    def test_cli_validates_resource_and_checks_a_field_decision(self) -> None:
        import io
        import json
        from contextlib import redirect_stdout

        from openfundscore.cli import main

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "platform-boundary",
                    "validate",
                    "--boundary-version",
                    "0.1.0",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("valid: ant_fortune@0.1.0", output.getvalue())

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "platform-boundary",
                    "check",
                    "subscription_fee",
                    "--access-mode",
                    "unauthenticated_official_page",
                    "--use",
                    "cache",
                    "--use",
                    "display",
                    "--boundary-version",
                    "0.1.0",
                ]
            )
        self.assertEqual(exit_code, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["authorization_status"], "unknown_blocked")
        self.assertEqual(document["reason_code"], "field_authorization_missing")
        self.assertFalse(document["ingestion_allowed"])
        self.assertFalse(document["cache_allowed"])
        self.assertFalse(document["derived_allowed"])
        self.assertFalse(document["display_allowed"])
        self.assertFalse(document["redistribution_allowed"])
        self.assertFalse(document["open_score_allowed"])
        self.assertFalse(document["automated_adapter_allowed"])
        self.assertFalse(document["publication_allowed"])
        self.assertFalse(document["affects_open_score"])

    def test_cli_rejects_duplicate_keys_and_non_finite_constants_without_echo(
        self,
    ) -> None:
        import io
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout
        from pathlib import Path

        from openfundscore.cli import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            for label, payload in (
                ("duplicate", '{"private-marker":1,"private-marker":2}'),
                ("nan", '{"private-marker":NaN}'),
                ("oversize", '{"private-marker":"' + ("x" * (1024 * 1024)) + '"}'),
            ):
                with self.subTest(label=label):
                    path = Path(temporary_directory) / f"{label}.json"
                    path.write_text(payload, encoding="utf-8")
                    output = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(stderr):
                        exit_code = main(
                            [
                                "platform-boundary",
                                "validate",
                                str(path),
                                "--boundary-version",
                                "0.1.0",
                            ]
                        )
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn(
                        "platform boundary operation failed", stderr.getvalue()
                    )
                    self.assertNotIn("private-marker", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_every_candidate_field_has_a_complete_fail_closed_matrix(self) -> None:
        from openfundscore.ant_fortune_boundary import load_ant_fortune_boundary

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        fields = {item["field_id"]: item for item in boundary["fields"]}
        per_fund_fields = {
            "fund_identifier",
            "share_class_identifier",
            "share_class_name",
            "subscription_fee",
            "redemption_fee_tiers",
            "sales_service_fee",
            "ongoing_fee",
            "management_fee",
            "custody_fee",
            "purchase_amount_limit",
            "subscription_availability",
            "redemption_availability",
            "sale_availability",
            "platform_rating",
        }
        self.assertEqual(set(fields), per_fund_fields | {"platform_brand_entry"})
        required = {
            "field_id",
            "definition",
            "value_type",
            "unit",
            "grain",
            "public_observation",
            "access_mode_status",
            "authorization_status",
            "official_source_url",
            "official_evidence_status",
            "evidence_retrieved_at",
            "evidence_reviewed_at",
            "terms_status",
            "terms_url",
            "robots_status",
            "robots_url",
            "robots_is_authorization",
            "rate_limit_status",
            "rate_limit_value",
            "cache_status",
            "cache_ttl_seconds",
            "retention_status",
            "retention_value",
            "derived_status",
            "display_status",
            "redistribution_status",
            "attribution_status",
            "provenance",
            "review_status",
            "pending_evidence",
            "reevaluation_triggers",
            "namespace",
            "open_score_eligible",
            "automated_ingestion_allowed",
        }
        for field_id in per_fund_fields:
            with self.subTest(field_id=field_id):
                field = fields[field_id]
                self.assertEqual(set(field), required)
                self.assertEqual(field["grain"], "per_fund_share_class")
                self.assertEqual(field["authorization_status"], "unknown_blocked")
                self.assertEqual(
                    field["access_mode_status"], "no_authorized_access_mode"
                )
                self.assertEqual(field["official_source_url"], "not_identified")
                self.assertEqual(field["official_evidence_status"], "not_identified")
                self.assertEqual(field["evidence_retrieved_at"], "not_retrieved")
                self.assertEqual(field["terms_status"], "unverified_unknown_blocked")
                self.assertEqual(field["terms_url"], "not_identified")
                self.assertEqual(field["robots_status"], "unverified_unavailable")
                self.assertEqual(field["robots_url"], "not_identified")
                self.assertFalse(field["robots_is_authorization"])
                self.assertEqual(
                    field["rate_limit_status"], "unverified_unknown_blocked"
                )
                self.assertEqual(field["rate_limit_value"], "not_established")
                self.assertEqual(field["cache_status"], "unknown_blocked")
                self.assertEqual(field["cache_ttl_seconds"], "not_established")
                self.assertEqual(field["retention_status"], "unknown_blocked")
                self.assertEqual(field["retention_value"], "not_established")
                self.assertEqual(field["derived_status"], "unknown_blocked")
                self.assertEqual(field["display_status"], "unknown_blocked")
                self.assertEqual(field["redistribution_status"], "unknown_blocked")
                self.assertEqual(
                    field["attribution_status"], "unverified_unknown_blocked"
                )
                self.assertEqual(field["review_status"], "pending_evidence")
                self.assertFalse(field["open_score_eligible"])
                self.assertFalse(field["automated_ingestion_allowed"])
                self.assertTrue(field["pending_evidence"])
                self.assertTrue(field["reevaluation_triggers"])

    def test_validator_rejects_any_matrix_rights_escalation(self) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        field_index = next(
            index
            for index, item in enumerate(original["fields"])
            if item["field_id"] == "subscription_fee"
        )
        mutations = {
            "authorization_status": "authorized",
            "cache_status": "allowed",
            "cache_ttl_seconds": 3600,
            "retention_status": "allowed",
            "retention_value": "30_days",
            "derived_status": "allowed",
            "display_status": "allowed",
            "redistribution_status": "allowed",
            "attribution_status": "not_required",
            "open_score_eligible": True,
            "automated_ingestion_allowed": True,
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                boundary = deepcopy(original)
                boundary["fields"][field_index][key] = value
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "policy_violation")

    def test_validator_rejects_invalid_version_digest_timestamp_and_source_host(
        self,
    ) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        cases = (
            (
                "version",
                lambda d: d.__setitem__("boundary_version", "latest"),
                "0" * 64,
            ),
            (
                "timestamp",
                lambda d: d.__setitem__("reviewed_at", "2026-08-22"),
                "0" * 64,
            ),
            (
                "host",
                lambda d: d["sources"][0].__setitem__("host", "open.alipay.com"),
                "0" * 64,
            ),
            ("digest", lambda d: None, "not-a-digest"),
        )
        for label, mutate, digest in cases:
            with self.subTest(label=label):
                boundary = deepcopy(original)
                mutate(boundary)
                with self.assertRaises(BoundaryValidationError):
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256=digest,
                    )

    def test_validator_rejects_impossible_calendar_timestamps(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        impossible = "2026-02-31T00:22:00Z"
        boundary["reviewed_at"] = impossible
        boundary["as_of"] = impossible
        for source in boundary["sources"]:
            source["reviewed_at"] = impossible
        for field in boundary["fields"]:
            field["evidence_reviewed_at"] = impossible

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="0.1.0",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid_timestamp")
        self.assertEqual(raised.exception.path, "$.reviewed_at")
        self.assertNotIn(impossible, str(raised.exception))

    def test_validator_rejects_unpublished_boundary_versions(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        boundary = load_ant_fortune_boundary(boundary_version="0.1.0")
        boundary["boundary_version"] = "9.9.9"

        with self.assertRaises(BoundaryValidationError) as raised:
            validate_ant_fortune_boundary(
                boundary,
                expected_version="9.9.9",
                resource_sha256="0" * 64,
            )

        self.assertEqual(raised.exception.code, "invalid_selector")
        self.assertEqual(raised.exception.path, "$expected_version")

    def test_validator_rejects_changed_reassessment_or_unresolved_inventory(
        self,
    ) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        for key in ("reassessment_conditions", "unresolved_items"):
            with self.subTest(key=key):
                boundary = deepcopy(original)
                boundary[key][0] = "private-marker"
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "policy_violation")
                self.assertEqual(raised.exception.path, f"$.{key}")
                self.assertNotIn("private-marker", str(raised.exception))

    def test_validator_rejects_changed_source_or_marketing_audit_inventory(
        self,
    ) -> None:
        from copy import deepcopy

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        original = load_ant_fortune_boundary(boundary_version="0.1.0")
        marketing_index = next(
            index
            for index, field in enumerate(original["fields"])
            if field["field_id"] == "platform_brand_entry"
        )
        mutations = (
            lambda document: document["sources"][0].__setitem__(
                "observation", "Changed but visible observation."
            ),
            lambda document: document["fields"][marketing_index].__setitem__(
                "pending_evidence", ["official_terms"]
            ),
            lambda document: document["fields"][marketing_index].__setitem__(
                "reevaluation_triggers", ["official_terms_or_robots_change"]
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                boundary = deepcopy(original)
                mutate(boundary)
                with self.assertRaises(BoundaryValidationError) as raised:
                    validate_ant_fortune_boundary(
                        boundary,
                        expected_version="0.1.0",
                        resource_sha256="0" * 64,
                    )
                self.assertEqual(raised.exception.code, "policy_violation")

    def test_validator_canonicalizes_sequences_and_does_not_retain_input(self) -> None:
        from collections.abc import Mapping, Sequence

        from openfundscore.ant_fortune_boundary import (
            BoundaryValidationError,
            load_ant_fortune_boundary,
            validate_ant_fortune_boundary,
        )

        document = load_ant_fortune_boundary(boundary_version="0.1.0")
        decision = validate_ant_fortune_boundary(
            document,
            expected_version="0.1.0",
            resource_sha256="0" * 64,
        )
        document["fields"][0]["definition"] = "mutated"
        self.assertNotEqual(decision.fields[0].definition, "mutated")

        class HostileSequence(Sequence[object]):
            def __getitem__(self, index: int) -> object:
                raise RuntimeError("private-marker")

            def __len__(self) -> int:
                raise RuntimeError("private-marker")

        class HostileMapping(Mapping[str, object]):
            def __getitem__(self, key: str) -> object:
                raise RuntimeError("private-marker")

            def __iter__(self):
                raise RuntimeError("private-marker")

            def __len__(self) -> int:
                raise RuntimeError("private-marker")

        for value in (HostileSequence(), HostileMapping()):
            with (
                self.subTest(kind=type(value).__name__),
                self.assertRaises(BoundaryValidationError) as raised,
            ):
                validate_ant_fortune_boundary(
                    value,
                    expected_version="0.1.0",
                    resource_sha256="0" * 64,
                )
            self.assertNotIn("private-marker", str(raised.exception))

    def test_decision_rejects_automated_and_core_score_paths(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            AccessMode,
            BoundaryUse,
            decide_ant_fortune_field,
        )

        for access_mode in (
            AccessMode.LOGIN,
            AccessMode.COOKIE,
            AccessMode.SESSION,
            AccessMode.AUTOMATED,
            AccessMode.LOGIN_SESSION,
        ):
            with self.subTest(access_mode=access_mode):
                decision = decide_ant_fortune_field(
                    "subscription_fee",
                    access_mode=access_mode,
                    requested_uses=frozenset({BoundaryUse.INGESTION}),
                    boundary_version="0.1.0",
                )
                self.assertEqual(decision.reason_code, "access_mode_prohibited")
                self.assertFalse(any(allowed for _, allowed in decision.allowed_uses))

        rating = decide_ant_fortune_field(
            "platform_rating",
            access_mode=AccessMode.UNAUTHENTICATED_OFFICIAL_PAGE,
            requested_uses=frozenset(
                {BoundaryUse.OPEN_SCORE, BoundaryUse.AUTOMATED_ADAPTER}
            ),
            boundary_version="0.1.0",
        )
        self.assertEqual(rating.namespace, "external_ratings")
        self.assertEqual(rating.reason_code, "external_rating_core_score_prohibited")
        self.assertFalse(rating.open_score_allowed)
        self.assertFalse(rating.automated_adapter_allowed)

    def test_every_field_and_access_mode_decision_is_fully_false(self) -> None:
        from openfundscore.ant_fortune_boundary import (
            AccessMode,
            BoundaryUse,
            decide_ant_fortune_field,
            load_ant_fortune_boundary,
        )

        field_ids = tuple(
            field["field_id"]
            for field in load_ant_fortune_boundary(boundary_version="0.1.0")["fields"]
        )
        requested_uses = frozenset(BoundaryUse)

        decisions = [
            decide_ant_fortune_field(
                field_id,
                access_mode=AccessMode.UNAUTHENTICATED_OFFICIAL_PAGE,
                requested_uses=requested_uses,
                boundary_version="0.1.0",
            )
            for field_id in field_ids
        ]
        decisions.extend(
            decide_ant_fortune_field(
                "subscription_fee",
                access_mode=access_mode,
                requested_uses=requested_uses,
                boundary_version="0.1.0",
            )
            for access_mode in AccessMode
        )

        for decision in decisions:
            with self.subTest(field=decision.field_id, access=decision.access_mode):
                self.assertFalse(any(allowed for _, allowed in decision.allowed_uses))
                self.assertFalse(decision.ingestion_allowed)
                self.assertFalse(decision.cache_allowed)
                self.assertFalse(decision.derived_allowed)
                self.assertFalse(decision.display_allowed)
                self.assertFalse(decision.redistribution_allowed)
                self.assertFalse(decision.publication_allowed)
                self.assertFalse(decision.open_score_allowed)
                self.assertFalse(decision.automated_adapter_allowed)
                self.assertFalse(decision.affects_open_score)

    def test_package_root_lazily_exports_boundary_api(self) -> None:
        import openfundscore

        self.assertTrue(callable(openfundscore.load_ant_fortune_boundary))
        self.assertTrue(callable(openfundscore.validate_ant_fortune_boundary))
        self.assertTrue(callable(openfundscore.decide_ant_fortune_field))
        self.assertTrue(issubclass(openfundscore.BoundaryValidationError, ValueError))
        self.assertEqual(openfundscore.AccessMode.AUTOMATED, "automated")
        self.assertEqual(openfundscore.BoundaryUse.OPEN_SCORE, "open_score")


if __name__ == "__main__":
    unittest.main()
