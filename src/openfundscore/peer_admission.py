"""Versioned profile-to-peer-bucket admission contract."""

from __future__ import annotations

import re
from typing import Any

from .resources import ResourceError, resolve_resource


class PeerAdmissionValidationError(ValueError):
    """The packaged peer-admission contract is unavailable or invalid."""


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
_BUCKET = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)


def validate_peer_admission_contract(document: object) -> None:
    """Validate the closed 0.1.0 category-profile admission contract."""
    if type(document) is not dict or set(document) != {
        "contract_id",
        "contract_version",
        "status",
        "profiles",
    }:
        raise PeerAdmissionValidationError("peer admission fields are closed")
    if document["contract_id"] != "category-profile-peer-admission":
        raise PeerAdmissionValidationError("peer admission identity is invalid")
    if document["contract_version"] != "0.1.0":
        raise PeerAdmissionValidationError("peer admission version is invalid")
    if document["status"] != "research-preview":
        raise PeerAdmissionValidationError("peer admission status is invalid")
    profiles = document["profiles"]
    if type(profiles) is not dict or set(profiles) != _PROFILE_IDS:
        raise PeerAdmissionValidationError("peer admission must define ten profiles")
    seen: set[str] = set()
    for profile_id, admission in profiles.items():
        if type(admission) is not dict or set(admission) != {
            "allowed_peer_buckets",
            "peer_bucket_versions",
        }:
            raise PeerAdmissionValidationError(
                f"{profile_id} admission fields are closed"
            )
        buckets = admission["allowed_peer_buckets"]
        versions = admission["peer_bucket_versions"]
        if (
            type(buckets) is not list
            or not buckets
            or len(buckets) != len(set(buckets))
            or any(
                type(bucket) is not str or _BUCKET.fullmatch(bucket) is None
                for bucket in buckets
            )
            or type(versions) is not dict
            or set(versions) != set(buckets)
            or any(version != "0.1.0" for version in versions.values())
        ):
            raise PeerAdmissionValidationError(f"{profile_id} buckets are invalid")
        overlap = seen.intersection(buckets)
        if overlap:
            raise PeerAdmissionValidationError(
                "peer buckets cannot span category profiles"
            )
        seen.update(buckets)


def load_peer_admission_contract(version: str = "0.1.0") -> tuple[dict[str, Any], str]:
    """Load one exact packaged admission contract and its verified digest."""
    try:
        resource = resolve_resource(
            resource_type="peer-admission",
            name="category-profile-buckets",
            version=version,
        )
        document = resource.load_json()
        validate_peer_admission_contract(document)
    except (ResourceError, PeerAdmissionValidationError):
        raise PeerAdmissionValidationError(
            "peer admission contract could not be loaded or validated"
        ) from None
    return document, resource.info.sha256
