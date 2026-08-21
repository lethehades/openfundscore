from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import openfundscore
from openfundscore.resources import resolve_resource
from openfundscore.score_config import _CATEGORY_PROFILE_IDS
from openfundscore.strategy_mapping import (
    UNRATED_PROFILE,
    MappingDecision,
    StrategyMappingError,
    load_packaged_strategy_mapping,
    load_strategy_mapping,
    map_strategy_family,
    validate_strategy_mapping,
)

NAMED_FAMILIES = {
    "market_neutral": "market_neutral",
    "long_short_equity": "long_short_equity",
    "absolute_return": "absolute_return_multi_strategy",
    "derivatives_heavy": "managed_futures_derivatives",
}
CATCH_ALL_FAMILY = "other_complex_alternative"
CATCH_ALL_BUCKET = "other_complex_alternative"


def _packaged_mapping() -> dict:
    return resolve_resource(
        resource_type="strategy-mapping",
        name="complex_alternatives",
        version="0.1.0",
    ).load_json()


class PackagedStrategyMappingTests(unittest.TestCase):
    def test_mapping_version_is_explicit_and_custom_documents_cannot_authorize(
        self,
    ) -> None:
        signature = inspect.signature(map_strategy_family)
        self.assertIn("mapping_version", signature.parameters)
        self.assertNotIn("mapping", signature.parameters)
        self.assertIs(
            signature.parameters["mapping_version"].default, inspect.Parameter.empty
        )

        with self.assertRaises(TypeError):
            map_strategy_family("market_neutral")  # type: ignore[call-arg]
        with self.assertRaises(StrategyMappingError):
            map_strategy_family("market_neutral", mapping_version="0.1.1")

    def test_decision_carries_the_verified_packaged_resource_digest(self) -> None:
        resource = resolve_resource(
            resource_type="strategy-mapping",
            name="complex_alternatives",
            version="0.1.0",
        )
        decision = map_strategy_family("market_neutral", mapping_version="0.1.0")
        self.assertEqual(resource.info.sha256, decision.resource_sha256)

    def test_packaged_mapping_resource_resolves_with_verified_digest(self) -> None:
        resource = resolve_resource(
            resource_type="strategy-mapping",
            name="complex_alternatives",
            version="0.1.0",
        )

        payload = resource.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), resource.info.sha256)
        self.assertEqual(
            resource.info.uri,
            "openfundscore://strategy-mapping/complex_alternatives/0.1.0",
        )
        self.assertEqual(resource.info.media_type, "application/json")

    def test_packaged_mapping_document_passes_the_public_contract(self) -> None:
        document = _packaged_mapping()
        validate_strategy_mapping(document)
        self.assertEqual("complex_alternatives", document["mapping_id"])
        self.assertEqual("0.1.0", document["mapping_version"])
        self.assertEqual("research-preview", document["status"])

    def test_load_packaged_strategy_mapping_returns_a_validated_document(self) -> None:
        document = load_packaged_strategy_mapping(mapping_version="0.1.0")
        self.assertEqual(document, _packaged_mapping())

    def test_every_named_complex_family_maps_to_its_own_peer_bucket(self) -> None:
        buckets = set()
        for family, expected_bucket in NAMED_FAMILIES.items():
            with self.subTest(family=family):
                decision = map_strategy_family(family, mapping_version="0.1.0")
                self.assertIsInstance(decision, MappingDecision)
                self.assertEqual(family, decision.strategy_family)
                self.assertEqual(expected_bucket, decision.peer_bucket)
                buckets.add(decision.peer_bucket)

        self.assertEqual(
            len(NAMED_FAMILIES),
            len(buckets),
            "named complex families must never share one diluted bucket",
        )

    def test_all_complex_buckets_are_explicitly_unrated_in_0_1_0(self) -> None:
        for family in (*NAMED_FAMILIES, CATCH_ALL_FAMILY):
            with self.subTest(family=family):
                decision = map_strategy_family(family, mapping_version="0.1.0")
                self.assertFalse(decision.is_rated)
                self.assertEqual(UNRATED_PROFILE, decision.score_profile)
                self.assertIsNotNone(decision.unrated_reason)
                self.assertNotEqual("", decision.unrated_reason.strip())

    def test_unrated_never_disguises_itself_as_a_category_profile(self) -> None:
        self.assertNotIn(UNRATED_PROFILE, _CATEGORY_PROFILE_IDS)
        for family in (*NAMED_FAMILIES, CATCH_ALL_FAMILY):
            with self.subTest(family=family):
                decision = map_strategy_family(family, mapping_version="0.1.0")
                self.assertNotIn(decision.score_profile, _CATEGORY_PROFILE_IDS)

    def test_named_complex_families_cite_insufficient_comparable_samples(self) -> None:
        for family in NAMED_FAMILIES:
            with self.subTest(family=family):
                decision = map_strategy_family(family, mapping_version="0.1.0")
                self.assertEqual(
                    "insufficient_comparable_sample", decision.unrated_reason
                )

    def test_catch_all_family_is_explicitly_unrated_without_a_defined_profile(
        self,
    ) -> None:
        decision = map_strategy_family(CATCH_ALL_FAMILY, mapping_version="0.1.0")
        self.assertEqual(CATCH_ALL_BUCKET, decision.peer_bucket)
        self.assertEqual(UNRATED_PROFILE, decision.score_profile)
        self.assertEqual("undefined_complex_strategy", decision.unrated_reason)

    def test_decisions_carry_the_mapping_identity(self) -> None:
        decision = map_strategy_family("market_neutral", mapping_version="0.1.0")
        self.assertEqual("complex_alternatives", decision.mapping_id)
        self.assertEqual("0.1.0", decision.mapping_version)

    def test_custom_document_cannot_change_packaged_scoring_decision(self) -> None:
        promoted = _packaged_mapping()
        bucket = promoted["peer_buckets"]["market_neutral"]
        bucket["score_profile"] = "bond"
        del bucket["unrated_reason"]
        validate_strategy_mapping(promoted)

        decision = map_strategy_family("market_neutral", mapping_version="0.1.0")

        self.assertFalse(decision.is_rated)
        self.assertEqual(UNRATED_PROFILE, decision.score_profile)
        self.assertEqual("insufficient_comparable_sample", decision.unrated_reason)

    def test_unknown_family_fails_closed_without_any_default_mapping(self) -> None:
        for family in (
            "equity_like",
            "market-neutral",
            "MARKET_NEUTRAL",
            "hedge_fund",
            "structured_product",
        ):
            with self.subTest(family=family), self.assertRaises(StrategyMappingError):
                map_strategy_family(family, mapping_version="0.1.0")

    def test_invalid_family_values_fail_closed(self) -> None:
        for family in ("", "   ", "../market_neutral", "市场 neutral"):
            with self.subTest(family=family), self.assertRaises(StrategyMappingError):
                map_strategy_family(family, mapping_version="0.1.0")

    def test_package_level_lazy_exports_resolve(self) -> None:
        self.assertIs(openfundscore.map_strategy_family, map_strategy_family)
        self.assertIs(openfundscore.StrategyMappingError, StrategyMappingError)
        self.assertIs(openfundscore.MappingDecision, MappingDecision)


class StrategyMappingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = _packaged_mapping()

    def test_identity_fields_are_exact(self) -> None:
        for field, value in (
            ("mapping_id", "renamed"),
            ("mapping_version", "0.1.1"),
        ):
            with self.subTest(field=field):
                invalid = deepcopy(self.base)
                invalid[field] = value
                with self.assertRaisesRegex(StrategyMappingError, field):
                    validate_strategy_mapping(invalid)

        for field in ("mapping_id", "mapping_version", "status"):
            with self.subTest(field=field, case="missing"):
                invalid = deepcopy(self.base)
                del invalid[field]
                with self.assertRaisesRegex(StrategyMappingError, field):
                    validate_strategy_mapping(invalid)

    def test_status_must_be_research_preview(self) -> None:
        invalid = deepcopy(self.base)
        invalid["status"] = "production"
        with self.assertRaisesRegex(StrategyMappingError, "status"):
            validate_strategy_mapping(invalid)

    def test_scoring_config_selector_must_reference_the_packaged_config(self) -> None:
        cases = []
        for field, value in (
            ("type", "schema"),
            ("name", "other-model"),
            ("version", "0.1.1"),
        ):
            invalid = deepcopy(self.base)
            invalid["scoring_config"][field] = value
            cases.append((field, invalid))

        missing = deepcopy(self.base)
        del missing["scoring_config"]["version"]
        cases.append(("missing version", missing))

        for label, invalid in cases:
            with (
                self.subTest(case=label),
                self.assertRaisesRegex(StrategyMappingError, "scoring_config"),
            ):
                validate_strategy_mapping(invalid)

    def test_unknown_fields_are_rejected_at_every_boundary(self) -> None:
        cases = []

        top_level = deepcopy(self.base)
        top_level["unexpected"] = True
        cases.append(("top-level", top_level))

        selector = deepcopy(self.base)
        selector["scoring_config"]["unexpected"] = True
        cases.append(("scoring_config", selector))

        bucket = deepcopy(self.base)
        bucket["peer_buckets"]["market_neutral"]["unexpected"] = True
        cases.append(("bucket", bucket))

        admission = deepcopy(self.base)
        admission["peer_buckets"]["market_neutral"]["admission_requirements"][
            "unexpected"
        ] = True
        cases.append(("admission", admission))

        family = deepcopy(self.base)
        family["strategy_families"]["market_neutral"]["unexpected"] = True
        cases.append(("family", family))

        for label, invalid in cases:
            with (
                self.subTest(case=label),
                self.assertRaisesRegex(StrategyMappingError, "unknown field"),
            ):
                validate_strategy_mapping(invalid)

    def test_rated_buckets_must_reference_a_real_category_profile(self) -> None:
        invalid = deepcopy(self.base)
        bucket = invalid["peer_buckets"]["market_neutral"]
        bucket["score_profile"] = "equity_like"
        del bucket["unrated_reason"]
        with self.assertRaisesRegex(StrategyMappingError, "score_profile"):
            validate_strategy_mapping(invalid)

    def test_unrated_buckets_require_a_defined_reason_and_rated_forbid_one(
        self,
    ) -> None:
        missing_reason = deepcopy(self.base)
        del missing_reason["peer_buckets"]["market_neutral"]["unrated_reason"]
        with self.assertRaisesRegex(StrategyMappingError, "unrated_reason"):
            validate_strategy_mapping(missing_reason)

        undefined_reason = deepcopy(self.base)
        undefined_reason["peer_buckets"]["market_neutral"]["unrated_reason"] = "made_up"
        with self.assertRaisesRegex(StrategyMappingError, "unrated_reason"):
            validate_strategy_mapping(undefined_reason)

        rated_with_reason = deepcopy(self.base)
        bucket = rated_with_reason["peer_buckets"]["market_neutral"]
        bucket["score_profile"] = "bond"
        with self.assertRaisesRegex(StrategyMappingError, "unrated_reason"):
            validate_strategy_mapping(rated_with_reason)

    def test_every_defined_reason_must_be_used_by_a_bucket(self) -> None:
        invalid = deepcopy(self.base)
        invalid["unrated_reasons"]["dead_reason"] = "never used by any bucket"
        with self.assertRaisesRegex(StrategyMappingError, "unrated_reasons"):
            validate_strategy_mapping(invalid)

    def test_buckets_and_families_must_be_non_empty_objects(self) -> None:
        for field in ("unrated_reasons", "peer_buckets", "strategy_families"):
            with self.subTest(field=field):
                invalid = deepcopy(self.base)
                invalid[field] = {}
                with self.assertRaisesRegex(StrategyMappingError, field):
                    validate_strategy_mapping(invalid)

    def test_bucket_labels_and_included_strategies_are_non_empty(self) -> None:
        empty_label = deepcopy(self.base)
        empty_label["peer_buckets"]["market_neutral"]["label"] = ""
        with self.assertRaisesRegex(StrategyMappingError, "label"):
            validate_strategy_mapping(empty_label)

        empty_strategies = deepcopy(self.base)
        empty_strategies["peer_buckets"]["market_neutral"]["included_strategies"] = []
        with self.assertRaisesRegex(StrategyMappingError, "included_strategies"):
            validate_strategy_mapping(empty_strategies)

        duplicate_strategies = deepcopy(self.base)
        bucket = duplicate_strategies["peer_buckets"]["market_neutral"]
        bucket["included_strategies"] = [
            bucket["included_strategies"][0],
            bucket["included_strategies"][0],
        ]
        with self.assertRaisesRegex(StrategyMappingError, "included_strategies"):
            validate_strategy_mapping(duplicate_strategies)

    def test_admission_requirements_are_bounded(self) -> None:
        def mutated(mutate) -> dict:
            document = deepcopy(self.base)
            mutate(document["peer_buckets"]["market_neutral"]["admission_requirements"])
            return document

        cases = [
            (
                "bool peer count",
                mutated(lambda a: a.__setitem__("min_peer_count", True)),
            ),
            ("tiny peer count", mutated(lambda a: a.__setitem__("min_peer_count", 1))),
            (
                "bool months",
                mutated(lambda a: a.__setitem__("min_track_months", False)),
            ),
            ("zero months", mutated(lambda a: a.__setitem__("min_track_months", 0))),
            (
                "empty disclosures",
                mutated(lambda a: a.__setitem__("required_disclosures", [])),
            ),
            (
                "duplicate disclosures",
                mutated(
                    lambda a: a.__setitem__(
                        "required_disclosures",
                        ["portfolio_holdings", "portfolio_holdings"],
                    )
                ),
            ),
        ]
        for label, invalid in cases:
            with (
                self.subTest(case=label),
                self.assertRaisesRegex(StrategyMappingError, "admission_requirements"),
            ):
                validate_strategy_mapping(invalid)

    def test_families_must_reference_an_existing_bucket(self) -> None:
        invalid = deepcopy(self.base)
        invalid["strategy_families"]["market_neutral"]["peer_bucket"] = "ghost_bucket"
        with self.assertRaisesRegex(StrategyMappingError, "peer_bucket"):
            validate_strategy_mapping(invalid)

    def test_identifiers_must_use_the_snake_case_ascii_profile(self) -> None:
        invalid = deepcopy(self.base)
        bucket = invalid["peer_buckets"].pop("market_neutral")
        invalid["peer_buckets"]["Market-Neutral"] = bucket
        with self.assertRaisesRegex(StrategyMappingError, "peer_buckets"):
            validate_strategy_mapping(invalid)

    def test_load_wraps_all_file_and_text_decoding_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            undecodable = root / "undecodable.json"
            undecodable.write_bytes(b"\xff")
            not_an_object = root / "array.json"
            not_an_object.write_text("[]", encoding="utf-8")

            with (
                self.subTest(error="directory"),
                self.assertRaises(StrategyMappingError),
            ):
                load_strategy_mapping(root)

            with self.subTest(error="unicode"), self.assertRaises(StrategyMappingError):
                load_strategy_mapping(undecodable)

            with (
                self.subTest(error="non-object"),
                self.assertRaises(StrategyMappingError),
            ):
                load_strategy_mapping(not_an_object)

        for error in (PermissionError("denied"), OSError("device failure")):
            with self.subTest(error=type(error).__name__):
                with (
                    patch(
                        "openfundscore.strategy_mapping.Path.open", side_effect=error
                    ) as mocked_open,
                    self.assertRaises(StrategyMappingError),
                ):
                    load_strategy_mapping("mapping.json")
                mocked_open.assert_called_once_with("rb")


