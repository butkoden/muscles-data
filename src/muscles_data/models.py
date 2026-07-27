from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import datetime
import json
import os
from typing import Any, Mapping
from uuid import UUID

from .errors import DataConfigurationError

from muscles import (
    Boolean as CoreBoolean,
    Column,
    DateTime as CoreDateTime,
    Enum as CoreEnum,
    Integer as CoreInteger,
    Json as CoreJson,
    List as CoreList,
    Model,
    String as CoreString,
    UUID4,
)


class DataCapability(str, Enum):
    VECTOR_SEARCH = "vector_search"
    VECTOR_WRITE = "vector_write"
    KEYWORD_SEARCH = "keyword_search"
    DOCUMENT_INDEX = "document_index"
    DOCUMENT_STORE = "document_store"
    OBJECT_STORE = "object_store"
    KEY_VALUE = "key_value"
    CACHE = "cache"
    LOCK = "lock"
    STREAM = "stream"
    EVENT_PUBLISH = "event_publish"
    EVENT_SUBSCRIBE = "event_subscribe"
    EVENT_STORE = "event_store"
    SQL_SESSION = "sql_session"
    NATIVE_CLIENT = "native_client"
    HEALTHCHECK = "healthcheck"


SECRET_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey", "dsn", "url", "uri", "credential")


def normalize_capability(value: DataCapability | str) -> DataCapability:
    if isinstance(value, DataCapability):
        return value
    return DataCapability(str(value))


def serialize_capabilities(values: set[DataCapability]) -> list[str]:
    return sorted(capability.value for capability in values)


def serialize_safe_capabilities(values: set[DataCapability]) -> list[str]:
    return sorted(
        capability.value
        for capability in values
        if capability is not DataCapability.NATIVE_CLIENT
    )


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text == "native_client":
            continue
        if any(marker in key_text.lower() for marker in SECRET_MARKERS):
            redacted[key_text] = "***"
        elif isinstance(item, Mapping):
            redacted[key_text] = redact_mapping(item)
        else:
            redacted[key_text] = item
    return redacted


