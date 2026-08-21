from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from openfundscore.cli import main
from openfundscore.resources import ResourceError, resolve_resource
from openfundscore.score_config import ConfigValidationError
from openfundscore.strategy_mapping import (
    StrategyMappingError,
    load_packaged_strategy_mapping,
    load_strategy_mapping,
    map_strategy_family,
    validate_strategy_mapping,
)

EXPECTED_FAMILY_BUCKETS = {
    "market_neutral": "market_neutral",
    "long_short_equity": "long_short_equity",
    "absolute_return": "absolute_return_multi_strategy",
    "derivatives_heavy": "managed_futures_derivatives",
    "other_complex_alternative": "other_complex_alternative",
}


def packaged_mapping() -> dict:
    return resolve_resource(
        resource_type="strategy-mapping",
        name="complex_alternatives",
        version="0.1.0",
    ).load_json()


class StrategyMappingHardeningTests(unittest.TestCase):
    def test_custom_loader_is_bounded_strict_and_redacted(self) -> None:
        marker = "TOP_SECRET_MAPPING_SENTINEL"
        with tempfile.TemporaryDirectory(prefix=f"{marker}-") as directory:
            root = Path(directory)
            cases = {
                "oversized.json": b"{" + b" " * (1024 * 1024 + 1) + b"}",
                "duplicate.json": (b'{"mapping_id":"first","mapping_id":"second"}'),
                "nonfinite.json": b'{"value": NaN}',
                "deep.json": (("[" * 2000) + "0" + ("]" * 2000)).encode(),
            }
            for filename, payload in cases.items():
                with self.subTest(filename=filename):
                    path = root / filename
                    path.write_bytes(payload)
                    with self.assertRaises(StrategyMappingError) as raised:
                        load_strategy_mapping(path)
                    rendered = str(raised.exception)
                    self.assertNotIn(marker, rendered)
                    self.assertNotIn(str(path), rendered)
                    self.assertNotIn("Traceback", rendered)
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertIsNone(raised.exception.__context__)

    def test_unknown_fields_and_dynamic_identifiers_are_not_echoed(self) -> None:
        marker = "top_secret_field"
        document = packaged_mapping()
        document[marker] = True
        with self.assertRaises(StrategyMappingError) as raised:
            validate_strategy_mapping(document)
        self.assertNotIn(marker, str(raised.exception))

        marker = "top_secret_bucket"
        document = packaged_mapping()
        document["peer_buckets"][marker] = deepcopy(
            document["peer_buckets"]["market_neutral"]
        )
        with self.assertRaises(StrategyMappingError) as raised:
            validate_strategy_mapping(document)
        self.assertNotIn(marker, str(raised.exception))

    def test_contract_bounds_strings_collections_and_admission_numbers(self) -> None:
        cases: list[dict] = []

        huge_label = packaged_mapping()
        huge_label["peer_buckets"]["market_neutral"]["label"] = "x" * 4097
        cases.append(huge_label)

        huge_list = packaged_mapping()
        huge_list["peer_buckets"]["market_neutral"]["included_strategies"] = [
            f"strategy_{index}" for index in range(257)
        ]
        cases.append(huge_list)

        huge_integer = packaged_mapping()
        huge_integer["peer_buckets"]["market_neutral"]["admission_requirements"][
            "min_peer_count"
        ] = 10**100
        cases.append(huge_integer)

        too_many_reasons = packaged_mapping()
        too_many_reasons["unrated_reasons"].update(
            {f"reason_{index}": "synthetic" for index in range(65)}
        )
        cases.append(too_many_reasons)

        for index, document in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(StrategyMappingError):
                validate_strategy_mapping(document)

    def test_v0_requires_exact_families_and_distinct_designated_buckets(self) -> None:
        cases: list[dict] = []

        missing = packaged_mapping()
        del missing["strategy_families"]["market_neutral"]
        cases.append(missing)

        collapsed = packaged_mapping()
        collapsed["strategy_families"]["long_short_equity"]["peer_bucket"] = (
            "market_neutral"
        )
        cases.append(collapsed)

        extra_family = packaged_mapping()
        extra_family["strategy_families"]["new_family"] = {
            "peer_bucket": "market_neutral"
        }
        cases.append(extra_family)

        extra_bucket = packaged_mapping()
        extra_bucket["peer_buckets"]["new_bucket"] = deepcopy(
            extra_bucket["peer_buckets"]["market_neutral"]
        )
        cases.append(extra_bucket)

        for index, document in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(StrategyMappingError):
                validate_strategy_mapping(document)

        valid = packaged_mapping()
        validate_strategy_mapping(valid)
        self.assertEqual(
            EXPECTED_FAMILY_BUCKETS,
            {
                family: entry["peer_bucket"]
                for family, entry in valid["strategy_families"].items()
            },
        )

    def test_packaged_resource_and_scoring_config_failures_are_normalized(self) -> None:
        marker = "PRIVATE_RESOURCE_SENTINEL"
        resource_error = ResourceError("resource_integrity", marker, marker)
        with patch(
            "openfundscore.strategy_mapping._resolve_packaged_mapping"
        ) as resolver:
            resolver.return_value.load_json.side_effect = resource_error
            for operation in (
                lambda: load_packaged_strategy_mapping(mapping_version="0.1.0"),
                lambda: map_strategy_family("market_neutral", mapping_version="0.1.0"),
            ):
                with (
                    self.subTest(operation=operation),
                    self.assertRaises(StrategyMappingError) as raised,
                ):
                    operation()
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

        with (
            patch(
                "openfundscore.strategy_mapping.validate_score_config",
                side_effect=ConfigValidationError(marker),
            ),
            self.assertRaises(StrategyMappingError) as raised,
        ):
            validate_strategy_mapping(packaged_mapping())
        self.assertNotIn(marker, str(raised.exception))

        with (
            patch(
                "openfundscore.strategy_mapping.validate_score_config",
                side_effect=RuntimeError(marker),
            ),
            self.assertRaises(StrategyMappingError) as raised,
        ):
            validate_strategy_mapping(packaged_mapping())
        self.assertNotIn(marker, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_cli_normalizes_resource_errors_without_traceback_or_echo(self) -> None:
        marker = "PRIVATE_RESOURCE_SENTINEL"
        with (
            patch(
                "openfundscore.cli.map_strategy_family",
                side_effect=ResourceError("resource_integrity", marker, marker),
            ),
            patch("sys.stderr") as stderr,
        ):
            exit_code = main(
                ["strategy-map", "market_neutral", "--mapping-version", "0.1.0"]
            )
        self.assertEqual(2, exit_code)
        rendered = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertNotIn(marker, rendered)
        self.assertNotIn("Traceback", rendered)


if __name__ == "__main__":
    unittest.main()
