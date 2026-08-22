"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import NoReturn

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
from .manager_research import (
    ManagerResearchHandoff,
    ManagerResearchValidationError,
    derive_manager_evidence_sources,
)
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

_MAX_RECORD_BYTES = 8 * 1024 * 1024
_MAX_CATEGORY_BYTES = 8 * 1024 * 1024


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

    category_score = subparsers.add_parser(
        "category-score",
        help="score strict audited JSON with manager handoff and evidence ledger 0.2.0",
        description=(
            "score strict audited JSON with manager handoff and evidence ledger 0.2.0"
        ),
    )
    category_score.add_argument("path", help="path to a category score JSON document")

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
