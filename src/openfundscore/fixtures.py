"""Deterministic synthetic canonical fixtures for tests and examples."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .canonical import (
    Benchmark,
    CanonicalEntity,
    Evidence,
    ExternalIdentifier,
    FeeSchedule,
    FundLifecycleEvent,
    FundStrategy,
    HoldingPosition,
    HoldingSnapshot,
    Manager,
    ManagerTenure,
    ShareClass,
)


def synthetic_canonical_records(*, fetched_at: datetime) -> tuple[CanonicalEntity, ...]:
    """Build a fixed multi-state universe without network or private data."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must be a timezone-aware datetime")
    published_at = fetched_at - timedelta(days=1)
    as_of = fetched_at - timedelta(days=2)

    def metadata(
        record_id: str,
        *,
        valid_from: datetime,
        valid_to: datetime | None = None,
        source_provider_id: str = "synthetic-open",
        quality_state: str = "verified",
        conflict_group: str | None = None,
    ) -> dict:
        return {
            "record_id": record_id,
            "source_provider_id": source_provider_id,
            "as_of": as_of,
            "published_at": published_at,
            "fetched_at": fetched_at,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "quality_state": quality_state,
            "conflict_group": conflict_group,
        }

    origin = datetime(2020, 1, 1, tzinfo=fetched_at.tzinfo)
    transformed_at = datetime(2024, 7, 1, tzinfo=fetched_at.tzinfo)
    lifecycle_at = datetime(2025, 1, 1, tzinfo=fetched_at.tzinfo)

    benchmark = Benchmark(
        **metadata("benchmark-alpha-v1", valid_from=origin),
        benchmark_id="ofs:benchmark:alpha",
        canonical_name="Synthetic Balanced Benchmark",
        identifiers=(ExternalIdentifier("synthetic_index", "SYN-BAL", "CN"),),
        benchmark_type="contractual",
        currency="CNY",
    )
    alpha = FundStrategy(
        **metadata("strategy-alpha-v1", valid_from=origin),
        fund_strategy_id="ofs:fund_strategy:alpha",
        canonical_name="Synthetic Alpha Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "ALPHA", "CN"),),
        jurisdiction="CN",
        strategy_profile="active_equity_mixed",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="mixed",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
        primary_benchmark_id=benchmark.benchmark_id,
        mandate="Synthetic balanced public-fund mandate",
    )
    fee_profiles = {
        "A": FeeSchedule(
            management_fee_bps=100,
            custody_fee_bps=20,
            subscription_fee_bps=150,
        ),
        "C": FeeSchedule(
            management_fee_bps=100,
            custody_fee_bps=20,
            sales_service_fee_bps=80,
        ),
        "E": FeeSchedule(
            management_fee_bps=100,
            custody_fee_bps=20,
            sales_service_fee_bps=40,
        ),
        "I": FeeSchedule(management_fee_bps=60, custody_fee_bps=15),
    }
    share_classes = tuple(
        ShareClass(
            **metadata(f"share-alpha-{code.lower()}-v1", valid_from=origin),
            share_class_id=f"ofs:share_class:alpha-{code.lower()}",
            fund_strategy_id=alpha.fund_strategy_id,
            canonical_name=f"Synthetic Alpha Fund {code}",
            class_code=code,
            identifiers=(ExternalIdentifier("synthetic_share", f"ALPHA-{code}", "CN"),),
            dealing_currency="CNY",
            distribution_policy="accumulating",
            investor_type="institutional" if code == "I" else "retail",
            subscription_status="open",
            redemption_status="open",
            inception_date=date(2020, 1, 1),
            fee_schedule=fee_profiles[code],
        )
        for code in ("A", "C", "E", "I")
    )
    manager = Manager(
        **metadata("manager-alpha-v1", valid_from=origin),
        manager_id="ofs:manager:alpha",
        canonical_name="Synthetic Public Manager",
        identifiers=(ExternalIdentifier("synthetic_manager", "MANAGER-A", "CN"),),
        current_employer_id="ofs:company:synthetic",
    )
    tenure = ManagerTenure(
        **metadata("tenure-alpha-v1", valid_from=origin),
        tenure_id="ofs:tenure:alpha",
        fund_strategy_id=alpha.fund_strategy_id,
        manager_id=manager.manager_id,
        role="lead",
        attribution_mode="individual",
        attribution_share=None,
        tenure_start=date(2020, 1, 1),
        tenure_end=None,
    )
    holdings = HoldingSnapshot(
        **metadata("holding-alpha-2026q1", valid_from=as_of),
        snapshot_id="ofs:holding_snapshot:alpha-2026q1",
        fund_strategy_id=alpha.fund_strategy_id,
        currency="CNY",
        positions=(
            HoldingPosition(
                instrument_id="ofs:instrument:synthetic-equity",
                issuer_id="ofs:issuer:synthetic",
                asset_type="equity",
                weight_bps=7000,
            ),
            HoldingPosition(
                instrument_id="ofs:instrument:cash-cny",
                asset_type="cash",
                weight_bps=3000,
            ),
        ),
    )

    closed_before = FundStrategy(
        **metadata(
            "strategy-closed-before",
            valid_from=origin,
            valid_to=lifecycle_at,
        ),
        fund_strategy_id="ofs:fund_strategy:closed",
        canonical_name="Synthetic Closed Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "CLOSED", "CN"),),
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
    )
    closed_after = FundStrategy(
        **metadata("strategy-closed-after", valid_from=lifecycle_at),
        fund_strategy_id=closed_before.fund_strategy_id,
        canonical_name=closed_before.canonical_name,
        identifiers=closed_before.identifiers,
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
                event_id="event-closed",
                event_type="closed",
                effective_at=lifecycle_at,
                evidence_ids=("evidence-closed",),
            ),
        ),
    )
    successor = FundStrategy(
        **metadata("strategy-successor-v1", valid_from=lifecycle_at),
        fund_strategy_id="ofs:fund_strategy:successor",
        canonical_name="Synthetic Successor Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "SUCCESSOR", "CN"),),
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2025, 1, 1),
        status="active",
    )
    merged_before = FundStrategy(
        **metadata(
            "strategy-merged-before",
            valid_from=origin,
            valid_to=lifecycle_at,
        ),
        fund_strategy_id="ofs:fund_strategy:merged",
        canonical_name="Synthetic Merged Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "MERGED", "CN"),),
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
    )
    merged_after = FundStrategy(
        **metadata("strategy-merged-after", valid_from=lifecycle_at),
        fund_strategy_id=merged_before.fund_strategy_id,
        canonical_name=merged_before.canonical_name,
        identifiers=merged_before.identifiers,
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="merged",
        lifecycle_events=(
            FundLifecycleEvent(
                event_id="event-merged",
                event_type="merged",
                effective_at=lifecycle_at,
                successor_strategy_id=successor.fund_strategy_id,
                evidence_ids=("evidence-merged",),
            ),
        ),
    )
    transformed_before = FundStrategy(
        **metadata(
            "strategy-transformed-before",
            valid_from=origin,
            valid_to=transformed_at,
        ),
        fund_strategy_id="ofs:fund_strategy:transformed",
        canonical_name="Synthetic Transforming Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "TRANSFORM", "CN"),),
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
    )
    transformed_after = FundStrategy(
        **metadata("strategy-transformed-after", valid_from=transformed_at),
        fund_strategy_id="ofs:fund_strategy:transformed",
        canonical_name="Synthetic Transforming Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "TRANSFORM", "CN"),),
        jurisdiction="CN",
        strategy_profile="fixed_income_plus",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="mixed",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="transformed",
        lifecycle_events=(
            FundLifecycleEvent(
                event_id="event-transformed",
                event_type="transformed",
                effective_at=transformed_at,
                evidence_ids=("evidence-transformed",),
            ),
        ),
    )
    conflict_group = "strategy-conflict:profile:2026-02-27"
    conflict_a = FundStrategy(
        **metadata(
            "strategy-conflict-a",
            valid_from=origin,
            quality_state="conflict",
            conflict_group=conflict_group,
        ),
        fund_strategy_id="ofs:fund_strategy:conflict",
        canonical_name="Synthetic Conflict Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "CONFLICT", "CN"),),
        jurisdiction="CN",
        strategy_profile="bond",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="bond",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
    )
    conflict_b = FundStrategy(
        **metadata(
            "strategy-conflict-b",
            valid_from=origin,
            source_provider_id="synthetic-open-2",
            quality_state="conflict",
            conflict_group=conflict_group,
        ),
        fund_strategy_id="ofs:fund_strategy:conflict",
        canonical_name="Synthetic Conflict Fund",
        identifiers=(ExternalIdentifier("synthetic_master", "CONFLICT", "CN"),),
        jurisdiction="CN",
        strategy_profile="fixed_income_plus",
        vehicle_type="open_ended",
        management_style="active",
        asset_class="mixed",
        base_currency="CNY",
        inception_date=date(2020, 1, 1),
        status="active",
    )

    def evidence(evidence_id: str, subject_id: str, excerpt: str) -> Evidence:
        return Evidence(
            **metadata(f"{evidence_id}-record", valid_from=origin),
            evidence_id=evidence_id,
            subject_type="fund_strategy",
            subject_id=subject_id,
            tier="A",
            source_url=f"https://example.com/{evidence_id}",
            fact_excerpt=excerpt,
            content_hash=None,
        )

    return (
        benchmark,
        alpha,
        *share_classes,
        manager,
        tenure,
        holdings,
        closed_before,
        closed_after,
        successor,
        merged_before,
        merged_after,
        transformed_before,
        transformed_after,
        conflict_a,
        conflict_b,
        evidence("evidence-alpha", alpha.fund_strategy_id, "Synthetic public mandate"),
        evidence(
            "evidence-closed",
            closed_after.fund_strategy_id,
            "Synthetic closure notice",
        ),
        evidence(
            "evidence-merged",
            merged_after.fund_strategy_id,
            "Synthetic merger notice",
        ),
        evidence(
            "evidence-transformed",
            transformed_after.fund_strategy_id,
            "Synthetic transformation notice",
        ),
    )


