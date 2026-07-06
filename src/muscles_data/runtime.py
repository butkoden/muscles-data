from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from .catalog import DataAdapterCatalog, DataAdapterFactory
from .config import DataConfig, DataResourceConfig
from .errors import DataAdapterNotFoundError, DataCapabilityError, DataResourceNotFoundError
from .models import DataCapability, HealthResult, InspectResult, serialize_capabilities, serialize_safe_capabilities
from .ports import (
    DocumentStorePort,
    KeyValuePort,
    LockPort,
    ObjectStorePort,
    SearchIndexPort,
    SqlResourcePort,
    StreamPort,
    VectorSearchPort,
)


PORT_CAPABILITIES: dict[type, set[DataCapability]] = {
    VectorSearchPort: {DataCapability.VECTOR_SEARCH},
    SearchIndexPort: {DataCapability.KEYWORD_SEARCH},
    ObjectStorePort: {DataCapability.OBJECT_STORE},
    KeyValuePort: {DataCapability.KEY_VALUE},
    LockPort: {DataCapability.LOCK},
    StreamPort: {DataCapability.STREAM},
    DocumentStorePort: {DataCapability.DOCUMENT_STORE},
    SqlResourcePort: {DataCapability.SQL_SESSION},
}


class DataResourceHandle:
    def __init__(
        self,
        *,
        config: DataResourceConfig,
        factory: DataAdapterFactory,
        capabilities: set[DataCapability],
    ) -> None:
        self.name = config.name
        self.type = config.type
        self.config = config
        self.capabilities = set(capabilities)
        self._factory = factory
        self._adapter = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def initialized(self) -> bool:
        return self._adapter is not None

    def adapter(self):
        if self._closed:
            raise RuntimeError(f"Data resource '{self.name}' is closed")
        if self._adapter is None:
            with self._lock:
                if self._adapter is None:
                    self._adapter = self._factory.create(self.config)
        return self._adapter

    def as_port(self, port_type: type):
        adapter = self.adapter()
        if not isinstance(adapter, port_type):
            raise DataCapabilityError(
                f"Data resource '{self.name}' type '{self.type}' does not provide port {port_type.__name__}"
            )
        return adapter

    def require_capability(self, capability: DataCapability) -> "DataResourceHandle":
        if capability not in self.capabilities:
            raise DataCapabilityError(
                f"Data resource '{self.name}' type '{self.type}' does not provide capability '{capability.value}'"
            )
        return self

    def native_client(self):
        self.require_capability(DataCapability.NATIVE_CLIENT)
        adapter = self.adapter()
        native = getattr(adapter, "native_client", None)
        if native is None or not callable(native):
            raise DataCapabilityError(f"Data resource '{self.name}' does not expose native_client()")
        return native()

    def inspect(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        status = "ok"
        if self.initialized:
            raw = self.adapter().inspect()
            if is_dataclass(raw):
                raw = asdict(raw)
            if isinstance(raw, Mapping):
                status = str(raw.get("status", status))
                details = dict(raw.get("details", {}))
        result = InspectResult(
            name=self.name,
            type=self.type,
            capabilities=serialize_safe_capabilities(self.capabilities),
            initialized=self.initialized,
            status=status,
            options=self.config.safe_options(),
            details=details,
        )
        return asdict(result)

    def health(self) -> dict[str, Any]:
        if not self.initialized and not self.config.healthcheck.get("enabled", True):
            return asdict(HealthResult(status="skipped", message="healthcheck disabled"))
        raw = self.adapter().health()
        return asdict(raw) if is_dataclass(raw) else dict(raw)

    def close(self) -> None:
        if not self.initialized:
            self._closed = True
            return
        adapter = self._adapter
        self._closed = True
        if adapter is not None:
            adapter.close()


class DataRuntime:
    def __init__(self, *, config: DataConfig, catalog: DataAdapterCatalog | None = None) -> None:
        self.config = config
        self.catalog = catalog or DataAdapterCatalog.with_defaults()
        self._handles: dict[str, DataResourceHandle] = {}
        self._lock = threading.RLock()
        self._closed = False

    def list_resources(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "type": resource.type,
                "capabilities": serialize_safe_capabilities(self._capabilities_for(resource)),
                "initialized": name in self._handles and self._handles[name].initialized,
            }
            for name, resource in sorted(self.config.resources.items())
        ]

    def require_port(self, name: str, port_type: type):
        required = PORT_CAPABILITIES.get(port_type)
        if required:
            handle = self.require_resource(name)
            missing = required - handle.capabilities
            if missing:
                missing_names = ", ".join(sorted(item.value for item in missing))
                raise DataCapabilityError(
                    f"Data resource '{name}' does not provide required capability: {missing_names}"
                )
            return handle.as_port(port_type)
        return self.require_resource(name).as_port(port_type)

    def require_resource(self, name: str, capability: DataCapability | None = None) -> DataResourceHandle:
        if name not in self.config.resources:
            raise DataResourceNotFoundError(f"Data resource '{name}' is not configured")
        with self._lock:
            if name not in self._handles:
                resource = self.config.resources[name]
                factory = self.catalog.resolve(resource.type)
                self._handles[name] = DataResourceHandle(
                    config=resource,
                    factory=factory,
                    capabilities=self._capabilities_for(resource),
                )
            handle = self._handles[name]
        if capability is not None:
            handle.require_capability(capability)
        return handle

    def inspect(self) -> dict[str, Any]:
        return {
            "namespace": "data",
            "resources": self.list_resources(),
            "catalog": self.catalog.inspect(),
        }

    def inspect_resource(self, name: str) -> dict[str, Any]:
        if name not in self.config.resources:
            raise DataResourceNotFoundError(f"Data resource '{name}' is not configured")
        resource = self.config.resources[name]
        if not self.catalog.has_factory(resource.type):
            return {
                "name": name,
                "type": resource.type,
                "capabilities": serialize_safe_capabilities(resource.capabilities),
                "initialized": False,
                "status": "failed",
                "options": resource.safe_options(),
                "details": {"reason": "adapter_factory_not_found"},
            }
        return self.require_resource(name).inspect()

    def doctor(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        for name, resource in sorted(self.config.resources.items()):
            if not self.catalog.has_factory(resource.type):
                checks.append(
                    {
                        "name": f"data.resource.{name}.factory",
                        "resource": name,
                        "type": resource.type,
                        "status": "failed",
                        "reason": "adapter_factory_not_found",
                    }
                )
                continue
            handle = self.require_resource(name)
            health = handle.health() if resource.healthcheck.get("enabled", True) else {"status": "skipped"}
            checks.append(
                {
                    "name": f"data.resource.{name}.health",
                    "resource": name,
                    "type": resource.type,
                    "status": health.get("status", "ok"),
                    "message": health.get("message"),
                }
            )
        statuses = {check["status"] for check in checks}
        status = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "ok"
        return {"status": status, "checks": checks}

    def close(self) -> dict[str, Any]:
        errors: list[str] = []
        with self._lock:
            handles = list(self._handles.values())
        for handle in handles:
            try:
                handle.close()
            except Exception as exc:  # pragma: no cover
                errors.append(f"{handle.name}: {exc}")
        self._closed = True
        return {"status": "failed" if errors else "ok", "errors": errors}

    def _capabilities_for(self, config: DataResourceConfig) -> set[DataCapability]:
        try:
            inferred = set(self.catalog.resolve(config.type).capabilities(config))
        except DataAdapterNotFoundError:
            inferred = set()
        return set(config.capabilities) | inferred
