"""Independent formula-rule manifest and cross-field economics."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Literal

FormulaCrossFieldRuleKind = Literal[
    "independent_range",
    "period_sample",
    "negative_day_count",
    "recovery_duration_months",
    "event_duration_days",
    "point_in_time_maturity_days",
]


@dataclass(frozen=True, slots=True)
class FormulaCrossFieldRule:
    """One reviewed formula rule and the reason that rule is sufficient."""

    kind: FormulaCrossFieldRuleKind
    reason: str


class FormulaCrossFieldManifestError(ValueError):
    """The independent 92-formula rule manifest is incomplete or incompatible."""


class FormulaCrossFieldValidationError(ValueError):
    """An observation is impossible under its formula's economic contract."""


def _rule(kind: FormulaCrossFieldRuleKind, reason: str) -> FormulaCrossFieldRule:
    return FormulaCrossFieldRule(kind=kind, reason=reason)


_PIT_REASON = (
    "Point-in-time snapshot value is independent of elapsed months and is fully "
    "bounded by its audited scalar range; no period sample relation is meaningful."
)
_PERIOD_REASON = (
    "Period-derived value requires at least monthly coverage and cannot claim more "
    "than daily observations within its UTC calendar window."
)

# Formula names are listed explicitly. This is not a name-token classifier and no
# unknown/window-only placeholder is accepted by validate_formula_rule_manifest().
FORMULA_CROSS_FIELD_RULES: Final[dict[str, FormulaCrossFieldRule]] = {
    "absolute_tracking_difference": _rule("period_sample", _PERIOD_REASON),
    "allocation_effect": _rule("period_sample", _PERIOD_REASON),
    "allocation_process_disclosure": _rule("independent_range", _PIT_REASON),
    "annualized_benchmark_excess": _rule("period_sample", _PERIOD_REASON),
    "asset_quality": _rule("independent_range", _PIT_REASON),
    "asset_valuation_governance": _rule("independent_range", _PIT_REASON),
    "below_investment_grade_exposure": _rule("independent_range", _PIT_REASON),
    "benchmark_coverage": _rule("independent_range", _PIT_REASON),
    "benchmark_excess": _rule("period_sample", _PERIOD_REASON),
    "benchmark_excess_return": _rule("period_sample", _PERIOD_REASON),
    "benchmark_return_gap": _rule("period_sample", _PERIOD_REASON),
    "benchmark_yield_excess": _rule("period_sample", _PERIOD_REASON),
    "carry_efficiency": _rule("period_sample", _PERIOD_REASON),
    "carry_roll_excess": _rule("period_sample", _PERIOD_REASON),
    "collateral_quality": _rule("independent_range", _PIT_REASON),
    "concentration_deviation": _rule("independent_range", _PIT_REASON),
    "concentration_hhi": _rule("independent_range", _PIT_REASON),
    "contract_concentration": _rule("independent_range", _PIT_REASON),
    "country_weight_deviation": _rule("independent_range", _PIT_REASON),
    "credit_concentration": _rule("independent_range", _PIT_REASON),
    "credit_drawdown": _rule("period_sample", _PERIOD_REASON),
    "credit_event_disclosure": _rule("independent_range", _PIT_REASON),
    "credit_valuation_controls": _rule("independent_range", _PIT_REASON),
    "cross_border_custody_controls": _rule("independent_range", _PIT_REASON),
    "cross_border_disclosure": _rule("independent_range", _PIT_REASON),
    "currency_adjusted_excess": _rule("period_sample", _PERIOD_REASON),
    "currency_adjusted_tracking_gap": _rule("period_sample", _PERIOD_REASON),
    "currency_concentration": _rule("independent_range", _PIT_REASON),
    "currency_downside_capture": _rule("period_sample", _PERIOD_REASON),
    "currency_stress_loss": _rule("period_sample", _PERIOD_REASON),
    "custody_or_collateral_controls": _rule("independent_range", _PIT_REASON),
    "disclosure_timeliness": _rule("period_sample", _PERIOD_REASON),
    "distribution_growth": _rule("period_sample", _PERIOD_REASON),
    "distribution_stability": _rule("period_sample", _PERIOD_REASON),
    "distribution_stress_loss": _rule("period_sample", _PERIOD_REASON),
    "downside_capture": _rule("period_sample", _PERIOD_REASON),
    "duration_mandate_fit": _rule("independent_range", _PIT_REASON),
    "expected_shortfall": _rule("period_sample", _PERIOD_REASON),
    "factor_residual_alpha": _rule("period_sample", _PERIOD_REASON),
    "futures_stress_loss": _rule("period_sample", _PERIOD_REASON),
    "fx_hedge_stability": _rule("period_sample", _PERIOD_REASON),
    "fx_implementation_cost": _rule("period_sample", _PERIOD_REASON),
    "fx_tracking_error": _rule("period_sample", _PERIOD_REASON),
    "global_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "high_quality_liquid_assets": _rule("independent_range", _PIT_REASON),
    "index_method_disclosure": _rule("independent_range", _PIT_REASON),
    "lifecycle_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "liquidity_cost": _rule("period_sample", _PERIOD_REASON),
    "liquidity_governance_quality": _rule("independent_range", _PIT_REASON),
    "liquidity_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "liquidity_stress_loss": _rule("period_sample", _PERIOD_REASON),
    "lookthrough_concentration": _rule("independent_range", _PIT_REASON),
    "lookthrough_total_cost": _rule("period_sample", _PERIOD_REASON),
    "mandate_active_share": _rule("independent_range", _PIT_REASON),
    "mandate_country_fit": _rule("independent_range", _PIT_REASON),
    "market_liquidity_cost": _rule("period_sample", _PERIOD_REASON),
    "maximum_drawdown": _rule("period_sample", _PERIOD_REASON),
    "negative_return_days": _rule(
        "negative_day_count",
        "Negative-return days cannot exceed sampled observations or calendar days in the window.",
    ),
    "occupancy_persistence": _rule("period_sample", _PERIOD_REASON),
    "ongoing_charge": _rule("period_sample", _PERIOD_REASON),
    "policy_benchmark_excess": _rule("period_sample", _PERIOD_REASON),
    "rate_credit_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "rate_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "recovery_months": _rule(
        "recovery_duration_months",
        "Recovery duration in months cannot exceed its cumulative observation window.",
    ),
    "redemption_liquidity_buffer": _rule("independent_range", _PIT_REASON),
    "regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "related_party_controls": _rule("independent_range", _PIT_REASON),
    "replication_method_stability": _rule("period_sample", _PERIOD_REASON),
    "roll_implementation_cost": _rule("period_sample", _PERIOD_REASON),
    "roll_regime_persistence": _rule("period_sample", _PERIOD_REASON),
    "roll_yield_efficiency": _rule("period_sample", _PERIOD_REASON),
    "rolling_excess_hit_rate": _rule("period_sample", _PERIOD_REASON),
    "rolling_goal_hit_rate": _rule("period_sample", _PERIOD_REASON),
    "rolling_positive_excess": _rule("period_sample", _PERIOD_REASON),
    "rolling_tracking_stability": _rule("period_sample", _PERIOD_REASON),
    "rolling_yield_rank_stability": _rule("period_sample", _PERIOD_REASON),
    "securities_lending_controls": _rule("independent_range", _PIT_REASON),
    "settlement_delay": _rule(
        "event_duration_days",
        "Settlement delay is an event duration bounded by calendar days in its reporting window.",
    ),
    "seven_day_yield_stability": _rule("period_sample", _PERIOD_REASON),
    "shadow_nav_disclosure": _rule("independent_range", _PIT_REASON),
    "spot_tracking_gap": _rule("period_sample", _PERIOD_REASON),
    "tenant_concentration": _rule("independent_range", _PIT_REASON),
    "total_expense": _rule("period_sample", _PERIOD_REASON),
    "total_return_excess": _rule("period_sample", _PERIOD_REASON),
    "tracking_error": _rule("period_sample", _PERIOD_REASON),
    "underlying_diversification": _rule("independent_range", _PIT_REASON),
    "underlying_due_diligence": _rule("independent_range", _PIT_REASON),
    "underlying_liquidity_cost": _rule("period_sample", _PERIOD_REASON),
    "valuation_control_quality": _rule("independent_range", _PIT_REASON),
    "valuation_cutoff_controls": _rule("independent_range", _PIT_REASON),
    "valuation_method_disclosure": _rule("independent_range", _PIT_REASON),
    "weighted_average_maturity": _rule(
        "point_in_time_maturity_days",
        "Money-market WAM is a point-in-time holdings duration bounded by the catalog screening ceiling.",
    ),
}

