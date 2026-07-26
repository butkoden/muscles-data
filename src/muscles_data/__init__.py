from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .catalog import DataAdapterCatalog, DataAdapterFactory
    from .config import DataConfig
    from .models import DataCapability, DataResourceConfig
    from .package import DataPackage
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
    from .runtime import DataResourceHandle, DataRuntime


__all__ = [
    "DataAdapterCatalog",
    "DataAdapterFactory",
    "DataCapability",
    "DataConfig",
    "DataPackage",
    "DataResourceConfig",
    "DataResourceHandle",
    "DataRuntime",
    "DocumentStorePort",
    "KeyValuePort",
    "LockPort",
    "ObjectStorePort",
    "SearchIndexPort",
    "SqlResourcePort",
    "StreamPort",
    "VectorSearchPort",
    "init_package",
]


def __getattr__(name: str):
    if name == "DataAdapterCatalog":
        from .catalog import DataAdapterCatalog
        return DataAdapterCatalog
    if name == "DataAdapterFactory":
        from .catalog import DataAdapterFactory
        return DataAdapterFactory
    if name == "DataCapability":
        from .models import DataCapability
        return DataCapability
    if name == "DataConfig":
        from .config import DataConfig
        return DataConfig
    if name == "DataPackage":
        from .package import DataPackage
        return DataPackage
    if name == "DataResourceConfig":
        from .models import DataResourceConfig
        return DataResourceConfig
    if name == "DataResourceHandle":
        from .runtime import DataResourceHandle
        return DataResourceHandle
    if name == "DataRuntime":
        from .runtime import DataRuntime
        return DataRuntime
    if name == "DocumentStorePort":
        from .ports import DocumentStorePort
        return DocumentStorePort
    if name == "KeyValuePort":
        from .ports import KeyValuePort
        return KeyValuePort
    if name == "LockPort":
        from .ports import LockPort
        return LockPort
    if name == "ObjectStorePort":
        from .ports import ObjectStorePort
        return ObjectStorePort
    if name == "SearchIndexPort":
        from .ports import SearchIndexPort
        return SearchIndexPort
    if name == "SqlResourcePort":
        from .ports import SqlResourcePort
        return SqlResourcePort
    if name == "StreamPort":
        from .ports import StreamPort
        return StreamPort
    if name == "VectorSearchPort":
        from .ports import VectorSearchPort
        return VectorSearchPort
    if name == "init_package":
        from .package import init_package
        return init_package
    raise AttributeError(name)


def __dir__():
    return sorted(__all__)
