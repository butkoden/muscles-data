from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .models import HealthResult, ObjectBlob, ObjectInfo, StreamReadResult, WriteResult


@runtime_checkable
class VectorSearchPort(Protocol):
    def search_vectors(
        self,
        vector: list[float],
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
        options: Mapping[str, Any] | None = None,
    ) -> list[Any]: ...

    def upsert_vectors(self, items: list[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> WriteResult: ...

    def delete_vectors(
        self,
        ids: list[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult: ...


@runtime_checkable
class SearchIndexPort(Protocol):
    def search_text(
        self,
        query: str,
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
        options: Mapping[str, Any] | None = None,
    ) -> list[Any]: ...

    def upsert_documents(self, items: list[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> WriteResult: ...

    def delete_documents(
        self,
        ids: list[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult: ...


@runtime_checkable
class ObjectStorePort(Protocol):
    def put_object(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> WriteResult: ...

    def get_object(self, key: str, options: Mapping[str, Any] | None = None) -> ObjectBlob: ...

    def list_objects(
        self,
        prefix: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> list[ObjectInfo]: ...

    def delete_object(self, key: str, options: Mapping[str, Any] | None = None) -> WriteResult: ...


@runtime_checkable
class KeyValuePort(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes, ttl_seconds: float | None = None) -> WriteResult: ...

    def delete(self, key: str) -> WriteResult: ...

    def exists(self, key: str) -> bool: ...


@runtime_checkable
class LockPort(Protocol):
    def acquire_lock(self, name: str, ttl_seconds: float): ...

    def release_lock(self, handle) -> WriteResult: ...


@runtime_checkable
class StreamPort(Protocol):
    def publish(self, stream: str, message: Mapping[str, Any]) -> WriteResult: ...

    def read(self, stream: str, cursor: str | None = None, limit: int = 100) -> StreamReadResult: ...

    def ack(self, stream: str, message_id: str) -> WriteResult: ...


@runtime_checkable
class DocumentStorePort(Protocol):
    def get_document(self, collection: str, document_id: str) -> Mapping[str, Any] | None: ...

    def upsert_document(self, collection: str, document_id: str, document: Mapping[str, Any]) -> WriteResult: ...

    def find_documents(
        self,
        collection: str,
        filters: Mapping[str, Any] | None = None,
        limit: int = 100,
        options: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]: ...

    def delete_document(self, collection: str, document_id: str) -> WriteResult: ...


@runtime_checkable
class SqlResourcePort(Protocol):
    def connection_name(self) -> str: ...

    def session(self): ...

    def inspect(self) -> Mapping[str, Any]: ...

    def doctor(self) -> Mapping[str, Any]: ...


@runtime_checkable
class DataResourceAdapter(Protocol):
    resource_type: str
    capabilities: set

    def inspect(self): ...

    def health(self) -> HealthResult: ...

    def close(self) -> None: ...