_ALLOWED_KINDS = frozenset(
    {
        "independent_range",
        "period_sample",
        "negative_day_count",
        "recovery_duration_months",
        "event_duration_days",
        "point_in_time_maturity_days",
    }
)
_SPECIAL_KINDS: Final[dict[str, FormulaCrossFieldRuleKind]] = {
    "negative_return_days": "negative_day_count",
    "recovery_months": "recovery_duration_months",
    "settlement_delay": "event_duration_days",
    "weighted_average_maturity": "point_in_time_maturity_days",
}


def validate_formula_rule_manifest(
    rules: Mapping[str, FormulaCrossFieldRule],
    formula_semantics: Mapping[str, Mapping[str, object]],
) -> None:
    """Validate the manifest independently from catalog profile-row validation."""
    expected = {formula.split("/")[-2] for formula in formula_semantics}
    if set(rules) != expected or len(rules) != 92:
        raise FormulaCrossFieldManifestError(
            "formula rule manifest must cover the exact 92 semantic formulas"
        )
    forbidden_reason_tokens = ("todo", "placeholder", "window_only", "unknown")
    semantics_by_name = {
        formula.split("/")[-2]: semantic
        for formula, semantic in formula_semantics.items()
    }
    for name, rule in rules.items():
        if type(rule) is not FormulaCrossFieldRule or rule.kind not in _ALLOWED_KINDS:
            raise FormulaCrossFieldManifestError(f"{name} has an unknown rule kind")
        normalized_reason = rule.reason.strip().lower()
        if (
            not normalized_reason
            or len(rule.reason) > 500
            or not rule.reason.isascii()
            or any(token in normalized_reason for token in forbidden_reason_tokens)
        ):
            raise FormulaCrossFieldManifestError(
                f"{name} must have a substantive bounded ASCII review reason"
            )
        semantic = semantics_by_name[name]
        window = semantic.get("observation_window")
        if not isinstance(window, Mapping):
            raise FormulaCrossFieldManifestError(f"{name} has no semantic window")
        expected_kind = _SPECIAL_KINDS.get(
            name,
            "independent_range"
            if window.get("kind") == "point_in_time"
            else "period_sample",
        )
        if rule.kind != expected_kind:
            raise FormulaCrossFieldManifestError(
                f"{name} rule kind is incompatible with its unit/window semantics"
            )


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _calendar_days(observation_as_of: datetime, window_months: int) -> int:
    utc_date = observation_as_of.astimezone(UTC).date()
    return (utc_date - _subtract_months(utc_date, window_months)).days


