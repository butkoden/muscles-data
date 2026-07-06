from __future__ import annotations

import math
import time
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any, Mapping

from ..config import DataResourceConfig
from ..errors import SqlConnectionMissingError, SqlRegistryMissingError
from ..models import DataCapability, HealthResult, InspectResult, ObjectBlob, ObjectInfo, SearchHit, VectorHit, WriteResult, redact_mapping


def _native_capability(config: DataResourceConfig) -> set[DataCapability]:
    return {DataCapability.NATIVE_CLIENT} if bool(config.options.get("native_client")) else set()


class _MemoryAdapterBase:
    resource_type = "memory"

    def __init__(self, config: DataResourceConfig) -> None:
        self.config = config
        self.closed = False

    def inspect(self) -> dict[str, Any]:
        return asdict(
            InspectResult(
                name=self.config.name,
                type=self.config.type,
                capabilities=[],
                initialized=True,
                status="ok",
                options=self.config.safe_options(),
                details={"backend": "in-memory"},
            )
        )

    def health(self) -> HealthResult:
        return HealthResult(status="ok", message="in-memory adapter ready")

    def close(self) -> None:
        self.closed = True

    def native_client(self):
        return self


class InMemoryVectorAdapter(_MemoryAdapterBase):
    resource_type = "memory_vector"

    def __init__(self, config: DataResourceConfig) -> None:
        super().__init__(config)
        self._items: dict[str, tuple[list[float], dict[str, Any]]] = {}

    def search_vectors(
        self,
        vector: list[float],
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
        options: Mapping[str, Any] | None = None,
    ) -> list[VectorHit]:
        del options
        hits: list[VectorHit] = []
        for item_id, (item_vector, payload) in self._items.items():
            if filters and not _matches(payload, filters):
                continue
            hits.append(VectorHit(id=item_id, score=_cosine(vector, item_vector), payload=dict(payload)))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[: max(0, limit)]

    def upsert_vectors(self, items: list[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> WriteResult:
        del options
        for item in items:
            item_id = str(item["id"])
            vector = [float(value) for value in item["vector"]]
            payload = dict(item.get("payload", {}) or {})
            self._items[item_id] = (vector, payload)
        return WriteResult(written=len(items), matched=len(items))

    def delete_vectors(
        self,
        ids: list[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult:
        del options
        deleted = 0
        if ids is not None:
            for item_id in ids:
                deleted += 1 if self._items.pop(str(item_id), None) is not None else 0
            return WriteResult(deleted=deleted)
        if filters:
            for item_id, (_vector, payload) in list(self._items.items()):
                if _matches(payload, filters):
                    self._items.pop(item_id, None)
                    deleted += 1
        return WriteResult(deleted=deleted)


class InMemorySearchIndexAdapter(_MemoryAdapterBase):
    resource_type = "memory_search"

    def __init__(self, config: DataResourceConfig) -> None:
        super().__init__(config)
        self._documents: dict[str, tuple[str, dict[str, Any]]] = {}

    def search_text(
        self,
        query: str,
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
        options: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        del options
        query_text = query.lower()
        hits: list[SearchHit] = []
        for document_id, (text, metadata) in self._documents.items():
            if filters and not _matches(metadata, filters):
                continue
            haystack = text.lower()
            if query_text in haystack:
                score = haystack.count(query_text) + (1.0 / max(1, len(text)))
                hits.append(SearchHit(id=document_id, score=score, text=text, metadata=dict(metadata)))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[: max(0, limit)]

    def upsert_documents(self, items: list[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> WriteResult:
        del options
        for item in items:
            document_id = str(item["id"])
            self._documents[document_id] = (str(item.get("text", "")), dict(item.get("metadata", {}) or {}))
        return WriteResult(written=len(items), matched=len(items))

    def delete_documents(
        self,
        ids: list[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult:
        del options
        deleted = 0
        if ids is not None:
            for document_id in ids:
                deleted += 1 if self._documents.pop(str(document_id), None) is not None else 0
            return WriteResult(deleted=deleted)
        if filters:
            for document_id, (_text, metadata) in list(self._documents.items()):
                if _matches(metadata, filters):
                    self._documents.pop(document_id, None)
                    deleted += 1
        return WriteResult(deleted=deleted)


class InMemoryObjectStoreAdapter(_MemoryAdapterBase):
    resource_type = "memory_object"

    def __init__(self, config: DataResourceConfig) -> None:
        super().__init__(config)
        self._objects: dict[str, ObjectBlob] = {}

    def put_object(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult:
        del options
        normalized = _normalize_object_key(key)
        self._objects[normalized] = ObjectBlob(
            key=normalized,
            content=bytes(content),
            content_type=content_type,
            metadata=dict(metadata or {}),
        )
        return WriteResult(written=1, matched=1)

    def get_object(self, key: str, options: Mapping[str, Any] | None = None) -> ObjectBlob:
        del options
        return self._objects[_normalize_object_key(key)]

    def list_objects(
        self,
        prefix: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> list[ObjectInfo]:
        del cursor, options
        normalized_prefix = _normalize_object_prefix(prefix)
        output: list[ObjectInfo] = []
        for key, blob in sorted(self._objects.items()):
            if normalized_prefix and not key.startswith(normalized_prefix):
                continue
            output.append(
                ObjectInfo(
                    key=key,
                    size=len(blob.content),
                    content_type=blob.content_type,
                    metadata=dict(blob.metadata),
                )
            )
        return output[: max(0, limit)]

    def delete_object(self, key: str, options: Mapping[str, Any] | None = None) -> WriteResult:
        del options
        deleted = 1 if self._objects.pop(_normalize_object_key(key), None) is not None else 0
        return WriteResult(deleted=deleted)


class InMemoryKeyValueAdapter(_MemoryAdapterBase):
    resource_type = "memory_kv"

    def __init__(self, config: DataResourceConfig) -> None:
        super().__init__(config)
        self._values: dict[str, tuple[bytes, float | None]] = {}

    def get(self, key: str) -> bytes | None:
        self._expire_if_needed(key)
        item = self._values.get(key)
        return item[0] if item else None

    def set(self, key: str, value: bytes, ttl_seconds: float | None = None) -> WriteResult:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        self._values[key] = (bytes(value), expires_at)
        return WriteResult(written=1, matched=1)

    def delete(self, key: str) -> WriteResult:
        deleted = 1 if self._values.pop(key, None) is not None else 0
        return WriteResult(deleted=deleted)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def _expire_if_needed(self, key: str) -> None:
        item = self._values.get(key)
        if item is None:
            return
        _value, expires_at = item
        if expires_at is not None and expires_at <= time.monotonic():
            self._values.pop(key, None)


class InMemoryDocumentStoreAdapter(_MemoryAdapterBase):
    resource_type = "memory_document"

    def __init__(self, config: DataResourceConfig) -> None:
        super().__init__(config)
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}

    def get_document(self, collection: str, document_id: str) -> Mapping[str, Any] | None:
        document = self._collections.get(collection, {}).get(document_id)
        return dict(document) if document is not None else None

    def upsert_document(self, collection: str, document_id: str, document: Mapping[str, Any]) -> WriteResult:
        self._collections.setdefault(collection, {})[document_id] = dict(document)
        return WriteResult(written=1, matched=1)

    def find_documents(
        self,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        limit: int = 100,
        options: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        del options
        documents = self._collections.get(collection, {})
        output = [
            dict(document)
            for document in documents.values()
            if not filters or _matches(document, filters)
        ]
        return output[: max(0, limit)]

    def delete_document(self, collection: str, document_id: str) -> WriteResult:
        deleted = 1 if self._collections.get(collection, {}).pop(document_id, None) is not None else 0
        return WriteResult(deleted=deleted)


class SqlBridgeAdapter(_MemoryAdapterBase):
    resource_type = "sql"

    def __init__(self, config: DataResourceConfig, *, registry_provider=None) -> None:
        super().__init__(config)
        self._registry_provider = registry_provider

    def connection_name(self) -> str:
        return str(self.config.options.get("connection", self.config.name))

    def session(self):
        registry = self._registry()
        try:
            return registry.session(self.connection_name())
        except Exception as exc:
            raise SqlConnectionMissingError(f"Unknown SQL connection: {self.connection_name()}") from exc

    def session_factory(self):
        registry = self._registry()
        try:
            return registry.session_factory(self.connection_name())
        except Exception as exc:
            raise SqlConnectionMissingError(f"Unknown SQL connection: {self.connection_name()}") from exc

    def inspect(self) -> Mapping[str, Any]:
        registry = self._registry()
        try:
            report = registry.inspect(self.connection_name())
        except Exception as exc:
            raise SqlConnectionMissingError(f"Unknown SQL connection: {self.connection_name()}") from exc
        return _redact_sql_report(report)

    def doctor(self) -> Mapping[str, Any]:
        try:
            report = self.inspect()
        except SqlRegistryMissingError as exc:
            return {"status": "failed", "message": str(exc)}
        except SqlConnectionMissingError as exc:
            return {"status": "failed", "message": str(exc)}
        return {
            "status": "ok" if report.get("status") == "ok" else "failed",
            "message": report.get("message"),
        }

    def health(self) -> HealthResult:
        doctor = self.doctor()
        return HealthResult(status=str(doctor.get("status", "failed")), message=doctor.get("message"))

    def native_client(self):
        return self._registry()

    def _registry(self):
        if self._registry_provider is None:
            raise SqlRegistryMissingError("SQL registry provider is not configured")
        registry = self._registry_provider()
        if registry is None:
            raise SqlRegistryMissingError("SQL connection registry is not available")
        return registry


class InMemoryVectorFactory:
    resource_type = "memory_vector"

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.VECTOR_SEARCH, DataCapability.VECTOR_WRITE, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> InMemoryVectorAdapter:
        return InMemoryVectorAdapter(config)


class InMemorySearchIndexFactory:
    resource_type = "memory_search"

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.KEYWORD_SEARCH, DataCapability.DOCUMENT_INDEX, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> InMemorySearchIndexAdapter:
        return InMemorySearchIndexAdapter(config)


class InMemoryObjectStoreFactory:
    resource_type = "memory_object"

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.OBJECT_STORE, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> InMemoryObjectStoreAdapter:
        return InMemoryObjectStoreAdapter(config)


class InMemoryKeyValueFactory:
    resource_type = "memory_kv"

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.KEY_VALUE, DataCapability.CACHE, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> InMemoryKeyValueAdapter:
        return InMemoryKeyValueAdapter(config)


class InMemoryDocumentStoreFactory:
    resource_type = "memory_document"

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.DOCUMENT_STORE, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> InMemoryDocumentStoreAdapter:
        return InMemoryDocumentStoreAdapter(config)


class SqlBridgeFactory:
    resource_type = "sql"

    def __init__(self, *, registry_provider=None) -> None:
        self._registry_provider = registry_provider

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        return {DataCapability.SQL_SESSION, DataCapability.HEALTHCHECK} | _native_capability(config)

    def create(self, config: DataResourceConfig) -> SqlBridgeAdapter:
        return SqlBridgeAdapter(config, registry_provider=self._registry_provider)


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _matches(payload: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    return all(payload.get(key) == value for key, value in filters.items())


def _redact_sql_report(report: Mapping[str, Any]) -> dict[str, Any]:
    redacted = redact_mapping(report)
    original_connection = report.get("connection")
    connection = redacted.get("connection")
    if isinstance(connection, dict):
        if isinstance(original_connection, Mapping) and "safe_url" in original_connection:
            connection["safe_url"] = original_connection["safe_url"]
        for key in ("url", "dsn"):
            if key in connection:
                connection[key] = "***"
    return redacted


def _normalize_object_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe object key: {key}")
    return path.as_posix()


def _normalize_object_prefix(prefix: str | None) -> str | None:
    if not prefix:
        return None
    cleaned = prefix.strip("/")
    if not cleaned:
        return None
    return _normalize_object_key(cleaned) + "/"
