"""Cross-component validation for score evidence usage records."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping


class EvidenceUsageValidationError(ValueError):
    """Raised when evidence usage would violate the scoring contract."""


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


def validate_score_evidence_usage(document: Mapping[str, Any]) -> None:
    """Reject cross-component reuse of raw current-fund evidence."""
    usages = document["usage"]
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
        windows.append((window_start, window_end))

    for left_index, left in enumerate(usages):
        for right_index in range(left_index + 1, len(usages)):
            right = usages[right_index]
            components = {left["target_component"], right["target_component"]}
            crosses_fund_and_manager = bool(components & FUND_COMPONENTS) and bool(
                components & MANAGER_TENURE_COMPONENTS
            )
            same_raw_current_evidence = (
                left["source_scope"] == right["source_scope"] == "current_fund"
                and left["usage_mode"] == right["usage_mode"] == "raw"
                and (
                    left["lineage_id"] == right["lineage_id"]
                    or left["series_id"] == right["series_id"]
                )
            )
            left_start, left_end = windows[left_index]
            right_start, right_end = windows[right_index]
            windows_overlap = max(left_start, right_start) <= min(left_end, right_end)
            if crosses_fund_and_manager and same_raw_current_evidence and windows_overlap:
                raise EvidenceUsageValidationError(
                    "double-counted raw current_fund evidence: "
                    f"usage[{left_index}] and usage[{right_index}] have an identity "
                    f"collision involving lineage_id={left['lineage_id']!r}, "
                    f"series_id={left['series_id']!r}, "
                    f"evidence_family={left['evidence_family']!r}, and overlapping windows"
                )
