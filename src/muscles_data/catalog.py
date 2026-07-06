from __future__ import annotations

from typing import Protocol

from .config import DataResourceConfig
from .errors import DataAdapterNotFoundError
from .models import DataCapability


class DataAdapterFactory(Protocol):
    resource_type: str

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]: ...

    def create(self, config: DataResourceConfig): ...


class DataAdapterCatalog:
    def __init__(self) -> None:
        self._factories: dict[str, DataAdapterFactory] = {}

    def register(self, factory: DataAdapterFactory) -> None:
        if factory.resource_type in self._factories:
            raise ValueError(f"Adapter factory for '{factory.resource_type}' is already registered")
        self._factories[factory.resource_type] = factory

    def resolve(self, resource_type: str) -> DataAdapterFactory:
        try:
            return self._factories[resource_type]
        except KeyError as exc:
            raise DataAdapterNotFoundError(f"No data adapter factory registered for type '{resource_type}'") from exc

    def has_factory(self, resource_type: str) -> bool:
        return resource_type in self._factories

    def inspect(self) -> list[dict[str, str]]:
        return [{"type": name} for name in sorted(self._factories)]

    @classmethod
    def with_defaults(
        cls,
        *,
        sql_registry_provider=None,
        sqlalchemy_provider=None,
        elasticsearch_client_factory=None,
        opensearch_client_factory=None,
        qdrant_client_factory=None,
        qdrant_models_provider=None,
    ) -> "DataAdapterCatalog":
        from .adapters.elasticsearch import ElasticsearchSearchFactory
        from .adapters.memory import (
            InMemoryDocumentStoreFactory,
            InMemoryKeyValueFactory,
            InMemoryObjectStoreFactory,
            InMemorySearchIndexFactory,
            InMemoryVectorFactory,
            SqlBridgeFactory,
        )
        from .adapters.opensearch import OpenSearchSearchFactory
        from .adapters.qdrant import QdrantVectorFactory
        from .adapters.sqlalchemy import SqlAlchemySqlResourceFactory

        catalog = cls()
        for factory in (
            InMemoryVectorFactory(),
            QdrantVectorFactory(client_factory=qdrant_client_factory, models_provider=qdrant_models_provider),
            InMemorySearchIndexFactory(),
            ElasticsearchSearchFactory(client_factory=elasticsearch_client_factory),
            OpenSearchSearchFactory(client_factory=opensearch_client_factory),
            InMemoryObjectStoreFactory(),
            InMemoryKeyValueFactory(),
            InMemoryDocumentStoreFactory(),
            SqlBridgeFactory(registry_provider=sql_registry_provider),
            SqlAlchemySqlResourceFactory(sqlalchemy_provider=sqlalchemy_provider),
        ):
            catalog.register(factory)
        return catalog
