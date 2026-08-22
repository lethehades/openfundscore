"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from .ant_fortune_boundary import (
    AccessMode,
    BoundaryUse,
    BoundaryValidationError,
    decide_ant_fortune_field,
    validate_ant_fortune_boundary,
)
from .category_metrics import (
    ApplicabilityContext,
    CaptureDenominatorAudit,
    CaptureDenominatorStatus,
    CategoryMetricError,
    MetricObservation,
    MetricState,
    PeerObservation,
    score_category_metrics,
)
from .mainland_official import (
    MainlandOfficialSnapshotAdapter,
    SnapshotValidationError,
    load_mainland_entitlements,
)
from .manager_research import (
    ManagerResearchHandoff,
    ManagerResearchValidationError,
    derive_manager_evidence_sources,
)
from .official_providers import (
    OFFICIAL_PROVIDER_SCHEMA_VERSION,
    ProviderHttpError,
    SecEdgarSubmissionsAdapter,
    WorldBankIndicatorsAdapter,
)
from .provider_semantics import ProviderRecordValidationError, parse_rfc3339_timestamp
from .resources import (
    ResourceError,
    ResourceInfo,
    ResourceType,
    list_resources,
    resolve_resource,
)
from .score_config import (
    ConfigValidationError,
    load_score_config,
    validate_score_config,
)
from .strategy_mapping import (
    StrategyMappingError,
    load_strategy_mapping,
    map_strategy_family,
    validate_strategy_mapping,
)
from .validation import RecordType, RecordValidationError, validate_record
from .walk_forward import WalkForwardError, run_walk_forward
from .walk_forward_io import walk_forward_from_document, walk_forward_report_document

_MAX_RECORD_BYTES = 8 * 1024 * 1024
_MAX_BOUNDARY_BYTES = 1024 * 1024
_MAX_CATEGORY_BYTES = 8 * 1024 * 1024
_MAX_PROVIDER_FIXTURE_BYTES = 2 * 1024 * 1024


class _DocumentFormatError(ValueError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.exit(
            2,
            "openfundscore: error: argument_error at $arguments: "
            "command arguments are invalid\n",
        )


def _reject_json_constant(_: str) -> object:
    raise _DocumentFormatError


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DocumentFormatError
        document[key] = value
    return document


def _record_error(
    *,
    record_type: str,
    schema_version: str,
    code: str,
    message: str,
) -> RecordValidationError:
    return RecordValidationError(
        record_type=record_type,
        schema_version=schema_version,
        stage="document",
        code=code,
        path="$document",
        message=message,
    )


def _load_record_document(
    path: str,
    *,
    record_type: str,
    schema_version: str,
) -> object:
    read_error: OSError | None = None
    payload: bytes | None = None
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_RECORD_BYTES + 1)
    except OSError as exc:
        read_error = exc
    if read_error is not None or payload is None:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_io",
            message="record document could not be read",
        )
    if len(payload) > _MAX_RECORD_BYTES:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_too_large",
            message="record document exceeds the validation size limit",
        )

    decode_failed = False
    text: str | None = None
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        decode_failed = True
    if decode_failed or text is None:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_format",
            message="record document must be strict UTF-8 JSON",
        )

    parse_failed = False
    document: object | None = None
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, RecursionError):
        parse_failed = True
    if parse_failed:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_format",
            message="record document must be strict UTF-8 JSON",
        )
    return document


def _load_boundary_document(path: str) -> tuple[object, str]:
    payload: bytes | None = None
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_BOUNDARY_BYTES + 1)
    except OSError:
        pass
    if payload is None or len(payload) > _MAX_BOUNDARY_BYTES:
        raise BoundaryValidationError(
            code="document_io",
            path="$document",
            message="boundary document could not be read within its size limit",
        ) from None
    try:
        text = payload.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise BoundaryValidationError(
            code="document_format",
            path="$document",
            message="boundary document must be strict UTF-8 JSON",
        ) from None
    return document, hashlib.sha256(payload).hexdigest()


