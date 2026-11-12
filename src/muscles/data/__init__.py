from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .migrations import MigrationBackend, MigrationRegistry, MigrationSource, discover_migration_modules
    from .catalog import DataAdapterCatalog, DataAdapterFactory
    from .config import DataConfig
    from .models import (
        DataCapability,
        DataEventAckRequest,
        DataEventAckResult,
        DataEventEnvelope,
        DataEventPublishRequest,
        DataEventPublishResult,
        DataEventReadRequest,
        DataEventReadResult,
        DataEventSchemaRef,
        DataResourceConfig,
    )
    from .package import DataPackage
    from .policies import (
        DataNonAtomicPolicyMode,
        DataOperationContext,
        DataOperationKind,
        DataOperationPolicy,
        DataOperationRequest,
        DataPolicyDecision,
        DataPolicyPipeline,
        DataPredicate,
        DataPredicateOperator,
        DataRelatedExists,
    )
    from .object_lifecycle import ObjectLifecycle, ObjectLifecycleEvent
    from .ports import (
        DocumentStorePort,
        EventConsumerPort,
        EventPublisherPort,
        EventStorePort,
        KeyValuePort,
        LockPort,
        ObjectStorePort,
        SearchIndexPort,
        SqlResourcePort,
        StreamPort,
        VectorSearchPort,
    )
    from .runtime import DataResourceHandle, DataRuntime
    from .policy_search import PolicySearchIndex, PolicyVectorSearch
    from .operation_journal import SqliteOperationJournal


__all__ = [
    "MigrationBackend",
    "MigrationRegistry",
    "MigrationSource",
    "discover_migration_modules",
    "DataAdapterCatalog",
    "DataAdapterFactory",
    "DataCapability",
    "DataEventAckRequest",
    "DataEventAckResult",
    "DataEventEnvelope",
    "DataEventPublishRequest",
    "DataEventPublishResult",
    "DataEventReadRequest",
    "DataEventReadResult",
    "DataEventSchemaRef",
    "DataConfig",
    "DataPackage",
    "DataOperationContext",
    "DataNonAtomicPolicyMode",
    "DataOperationKind",
    "DataOperationPolicy",
    "DataOperationRequest",
    "DataPolicyDecision",
    "DataPolicyPipeline",
    "PolicySearchIndex",
    "PolicyVectorSearch",
    "SqliteOperationJournal",
    "DataPredicate",
    "DataPredicateOperator",
    "DataRelatedExists",
    "ObjectLifecycle",
    "ObjectLifecycleEvent",
    "DataResourceConfig",
    "DataResourceHandle",
    "DataRuntime",
    "DocumentStorePort",
    "EventConsumerPort",
    "EventPublisherPort",
    "EventStorePort",
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
    if name == "SqliteOperationJournal":
        from .operation_journal import SqliteOperationJournal
        return SqliteOperationJournal
    if name in {"PolicySearchIndex", "PolicyVectorSearch"}:
        from . import policy_search
        return getattr(policy_search, name)
    if name in {"MigrationBackend", "MigrationRegistry", "MigrationSource", "discover_migration_modules"}:
        from . import migrations
        return getattr(migrations, name)
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
    if name == "DataEventAckRequest":
        from .models import DataEventAckRequest
        return DataEventAckRequest
    if name == "DataEventAckResult":
        from .models import DataEventAckResult
        return DataEventAckResult
    if name == "DataEventEnvelope":
        from .models import DataEventEnvelope
        return DataEventEnvelope
    if name == "DataEventPublishRequest":
        from .models import DataEventPublishRequest
        return DataEventPublishRequest
    if name == "DataEventPublishResult":
        from .models import DataEventPublishResult
        return DataEventPublishResult
    if name == "DataEventReadRequest":
        from .models import DataEventReadRequest
        return DataEventReadRequest
    if name == "DataEventReadResult":
        from .models import DataEventReadResult
        return DataEventReadResult
    if name == "DataEventSchemaRef":
        from .models import DataEventSchemaRef
        return DataEventSchemaRef
    if name == "DataPackage":
        from .package import DataPackage
        return DataPackage
    if name in {
        "DataNonAtomicPolicyMode",
        "DataOperationContext",
        "DataOperationKind",
        "DataOperationPolicy",
        "DataOperationRequest",
        "DataPolicyDecision",
        "DataPolicyPipeline",
        "DataPredicate",
        "DataPredicateOperator",
        "DataRelatedExists",
    }:
        from . import policies
        return getattr(policies, name)
    if name in {"ObjectLifecycle", "ObjectLifecycleEvent"}:
        from . import object_lifecycle
        return getattr(object_lifecycle, name)
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
    if name == "EventConsumerPort":
        from .ports import EventConsumerPort
        return EventConsumerPort
    if name == "EventPublisherPort":
        from .ports import EventPublisherPort
        return EventPublisherPort
    if name == "EventStorePort":
        from .ports import EventStorePort
        return EventStorePort
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