def synthetic_mainland_snapshot_bundle() -> dict[str, Any]:
    """Return a fresh, deterministic, wholly synthetic official-snapshot fixture."""
    source = "https://www.csrc.gov.cn/synthetic/disclosure.json"
    terms = "https://www.csrc.gov.cn/synthetic/terms"
    document_hash = "sha256:" + "a" * 64

    def observation(
        observation_id: str,
        field: str,
        raw_value: object,
        *,
        as_of: str = "2026-08-15T00:00:00Z",
        unit: str | None = None,
        currency: str | None = None,
        quality_state: str = "verified",
        conflict_group: str | None = None,
    ) -> dict[str, object]:
        return {
            "observation_id": observation_id,
            "field": field,
            "raw_value": raw_value,
            "as_of": as_of,
            "published_at": "2026-08-16T00:00:00Z",
            "fetched_at": "2026-08-17T00:00:00Z",
            "valid_from": as_of,
            "valid_to": None,
            "currency": currency,
            "unit": unit,
            "source_url": source,
            "source_document_hash": document_hash,
            "point_in_time_status": "verified",
            "methodology": None,
            "quality_state": quality_state,
            "conflict_group": conflict_group,
        }

    def item(
        item_id: str,
        item_type: str,
        entity_type: str,
        entity_id: str,
        observations: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "item_id": item_id,
            "item_type": item_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "exact_identifiers": [
                {
                    "scheme": "official_entity_id",
                    "value": entity_id,
                    "jurisdiction": "CN",
                }
            ],
            "observations": observations,
        }

    def action(
        item_id: str,
        action_type: str,
        before_id: str,
        after_id: str | None,
    ) -> dict[str, object]:
        return item(
            item_id,
            "corporate_action",
            "corporate_action",
            item_id,
            [
                observation(f"{item_id}-type", "action_type", action_type),
                observation(
                    f"{item_id}-effective",
                    "effective_at",
                    "2026-08-15T00:00:00Z",
                ),
                observation(f"{item_id}-before", "before_id", before_id),
                observation(f"{item_id}-after", "after_id", after_id),
            ],
        )

    return {
        "schema_version": "0.1.0",
        "provider_id": "mainland-official-pilot",
        "snapshot_id": "synthetic-mainland-snapshot-2026-08-17",
        "source_type": "regulator",
        "jurisdiction": "CN",
        "official_source_url": source,
        "retrieved_at": "2026-08-17T00:00:00Z",
        "published_at": "2026-08-16T00:00:00Z",
        "as_of": "2026-08-15T00:00:00Z",
        "effective_at": "2026-08-15T00:00:00Z",
        "document_sha256": document_hash,
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "units": {
            "nav": "CNY_per_share",
            "weight": "bps",
            "coverage": "bps",
        },
        "rights": {
            "mode": "local_entitlement",
            "terms_url": terms,
            "reviewed_at": "2026-08-20T00:00:00Z",
            "valid_until": "2026-09-01T00:00:00Z",
            "cache_allowed": True,
            "derived_works_allowed": True,
            "redistribution_allowed": False,
            "attribution_required": True,
            "public_display_allowed": False,
            "retention_days": 30,
            "source_evidence_url": terms,
        },
        "items": [
            item(
                "identity-a",
                "identity",
                "share_class",
                "synthetic-share-a",
                [
                    observation(
                        "identity-a-name-1",
                        "canonical_name",
                        "Synthetic Fund A",
                        quality_state="conflict",
                        conflict_group="synthetic-name-conflict",
                    ),
                    observation(
                        "identity-a-name-2",
                        "canonical_name",
                        "Synthetic Fund Class A",
                        quality_state="conflict",
                        conflict_group="synthetic-name-conflict",
                    ),
                    observation("identity-a-class", "class_code", "A"),
                ],
            ),
            item(
                "identity-c",
                "identity",
                "share_class",
                "synthetic-share-c",
                [
                    observation(
                        "identity-c-name", "canonical_name", "Synthetic Fund C"
                    ),
                    observation("identity-c-class", "class_code", "C"),
                ],
            ),
            item(
                "nav-a",
                "nav",
                "share_class",
                "synthetic-share-a",
                [
                    observation(
                        "nav-a-1",
                        "nav",
                        1.0,
                        as_of="2026-08-14T00:00:00Z",
                        currency="CNY",
                        unit="CNY_per_share",
                    ),
                    observation(
                        "nav-a-2",
                        "nav",
                        1.01,
                        currency="CNY",
                        unit="CNY_per_share",
                    ),
                ],
            ),
            item(
                "report-q2",
                "report",
                "report",
                "synthetic-report-q2",
                [
                    observation("report-url", "report_url", source),
                    observation("report-hash", "report_document_hash", document_hash),
                ],
            ),
            item(
                "manager-tenure",
                "manager_tenure",
                "manager_tenure",
                "synthetic-tenure",
                [
                    observation("tenure-manager", "manager_id", "synthetic-manager"),
                    observation("tenure-fund", "fund_strategy_id", "synthetic-fund"),
                    observation("tenure-start", "tenure_start", "2024-01-01"),
                    observation("tenure-end", "tenure_end", None),
                ],
            ),
            item(
                "benchmark",
                "benchmark",
                "benchmark",
                "synthetic-benchmark",
                [
                    observation(
                        "benchmark-name", "canonical_name", "Synthetic Benchmark"
                    )
                ],
            ),
            item(
                "holding",
                "holding",
                "holding",
                "synthetic-holding",
                [
                    observation("holding-fund", "fund_strategy_id", "synthetic-fund"),
                    observation("holding-instrument", "instrument_id", "SYN-CN-1"),
                    observation("holding-weight", "weight", 6000, unit="bps"),
                    observation("holding-coverage", "coverage", 8000, unit="bps"),
                ],
            ),
            action("action-closed", "closed", "synthetic-closed", None),
            action(
                "action-merged",
                "merged",
                "synthetic-merged",
                "synthetic-successor",
            ),
            action(
                "action-transformed",
                "transformed",
                "synthetic-before-transform",
                "synthetic-after-transform",
            ),
        ],
    }