def _load_category_document(path: str) -> object:
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_CATEGORY_BYTES + 1)
    except OSError:
        raise CategoryMetricError(
            "document_io", "$document", "category score document could not be read"
        ) from None
    if len(payload) > _MAX_CATEGORY_BYTES:
        raise CategoryMetricError(
            "document_too_large",
            "$document",
            "category score document exceeds the size limit",
        )
    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise CategoryMetricError(
            "document_format", "$document", "document must be strict UTF-8 JSON"
        ) from None


def _closed_document(value: object, *, fields: set[str], path: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise CategoryMetricError(
            "document_shape",
            path,
            "object must contain the exact required fields",
        )
    return value


def _category_timestamp(value: object, *, path: str) -> datetime:
    if type(value) is not str or len(value) > 64:
        raise CategoryMetricError(
            "document_timestamp", path, "timestamp must be bounded ISO 8601 text"
        )
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise CategoryMetricError(
            "document_timestamp", path, "timestamp must be ISO 8601 text"
        ) from None


def _capture_denominator_from_document(
    value: object, *, path: str
) -> CaptureDenominatorAudit | None:
    if value is None:
        return None
    item = _closed_document(
        value,
        fields={
            "denominator_status",
            "benchmark_downside_sample_count",
            "evidence_id",
            "lineage_id",
            "series_id",
        },
        path=path,
    )
    try:
        status = CaptureDenominatorStatus(item["denominator_status"])
    except (TypeError, ValueError):
        raise CategoryMetricError(
            "document_state",
            f"{path}.denominator_status",
            "capture denominator status is unsupported",
        ) from None
    return CaptureDenominatorAudit(
        denominator_status=status,
        benchmark_downside_sample_count=item["benchmark_downside_sample_count"],
        evidence_id=item["evidence_id"],
        lineage_id=item["lineage_id"],
        series_id=item["series_id"],
    )


def _manager_handoff_from_document(value: object) -> ManagerResearchHandoff:
    item = _closed_document(
        value,
        fields={
            "manager_research",
            "as_of",
            "fund_strategy_id",
            "sources",
            "assertion_status",
        },
        path="$document.manager_handoff",
    )
    if type(item["manager_research"]) is not dict:
        raise CategoryMetricError(
            "document_shape",
            "$document.manager_handoff.manager_research",
            "manager research must be a JSON object",
        )
    fund_strategy_id = item["fund_strategy_id"]
    if (
        type(fund_strategy_id) is not str
        or not fund_strategy_id
        or len(fund_strategy_id) > 64
    ):
        raise CategoryMetricError(
            "document_shape",
            "$document.manager_handoff.fund_strategy_id",
            "manager target must be bounded text",
        )
    as_of = _category_timestamp(item["as_of"], path="$document.manager_handoff.as_of")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise CategoryMetricError(
            "document_timestamp",
            "$document.manager_handoff.as_of",
            "manager handoff timestamp must include an offset",
        )
    if item["assertion_status"] != "caller_provided":
        raise CategoryMetricError(
            "document_manager_handoff",
            "$document.manager_handoff.assertion_status",
            "manager assertion status must be exactly caller_provided",
        )
    try:
        sources = derive_manager_evidence_sources(
            item["manager_research"],
            fund_strategy_id,
            item["sources"],
        )
        return ManagerResearchHandoff(
            manager_research=item["manager_research"],
            as_of=as_of,
            fund_strategy_id=fund_strategy_id,
            sources=sources,
            assertion_status=item["assertion_status"],
        )
    except ManagerResearchValidationError:
        raise CategoryMetricError(
            "document_manager_handoff",
            "$document.manager_handoff",
            "manager handoff input is invalid",
        ) from None


def _category_score_from_document(document: object):
    top_fields = {
        "profile_id",
        "peer_bucket",
        "peer_bucket_version",
        "peer_admission_version",
        "history_months",
        "adequate_regime_coverage",
        "applicability_context",
        "manager_handoff",
        "evidence_ledger",
        "config_version",
        "metric_catalog_version",
        "final_precision",
        "observations",
        "peers",
    }
    root = _closed_document(document, fields=top_fields, path="$document")
    applicability_fields = {
        "declared_benchmark",
        "cross_border_or_currency_exposure",
        "derivative_or_commodity_exposure",
        "income_distributing_assets",
        "lookthrough_portfolio",
        "securities_lending_program",
    }
    applicability_document = _closed_document(
        root["applicability_context"],
        fields=applicability_fields,
        path="$document.applicability_context",
    )
    for field in applicability_fields:
        if type(applicability_document[field]) is not bool:
            raise CategoryMetricError(
                "document_shape",
                f"$document.applicability_context.{field}",
                "applicability prerequisites must be exact booleans",
            )
    applicability_context = ApplicabilityContext(**applicability_document)
    observation_fields = {
        "metric_id",
        "state",
        "raw_value",
        "fund_id",
        "series_id",
        "evidence_id",
        "lineage_id",
        "as_of",
        "published_at",
        "evaluation_timestamp",
        "sample_size",
        "window_months",
        "uncertainty",
        "capture_denominator",
    }
    values = root["observations"]
    if type(values) is not list or len(values) > 100:
        raise CategoryMetricError(
            "document_shape",
            "$document.observations",
            "observations must be a bounded array",
        )
    observations = []
    for index, value in enumerate(values):
        path = f"$document.observations[{index}]"
        required_observation_fields = observation_fields - {"uncertainty"}
        if (
            type(value) is not dict
            or not required_observation_fields <= set(value)
            or not set(value) <= observation_fields
        ):
            raise CategoryMetricError(
                "document_shape",
                path,
                "object must contain all required fields and only optional uncertainty",
            )
        item = value
        try:
            state = MetricState(item["state"])
        except (TypeError, ValueError):
            raise CategoryMetricError(
                "document_state", f"{path}.state", "metric state is unsupported"
            ) from None
        observations.append(
            MetricObservation(
                metric_id=item["metric_id"],
                state=state,
                raw_value=item["raw_value"],
                fund_id=item["fund_id"],
                series_id=item["series_id"],
                evidence_id=item["evidence_id"],
                lineage_id=item["lineage_id"],
                as_of=_category_timestamp(item["as_of"], path=f"{path}.as_of"),
                published_at=_category_timestamp(
                    item["published_at"], path=f"{path}.published_at"
                ),
                evaluation_timestamp=_category_timestamp(
                    item["evaluation_timestamp"],
                    path=f"{path}.evaluation_timestamp",
                ),
                sample_size=item["sample_size"],
                window_months=item["window_months"],
                uncertainty=item.get("uncertainty"),
                capture_denominator=_capture_denominator_from_document(
                    item["capture_denominator"], path=f"{path}.capture_denominator"
                ),
            )
        )
    peer_values = root["peers"]
    if type(peer_values) is not list or len(peer_values) > 120_000:
        raise CategoryMetricError(
            "document_shape", "$document.peers", "peers must be a bounded array"
        )
    peers = []
    for index, value in enumerate(peer_values):
        path = f"$document.peers[{index}]"
        item = _closed_document(
            value,
            fields={
                "peer_id",
                "metric_id",
                "raw_value",
                "series_id",
                "source_id",
                "lineage_id",
                "as_of",
                "published_at",
                "evaluation_timestamp",
                "peer_bucket",
                "peer_bucket_version",
                "category_profile",
                "admission_contract_version",
                "admission_contract_sha256",
                "snapshot_hash",
                "document_hash",
                "sample_size",
                "window_basis",
                "window_months",
                "window_start",
                "window_end",
                "capture_denominator",
            },
            path=path,
        )
        peers.append(
            PeerObservation(
                peer_id=item["peer_id"],
                metric_id=item["metric_id"],
                raw_value=item["raw_value"],
                series_id=item["series_id"],
                source_id=item["source_id"],
                lineage_id=item["lineage_id"],
                as_of=_category_timestamp(item["as_of"], path=f"{path}.as_of"),
                published_at=_category_timestamp(
                    item["published_at"], path=f"{path}.published_at"
                ),
                evaluation_timestamp=_category_timestamp(
                    item["evaluation_timestamp"],
                    path=f"{path}.evaluation_timestamp",
                ),
                peer_bucket=item["peer_bucket"],
                peer_bucket_version=item["peer_bucket_version"],
                category_profile=item["category_profile"],
                admission_contract_version=item["admission_contract_version"],
                admission_contract_sha256=item["admission_contract_sha256"],
                snapshot_hash=item["snapshot_hash"],
                document_hash=item["document_hash"],
                sample_size=item["sample_size"],
                window_basis=item["window_basis"],
                window_months=item["window_months"],
                window_start=item["window_start"],
                window_end=item["window_end"],
                capture_denominator=_capture_denominator_from_document(
                    item["capture_denominator"], path=f"{path}.capture_denominator"
                ),
            )
        )
    return score_category_metrics(
        profile_id=root["profile_id"],
        peer_bucket=root["peer_bucket"],
        peer_bucket_version=root["peer_bucket_version"],
        peer_admission_version=root["peer_admission_version"],
        history_months=root["history_months"],
        adequate_regime_coverage=root["adequate_regime_coverage"],
        applicability_context=applicability_context,
        observations=tuple(observations),
        peers=tuple(peers),
        manager_handoff=_manager_handoff_from_document(root["manager_handoff"]),
        evidence_ledger=root["evidence_ledger"],
        config_version=root["config_version"],
        metric_catalog_version=root["metric_catalog_version"],
        final_precision=root["final_precision"],
    )


def _load_provider_fixture(path: str) -> bytes:
    payload: bytes | None = None
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_PROVIDER_FIXTURE_BYTES + 1)
    except OSError:
        pass
    if payload is None:
        raise ProviderHttpError(
            code="fixture_io",
            path="$fixture",
            message="provider fixture could not be read",
        ) from None
    if len(payload) > _MAX_PROVIDER_FIXTURE_BYTES:
        raise ProviderHttpError(
            code="response_too_large",
            path="$fixture",
            message="provider fixture exceeds the size limit",
        )
    return payload


