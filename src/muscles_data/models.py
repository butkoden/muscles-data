from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any, Mapping

from .errors import DataConfigurationError


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
