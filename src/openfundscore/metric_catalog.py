"""Versioned category-metric catalog loading and validation."""

from __future__ import annotations

import math
import re
from typing import Any

from .formula_cross_fields import (
    FORMULA_CROSS_FIELD_RULES,
    FormulaCrossFieldManifestError,
    validate_formula_rule_manifest,
)
from .metric_taxonomy import (
    APPLICABILITY,
    DATA_SOURCES,
    FORMULA_OWNER,
    FORMULA_SEMANTICS,
    SEMANTIC_FIELDS,
    UNITS,
    WINDOW_KINDS,
    WINDOW_UNITS,
)
from .resources import ResourceError, resolve_resource


class MetricCatalogValidationError(ValueError):
    """Stable fail-closed metric-catalog validation error."""


_PROFILE_IDS = {
    "active_equity_mixed",
    "fixed_income_plus",
    "index_etf",
    "bond",
    "money_market",
    "qdii_active",
    "qdii_index",
    "fof_pension",
    "gold_commodity",
    "public_reit",
}
_DIMENSION_IDS = {
    "performance_evidence",
    "downside_risk",
    "consistency",
    "portfolio_structure",
    "implementation_efficiency",
    "governance_operations",
}
_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", re.ASCII)
_FORMULA = re.compile(r"upstream_audited_raw/[a-z][a-z0-9_]{0,63}/0\.1\.0", re.ASCII)
_ENGINE_CONTRACT = {
    "formula_version": "robust-percentile-iqr-mad/0.1.0",
    "minimum_peer_sample": 5,
    "maximum_peer_sample": 10000,
    "winsorization": "iqr_1.5_then_mad_3.0_zero_dispersion_neutral",
    "ranking": "empirical_midrank",
    "subject_in_peer_policy": "target_fund_must_not_appear_in_peers",
    "raw_metric_ownership": "upstream_audited_observation",
    "optional_metric_denominator_policy": "fixed_no_reweighting",
}
_METRIC_FIELDS = {
    "applicability",
    "id",
    "weight",
    "direction",
    "core",
    "domain",
    "evidence_family",
    "formula",
    "formula_owner",
    "data_source",
    "observation_window",
    "provenance_required",
    "unit",
    "value_range",
}
_DOMAIN_BY_DIMENSION = {
    "performance_evidence": "performance_return",
    "downside_risk": "downside_risk",
    "consistency": "consistency_stability",
    "portfolio_structure": "portfolio_exposure",
    "implementation_efficiency": "implementation_cost",
    "governance_operations": "governance_control",
}
_CAPTURE_RATIO_FORMULAS = {
    "upstream_audited_raw/downside_capture/0.1.0",
    "upstream_audited_raw/currency_downside_capture/0.1.0",
}


def _error(message: str) -> None:
    raise MetricCatalogValidationError(message)