def validate_formula_cross_fields(
    *,
    formula: str,
    raw_value: float,
    sample_size: int,
    window_months: int,
    observation_as_of: datetime,
) -> None:
    """Validate one observed metric against its explicit reviewed rule."""
    formula_name = formula.removeprefix("upstream_audited_raw/").removesuffix("/0.1.0")
    rule = FORMULA_CROSS_FIELD_RULES.get(formula_name)
    if rule is None:
        raise FormulaCrossFieldValidationError(
            "formula has no reviewed cross-field economic rule"
        )
    if type(sample_size) is not int or sample_size <= 0:
        raise FormulaCrossFieldValidationError(
            "observed metric sample size must be a positive built-in integer"
        )
    if type(window_months) is not int or window_months < 0:
        raise FormulaCrossFieldValidationError(
            "metric window months must be a non-negative built-in integer"
        )
    calendar_days = _calendar_days(observation_as_of, window_months)
    inclusive_day_capacity = calendar_days + 1
    if (
        rule.kind
        in {
            "negative_day_count",
            "recovery_duration_months",
            "event_duration_days",
            "point_in_time_maturity_days",
        }
        and type(raw_value) is not int
    ):
        raise FormulaCrossFieldValidationError(
            "count, day, and month values must be built-in integers"
        )
    if rule.kind == "independent_range":
        if window_months != 0:
            raise FormulaCrossFieldValidationError(
                "point-in-time independent metric cannot declare an elapsed month window"
            )
    elif rule.kind == "period_sample":
        if (
            window_months <= 0
            or sample_size < window_months
            or sample_size > inclusive_day_capacity
        ):
            raise FormulaCrossFieldValidationError(
                "period metric sample must cover each month without exceeding daily calendar coverage"
            )
    elif rule.kind == "negative_day_count":
        if (
            window_months <= 0
            or sample_size < window_months
            or raw_value > sample_size
            or sample_size > inclusive_day_capacity
        ):
            raise FormulaCrossFieldValidationError(
                "negative-return count requires monthly coverage and cannot exceed samples or inclusive calendar days"
            )
    elif rule.kind == "recovery_duration_months":
        if raw_value > window_months or (raw_value > 0 and window_months == 0):
            raise FormulaCrossFieldValidationError(
                "recovery duration cannot exceed or exist outside its observation window"
            )
    elif rule.kind == "event_duration_days":
        if window_months <= 0 or raw_value > inclusive_day_capacity:
            raise FormulaCrossFieldValidationError(
                "event duration cannot exceed inclusive calendar days in its reporting window"
            )
    elif rule.kind == "point_in_time_maturity_days" and window_months != 0:
        raise FormulaCrossFieldValidationError(
            "point-in-time maturity cannot declare an elapsed month window"
        )
