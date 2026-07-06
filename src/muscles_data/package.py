from __future__ import annotations

import inspect
from typing import Any

from .actions import register_data_actions
from .catalog import DataAdapterCatalog
from .config import DataConfig
from .runtime import DataRuntime


class DataPackage:
    namespace = "data"

    def build_runtime(self, app, config):
        del app
        return DataRuntime(config=_normalize_config(config or {}), catalog=DataAdapterCatalog.with_defaults())

    def services(self, app, runtime: DataRuntime):
        del app
        return [_package_service(DataRuntime, lambda: runtime)]

    def actions(self, app, runtime: DataRuntime, *, config):
        del runtime, config
        register_data_actions(app, transports=["http", "mcp", "cli"])
        return []

    def inspection_provider(self, app, runtime: DataRuntime, config=None):
        del app, config
        return runtime.inspect

    def doctor_provider(self, app, runtime: DataRuntime, config=None):
        del app, config
        return runtime.doctor

    def init(self, app, config):
        runtime = self.build_runtime(app, config or {})
        _apply_services(app, self.services(app, runtime))
        self.actions(app, runtime, config=config)
        return runtime


def init_package(app, config):
    package = DataPackage()
    installable = _resolve_install_hook()
    if installable is not None:
        try:
            return installable(app=app, config=config, package=package)  # type: ignore[call-arg]
        except Exception:
            pass
    return package.init(app, config or {})


def _normalize_config(config) -> DataConfig:
    if isinstance(config, DataConfig):
        return config
    if not isinstance(config, dict):
        if hasattr(config, "_object"):
            raw = getattr(config, "_object")
            if isinstance(raw, dict):
                config = raw
        elif hasattr(config, "__dict__"):
            config = dict(config.__dict__)
        else:
            config = dict(config) if config is not None else {}
    return DataConfig.from_raw(config or {})


def _package_service(interface: type, provider: Any):
    try:
        from muscles import PackageService  # type: ignore[import-not-found]

        return PackageService(interface=interface, provider=provider)
    except Exception:
        return {"interface": interface, "provider": provider}


def _apply_services(app, services: Any) -> None:
    container = getattr(app, "container", None)
    if container is None:
        container = _dependency_container()
        setattr(app, "container", container)
    for service in services or []:
        if isinstance(service, dict):
            container.register(
                service["interface"],
                service["provider"],
                *tuple(service.get("args", ())),
                scope=service.get("scope", getattr(container, "APP", "app")),
                **dict(service.get("kwargs", {})),
            )
            continue
        container.register(
            service.interface,
            service.provider,
            *tuple(getattr(service, "args", ())),
            scope=getattr(service, "scope", getattr(container, "APP", "app")),
            **dict(getattr(service, "kwargs", {})),
        )


def _resolve_install_hook():
    try:
        from muscles.core.lifecycle import install_package  # type: ignore[import-not-found]
        return install_package
    except Exception:
        try:
            from muscles.lifecycle import install_package  # type: ignore[import-not-found]
            return install_package
        except Exception:
            return None


def _dependency_container():
    try:
        from muscles.core import DependencyContainer  # type: ignore[import-not-found]
        return DependencyContainer()
    except Exception:  # pragma: no cover
        return _LegacyContainer()


class _LegacyContainer:
    def __init__(self):
        self._entries: dict[type, tuple[Any, tuple[Any, ...], dict[str, Any]]] = {}

    def register(self, interface: type, provider: Any, *args: Any, **kwargs: Any):
        self._entries[interface] = (provider, args, kwargs)

    def resolve(self, interface: type):
        if interface not in self._entries:
            raise KeyError(f"Dependency {interface.__name__} not registered")
        provider, args, kwargs = self._entries[interface]
        if inspect.isclass(provider):
            return provider(*args, **kwargs)
        if callable(provider):
            return provider(*args, **kwargs)
        return provider
