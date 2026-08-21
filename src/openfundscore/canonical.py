"""Typed canonical fund entities for local, point-in-time research."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import urlsplit


class CanonicalValidationError(ValueError):
    """Raised when a canonical entity violates its public contract."""


def _require_non_empty(label: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalValidationError(f"{label} must be a non-empty string")


def _require_aware(label: str, value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanonicalValidationError(f"{label} must be a timezone-aware datetime")


def _require_date_only(label: str, value: object) -> None:
    if type(value) is not date:
        raise CanonicalValidationError(f"{label} must be a date")


def _require_currency(label: str, value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise CanonicalValidationError(
            f"{label} must be an ISO 4217-style currency code"
        )


def _require_http_url(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise CanonicalValidationError(f"{label} must be an HTTP(S) URL")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise CanonicalValidationError(f"{label} must be an HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CanonicalValidationError(f"{label} must be an HTTP(S) URL")
    return value


def _require_tuple_of(
    label: str,
    value: object,
    item_type: type[Any],
    *,
    non_empty: bool = False,
) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, item_type) for item in value
    ):
        raise CanonicalValidationError(
            f"{label} must be a tuple of {item_type.__name__} values"
        )
    if non_empty and not value:
        raise CanonicalValidationError(f"{label} must not be empty")


@dataclass(frozen=True)
class ExternalIdentifier:
    """A provider-independent exact identifier; names are never identifiers."""

    scheme: str
    value: str
    jurisdiction: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("scheme", self.scheme)
        _require_non_empty("value", self.value)
        if self.jurisdiction is not None:
            _require_non_empty("jurisdiction", self.jurisdiction)


@dataclass(frozen=True, kw_only=True)
class CanonicalRecord:
    """Common immutable metadata for one effective-dated entity version."""

    record_id: str
    source_provider_id: str
    as_of: datetime
    published_at: datetime
    fetched_at: datetime
    valid_from: datetime
    quality_state: str
    valid_to: datetime | None = None
    conflict_group: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("record_id", self.record_id)
        _require_non_empty("source_provider_id", self.source_provider_id)
        for label in ("as_of", "published_at", "fetched_at", "valid_from"):
            _require_aware(label, getattr(self, label))
        if self.valid_to is not None:
            _require_aware("valid_to", self.valid_to)
            if self.valid_from > self.valid_to:
                raise CanonicalValidationError(
                    "valid_from must be on or before valid_to"
                )
        if self.published_at > self.fetched_at:
            raise CanonicalValidationError(
                "published_at must be on or before fetched_at"
            )
        if self.quality_state not in {
            "verified",
            "unverified",
            "stale",
            "conflict",
            "missing",
            "not_applicable",
        }:
            raise CanonicalValidationError(
                f"unknown quality_state {self.quality_state!r}"
            )
        if self.conflict_group is not None:
            _require_non_empty("conflict_group", self.conflict_group)
        if self.quality_state == "conflict" and self.conflict_group is None:
            raise CanonicalValidationError(
                "quality_state 'conflict' requires conflict_group"
            )
        if self.quality_state != "conflict" and self.conflict_group is not None:
            raise CanonicalValidationError(
                "conflict_group requires quality_state 'conflict'"
            )


_STRATEGY_PROFILES = {
    "money_market",
    "bond",
    "fixed_income_plus",
    "active_equity_mixed",
    "index_etf",
    "qdii_active",
    "qdii_index",
    "fof_pension",
    "gold_commodity",
    "public_reit",
    "unrated",
}


@dataclass(frozen=True, kw_only=True)
class FundLifecycleEvent:
    """An append-only closed, merged or transformed strategy event."""

    event_id: str
    event_type: str
    effective_at: datetime
    evidence_ids: tuple[str, ...]
    successor_strategy_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("event_id", self.event_id)
        if self.event_type not in {"closed", "merged", "transformed"}:
            raise CanonicalValidationError(
                f"unknown lifecycle event_type {self.event_type!r}"
            )
        _require_aware("effective_at", self.effective_at)
        if not self.evidence_ids or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_ids
        ):
            raise CanonicalValidationError(
                "lifecycle event evidence_ids must be non-empty strings"
            )
        if self.event_type == "merged" and self.successor_strategy_id is None:
            raise CanonicalValidationError(
                "merged lifecycle event requires successor_strategy_id"
            )
        if self.event_type == "closed" and self.successor_strategy_id is not None:
            raise CanonicalValidationError(
                "closed lifecycle event cannot have successor_strategy_id"
            )
        if self.successor_strategy_id is not None:
            _require_non_empty("successor_strategy_id", self.successor_strategy_id)


@dataclass(frozen=True, kw_only=True)
class FundStrategy(CanonicalRecord):
    """A strategy entity shared by all economically equivalent share classes."""

    fund_strategy_id: str
    canonical_name: str
    identifiers: tuple[ExternalIdentifier, ...]
    jurisdiction: str
    strategy_profile: str
    vehicle_type: str
    management_style: str
    asset_class: str
    base_currency: str
    inception_date: date
    status: str
    lifecycle_events: tuple[FundLifecycleEvent, ...] = ()
    primary_benchmark_id: str | None = None
    mandate: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for label in (
            "fund_strategy_id",
            "canonical_name",
            "jurisdiction",
            "vehicle_type",
            "management_style",
            "asset_class",
        ):
            _require_non_empty(label, getattr(self, label))
        _require_tuple_of(
            "identifiers",
            self.identifiers,
            ExternalIdentifier,
            non_empty=True,
        )
        if self.strategy_profile not in _STRATEGY_PROFILES:
            raise CanonicalValidationError(
                f"unknown strategy_profile {self.strategy_profile!r}"
            )
        _require_currency("base_currency", self.base_currency)
        _require_date_only("inception_date", self.inception_date)
        if self.status not in {"active", "closed", "merged", "transformed"}:
            raise CanonicalValidationError(
                f"unknown fund strategy status {self.status!r}"
            )
        _require_tuple_of(
            "lifecycle_events",
            self.lifecycle_events,
            FundLifecycleEvent,
        )
        event_ids = [event.event_id for event in self.lifecycle_events]
        if len(event_ids) != len(set(event_ids)):
            raise CanonicalValidationError("lifecycle event_id values must be unique")
        matching_events = tuple(
            event for event in self.lifecycle_events if event.event_type == self.status
        )
        if self.status != "active" and not matching_events:
            raise CanonicalValidationError(
                f"status {self.status!r} requires a matching lifecycle event"
            )
        if self.status != "active" and not any(
            event.effective_at == self.valid_from for event in matching_events
        ):
            raise CanonicalValidationError(
                "lifecycle status version must start at the matching event"
            )
        for event in self.lifecycle_events:
            if event.successor_strategy_id == self.fund_strategy_id:
                raise CanonicalValidationError(
                    "lifecycle successor_strategy_id must differ from fund_strategy_id"
                )
        if self.primary_benchmark_id is not None:
            _require_non_empty("primary_benchmark_id", self.primary_benchmark_id)
        if self.mandate is not None:
            _require_non_empty("mandate", self.mandate)


@dataclass(frozen=True, kw_only=True)
class FeeSchedule:
    """Share-class fees encoded as integer basis points."""

    management_fee_bps: int = 0
    custody_fee_bps: int = 0
    sales_service_fee_bps: int = 0
    subscription_fee_bps: int = 0
    redemption_fee_bps: int = 0

    def __post_init__(self) -> None:
        for label in (
            "management_fee_bps",
            "custody_fee_bps",
            "sales_service_fee_bps",
            "subscription_fee_bps",
            "redemption_fee_bps",
        ):
            value = getattr(self, label)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 10_000
            ):
                raise CanonicalValidationError(
                    f"{label} must be an integer in [0, 10000]"
                )

    @property
    def is_basis_point_encoded(self) -> bool:
        return True


@dataclass(frozen=True, kw_only=True)
class ShareClass(CanonicalRecord):
    """A fee, dealing and distribution wrapper around one fund strategy."""

    share_class_id: str
    fund_strategy_id: str
    canonical_name: str
    class_code: str
    identifiers: tuple[ExternalIdentifier, ...]
    dealing_currency: str
    distribution_policy: str
    investor_type: str
    subscription_status: str
    redemption_status: str
    inception_date: date
    fee_schedule: FeeSchedule = field(default_factory=FeeSchedule)
    termination_date: date | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for label in (
            "share_class_id",
            "fund_strategy_id",
            "canonical_name",
            "class_code",
            "distribution_policy",
            "investor_type",
        ):
            _require_non_empty(label, getattr(self, label))
        _require_tuple_of(
            "identifiers",
            self.identifiers,
            ExternalIdentifier,
            non_empty=True,
        )
        _require_currency("dealing_currency", self.dealing_currency)
        if not isinstance(self.fee_schedule, FeeSchedule):
            raise CanonicalValidationError("fee_schedule must be a FeeSchedule")
        _require_date_only("inception_date", self.inception_date)
        if self.termination_date is not None:
            _require_date_only("termination_date", self.termination_date)
            if self.inception_date > self.termination_date:
                raise CanonicalValidationError(
                    "inception_date must be on or before termination_date"
                )
        for label in ("subscription_status", "redemption_status"):
            value = getattr(self, label)
            if value not in {"open", "suspended", "closed"}:
                raise CanonicalValidationError(f"unknown {label} {value!r}")


@dataclass(frozen=True, kw_only=True)
class Benchmark(CanonicalRecord):
    """A contractual or analytical comparison benchmark."""

    benchmark_id: str
    canonical_name: str
    identifiers: tuple[ExternalIdentifier, ...]
    benchmark_type: str
    currency: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty("benchmark_id", self.benchmark_id)
        _require_non_empty("canonical_name", self.canonical_name)
        _require_tuple_of(
            "identifiers",
            self.identifiers,
            ExternalIdentifier,
            non_empty=True,
        )
        if self.benchmark_type not in {
            "index",
            "composite",
            "peer_rate",
            "contractual",
        }:
            raise CanonicalValidationError(
                f"unknown benchmark_type {self.benchmark_type!r}"
            )
        _require_currency("currency", self.currency)


@dataclass(frozen=True, kw_only=True)
class Manager(CanonicalRecord):
    """A public professional identity, separate from private-person data."""

    manager_id: str
    canonical_name: str
    identifiers: tuple[ExternalIdentifier, ...]
    current_employer_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty("manager_id", self.manager_id)
        _require_non_empty("canonical_name", self.canonical_name)
        _require_tuple_of(
            "identifiers",
            self.identifiers,
            ExternalIdentifier,
            non_empty=True,
        )
        if self.current_employer_id is not None:
            _require_non_empty("current_employer_id", self.current_employer_id)


@dataclass(frozen=True, kw_only=True)
class ManagerTenure(CanonicalRecord):
    """An exact manager-to-strategy responsibility window."""

    tenure_id: str
    fund_strategy_id: str
    manager_id: str
    role: str
    attribution_mode: str
    attribution_share: float | None
    tenure_start: date
    tenure_end: date | None

    def __post_init__(self) -> None:
        super().__post_init__()
        for label in ("tenure_id", "fund_strategy_id", "manager_id"):
            _require_non_empty(label, getattr(self, label))
        if self.role not in {
            "lead",
            "co_manager",
            "team_member",
            "adviser",
            "operator",
        }:
            raise CanonicalValidationError(f"unknown manager role {self.role!r}")
        if self.attribution_mode not in {"individual", "team", "role_weighted"}:
            raise CanonicalValidationError(
                f"unknown attribution_mode {self.attribution_mode!r}"
            )
        if self.attribution_mode == "role_weighted":
            if (
                not isinstance(self.attribution_share, (int, float))
                or isinstance(self.attribution_share, bool)
                or not 0 <= self.attribution_share <= 1
            ):
                raise CanonicalValidationError(
                    "role_weighted attribution requires attribution_share in [0, 1]"
                )
        elif self.attribution_share is not None:
            raise CanonicalValidationError(
                "attribution_share is only valid for role_weighted attribution"
            )
        _require_date_only("tenure_start", self.tenure_start)
        if self.tenure_end is not None:
            _require_date_only("tenure_end", self.tenure_end)
            if self.tenure_start > self.tenure_end:
                raise CanonicalValidationError(
                    "tenure_start must be on or before tenure_end"
                )


@dataclass(frozen=True, kw_only=True)
class HoldingPosition:
    """One exact-identifier holding expressed in integer basis points."""

    instrument_id: str
    asset_type: str
    weight_bps: int
    issuer_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("instrument_id", self.instrument_id)
        _require_non_empty("asset_type", self.asset_type)
        if (
            not isinstance(self.weight_bps, int)
            or isinstance(self.weight_bps, bool)
            or not 0 <= self.weight_bps <= 10_000
        ):
            raise CanonicalValidationError(
                "weight_bps must be an integer in [0, 10000]"
            )
        if self.issuer_id is not None:
            _require_non_empty("issuer_id", self.issuer_id)


@dataclass(frozen=True, kw_only=True)
class HoldingSnapshot(CanonicalRecord):
    """A fund-strategy holding snapshot, never a share-class holding copy."""

    snapshot_id: str
    fund_strategy_id: str
    currency: str
    positions: tuple[HoldingPosition, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty("snapshot_id", self.snapshot_id)
        _require_non_empty("fund_strategy_id", self.fund_strategy_id)
        _require_currency("currency", self.currency)
        _require_tuple_of("positions", self.positions, HoldingPosition)
        instrument_ids = [position.instrument_id for position in self.positions]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise CanonicalValidationError(
                "holding positions must not repeat an instrument_id"
            )
        if sum(position.weight_bps for position in self.positions) > 10_000:
            raise CanonicalValidationError(
                "holding position weights must not exceed 10000 basis points"
            )


@dataclass(frozen=True, kw_only=True)
class Evidence(CanonicalRecord):
    """A public, auditable fact supporting one canonical entity."""

    evidence_id: str
    subject_type: str
    subject_id: str
    tier: str
    source_url: str
    fact_excerpt: str | None
    content_hash: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty("evidence_id", self.evidence_id)
        if self.subject_type not in {
            "fund_strategy",
            "share_class",
            "benchmark",
            "manager",
            "manager_tenure",
            "holding_snapshot",
        }:
            raise CanonicalValidationError(
                f"unknown evidence subject_type {self.subject_type!r}"
            )
        _require_non_empty("subject_id", self.subject_id)
        if self.tier not in {"A", "B", "C", "D"}:
            raise CanonicalValidationError(f"unknown evidence tier {self.tier!r}")
        _require_http_url("source_url", self.source_url)
        if self.fact_excerpt is None and self.content_hash is None:
            raise CanonicalValidationError(
                "evidence requires fact_excerpt or content_hash"
            )
        if self.fact_excerpt is not None:
            _require_non_empty("fact_excerpt", self.fact_excerpt)
        if self.subject_type in {"manager", "manager_tenure"}:
            from .manager_research import (
                validate_public_professional_source_url,
                validate_public_professional_text,
            )

            try:
                validate_public_professional_source_url(self.source_url)
                if self.fact_excerpt is not None:
                    validate_public_professional_text(
                        self.fact_excerpt, "$.fact_excerpt"
                    )
            except ValueError as exc:
                raise CanonicalValidationError(str(exc)) from exc
        if self.content_hash is not None:
            _require_non_empty("content_hash", self.content_hash)


CanonicalEntity = (
    FundStrategy
    | ShareClass
    | Benchmark
    | Manager
    | ManagerTenure
    | HoldingSnapshot
    | Evidence
)

_RECORD_TYPES: dict[str, type[CanonicalRecord]] = {
    "fund_strategy": FundStrategy,
    "share_class": ShareClass,
    "benchmark": Benchmark,
    "manager": Manager,
    "manager_tenure": ManagerTenure,
    "holding_snapshot": HoldingSnapshot,
    "evidence": Evidence,
}
_TYPE_NAMES = {record_type: name for name, record_type in _RECORD_TYPES.items()}
_ENTITY_ID_ATTRIBUTES = {
    FundStrategy: "fund_strategy_id",
    ShareClass: "share_class_id",
    Benchmark: "benchmark_id",
    Manager: "manager_id",
    ManagerTenure: "tenure_id",
    HoldingSnapshot: "snapshot_id",
    Evidence: "evidence_id",
}


def resolve_external_identifier(
    records: tuple[CanonicalEntity, ...] | list[CanonicalEntity],
    identifier: ExternalIdentifier,
) -> tuple[tuple[str, str], ...]:
    """Resolve exact identifiers; canonical names are deliberately ignored."""
    matches: set[tuple[str, str]] = set()
    for record in records:
        identifiers = getattr(record, "identifiers", ())
        if identifier not in identifiers:
            continue
        record_type = _TYPE_NAMES[type(record)]
        entity_id = getattr(record, _ENTITY_ID_ATTRIBUTES[type(record)])
        matches.add((record_type, entity_id))
    return tuple(sorted(matches))


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)
        }
    return value


def record_to_document(record: CanonicalEntity) -> dict[str, Any]:
    """Return the versioned, JSON-compatible canonical document."""
    record_type = _TYPE_NAMES.get(type(record))
    if record_type is None:
        raise CanonicalValidationError(
            f"unsupported canonical record type {type(record).__name__}"
        )
    return {
        "schema_version": "0.2.0",
        "record_type": record_type,
        **{
            field.name: _encode(getattr(record, field.name)) for field in fields(record)
        },
    }


def _parse_datetime(label: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise CanonicalValidationError(f"{label} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CanonicalValidationError(f"{label} must be an ISO-8601 datetime") from exc
    _require_aware(label, parsed)
    return parsed


def _parse_date(label: str, value: Any) -> date:
    if not isinstance(value, str):
        raise CanonicalValidationError(f"{label} must be an ISO-8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CanonicalValidationError(f"{label} must be an ISO-8601 date") from exc


def _build_nested(label: str, constructor: Callable[[], Any]) -> Any:
    try:
        return constructor()
    except (CanonicalValidationError, KeyError, TypeError) as exc:
        raise CanonicalValidationError(
            f"invalid nested canonical value at {label}: {exc}"
        ) from exc


def record_from_document(document: object) -> CanonicalEntity:
    """Validate and restore one canonical entity document."""
    if not isinstance(document, Mapping):
        raise CanonicalValidationError("canonical document must be an object")
    if document.get("schema_version") != "0.2.0":
        raise CanonicalValidationError("schema_version must be '0.2.0'")
    record_type = document.get("record_type")
    if not isinstance(record_type, str):
        raise CanonicalValidationError("record_type must be a string")
    record_class = _RECORD_TYPES.get(record_type)
    if record_class is None:
        raise CanonicalValidationError(f"unknown record_type {record_type!r}")

    expected = {field.name for field in fields(record_class)} | {
        "schema_version",
        "record_type",
    }
    unknown = set(document) - expected
    missing = expected - set(document)
    if unknown:
        raise CanonicalValidationError(
            f"unknown fields for {record_type}: {sorted(unknown)!r}"
        )
    if missing:
        raise CanonicalValidationError(
            f"missing fields for {record_type}: {sorted(missing)!r}"
        )

    values = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", "record_type"}
    }
    for label in ("as_of", "published_at", "fetched_at", "valid_from"):
        values[label] = _parse_datetime(label, values[label])
    if values["valid_to"] is not None:
        values["valid_to"] = _parse_datetime("valid_to", values["valid_to"])
    if "identifiers" in values:
        if not isinstance(values["identifiers"], list):
            raise CanonicalValidationError("identifiers must be an array")
        values["identifiers"] = tuple(
            _build_nested(
                f"identifiers[{index}]",
                lambda identifier=identifier: ExternalIdentifier(**identifier),
            )
            for index, identifier in enumerate(values["identifiers"])
        )
    for label in ("inception_date", "tenure_start"):
        if label in values:
            values[label] = _parse_date(label, values[label])
    for label in ("tenure_end", "termination_date"):
        if label in values and values[label] is not None:
            values[label] = _parse_date(label, values[label])
    if "fee_schedule" in values:
        if not isinstance(values["fee_schedule"], Mapping):
            raise CanonicalValidationError("fee_schedule must be an object")
        values["fee_schedule"] = _build_nested(
            "fee_schedule",
            lambda: FeeSchedule(**values["fee_schedule"]),
        )
    if "positions" in values:
        if not isinstance(values["positions"], list):
            raise CanonicalValidationError("positions must be an array")
        values["positions"] = tuple(
            _build_nested(
                f"positions[{index}]",
                lambda position=position: HoldingPosition(**position),
            )
            for index, position in enumerate(values["positions"])
        )
    if "lifecycle_events" in values:
        if not isinstance(values["lifecycle_events"], list):
            raise CanonicalValidationError("lifecycle_events must be an array")
        events = []
        for index, event in enumerate(values["lifecycle_events"]):
            if not isinstance(event, Mapping):
                raise CanonicalValidationError(
                    f"lifecycle_events[{index}] must be an object"
                )
            event_values = dict(event)
            event_values["effective_at"] = _parse_datetime(
                f"lifecycle_events[{index}].effective_at",
                event_values.get("effective_at"),
            )
            evidence_ids = event_values.get("evidence_ids")
            if not isinstance(evidence_ids, list):
                raise CanonicalValidationError(
                    f"lifecycle_events[{index}].evidence_ids must be an array"
                )
            event_values["evidence_ids"] = tuple(evidence_ids)
            events.append(
                _build_nested(
                    f"lifecycle_events[{index}]",
                    lambda event_values=event_values: FundLifecycleEvent(
                        **event_values
                    ),
                )
            )
        values["lifecycle_events"] = tuple(events)
    try:
        return cast(CanonicalEntity, record_class(**values))
    except TypeError as exc:
        raise CanonicalValidationError(
            f"invalid {record_type} document: {exc}"
        ) from exc


def canonical_json(record: CanonicalEntity) -> str:
    """Return deterministic UTF-8 JSON for hashing, storage and review."""
    return json.dumps(
        record_to_document(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
