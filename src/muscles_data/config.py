from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import DataCapability, DataResourceConfig, normalize_capability


RESERVED_RESOURCE_KEYS = {"type", "capabilities", "role", "healthcheck"}


@dataclass(frozen=True)
class DataConfig:
    resources: dict[str, DataResourceConfig] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, value: Mapping[str, Any] | None) -> "DataConfig":
        raw = dict(value or {})
        if "data" in raw and isinstance(raw["data"], Mapping):
            raw = dict(raw["data"])
        raw_resources = dict(raw.get("resources", {}) or {})
        resources: dict[str, DataResourceConfig] = {}
        for name, resource_value in raw_resources.items():
            normalized = dict(resource_value or {})
            resource_type = str(normalized.get("type", "")).strip()
            if not resource_type:
                raise ValueError(f"data resource '{name}' requires type")
            if resource_type == "sql" and not normalized.get("connection"):
                raise ValueError(f"sql data resource '{name}' requires connection")
            if resource_type == "sqlalchemy" and not normalized.get("url"):
                raise ValueError(f"sqlalchemy data resource '{name}' requires url")
            if resource_type == "qdrant":
                if not normalized.get("url"):
                    raise ValueError(f"qdrant data resource '{name}' requires url")
                if not normalized.get("collection"):
                    raise ValueError(f"qdrant data resource '{name}' requires collection")
            if resource_type == "elasticsearch":
                if not normalized.get("url"):
                    raise ValueError(f"elasticsearch data resource '{name}' requires url")
                if not normalized.get("index"):
                    raise ValueError(f"elasticsearch data resource '{name}' requires index")
            capabilities = {
                normalize_capability(item)
                for item in normalized.get("capabilities", []) or []
            }
            options = {
                key: item
                for key, item in normalized.items()
                if key not in RESERVED_RESOURCE_KEYS
            }
            resources[str(name)] = DataResourceConfig(
                name=str(name),
                type=resource_type,
                capabilities=capabilities,
                role=str(normalized["role"]) if normalized.get("role") is not None else None,
                options=options,
                healthcheck=dict(normalized.get("healthcheck", {}) or {}),
            )
        return cls(resources=resources)