class StrategyMappingCliTests(unittest.TestCase):
    def test_validate_mapping_reports_bucket_and_family_counts(self) -> None:
        from openfundscore.cli import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            mapping_path = Path(temporary_directory) / "mapping.json"
            mapping_path.write_text(json.dumps(_packaged_mapping()), encoding="utf-8")
            with patch("sys.stdout") as stdout:
                exit_code = main(["validate-mapping", str(mapping_path)])

        self.assertEqual(0, exit_code)
        rendered = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("valid:", rendered)
        self.assertIn("peer buckets", rendered)
        self.assertIn("strategy families", rendered)

    def test_validate_mapping_failures_return_2_without_traceback(self) -> None:
        from openfundscore.cli import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            invalid = root / "invalid.json"
            document = _packaged_mapping()
            document["status"] = "production"
            invalid.write_text(json.dumps(document), encoding="utf-8")
            missing = root / "missing.json"

            for path in (invalid, missing):
                with self.subTest(path=path.name):
                    with patch("sys.stderr"):
                        exit_code = main(["validate-mapping", str(path)])
                    self.assertEqual(2, exit_code)

    def test_strategy_map_emits_the_explicit_unrated_decision_as_json(self) -> None:
        from openfundscore.cli import main

        with patch("sys.stdout") as stdout:
            exit_code = main(
                [
                    "strategy-map",
                    "derivatives_heavy",
                    "--mapping-version",
                    "0.1.0",
                ]
            )

        self.assertEqual(0, exit_code)
        rendered = "".join(call.args[0] for call in stdout.write.call_args_list)
        decision = json.loads(rendered)
        self.assertEqual("derivatives_heavy", decision["strategy_family"])
        self.assertEqual("managed_futures_derivatives", decision["peer_bucket"])
        self.assertEqual("unrated", decision["score_profile"])
        self.assertEqual("insufficient_comparable_sample", decision["unrated_reason"])
        self.assertFalse(decision["is_rated"])

    def test_strategy_map_unknown_family_returns_2_without_traceback(self) -> None:
        from openfundscore.cli import main

        with patch("sys.stderr"):
            exit_code = main(
                ["strategy-map", "hedge_fund", "--mapping-version", "0.1.0"]
            )
        self.assertEqual(2, exit_code)


if __name__ == "__main__":
    unittest.main()