def _add_resource_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--type",
        dest="resource_type",
        required=True,
        choices=tuple(resource_type.value for resource_type in ResourceType),
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = _RedactedArgumentParser(prog="openfundscore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-config", help="validate a versioned scoring configuration"
    )
    validate.add_argument("path", help="path to a scoring JSON file")

    validate_mapping = subparsers.add_parser(
        "validate-mapping",
        help="validate a versioned complex-alternatives strategy mapping",
    )
    validate_mapping.add_argument("path", help="path to a strategy mapping JSON file")

    strategy_map = subparsers.add_parser(
        "strategy-map",
        help="print the peer-bucket and score-profile decision for a strategy family",
    )
    strategy_map.add_argument("family", help="snake_case strategy family identifier")
    strategy_map.add_argument("--mapping-version", required=True)

    validate_record_command = subparsers.add_parser(
        "validate-record",
        help="validate a contract record with its schema and semantics",
    )
    validate_record_command.add_argument(
        "--type",
        dest="record_type",
        required=True,
        choices=tuple(record_type.value for record_type in RecordType),
    )
    validate_record_command.add_argument("--schema-version", required=True)
    validate_record_command.add_argument("--evaluation-timestamp")
    validate_record_command.add_argument("path", help="path to a contract JSON file")

    walk_forward = subparsers.add_parser(
        "walk-forward",
        help="run a local point-in-time walk-forward report from strict JSON",
    )
    walk_forward.add_argument("path", help="path to a walk-forward JSON document")
    provider = subparsers.add_parser(
        "provider", help="run explicit offline provider operations"
    )
    provider_subparsers = provider.add_subparsers(
        dest="provider_command", required=True
    )
    mainland_parse = provider_subparsers.add_parser(
        "mainland-parse",
        help="parse and authorize a local frozen Mainland official snapshot",
    )
    mainland_parse.add_argument("snapshot")
    mainland_parse.add_argument("--entitlements", required=True)
    mainland_parse.add_argument("--evaluation-timestamp", required=True)
    mainland_parse.add_argument(
        "--fund-company-host",
        action="append",
        default=[],
        metavar="EXACT_HOST=EVIDENCE_URL",
    )
    category_score = subparsers.add_parser(
        "category-score",
        help="score strict audited JSON with manager handoff and evidence ledger 0.2.0",
        description=(
            "score strict audited JSON with manager handoff and evidence ledger 0.2.0"
        ),
    )
    category_score.add_argument("path", help="path to a category score JSON document")
    provider_fixture = subparsers.add_parser(
        "provider-fixture",
        help="parse a bounded official-provider JSON fixture without network access",
    )
    provider_subparsers = provider_fixture.add_subparsers(
        dest="provider_fixture_type", required=True
    )
    sec_fixture = provider_subparsers.add_parser("sec")
    sec_fixture.add_argument(
        "--schema-version",
        choices=(OFFICIAL_PROVIDER_SCHEMA_VERSION,),
        default=OFFICIAL_PROVIDER_SCHEMA_VERSION,
    )
    sec_fixture.add_argument("--cik", required=True)
    sec_fixture.add_argument("--user-agent", required=True)
    sec_fixture.add_argument("--fetched-at", required=True)
    sec_fixture.add_argument("--evaluation-timestamp", required=True)
    sec_fixture.add_argument("path")
    world_bank_fixture = provider_subparsers.add_parser("world-bank")
    world_bank_fixture.add_argument(
        "--schema-version",
        choices=(OFFICIAL_PROVIDER_SCHEMA_VERSION,),
        default=OFFICIAL_PROVIDER_SCHEMA_VERSION,
    )
    world_bank_fixture.add_argument("--country", required=True)
    world_bank_fixture.add_argument("--indicator", required=True)
    world_bank_fixture.add_argument("--source", required=True, type=int)
    world_bank_fixture.add_argument("--page", required=True, type=int)
    world_bank_fixture.add_argument("--per-page", required=True, type=int)
    world_bank_fixture.add_argument("--fetched-at", required=True)
    world_bank_fixture.add_argument("--evaluation-timestamp", required=True)
    world_bank_fixture.add_argument("path")

    resources = subparsers.add_parser(
        "resources", help="inspect versioned package resources"
    )
    resource_subparsers = resources.add_subparsers(
        dest="resource_command", required=True
    )
    list_command = resource_subparsers.add_parser(
        "list", help="list packaged resources"
    )
    list_command.add_argument(
        "--type",
        dest="resource_type",
        choices=tuple(resource_type.value for resource_type in ResourceType),
    )
    resolve_command = resource_subparsers.add_parser(
        "resolve", help="resolve an exact resource selector"
    )
    _add_resource_selector(resolve_command)
    show_command = resource_subparsers.add_parser(
        "show", help="write one packaged resource to stdout"
    )
    _add_resource_selector(show_command)
    platform_boundary = subparsers.add_parser(
        "platform-boundary",
        help="validate or inspect the Ant Fortune public-data boundary",
    )
    boundary_subparsers = platform_boundary.add_subparsers(
        dest="boundary_command",
        required=True,
    )
    boundary_validate = boundary_subparsers.add_parser(
        "validate",
        help="validate the packaged Ant Fortune boundary or a local document",
    )
    boundary_validate.add_argument("path", nargs="?")
    boundary_validate.add_argument("--boundary-version", required=True)
    boundary_check = boundary_subparsers.add_parser(
        "check",
        help="check one field and requested-use set without collecting data",
    )
    boundary_check.add_argument("field_id")
    boundary_check.add_argument(
        "--access-mode",
        required=True,
        choices=tuple(item.value for item in AccessMode),
    )
    boundary_check.add_argument(
        "--use",
        dest="uses",
        required=True,
        action="append",
        choices=tuple(item.value for item in BoundaryUse),
    )
    boundary_check.add_argument("--boundary-version", required=True)
    return parser


