from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from openfundscore.canonical import ExternalIdentifier, FundStrategy, ShareClass


class CanonicalStoreTests(unittest.TestCase):
    def _metadata(
        self,
        record_id: str,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        published_at: datetime | None = None,
        fetched_at: datetime | None = None,
        quality_state: str = "verified",
        conflict_group: str | None = None,
    ) -> dict:
        published = published_at or datetime(2026, 2, 10, tzinfo=UTC)
        return {
            "record_id": record_id,
            "source_provider_id": "synthetic-open",
            "as_of": datetime(2026, 1, 31, tzinfo=UTC),
            "published_at": published,
            "fetched_at": fetched_at or published,
            "valid_from": valid_from or datetime(2020, 1, 1, tzinfo=UTC),
            "valid_to": valid_to,
            "quality_state": quality_state,
            "conflict_group": conflict_group,
        }

    def _strategy(self, record_id: str = "strategy-record-1", **changes: object) -> FundStrategy:
        values = {
            **self._metadata(record_id),
            "fund_strategy_id": "strategy-1",
            "canonical_name": "Synthetic Strategy",
            "identifiers": (ExternalIdentifier("synthetic_master", "MASTER-1"),),
            "jurisdiction": "CN",
            "strategy_profile": "bond",
            "vehicle_type": "open_ended",
            "management_style": "active",
            "asset_class": "bond",
            "base_currency": "CNY",
            "inception_date": date(2020, 1, 1),
            "status": "active",
        }
        values.update(changes)
        return FundStrategy(**values)

    def _share_class(self) -> ShareClass:
        return ShareClass(
            **self._metadata("share-record-1"),
            share_class_id="share-1",
            fund_strategy_id="strategy-1",
            canonical_name="Synthetic Strategy A",
            class_code="A",
            identifiers=(ExternalIdentifier("cn_fund_code", "000001"),),
            dealing_currency="CNY",
            distribution_policy="accumulating",
            investor_type="retail",
            subscription_status="open",
            redemption_status="open",
            inception_date=date(2020, 1, 1),
        )

    def test_store_dump_load_round_trip_is_byte_deterministic(self) -> None:
        from openfundscore.storage import CanonicalStore

        with CanonicalStore(":memory:") as source:
            source.put(self._share_class())
            source.put(self._strategy())
            first_dump = source.dump_json()

        with CanonicalStore(":memory:") as restored:
            restored.load_json(first_dump)
            second_dump = restored.dump_json()
            self.assertEqual(restored.get("strategy-record-1"), self._strategy())

        self.assertEqual(second_dump, first_dump)

    def test_point_in_time_query_applies_validity_and_knowledge_cutoff(self) -> None:
        from openfundscore.storage import CanonicalStore

        boundary = datetime(2025, 1, 1, tzinfo=UTC)
        old = self._strategy(
            "strategy-old",
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            valid_to=boundary,
            published_at=datetime(2020, 1, 2, tzinfo=UTC),
            fetched_at=datetime(2020, 1, 3, tzinfo=UTC),
            strategy_profile="bond",
        )
        changed = self._strategy(
            "strategy-changed",
            valid_from=boundary,
            valid_to=None,
            published_at=datetime(2025, 2, 1, tzinfo=UTC),
            fetched_at=datetime(2025, 2, 2, tzinfo=UTC),
            strategy_profile="fixed_income_plus",
        )

        with CanonicalStore(":memory:") as store:
            store.put(changed)
            store.put(old)
            before_boundary = store.query_versions(
                "fund_strategy",
                "strategy-1",
                effective_at=datetime(2024, 12, 31, tzinfo=UTC),
                knowledge_cutoff=datetime(2024, 12, 31, tzinfo=UTC),
            )
            unavailable_at_boundary = store.query_versions(
                "fund_strategy",
                "strategy-1",
                effective_at=boundary,
                knowledge_cutoff=datetime(2025, 2, 1, tzinfo=UTC),
            )
            known_after_fetch = store.query_versions(
                "fund_strategy",
                "strategy-1",
                effective_at=boundary,
                knowledge_cutoff=datetime(2025, 2, 2, tzinfo=UTC),
            )

        self.assertEqual(before_boundary, (old,))
        self.assertEqual(unavailable_at_boundary, ())
        self.assertEqual(known_after_fetch, (changed,))

    def test_share_class_join_preserves_all_conflicting_strategy_candidates(self) -> None:
        from openfundscore.storage import CanonicalStore

        first = self._strategy(
            "strategy-conflict-a",
            strategy_profile="bond",
            quality_state="conflict",
            conflict_group="strategy-1:profile:2026-01-31",
        )
        second = self._strategy(
            "strategy-conflict-b",
            strategy_profile="fixed_income_plus",
            quality_state="conflict",
            conflict_group="strategy-1:profile:2026-01-31",
            source_provider_id="synthetic-registry-2",
        )

        with CanonicalStore(":memory:") as store:
            store.put(first)
            store.put(second)
            store.put(self._share_class())
            resolutions = store.resolve_share_class(
                "share-1",
                effective_at=datetime(2026, 1, 31, tzinfo=UTC),
                knowledge_cutoff=datetime(2026, 2, 11, tzinfo=UTC),
            )

        self.assertEqual(len(resolutions), 1)
        self.assertEqual(
            {candidate.strategy_profile for candidate in resolutions[0].strategy_candidates},
            {"bond", "fixed_income_plus"},
        )
        self.assertEqual(
            resolutions[0].conflict_groups,
            ("strategy-1:profile:2026-01-31",),
        )

    def test_record_id_replay_is_idempotent_but_reuse_is_rejected(self) -> None:
        from openfundscore.storage import CanonicalStore, RecordIdentityConflict

        original = self._strategy()
        changed = replace(original, strategy_profile="fixed_income_plus")
        with CanonicalStore(":memory:") as store:
            self.assertTrue(store.put(original))
            self.assertFalse(store.put(original))
            with self.assertRaisesRegex(
                RecordIdentityConflict,
                "already has different immutable content",
            ):
                store.put(changed)

    def test_fractional_seconds_do_not_break_point_in_time_boundaries(self) -> None:
        from openfundscore.storage import CanonicalStore

        whole_second = datetime(2025, 1, 1, tzinfo=UTC)
        later_in_same_second = datetime(
            2025,
            1,
            1,
            microsecond=500_000,
            tzinfo=UTC,
        )
        not_yet_effective = self._strategy(
            "strategy-fractional-validity",
            fund_strategy_id="strategy-fractional-validity",
            valid_from=later_in_same_second,
            published_at=datetime(2024, 12, 1, tzinfo=UTC),
            fetched_at=datetime(2024, 12, 2, tzinfo=UTC),
        )
        not_yet_fetched = self._strategy(
            "strategy-fractional-knowledge",
            fund_strategy_id="strategy-fractional-knowledge",
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            published_at=whole_second,
            fetched_at=datetime(
                2025,
                1,
                1,
                microsecond=123_456,
                tzinfo=UTC,
            ),
        )

        with CanonicalStore(":memory:") as store:
            store.put(not_yet_effective)
            store.put(not_yet_fetched)
            validity_result = store.query_versions(
                "fund_strategy",
                "strategy-fractional-validity",
                effective_at=whole_second,
                knowledge_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
            )
            knowledge_result = store.query_versions(
                "fund_strategy",
                "strategy-fractional-knowledge",
                effective_at=whole_second,
                knowledge_cutoff=whole_second,
            )

        self.assertEqual(validity_result, ())
        self.assertEqual(knowledge_result, ())


if __name__ == "__main__":
    unittest.main()