def _closed(value: object, *, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _error(f"{label} must be an object with the exact required fields")
    return value


def _ascii_identifier(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) > 64
        or _IDENTIFIER.fullmatch(value) is None
    ):
        _error(f"{label} must be a bounded ASCII snake_case identifier")
    return value


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(f"{label} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        _error(f"{label} must be a finite number")
    return converted


def _validate_formula_semantic(
    value: object, *, formula: str, label: str
) -> tuple[object, ...]:
    semantic = _closed(value, fields=set(SEMANTIC_FIELDS), label=label)
    if formula not in FORMULA_SEMANTICS:
        _error(f"{label} refers to an unknown formula")
    if semantic["formula_owner"] != FORMULA_OWNER:
        _error(f"{label}.formula_owner must preserve upstream raw ownership")
    if semantic["unit"] not in UNITS:
        _error(f"{label}.unit is unsupported")

    value_range = _closed(
        semantic["value_range"],
        fields={"minimum", "maximum"},
        label=f"{label}.value_range",
    )
    minimum = _finite_number(
        value_range["minimum"], label=f"{label}.value_range.minimum"
    )
    maximum = _finite_number(
        value_range["maximum"], label=f"{label}.value_range.maximum"
    )
    if minimum >= maximum:
        _error(f"{label}.value_range must have minimum below maximum")
    if semantic["unit"] == "ratio":
        expected_ratio_range = (
            (-5.0, 5.0) if formula in _CAPTURE_RATIO_FORMULAS else (0.0, 1.0)
        )
        if (minimum, maximum) != expected_ratio_range:
            _error(f"{label}.value_range must use its closed ratio range")
    if semantic["unit"] in {"percent", "score_0_100"} and (
        minimum,
        maximum,
    ) != (0.0, 100.0):
        _error(f"{label}.value_range must use the closed zero-to-100 range")
    if semantic["unit"] in {"basis_points", "count", "days", "months"} and (
        minimum < 0.0
    ):
        _error(f"{label}.value_range cannot admit negative values for its unit")

    window = _closed(
        semantic["observation_window"],
        fields={"kind", "unit", "minimum", "maximum"},
        label=f"{label}.observation_window",
    )
    if window["kind"] not in WINDOW_KINDS:
        _error(f"{label}.observation_window.kind is unsupported")
    if window["unit"] not in WINDOW_UNITS:
        _error(f"{label}.observation_window.unit is unsupported")
    window_minimum = window["minimum"]
    window_maximum = window["maximum"]
    if (
        type(window_minimum) is not int
        or type(window_maximum) is not int
        or not 0 <= window_minimum <= window_maximum <= 1200
    ):
        _error(f"{label}.observation_window bounds are invalid")
    if window["kind"] == "point_in_time":
        if (window["unit"], window_minimum, window_maximum) != ("instant", 0, 0):
            _error(f"{label}.observation_window point-in-time contract is invalid")
    elif window["unit"] != "months" or (
        window["kind"] != "cumulative_period" and window_minimum < 1
    ):
        _error(f"{label}.observation_window period contract is invalid")

    if semantic["applicability"] not in APPLICABILITY:
        _error(f"{label}.applicability is unsupported")
    if semantic["data_source"] not in DATA_SOURCES:
        _error(f"{label}.data_source is unsupported")
    if semantic != FORMULA_SEMANTICS[formula]:
        _error(f"{label} must match the formula's audited economic contract")

    return (
        semantic["domain"],
        semantic["unit"],
        minimum,
        maximum,
        window["kind"],
        window["unit"],
        window_minimum,
        window_maximum,
        semantic["applicability"],
        semantic["formula_owner"],
        semantic["data_source"],
    )


def _validate_metric_catalog(document: object) -> None:
    catalog = _closed(
        document,
        fields={
            "catalog_id",
            "catalog_version",
            "status",
            "scoring_config",
            "engine_contract",
            "formula_semantics",
            "profiles",
        },
        label="metric catalog",
    )
    expected_scalars = {
        "catalog_id": "openfundscore-category-metrics",
        "catalog_version": "0.1.0",
        "status": "research-preview",
    }
    for field, expected in expected_scalars.items():
        if type(catalog[field]) is not str or catalog[field] != expected:
            _error(f"metric catalog {field} must match the v0.1 contract")

    scoring = _closed(
        catalog["scoring_config"],
        fields={"name", "version"},
        label="scoring_config",
    )
    if scoring != {"name": "openfundscore-core", "version": "0.1.0"}:
        _error("scoring_config must reference openfundscore-core 0.1.0")

    engine = _closed(
        catalog["engine_contract"],
        fields=set(_ENGINE_CONTRACT),
        label="engine_contract",
    )
    for field, expected in _ENGINE_CONTRACT.items():
        if type(engine[field]) is not type(expected) or engine[field] != expected:
            _error(f"engine_contract.{field} must match the v0.1 contract")

    manifest = catalog["formula_semantics"]
    if type(manifest) is not dict or set(manifest) != set(FORMULA_SEMANTICS):
        _error("formula_semantics must define the exact 92 v0.1 formulas")
    for formula, semantic in manifest.items():
        if type(formula) is not str or _FORMULA.fullmatch(formula) is None:
            _error("formula_semantics keys must be valid upstream formulas")
        _validate_formula_semantic(
            semantic,
            formula=formula,
            label=f"formula_semantics.{formula}",
        )
    formula_names = {formula.split("/")[-2] for formula in manifest}
    if set(FORMULA_CROSS_FIELD_RULES) != formula_names:
        _error("cross-field rules must define the exact 92 v0.1 formulas")
    try:
        validate_formula_rule_manifest(FORMULA_CROSS_FIELD_RULES, manifest)
    except FormulaCrossFieldManifestError:
        _error("cross-field formula rule manifest is invalid")

    profiles = catalog["profiles"]
    if type(profiles) is not dict or set(profiles) != _PROFILE_IDS:
        _error("profiles must define the exact ten v0.1 profiles")
    formula_contracts: dict[str, tuple[object, ...]] = {}
    data_sources: set[str] = set()
    formula_count = 0
    for profile_id, profile_value in profiles.items():
        _ascii_identifier(profile_id, label="profile id")
        profile = _closed(
            profile_value,
            fields={"dimensions"},
            label=f"profiles.{profile_id}",
        )
        dimensions = profile["dimensions"]
        if type(dimensions) is not dict or set(dimensions) != _DIMENSION_IDS:
            _error(
                f"profiles.{profile_id}.dimensions must define the exact six dimensions"
            )
        seen_ids: set[str] = set()
        seen_families: set[str] = set()
        for dimension, metric_values in dimensions.items():
            if type(metric_values) is not list or len(metric_values) != 2:
                _error(
                    f"profiles.{profile_id}.{dimension} must define exactly two metrics"
                )
            weight_total = 0
            for index, metric_value in enumerate(metric_values):
                label = f"profiles.{profile_id}.{dimension}[{index}]"
                metric = _closed(metric_value, fields=_METRIC_FIELDS, label=label)
                metric_id = _ascii_identifier(metric["id"], label=f"{label}.id")
                if metric_id in seen_ids:
                    _error(f"{label}.id must be unique within the profile")
                seen_ids.add(metric_id)
                weight = metric["weight"]
                if type(weight) is not int or not 0 <= weight <= 100:
                    _error(f"{label}.weight must be an integer from 0 through 100")
                weight_total += weight
                if metric["direction"] not in {
                    "higher_is_better",
                    "lower_is_better",
                }:
                    _error(f"{label}.direction is unsupported")
                if metric["core"] is not True:
                    _error(f"{label}.core must be true in catalog 0.1.0")
                family = metric["evidence_family"]
                if (
                    type(family) is not str
                    or not family
                    or len(family) > 200
                    or not family.isascii()
                    or family in seen_families
                ):
                    _error(f"{label}.evidence_family must be unique bounded ASCII text")
                seen_families.add(family)
                formula = metric["formula"]
                if type(formula) is not str or _FORMULA.fullmatch(formula) is None:
                    _error(
                        f"{label}.formula must declare the upstream formula contract"
                    )
                semantic = {field: metric[field] for field in SEMANTIC_FIELDS}
                contract = _validate_formula_semantic(
                    semantic,
                    formula=formula,
                    label=f"{label}.semantic",
                )
                if metric["domain"] != _DOMAIN_BY_DIMENSION[dimension]:
                    _error(f"{label}.domain must match the declared scoring dimension")
                data_sources.add(metric["data_source"])
                if metric["provenance_required"] is not True:
                    _error(f"{label}.provenance_required must be true")
                prior = formula_contracts.setdefault(formula, contract)
                if prior != contract:
                    _error(f"{label}.formula taxonomy conflicts with another entry")
                formula_count += 1
            if weight_total != 100:
                _error(
                    f"profiles.{profile_id}.{dimension} metric weights must total 100"
                )
    if formula_count != 120 or len(formula_contracts) != 92:
        _error("metric catalog must define 120 entries and 92 formula contracts")
    if len(data_sources) < 6:
        _error("metric catalog must use a meaningful source-family taxonomy")


def validate_metric_catalog(document: object) -> None:
    """Validate the closed v0.1 metric-catalog contract."""
    try:
        _validate_metric_catalog(document)
    except MetricCatalogValidationError:
        raise
    except Exception:  # noqa: BLE001 - stable public error boundary
        raise MetricCatalogValidationError(
            "metric catalog validation failed at the public boundary"
        ) from None


def load_metric_catalog(version: str = "0.1.0") -> tuple[dict[str, Any], str]:
    """Load and validate one exact packaged catalog version and return its digest."""
    try:
        resource = resolve_resource(
            resource_type="metric-catalog",
            name="openfundscore-category-metrics",
            version=version,
        )
        document = resource.load_json()
        validate_metric_catalog(document)
    except (ResourceError, MetricCatalogValidationError):
        raise MetricCatalogValidationError(
            "metric catalog could not be loaded or validated"
        ) from None
    return document, resource.info.sha256
