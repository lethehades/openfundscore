from __future__ import annotations

import unittest
from datetime import UTC, datetime

from openfundscore.canonical import (
    FundStrategy,
    HoldingSnapshot,
    ManagerTenure,
    ShareClass,
)
from openfundscore.storage import CanonicalStore


class CanonicalFixtureTests(unittest.TestCase):
    def test_synthetic_fixture_covers_lifecycle_dedup_and_round_trip(self) -> None:
        from openfundscore.fixtures import synthetic_canonical_records

        fetched_at = datetime(2026, 3, 1, tzinfo=UTC)
        records = synthetic_canonical_records(fetched_at=fetched_at)
        strategies = tuple(item for item in records if isinstance(item, FundStrategy))
        share_classes = tuple(item for item in records if isinstance(item, ShareClass))
        tenures = tuple(item for item in records if isinstance(item, ManagerTenure))
        snapshots = tuple(item for item in records if isinstance(item, HoldingSnapshot))

        alpha_classes = tuple(
            item
            for item in share_classes
            if item.fund_strategy_id == "ofs:fund_strategy:alpha"
        )
        self.assertEqual({item.class_code for item in alpha_classes}, {"A", "C", "E", "I"})
        self.assertEqual(
            {item.fund_strategy_id for item in alpha_classes},
            {"ofs:fund_strategy:alpha"},
        )
        self.assertEqual(
            {item.status for item in strategies},
            {"active", "closed", "merged", "transformed"},
        )
        alpha = next(
            item
            for item in strategies
            if item.fund_strategy_id == "ofs:fund_strategy:alpha"
        )
        self.assertEqual(alpha.primary_benchmark_id, "ofs:benchmark:alpha")
        self.assertTrue(
            all(
                item.fund_strategy_id != item.tenure_id
                and item.fund_strategy_id == "ofs:fund_strategy:alpha"
                for item in tenures
            )
        )
        self.assertTrue(
            all(item.fund_strategy_id == "ofs:fund_strategy:alpha" for item in snapshots)
        )
        self.assertTrue(all(item.fee_schedule.is_basis_point_encoded for item in alpha_classes))

        with CanonicalStore(":memory:") as first:
            for record in records:
                first.put(record)
            closed_before = first.query_versions(
                "fund_strategy",
                "ofs:fund_strategy:closed",
                effective_at=datetime(2024, 12, 31, tzinfo=UTC),
                knowledge_cutoff=fetched_at,
            )
            closed_after = first.query_versions(
                "fund_strategy",
                "ofs:fund_strategy:closed",
                effective_at=datetime(2025, 1, 1, tzinfo=UTC),
                knowledge_cutoff=fetched_at,
            )
            first_dump = first.dump_json()
        with CanonicalStore(":memory:") as second:
            second.load_json(first_dump)
            second_dump = second.dump_json()

        self.assertEqual(tuple(item.status for item in closed_before), ("active",))
        self.assertEqual(tuple(item.status for item in closed_after), ("closed",))
        self.assertEqual(second_dump, first_dump)


if __name__ == "__main__":
    unittest.main()