def _resource_document(resource: ResourceInfo) -> dict[str, str]:
    return {
        "media_type": resource.media_type,
        "name": resource.key.name,
        "sha256": resource.sha256,
        "type": resource.key.resource_type.value,
        "uri": resource.uri,
        "version": resource.key.version,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OpenFundScore CLI and return a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "walk-forward":
        try:
            try:
                document = _load_record_document(
                    args.path,
                    record_type="walk_forward_input",
                    schema_version="0.1.0",
                )
                config, candidates, snapshots, outcomes, scores = (
                    walk_forward_from_document(document)
                )
            except (RecordValidationError, WalkForwardError):
                raise WalkForwardError(
                    code="walk_forward_document",
                    path="$document",
                    message="input must be bounded strict UTF-8 JSON",
                ) from None
            report = run_walk_forward(
                config,
                candidates=candidates,
                snapshots=snapshots,
                outcomes=outcomes,
                precomputed_scores=scores,
            )
            output = walk_forward_report_document(report)
            print(
                json.dumps(
                    output,
                    allow_nan=False,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        except WalkForwardError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2

    if args.command == "platform-boundary":
        try:
            if args.boundary_command == "validate":
                if args.path is None:
                    resource = resolve_resource(
                        resource_type="platform-boundary",
                        name="ant_fortune",
                        version=args.boundary_version,
                    )
                    boundary_document = resource.load_json()
                    boundary_sha256 = resource.info.sha256
                else:
                    boundary_document, boundary_sha256 = _load_boundary_document(
                        args.path
                    )
                decision = validate_ant_fortune_boundary(
                    boundary_document,
                    expected_version=args.boundary_version,
                    resource_sha256=boundary_sha256,
                )
                print(
                    f"valid: ant_fortune@{decision.boundary_version}; "
                    f"sha256={decision.resource_sha256}"
                )
                return 0
            decision = decide_ant_fortune_field(
                args.field_id,
                access_mode=args.access_mode,
                requested_uses=frozenset(BoundaryUse(item) for item in args.uses),
                boundary_version=args.boundary_version,
            )
            print(
                json.dumps(
                    {
                        "access_mode": decision.access_mode,
                        "affects_open_score": decision.affects_open_score,
                        "allowed_uses": dict(decision.allowed_uses),
                        "automated_adapter_allowed": decision.automated_adapter_allowed,
                        "authorization_status": decision.authorization_status,
                        "boundary_id": decision.boundary_id,
                        "boundary_version": decision.boundary_version,
                        "cache_allowed": decision.cache_allowed,
                        "derived_allowed": decision.derived_allowed,
                        "display_allowed": decision.display_allowed,
                        "field_id": decision.field_id,
                        "ingestion_allowed": decision.ingestion_allowed,
                        "namespace": decision.namespace,
                        "open_score_allowed": decision.open_score_allowed,
                        "publication_allowed": decision.publication_allowed,
                        "reason_code": decision.reason_code,
                        "redistribution_allowed": decision.redistribution_allowed,
                        "requested_uses": decision.requested_uses,
                        "resource_sha256": decision.resource_sha256,
                        "reviewed_at": decision.reviewed_at,
                        "use_decisions": dict(decision.use_decisions),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        except (BoundaryValidationError, ResourceError):
            print(
                "openfundscore: error: platform boundary operation failed",
                file=sys.stderr,
            )
            return 2

    if args.command == "provider" and args.provider_command == "mainland-parse":
        try:
            evaluation_timestamp = parse_rfc3339_timestamp(
                args.evaluation_timestamp,
                path="$evaluation_timestamp",
            )
            host_approvals: dict[str, str] = {}
            for approval in args.fund_company_host:
                if (
                    not isinstance(approval, str)
                    or "=" not in approval
                    or not approval.split("=", 1)[0]
                    or not approval.split("=", 1)[1]
                ):
                    raise SnapshotValidationError(
                        code="invalid_host_approval",
                        path="$fund_company_hosts",
                        message="fund-company host approval is malformed",
                    )
                host, evidence_url = approval.split("=", 1)
                if host in host_approvals:
                    raise SnapshotValidationError(
                        code="invalid_host_approval",
                        path="$fund_company_hosts",
                        message="fund-company host approvals must be unique",
                    )
                host_approvals[host] = evidence_url
            entitlements = load_mainland_entitlements(Path(args.entitlements))
            records = MainlandOfficialSnapshotAdapter(
                entitlements=entitlements,
                fund_company_hosts=host_approvals,
            ).parse(
                Path(args.snapshot),
                evaluation_timestamp=evaluation_timestamp,
            )
        except SnapshotValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2
        except (ProviderRecordValidationError, ValueError):
            print(
                "openfundscore: error: mainland_snapshot_failed at $provider: "
                "offline provider operation failed",
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "category-score":
        try:
            result = _category_score_from_document(_load_category_document(args.path))
            print(
                json.dumps(
                    asdict(result),
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        except ManagerResearchValidationError:
            print(
                "openfundscore: error: invalid manager handoff input",
                file=sys.stderr,
            )
            return 2
        except CategoryMetricError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "validate-record":
        try:
            document = _load_record_document(
                args.path,
                record_type=args.record_type,
                schema_version=args.schema_version,
            )
            validate_record(
                args.record_type,
                document,
                schema_version=args.schema_version,
                evaluation_timestamp=args.evaluation_timestamp,
            )
        except RecordValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2
        print(f"valid: {args.record_type}@{args.schema_version} (schema+semantics)")
        return 0

    if args.command == "provider-fixture":
        try:
            payload = _load_provider_fixture(args.path)
            fetched_at = parse_rfc3339_timestamp(
                args.fetched_at,
                path="$arguments.fetched_at",
            )
            evaluation_timestamp = parse_rfc3339_timestamp(
                args.evaluation_timestamp,
                path="$arguments.evaluation_timestamp",
            )
            if args.provider_fixture_type == "sec":
                records = SecEdgarSubmissionsAdapter(
                    user_agent=args.user_agent
                ).parse_submissions_fixture(
                    payload,
                    cik=args.cik,
                    fetched_at=fetched_at,
                    evaluation_timestamp=evaluation_timestamp,
                )
            else:
                records = WorldBankIndicatorsAdapter(
                    countries=frozenset({args.country})
                ).parse_page_fixture(
                    payload,
                    country=args.country,
                    indicator=args.indicator,
                    source=args.source,
                    page=args.page,
                    per_page=args.per_page,
                    fetched_at=fetched_at,
                    evaluation_timestamp=evaluation_timestamp,
                )
        except ValueError:
            print(
                "openfundscore: error: provider fixture parse failed",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0

    if args.command == "resources":
        try:
            if args.resource_command == "list":
                document = [
                    _resource_document(resource)
                    for resource in list_resources(resource_type=args.resource_type)
                ]
                print(json.dumps(document, indent=2, sort_keys=True))
                return 0

            resource = resolve_resource(
                resource_type=args.resource_type,
                name=args.name,
                version=args.version,
            )
            if args.resource_command == "resolve":
                print(
                    json.dumps(
                        _resource_document(resource.info),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            if args.resource_command == "show":
                sys.stdout.write(resource.read_json_text())
                return 0
        except ResourceError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2

    if args.command == "validate-config":
        try:
            config = load_score_config(args.path)
            validate_score_config(config)
        except ConfigValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2

        manager_total = sum(
            component["weight"] for component in config["manager_model"]["components"]
        )
        print(
            f"valid: {len(config['category_profiles'])} category profiles; "
            f"manager model: {manager_total}"
        )
        return 0

    if args.command == "validate-mapping":
        try:
            mapping = load_strategy_mapping(args.path)
            validate_strategy_mapping(mapping)
        except (ResourceError, StrategyMappingError):
            print(
                "openfundscore: error: strategy mapping validation failed",
                file=sys.stderr,
            )
            return 2

        print(
            f"valid: {len(mapping['peer_buckets'])} peer buckets; "
            f"{len(mapping['strategy_families'])} strategy families"
        )
        return 0

    if args.command == "strategy-map":
        try:
            decision = map_strategy_family(
                args.family,
                mapping_version=args.mapping_version,
            )
        except (ResourceError, StrategyMappingError):
            print(
                "openfundscore: error: strategy mapping operation failed",
                file=sys.stderr,
            )
            return 2

        print(
            json.dumps(
                {
                    "is_rated": decision.is_rated,
                    "mapping_id": decision.mapping_id,
                    "mapping_version": decision.mapping_version,
                    "peer_bucket": decision.peer_bucket,
                    "resource_sha256": decision.resource_sha256,
                    "score_profile": decision.score_profile,
                    "strategy_family": decision.strategy_family,
                    "unrated_reason": decision.unrated_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
