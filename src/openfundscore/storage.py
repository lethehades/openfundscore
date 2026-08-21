"""Append-only SQLite storage for canonical entity versions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Any

from .canonical import (
    CanonicalEntity,
    CanonicalValidationError,
    FundStrategy,
    ShareClass,
    canonical_json,
    record_from_document,
    record_to_document,
)


class CanonicalStoreError(ValueError):
    """Raised when local canonical storage would lose or corrupt history."""


class RecordIdentityConflict(CanonicalStoreError):
    """Raised when a record_id is reused for different immutable content."""


_ENTITY_ID_FIELDS = {
    "fund_strategy": "fund_strategy_id",
    "share_class": "share_class_id",
    "benchmark": "benchmark_id",
    "manager": "manager_id",
    "manager_tenure": "tenure_id",
    "holding_snapshot": "snapshot_id",
    "evidence": "evidence_id",
}


@dataclass(frozen=True)
class ShareClassResolution:
    """One share-class candidate and every linked strategy candidate."""

    share_class: ShareClass
    strategy_candidates: tuple[FundStrategy, ...]
    conflict_groups: tuple[str, ...]


class CanonicalStore:
    """A small, deterministic, single-writer local canonical store."""

    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS canonical_record (
                record_id TEXT PRIMARY KEY,
                record_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                conflict_group TEXT,
                document TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS canonical_record_lookup
                ON canonical_record(record_type, entity_id, valid_from, valid_to);
            CREATE TABLE IF NOT EXISTS schema_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta(singleton, schema_version)
            VALUES (1, 'm1.0');
            """
        )
        self._connection.commit()

    def __enter__(self) -> CanonicalStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _put(self, record: CanonicalEntity) -> bool:
        document = record_to_document(record)
        record_type = document["record_type"]
        entity_id_field = _ENTITY_ID_FIELDS[record_type]
        payload = canonical_json(record)
        existing = self._connection.execute(
            "SELECT document FROM canonical_record WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] == payload:
                return False
            raise RecordIdentityConflict(
                f"record_id {record.record_id!r} already has different immutable content"
            )
        self._connection.execute(
            """
            INSERT INTO canonical_record(
                record_id, record_type, entity_id, valid_from, valid_to,
                published_at, fetched_at, conflict_group, document
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.record_id,
                record_type,
                document[entity_id_field],
                document["valid_from"],
                document["valid_to"],
                document["published_at"],
                document["fetched_at"],
                document["conflict_group"],
                payload,
            ),
        )
        return True

    def put(self, record: CanonicalEntity) -> bool:
        """Append one immutable version; identical replay is a no-op."""
        with self._connection:
            return self._put(record)

    def get(self, record_id: str) -> CanonicalEntity | None:
        row = self._connection.execute(
            "SELECT document FROM canonical_record WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return record_from_document(json.loads(row[0]))

    def query_versions(
        self,
        record_type: str,
        entity_id: str,
        *,
        effective_at: datetime,
        knowledge_cutoff: datetime | None = None,
    ) -> tuple[CanonicalEntity, ...]:
        """Return every effective candidate known by the requested cutoff."""
        if record_type not in _ENTITY_ID_FIELDS:
            raise CanonicalStoreError(f"unknown record_type {record_type!r}")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise CanonicalStoreError("entity_id must be a non-empty string")
        effective = self._utc_iso("effective_at", effective_at)
        parameters: list[str] = [record_type, entity_id, effective, effective]
        knowledge_clause = ""
        if knowledge_cutoff is not None:
            knowledge = self._utc_iso("knowledge_cutoff", knowledge_cutoff)
            knowledge_clause = " AND fetched_at <= ?"
            parameters.append(knowledge)
        rows = self._connection.execute(
            """
            SELECT document
            FROM canonical_record
            WHERE record_type = ?
              AND entity_id = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to > ?)
            """
            + knowledge_clause
            + " ORDER BY valid_from, published_at, record_id",
            parameters,
        ).fetchall()
        return tuple(record_from_document(json.loads(row[0])) for row in rows)

    def resolve_share_class(
        self,
        share_class_id: str,
        *,
        effective_at: datetime,
        knowledge_cutoff: datetime | None = None,
    ) -> tuple[ShareClassResolution, ...]:
        """Join share-class versions to every strategy candidate without collapse."""
        share_candidates = self.query_versions(
            "share_class",
            share_class_id,
            effective_at=effective_at,
            knowledge_cutoff=knowledge_cutoff,
        )
        resolutions = []
        for share_candidate in share_candidates:
            if not isinstance(share_candidate, ShareClass):
                raise CanonicalStoreError(
                    f"record for {share_class_id!r} is not a ShareClass"
                )
            raw_strategies = self.query_versions(
                "fund_strategy",
                share_candidate.fund_strategy_id,
                effective_at=effective_at,
                knowledge_cutoff=knowledge_cutoff,
            )
            if not all(isinstance(item, FundStrategy) for item in raw_strategies):
                raise CanonicalStoreError(
                    f"strategy link for {share_class_id!r} contains a wrong record type"
                )
            strategies = tuple(
                item for item in raw_strategies if isinstance(item, FundStrategy)
            )
            conflicts = tuple(
                sorted(
                    {
                        group
                        for group in (
                            share_candidate.conflict_group,
                            *(item.conflict_group for item in strategies),
                        )
                        if group is not None
                    }
                )
            )
            resolutions.append(
                ShareClassResolution(
                    share_class=share_candidate,
                    strategy_candidates=strategies,
                    conflict_groups=conflicts,
                )
            )
        return tuple(resolutions)

    @staticmethod
    def _utc_iso(label: str, value: datetime) -> str:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise CanonicalStoreError(f"{label} must be a timezone-aware datetime")
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def dump_json(self) -> str:
        """Export every immutable record in a deterministic order."""
        rows = self._connection.execute(
            """
            SELECT document
            FROM canonical_record
            ORDER BY record_type, entity_id, valid_from, published_at, record_id
            """
        ).fetchall()
        documents = [json.loads(row[0]) for row in rows]
        return json.dumps(
            documents,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def load_json(self, payload: str) -> None:
        """Atomically load a deterministic dump without replacing history."""
        try:
            documents: Any = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CanonicalStoreError("canonical dump must be valid JSON") from exc
        if not isinstance(documents, list):
            raise CanonicalStoreError("canonical dump must be a JSON array")
        try:
            with self._connection:
                for index, document in enumerate(documents):
                    if not isinstance(document, dict):
                        raise CanonicalStoreError(
                            f"canonical dump item {index} must be an object"
                        )
                    self._put(record_from_document(document))
        except CanonicalValidationError as exc:
            raise CanonicalStoreError(f"invalid canonical dump: {exc}") from exc
