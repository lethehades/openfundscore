"""Cross-component validation for score evidence usage records."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from heapq import heappop, heappush
from typing import Any

from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)
from .window_semantics import complete_months_between, subtract_months


class EvidenceUsageValidationError(ValueError):
    """Raised when evidence usage would violate the scoring contract."""


MAX_USAGE_ITEMS = 1000

FUND_COMPONENTS = frozenset(
    {
        "fund_d1_performance_evidence",
        "fund_d2_downside_risk",
        "fund_d3_consistency",
        "fund_d4_manager_capability",
        "fund_d5_portfolio_structure",
        "fund_d6_implementation_efficiency",
        "fund_d7_governance_operations",
    }
)

MANAGER_COMPONENTS = frozenset(
    {
        "manager_tenure_attributed_performance",
        "manager_downside_control",
        "manager_cross_cycle_consistency",
        "manager_style_discipline",
        "manager_career_track_record",
        "manager_workload_capacity",
        "manager_research_platform_team",
        "manager_compliance_integrity",
    }
)

MANAGER_TENURE_COMPONENTS = frozenset(
    {
        "manager_tenure_attributed_performance",
        "manager_downside_control",
        "manager_cross_cycle_consistency",
    }
)

TARGET_COMPONENTS = FUND_COMPONENTS | MANAGER_COMPONENTS


def _window(usage: Mapping[str, Any]) -> tuple[date, date]:
    return (
        date.fromisoformat(usage["window_start"]),
        date.fromisoformat(usage["window_end"]),
    )


def _timestamp(value: object, *, path: str) -> datetime:
    provider_error: ProviderRecordValidationError | None = None
    parsed = None
    try:
        parsed = parse_rfc3339_timestamp(value, path=path)
    except ProviderRecordValidationError as exc:
        provider_error = exc
    if provider_error is not None or parsed is None:
        raise EvidenceUsageValidationError(
            f"{path}: timestamp must use the OpenFundScore RFC3339 profile"
        )
    return parsed


def canonicalize_score_evidence_ledger_for_digest(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Deep-copy a ledger and normalize only schema-declared date-time fields.

    Usage order and ISO date window fields are preserved exactly. Invalid or missing
    RFC3339 date-time fields fail closed rather than producing an ambiguous digest.
    """
    try:
        snapshot = deepcopy(document)
    except Exception:  # noqa: BLE001 - input mappings may be untrusted
        raise EvidenceUsageValidationError(
            "score evidence ledger could not be safely copied for digest"
        ) from None
    if type(snapshot) is not dict:
        raise EvidenceUsageValidationError("score evidence ledger must be an object")
    usages = snapshot.get("usage")
    if type(usages) is not list:
        raise EvidenceUsageValidationError("$.usage: usage must be an array")

    def utc_z(value: object, *, path: str) -> str:
        return (
            _timestamp(value, path=path)
            .astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

    snapshot["as_of"] = utc_z(snapshot.get("as_of"), path="$.as_of")
    for index, usage in enumerate(usages):
        if type(usage) is not dict:
            raise EvidenceUsageValidationError(
                f"usage[{index}]: usage item must be an object"
            )
        usage["observation_as_of"] = utc_z(
            usage.get("observation_as_of"),
            path=f"usage[{index}].observation_as_of",
        )
    return snapshot


def _validate_v020_window(
    usage: Mapping[str, Any],
    *,
    index: int,
    ledger_as_of: datetime,
    window_start: date,
    window_end: date,
) -> None:
    """Apply the 0.2 knowledge-time and declared window-basis contract."""
    required = {
        "evidence_id",
        "observation_as_of",
        "window_basis",
        "window_months",
    }
    if not required.issubset(usage):
        return
    observation_as_of = _timestamp(
        usage["observation_as_of"],
        path=f"usage[{index}].observation_as_of",
    )
    if observation_as_of > ledger_as_of:
        raise EvidenceUsageValidationError(
            f"usage[{index}].observation_as_of must be on or before $.as_of"
        )
    observation_date = observation_as_of.astimezone(UTC).date()
    if window_end > observation_date:
        raise EvidenceUsageValidationError(
            f"usage[{index}].window_end must be on or before the UTC observation date"
        )
    window_months = usage["window_months"]
    if type(window_months) is not int or not 0 <= window_months <= 1200:
        raise EvidenceUsageValidationError(
            f"usage[{index}].window_months must be a bounded non-negative integer"
        )
    basis = usage["window_basis"]
    if basis == "point_in_time":
        if (
            window_months != 0
            or window_start != observation_date
            or window_end != observation_date
        ):
            raise EvidenceUsageValidationError(
                f"usage[{index}] point_in_time must be a zero-month UTC observation date"
            )
    elif basis == "calendar_months":
        expected_end = observation_date
        expected_start = subtract_months(expected_end, window_months)
        if window_end != expected_end or window_start != expected_start:
            raise EvidenceUsageValidationError(
                f"usage[{index}] calendar_months endpoints must equal the exact UTC "
                "observation-date reverse-clamped window"
            )
    elif basis == "actual_dates":
        if window_months != complete_months_between(window_start, window_end):
            raise EvidenceUsageValidationError(
                f"usage[{index}].window_months must match its actual-date endpoints"
            )
    else:
        raise EvidenceUsageValidationError(
            f"usage[{index}].window_basis is unsupported"
        )


def _first_cross_scope_overlap(
    usages: list[Mapping[str, Any]],
    windows: list[tuple[date, date]],
) -> tuple[int, int] | None:
    groups: dict[
        tuple[str, str],
        list[tuple[date, int, int, str]],
    ] = {}
    for index, usage in enumerate(usages):
        component = usage["target_component"]
        if usage["source_scope"] != "current_fund" or usage["usage_mode"] != "raw":
            continue
        if component in FUND_COMPONENTS:
            side = "fund"
        elif component in MANAGER_TENURE_COMPONENTS:
            side = "manager"
        else:
            continue
        start, end = windows[index]
        identities = [
            ("lineage", usage["lineage_id"]),
            ("series", usage["series_id"]),
        ]
        if "evidence_id" in usage:
            identities.append(("evidence", usage["evidence_id"]))
        for identity_kind, identity_value in identities:
            events = groups.setdefault((identity_kind, identity_value), [])
            events.append((start, 0, index, side))
            events.append((end, 1, index, side))

    best: tuple[int, int] | None = None
    for events in groups.values():
        active = {"fund": set(), "manager": set()}
        heaps: dict[str, list[int]] = {"fund": [], "manager": []}
        for _, phase, index, side in sorted(events):
            if phase == 0:
                other = "manager" if side == "fund" else "fund"
                while heaps[other] and heaps[other][0] not in active[other]:
                    heappop(heaps[other])
                if heaps[other]:
                    other_index = heaps[other][0]
                    pair = (
                        min(index, other_index),
                        max(index, other_index),
                    )
                    if best is None or pair < best:
                        best = pair
                active[side].add(index)
                heappush(heaps[side], index)
            else:
                active[side].discard(index)
    return best


def validate_score_evidence_usage(document: Mapping[str, Any]) -> None:
    """Reject cross-component reuse of raw current-fund evidence."""
    usages = document["usage"]
    if len(usages) > MAX_USAGE_ITEMS:
        raise EvidenceUsageValidationError(
            f"$.usage: usage must contain at most {MAX_USAGE_ITEMS} entries"
        )
    ledger_as_of = _timestamp(document.get("as_of"), path="$.as_of")
    as_of = ledger_as_of.astimezone(UTC).date()
    seen: dict[tuple[tuple[str, Any], ...], int] = {}
    windows: list[tuple[date, date]] = []
    for index, usage in enumerate(usages):
        component = usage["target_component"]
        if component not in TARGET_COMPONENTS:
            raise EvidenceUsageValidationError(
                f"usage[{index}].target_component {component!r} is unknown"
            )
        fingerprint = tuple(sorted(usage.items()))
        if fingerprint in seen:
            first_index = seen[fingerprint]
            raise EvidenceUsageValidationError(
                "duplicate usage entries: "
                f"usage[{first_index}] and usage[{index}] are identical"
            )
        seen[fingerprint] = index
        window_start, window_end = _window(usage)
        if window_start > window_end:
            raise EvidenceUsageValidationError(
                f"usage[{index}].window_start must be on or before window_end"
            )
        if window_end > as_of:
            raise EvidenceUsageValidationError(
                f"usage[{index}].window_end must be on or before $.as_of"
            )
        _validate_v020_window(
            usage,
            index=index,
            ledger_as_of=ledger_as_of,
            window_start=window_start,
            window_end=window_end,
        )
        windows.append((window_start, window_end))

    collision = _first_cross_scope_overlap(usages, windows)
    if collision is None:
        return
    left_index, right_index = collision
    left = usages[left_index]
    raise EvidenceUsageValidationError(
        "double-counted raw current_fund evidence: "
        f"usage[{left_index}] and usage[{right_index}] have an identity "
        f"collision involving evidence_id={left.get('evidence_id')!r}, "
        f"lineage_id={left['lineage_id']!r}, "
        f"series_id={left['series_id']!r}, "
        f"evidence_family={left['evidence_family']!r}, and overlapping windows"
    )
