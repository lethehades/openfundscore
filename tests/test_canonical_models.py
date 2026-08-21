from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime


class CanonicalModelTests(unittest.TestCase):
    def _metadata(self, record_id: str) -> dict:
        return {
            "record_id": record_id,
            "source_provider_id": "synthetic-open",
            "as_of": datetime(2026, 1, 31, tzinfo=UTC),
            "published_at": datetime(2026, 2, 10, tzinfo=UTC),
            "fetched_at": datetime(2026, 2, 11, tzinfo=UTC),
            "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
            "quality_state": "verified",
        }

    def test_share_classes_reference_one_strategy_entity(self) -> None:
        from openfundscore.canonical import ExternalIdentifier, FundStrategy, ShareClass

        strategy = FundStrategy(
            **self._metadata("fund-strategy-record-1"),
            fund_strategy_id="ofs:fund_strategy:alpha",
            canonical_name="Synthetic Alpha Fund",
            identifiers=(ExternalIdentifier("cn_fund_master", "SYNTH-ALPHA"),),
            jurisdiction="CN",
            strategy_profile="active_equity_mixed",
            vehicle_type="open_ended",
            management_style="active",
            asset_class="equity",
            base_currency="CNY",
            inception_date=date(2020, 1, 1),
            status="active",
        )
        share_classes = tuple(
            ShareClass(
                **self._metadata(f"share-{class_code}-record-1"),
                share_class_id=f"ofs:share_class:alpha-{class_code.lower()}",
                fund_strategy_id=strategy.fund_strategy_id,
                canonical_name=f"Synthetic Alpha Fund {class_code}",
                class_code=class_code,
                identifiers=(
                    ExternalIdentifier("cn_fund_code", f"00000{index}"),
                ),
                dealing_currency="CNY",
                distribution_policy="accumulating",
                investor_type="retail" if class_code != "I" else "institutional",
                subscription_status="open",
                redemption_status="open",
                inception_date=date(2020, 1, index),
            )
            for index, class_code in enumerate(("A", "C", "E", "I"), start=1)
        )

        self.assertEqual(
            {share_class.fund_strategy_id for share_class in share_classes},
            {strategy.fund_strategy_id},
        )
        self.assertEqual(len({item.share_class_id for item in share_classes}), 4)

    def test_all_seven_entities_round_trip_deterministically(self) -> None:
        from openfundscore.canonical import (
            Benchmark,
            Evidence,
            ExternalIdentifier,
            FundStrategy,
            HoldingPosition,
            HoldingSnapshot,
            Manager,
            ManagerTenure,
            ShareClass,
            canonical_json,
            record_from_document,
            record_to_document,
        )

        identifier = ExternalIdentifier("synthetic_id", "entity-1", "CN")
        records = (
            FundStrategy(
                **self._metadata("strategy-record"),
                fund_strategy_id="strategy-1",
                canonical_name="Synthetic Strategy",
                identifiers=(identifier,),
                jurisdiction="CN",
                strategy_profile="bond",
                vehicle_type="open_ended",
                management_style="active",
                asset_class="bond",
                base_currency="CNY",
                inception_date=date(2020, 1, 1),
                status="active",
            ),
            ShareClass(
                **self._metadata("share-record"),
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
            ),
            Benchmark(
                **self._metadata("benchmark-record"),
                benchmark_id="benchmark-1",
                canonical_name="Synthetic Bond Index",
                identifiers=(ExternalIdentifier("index_code", "SYN-BOND"),),
                benchmark_type="index",
                currency="CNY",
            ),
            Manager(
                **self._metadata("manager-record"),
                manager_id="manager-1",
                canonical_name="Synthetic Manager",
                identifiers=(ExternalIdentifier("manager_registry", "M-1"),),
                current_employer_id="company-1",
            ),
            ManagerTenure(
                **self._metadata("tenure-record"),
                tenure_id="tenure-1",
                fund_strategy_id="strategy-1",
                manager_id="manager-1",
                role="lead",
                attribution_mode="individual",
                attribution_share=None,
                tenure_start=date(2021, 1, 1),
                tenure_end=None,
            ),
            HoldingSnapshot(
                **self._metadata("holding-record"),
                snapshot_id="snapshot-1",
                fund_strategy_id="strategy-1",
                currency="CNY",
                positions=(
                    HoldingPosition(
                        instrument_id="bond-1",
                        asset_type="bond",
                        weight_bps=6250,
                        issuer_id="issuer-1",
                    ),
                    HoldingPosition(
                        instrument_id="cash-CNY",
                        asset_type="cash",
                        weight_bps=3750,
                    ),
                ),
            ),
            Evidence(
                **self._metadata("evidence-record"),
                evidence_id="evidence-1",
                subject_type="fund_strategy",
                subject_id="strategy-1",
                tier="A",
                source_url="https://example.com/official-disclosure",
                fact_excerpt="Synthetic public professional fact",
                content_hash=None,
            ),
        )

        for record in records:
            with self.subTest(record=record.record_id):
                document = record_to_document(record)
                restored = record_from_document(document)
                self.assertEqual(restored, record)
                self.assertEqual(canonical_json(restored), canonical_json(record))

    def test_lifecycle_events_preserve_closed_merged_and_transformed_history(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            ExternalIdentifier,
            FundLifecycleEvent,
            FundStrategy,
            canonical_json,
            record_from_document,
            record_to_document,
        )

        def strategy(record_id: str, status: str, **changes: object) -> FundStrategy:
            values = {
                **self._metadata(record_id),
                "fund_strategy_id": "strategy-lifecycle",
                "canonical_name": "Synthetic Lifecycle Fund",
                "identifiers": (ExternalIdentifier("synthetic_id", "LIFE-1"),),
                "jurisdiction": "CN",
                "strategy_profile": "bond",
                "vehicle_type": "open_ended",
                "management_style": "active",
                "asset_class": "bond",
                "base_currency": "CNY",
                "inception_date": date(2020, 1, 1),
                "status": status,
                "valid_from": datetime(2020, 1, 1, tzinfo=UTC),
            }
            values.update(changes)
            return FundStrategy(**values)

        closed = strategy(
            "closed-record",
            "closed",
            valid_from=datetime(2024, 12, 31, tzinfo=UTC),
            lifecycle_events=(
                FundLifecycleEvent(
                    event_id="event-closed",
                    event_type="closed",
                    effective_at=datetime(2024, 12, 31, tzinfo=UTC),
                    evidence_ids=("evidence-closed",),
                ),
            ),
        )
        merged = strategy(
            "merged-record",
            "merged",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            lifecycle_events=(
                FundLifecycleEvent(
                    event_id="event-merged",
                    event_type="merged",
                    effective_at=datetime(2025, 1, 1, tzinfo=UTC),
                    successor_strategy_id="strategy-successor",
                    evidence_ids=("evidence-merged",),
                ),
            ),
        )
        transformed_before = strategy(
            "transformed-before",
            "active",
            valid_to=datetime(2025, 1, 1, tzinfo=UTC),
        )
        transformed_after = strategy(
            "transformed-after",
            "transformed",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            strategy_profile="fixed_income_plus",
            lifecycle_events=(
                FundLifecycleEvent(
                    event_id="event-transformed",
                    event_type="transformed",
                    effective_at=datetime(2025, 1, 1, tzinfo=UTC),
                    evidence_ids=("evidence-transformed",),
                ),
            ),
        )

        self.assertEqual(
            transformed_before.fund_strategy_id,
            transformed_after.fund_strategy_id,
        )
        self.assertNotEqual(
            transformed_before.strategy_profile,
            transformed_after.strategy_profile,
        )
        for record in (closed, merged, transformed_before, transformed_after):
            self.assertEqual(record_from_document(record_to_document(record)), record)
            self.assertEqual(canonical_json(record), canonical_json(record))

        with self.assertRaisesRegex(
            CanonicalValidationError,
            "merged lifecycle event requires successor_strategy_id",
        ):
            FundLifecycleEvent(
                event_id="invalid-merge",
                event_type="merged",
                effective_at=datetime(2025, 1, 1, tzinfo=UTC),
                evidence_ids=("evidence-invalid",),
            )

    def test_entity_resolution_uses_exact_identifiers_not_names(self) -> None:
        from openfundscore.canonical import (
            ExternalIdentifier,
            FundStrategy,
            resolve_external_identifier,
        )

        def strategy(
            record_id: str,
            fund_strategy_id: str,
            identifier_value: str,
            name: str,
        ) -> FundStrategy:
            return FundStrategy(
                **self._metadata(record_id),
                fund_strategy_id=fund_strategy_id,
                canonical_name=name,
                identifiers=(
                    ExternalIdentifier("synthetic_master", identifier_value, "CN"),
                ),
                jurisdiction="CN",
                strategy_profile="bond",
                vehicle_type="open_ended",
                management_style="active",
                asset_class="bond",
                base_currency="CNY",
                inception_date=date(2020, 1, 1),
                status="active",
            )

        same_name_a = strategy("record-a", "strategy-a", "MASTER-A", "同名基金")
        same_name_b = strategy("record-b", "strategy-b", "MASTER-B", "同名基金")
        renamed_version = strategy(
            "record-a-v2",
            "strategy-a",
            "MASTER-A",
            "Renamed Synthetic Fund",
        )

        matches = resolve_external_identifier(
            (same_name_a, same_name_b, renamed_version),
            ExternalIdentifier("synthetic_master", "MASTER-A", "CN"),
        )
        no_name_match = resolve_external_identifier(
            (same_name_a, same_name_b),
            ExternalIdentifier("synthetic_master", "同名基金", "CN"),
        )

        self.assertEqual(matches, (("fund_strategy", "strategy-a"),))
        self.assertEqual(no_name_match, ())

    def test_lifecycle_status_version_starts_at_event_effective_time(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            ExternalIdentifier,
            FundLifecycleEvent,
            FundStrategy,
        )

        with self.assertRaisesRegex(
            CanonicalValidationError,
            "lifecycle status version must start at the matching event",
        ):
            FundStrategy(
                **{
                    **self._metadata("retroactive-closed-record"),
                    "valid_from": datetime(2020, 1, 1, tzinfo=UTC),
                },
                fund_strategy_id="strategy-retroactive",
                canonical_name="Synthetic Retroactive Closure",
                identifiers=(ExternalIdentifier("synthetic_id", "RETRO"),),
                jurisdiction="CN",
                strategy_profile="bond",
                vehicle_type="open_ended",
                management_style="active",
                asset_class="bond",
                base_currency="CNY",
                inception_date=date(2020, 1, 1),
                status="closed",
                lifecycle_events=(
                    FundLifecycleEvent(
                        event_id="retroactive-close",
                        event_type="closed",
                        effective_at=datetime(2025, 1, 1, tzinfo=UTC),
                        evidence_ids=("evidence-retroactive",),
                    ),
                ),
            )

    def test_manager_evidence_cannot_bypass_private_content_guard(self) -> None:
        from openfundscore.canonical import CanonicalValidationError, Evidence

        with self.assertRaisesRegex(
            CanonicalValidationError,
            "sensitive private information is not permitted",
        ):
            Evidence(
                **self._metadata("private-manager-evidence"),
                evidence_id="evidence-private",
                subject_type="manager",
                subject_id="manager-1",
                tier="D",
                source_url="https://example.com/unacceptable",
                fact_excerpt="Home address: 1 Private Road; phone +1 212 555 0198",
                content_hash=None,
            )

    def test_conflict_quality_requires_a_conflict_group(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            ExternalIdentifier,
            FundStrategy,
        )

        with self.assertRaisesRegex(
            CanonicalValidationError,
            "quality_state 'conflict' requires conflict_group",
        ):
            FundStrategy(
                **{
                    **self._metadata("untraceable-conflict"),
                    "quality_state": "conflict",
                },
                fund_strategy_id="strategy-conflict",
                canonical_name="Synthetic Conflict",
                identifiers=(ExternalIdentifier("synthetic_id", "CONFLICT"),),
                jurisdiction="CN",
                strategy_profile="bond",
                vehicle_type="open_ended",
                management_style="active",
                asset_class="bond",
                base_currency="CNY",
                inception_date=date(2020, 1, 1),
                status="active",
            )

    def test_nested_value_objects_are_runtime_checked(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            ExternalIdentifier,
            FundStrategy,
            HoldingSnapshot,
            ShareClass,
        )

        base_strategy = {
            **self._metadata("nested-strategy"),
            "fund_strategy_id": "strategy-nested",
            "canonical_name": "Synthetic Nested",
            "jurisdiction": "CN",
            "strategy_profile": "bond",
            "vehicle_type": "open_ended",
            "management_style": "active",
            "asset_class": "bond",
            "base_currency": "CNY",
            "inception_date": date(2020, 1, 1),
            "status": "active",
        }
        with self.assertRaises(CanonicalValidationError):
            FundStrategy(**base_strategy, identifiers=({"scheme": "x", "value": "y"},))

        with self.assertRaises(CanonicalValidationError):
            ShareClass(
                **self._metadata("nested-share"),
                share_class_id="share-nested",
                fund_strategy_id="strategy-nested",
                canonical_name="Synthetic Nested A",
                class_code="A",
                identifiers=(ExternalIdentifier("share_code", "NEST-A"),),
                dealing_currency="CNY",
                distribution_policy="accumulating",
                investor_type="retail",
                subscription_status="open",
                redemption_status="open",
                inception_date=date(2020, 1, 1),
                fee_schedule={"management_fee_bps": 100},
            )

        with self.assertRaises(CanonicalValidationError):
            HoldingSnapshot(
                **self._metadata("nested-holding"),
                snapshot_id="snapshot-nested",
                fund_strategy_id="strategy-nested",
                currency="CNY",
                positions=({"instrument_id": "x", "asset_type": "bond", "weight_bps": 1},),
            )

    def test_document_parser_wraps_malformed_nested_values(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            ExternalIdentifier,
            FundStrategy,
            record_from_document,
            record_to_document,
        )

        record = FundStrategy(
            **self._metadata("parser-strategy"),
            fund_strategy_id="strategy-parser",
            canonical_name="Synthetic Parser",
            identifiers=(ExternalIdentifier("synthetic_id", "PARSER"),),
            jurisdiction="CN",
            strategy_profile="bond",
            vehicle_type="open_ended",
            management_style="active",
            asset_class="bond",
            base_currency="CNY",
            inception_date=date(2020, 1, 1),
            status="active",
        )
        malformed = record_to_document(record)
        malformed["identifiers"] = [{"scheme": "synthetic_id"}]

        with self.assertRaisesRegex(
            CanonicalValidationError,
            "invalid nested canonical value",
        ):
            record_from_document(malformed)
        with self.assertRaisesRegex(
            CanonicalValidationError,
            "canonical document must be an object",
        ):
            record_from_document([])

    def test_date_only_fields_reject_datetime_values(self) -> None:
        from openfundscore.canonical import (
            CanonicalValidationError,
            FundStrategy,
            ManagerTenure,
            ShareClass,
        )
        from openfundscore.fixtures import synthetic_canonical_records

        records = synthetic_canonical_records(
            fetched_at=datetime(2026, 3, 1, tzinfo=UTC)
        )
        strategy = next(item for item in records if isinstance(item, FundStrategy))
        share_class = next(item for item in records if isinstance(item, ShareClass))
        tenure = next(item for item in records if isinstance(item, ManagerTenure))
        datetime_value = datetime(2020, 1, 1, tzinfo=UTC)

        cases = (
            (strategy, "inception_date"),
            (share_class, "inception_date"),
            (share_class, "termination_date"),
            (tenure, "tenure_start"),
            (tenure, "tenure_end"),
        )
        for record, field_name in cases:
            with self.subTest(field_name=field_name), self.assertRaisesRegex(
                CanonicalValidationError,
                "must be a date",
            ):
                replace(record, **{field_name: datetime_value})

    def test_manager_evidence_rejects_private_or_malformed_source_urls(self) -> None:
        from openfundscore.canonical import CanonicalValidationError, Evidence
        from openfundscore.fixtures import synthetic_canonical_records

        records = synthetic_canonical_records(
            fetched_at=datetime(2026, 3, 1, tzinfo=UTC)
        )
        evidence = next(item for item in records if isinstance(item, Evidence))
        manager_evidence = replace(
            evidence,
            record_id="manager-source-url-base",
            evidence_id="manager-source-url-base",
            subject_type="manager",
            subject_id="manager-synthetic-1",
            fact_excerpt=None,
            content_hash="sha256:synthetic",
        )

        rejected_urls = (
            "https://",
            "https://example.com/?email=person@example.com",
            "https://example.com/%2B1-212-555-0198",
            "https://example.com/212-555-0198",
            "https://example.com/212%2D555%2D0198",
            "https://example.com/2125550198",
            "https://example.com/person%25252540example.com",
        )
        for source_url in rejected_urls:
            with self.subTest(source_url=source_url), self.assertRaises(
                CanonicalValidationError
            ):
                replace(manager_evidence, source_url=source_url)


if __name__ == "__main__":
    unittest.main()
