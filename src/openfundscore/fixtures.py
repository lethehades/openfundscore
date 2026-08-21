"""Deterministic synthetic canonical fixtures for tests and examples."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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
            identifiers=(
                ExternalIdentifier("synthetic_share", f"ALPHA-{code}", "CN"),
            ),
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