@dataclass(frozen=True)
class DataResourceConfig:
    name: str
    type: str
    capabilities: set[DataCapability] = field(default_factory=set)
    role: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    healthcheck: dict[str, Any] = field(default_factory=dict)

    def safe_options(self) -> dict[str, Any]:
        return redact_mapping(self.options)

    def resolved_options(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Resolve canonical ``*_env`` settings without mutating the config."""
        options = dict(self.options)
        environment = os.environ if environ is None else environ
        url_env = options.get("url_env")
        if url_env:
            value = environment.get(str(url_env))
            if not value:
                raise DataConfigurationError(
                    f"Data resource '{self.name}' requires environment variable '{url_env}'"
                )
            options["url"] = value
        return options


@dataclass(frozen=True)
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    text: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    highlights: dict[str, list[str]] = field(default_factory=dict)
    title: str | None = None


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectBlob:
    key: str
    content: bytes
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteResult:
    status: str = "ok"
    written: int = 0
    deleted: int = 0
    matched: int = 0
    errors: list[str] = field(default_factory=list)
    message_id: str | None = None


@dataclass(frozen=True)
class HealthResult:
    status: str
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    code: str | None = None


@dataclass(frozen=True)
class InspectResult:
    name: str
    type: str
    capabilities: list[str]
    initialized: bool
    status: str = "ok"
    options: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LockHandle:
    name: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class StreamReadResult:
    messages: list[dict[str, Any]]
    cursor: str | None = None


class DataEventEnvelope(Model):
    """Framework-level envelope for a fact produced by a data resource."""

    __collection__ = "data_event_envelope"

    id = Column(UUID4, default="generate_uuid4", primary_key=True)
    type = Column(CoreString, index=True, nullable=False, example="document.indexed")
    source = Column(CoreString, index=True, nullable=False, example="documents.ingestion")
    subject = Column(CoreString, index=True, example="documents/doc-123")
    specversion = Column(CoreString, default="1.0")
    schema_version = Column(CoreString, default="1")
    resource = Column(CoreString, index=True, example="documents.local")
    operation = Column(
        CoreEnum(enum=["create", "update", "delete", "upsert", "publish", "ack"]),
        index=True,
        example="upsert",
    )
    payload = Column(CoreJson, default={})
    metadata = Column(CoreJson, default={})
    correlation_id = Column(CoreString, index=True)
    causation_id = Column(CoreString, index=True)
    occurred_at = Column(CoreDateTime, default="now", index=True)


class DataEventSchemaRef(Model):
    """Reference to a domain payload schema owned by an application."""

    __collection__ = "data_event_schema_ref"

    name = Column(CoreString, nullable=False)
    version = Column(CoreString, default="1")
    schema_uri = Column(CoreString)
    content_type = Column(CoreString, default="application/json")
    checksum = Column(CoreString)
    metadata = Column(CoreJson, default={})


class DataEventPublishRequest(Model):
    __collection__ = "data_event_publish_request"

    resource = Column(CoreString, nullable=False)
    stream = Column(CoreString, nullable=False)
    event = Column(CoreJson, default={})
    options = Column(CoreJson, default={})


class DataEventPublishResult(Model):
    __collection__ = "data_event_publish_result"

    status = Column(CoreEnum(enum=["ok", "failed"]), default="ok")
    event_id = Column(CoreString)
    stream = Column(CoreString)
    message_id = Column(CoreString)
    published = Column(CoreBoolean, default=False)
    errors = Column(CoreList(CoreString()), default=[])
    metadata = Column(CoreJson, default={})


class DataEventReadRequest(Model):
    __collection__ = "data_event_read_request"

    resource = Column(CoreString, nullable=False)
    stream = Column(CoreString, nullable=False)
    cursor = Column(CoreString)
    limit = Column(CoreInteger, default=100)
    consumer = Column(CoreString)
    options = Column(CoreJson, default={})


class DataEventReadResult(Model):
    __collection__ = "data_event_read_result"

    status = Column(CoreEnum(enum=["ok", "failed"]), default="ok")
    events = Column(CoreList(CoreJson()), default=[])
    cursor = Column(CoreString)
    count = Column(CoreInteger, default=0)
    errors = Column(CoreList(CoreString()), default=[])
    metadata = Column(CoreJson, default={})


class DataEventAckRequest(Model):
    __collection__ = "data_event_ack_request"

    resource = Column(CoreString, nullable=False)
    stream = Column(CoreString, nullable=False)
    message_id = Column(CoreString, nullable=False)
    event_id = Column(CoreString)
    consumer = Column(CoreString)
    options = Column(CoreJson, default={})


class DataEventAckResult(Model):
    __collection__ = "data_event_ack_result"

    status = Column(CoreEnum(enum=["ok", "failed"]), default="ok")
    event_id = Column(CoreString)
    message_id = Column(CoreString)
    acked = Column(CoreBoolean, default=False)
    errors = Column(CoreList(CoreString()), default=[])
    metadata = Column(CoreJson, default={})


def event_to_mapping(event: DataEventEnvelope | Mapping[str, Any]) -> dict[str, Any]:
    """Convert an envelope or plain mapping to a transport-safe event mapping."""

    if isinstance(event, Mapping):
        return _json_safe(dict(event))
    if not isinstance(event, DataEventEnvelope):
        raise TypeError("event must be a DataEventEnvelope or a mapping")

    values: dict[str, Any] = {}
    for name, column in event.columns.items():
        value = getattr(event, name, None)
        if getattr(column.field_type, "data_type", None) == "json":
            if value is None:
                value = column.default() if callable(column.default) else column.default
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
        elif value is None:
            value = column.field_type.getstate(value, column)
        values[name] = _json_safe(value)
    return values


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
