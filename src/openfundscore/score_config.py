"""Versioned scoring configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ConfigValidationError(ValueError):
    """Raised when a scoring configuration violates its public contract."""


_ALLOWED_MODEL_STATUSES = {"research-preview"}
_MODEL_IDENTITY_CONTRACT = {
    "model_id": "openfundscore-core",
    "model_version": "0.1.0",
}
_MANAGER_COMPONENT_WEIGHTS = {
    "tenure_attributed_performance": 25,
    "downside_control": 15,
    "cross_cycle_consistency": 15,
    "style_discipline": 15,
    "career_track_record": 10,
    "workload_capacity": 8,
    "research_platform_team": 7,
    "compliance_integrity": 5,
}
_DATA_CONFIDENCE_CONTRACT = {
    "role": "publication_gate",
    "levels": ["high", "medium", "low", "insufficient"],
    "missing_data_policy": "not_zero",
    "conflict_policy": "preserve_and_flag",
    "short_history_policy": "lower_confidence_not_higher_score",
}
_TOP_LEVEL_FIELDS = {
    "model_id",
    "model_version",
    "status",
    "score_dimensions",
    "category_profiles",
    "manager_model",
    "data_confidence",
}
_SCORE_DIMENSION_IDS = {
    "performance_evidence",
    "downside_risk",
    "consistency",
    "manager_capability",
    "portfolio_structure",
    "implementation_efficiency",
    "governance_operations",
}
_CATEGORY_PROFILE_IDS = {
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


def load_score_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON scoring configuration and validate its top-level shape."""
    config_path = Path(path)
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise ConfigValidationError(
            f"cannot read scoring config {config_path}: file is not valid UTF-8"
        ) from None
    except OSError as exc:
        detail = exc.strerror or str(exc) or type(exc).__name__
        raise ConfigValidationError(
            f"cannot read scoring config {config_path}: {detail}"
        ) from None
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(
            f"invalid JSON in scoring config {config_path}: {exc.msg}"
        ) from None

    if not isinstance(document, dict):
        raise ConfigValidationError("scoring config must be a JSON object")
    return document


def _validated_integer_weights(weights: Any, *, label: str) -> dict[str, int]:
    if not isinstance(weights, Mapping) or not weights:
        raise ConfigValidationError(f"{label} weights must be a non-empty object")

    validated: dict[str, int] = {}
    for name, value in weights.items():
        if not isinstance(name, str) or not name:
            raise ConfigValidationError(f"{label} weight names must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigValidationError(
                f"{label}.{name} weight must be a non-negative integer"
            )
        validated[name] = value

    total = sum(validated.values())
    if total != 100:
        raise ConfigValidationError(f"{label} weights total {total}, expected 100")
    return validated


def _reject_unknown_fields(
    value: Mapping[str, Any], *, allowed: set[str], label: str
) -> None:
    unknown = set(value) - allowed
    if unknown:
        rendered = ", ".join(sorted((repr(field) for field in unknown)))
        raise ConfigValidationError(f"{label} has unknown field(s): {rendered}")


def validate_score_config(document: Mapping[str, Any]) -> None:
    """Validate the stable v0 scoring configuration contract."""
    _reject_unknown_fields(document, allowed=_TOP_LEVEL_FIELDS, label="scoring config")

    for field in ("model_id", "model_version"):
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise ConfigValidationError(f"{field} must be a non-empty string")
        if value != _MODEL_IDENTITY_CONTRACT[field]:
            raise ConfigValidationError(
                f"{field} must be {_MODEL_IDENTITY_CONTRACT[field]!r}"
            )

    status = document.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_MODEL_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_MODEL_STATUSES))
        raise ConfigValidationError(f"status must be one of: {allowed}")

    dimensions = document.get("score_dimensions")
    if not isinstance(dimensions, Mapping) or len(dimensions) != 7:
        raise ConfigValidationError("score_dimensions must define exactly seven items")
    if set(dimensions) != _SCORE_DIMENSION_IDS:
        raise ConfigValidationError("score_dimensions must use the exact v0.1 dimension IDs")
    for name, description in dimensions.items():
        if not isinstance(name, str) or not name:
            raise ConfigValidationError("score_dimensions keys must be non-empty strings")
        if not isinstance(description, str) or not description:
            raise ConfigValidationError("score_dimensions values must be non-empty strings")
    if "data_confidence" in dimensions:
        raise ConfigValidationError("data_confidence must remain outside the 100-point score")

    profiles = document.get("category_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise ConfigValidationError("category_profiles must be a non-empty object")
    if set(profiles) != _CATEGORY_PROFILE_IDS:
        raise ConfigValidationError("category_profiles must use the exact v0.1 profile IDs")

    dimension_ids = set(dimensions)
    for category, profile in profiles.items():
        if not isinstance(profile, Mapping):
            raise ConfigValidationError(f"category profile {category} must be an object")
        _reject_unknown_fields(
            profile, allowed={"weights"}, label=f"category_profiles.{category}"
        )
        weights = _validated_integer_weights(
            profile.get("weights"), label=f"category_profiles.{category}"
        )
        weight_ids = set(weights)
        if weight_ids != dimension_ids:
            missing = sorted(dimension_ids - weight_ids)
            extra = sorted(weight_ids - dimension_ids)
            raise ConfigValidationError(
                f"category profile {category} dimension mismatch; "
                f"missing={missing}, extra={extra}"
            )

    manager_model = document.get("manager_model")
    if not isinstance(manager_model, Mapping):
        raise ConfigValidationError("manager_model must be an object")
    _reject_unknown_fields(
        manager_model, allowed={"total", "components"}, label="manager_model"
    )
    manager_total = manager_model.get("total")
    if isinstance(manager_total, bool) or not isinstance(manager_total, int):
        raise ConfigValidationError("manager_model.total must be the integer 100")
    if manager_total != 100:
        raise ConfigValidationError("manager_model.total must be 100")
    components = manager_model.get("components")
    if not isinstance(components, list) or not components:
        raise ConfigValidationError("manager_model.components must be a non-empty list")
    component_weights: dict[str, int] = {}
    for component in components:
        if not isinstance(component, Mapping):
            raise ConfigValidationError("each manager component must be an object")
        _reject_unknown_fields(
            component, allowed={"id", "weight"}, label="manager_model component"
        )
        component_id = component.get("id")
        weight = component.get("weight")
        if not isinstance(component_id, str) or not component_id:
            raise ConfigValidationError("manager component id must be a non-empty string")
        if component_id in component_weights:
            raise ConfigValidationError(f"duplicate manager component id: {component_id}")
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise ConfigValidationError(
                f"manager component {component_id} weight must be an integer"
            )
        component_weights[component_id] = weight
    _validated_integer_weights(component_weights, label="manager_model.components")
    if component_weights != _MANAGER_COMPONENT_WEIGHTS:
        raise ConfigValidationError(
            "manager_model.components must match the exact v0.1 component weights"
        )

    confidence = document.get("data_confidence")
    if not isinstance(confidence, Mapping):
        raise ConfigValidationError("data_confidence must be an object")
    _reject_unknown_fields(
        confidence,
        allowed=set(_DATA_CONFIDENCE_CONTRACT),
        label="data_confidence",
    )
    for field, expected in _DATA_CONFIDENCE_CONTRACT.items():
        if confidence.get(field) != expected:
            raise ConfigValidationError(
                f"data_confidence.{field} must be {expected!r}"
            )
