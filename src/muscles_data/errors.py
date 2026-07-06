from __future__ import annotations


class DataError(RuntimeError):
    """Base error for muscles-data runtime failures."""


class DataResourceNotFoundError(DataError):
    """Raised when a named data resource is not configured."""


class DataAdapterNotFoundError(DataError):
    """Raised when no adapter factory is registered for a resource type."""


class DataCapabilityError(DataError):
    """Raised when a resource cannot provide the requested typed port/capability."""


class SqlRegistryMissingError(DataError):
    """Raised when a SQL resource cannot find a SQL connection registry."""


class SqlConnectionMissingError(DataError):
    """Raised when a SQL resource references an unknown named SQL connection."""


class AdapterInitError(DataError):
    """Raised when an adapter cannot be initialized safely."""


class QdrantAdapterError(DataError):
    """Base error for Qdrant vector adapter failures."""


class QdrantClientMissingError(QdrantAdapterError):
    """Raised when Qdrant adapter is used without an available client."""


class QdrantConnectionError(QdrantAdapterError):
    """Raised when Qdrant operation cannot reach or use the backend."""


class QdrantFilterError(QdrantAdapterError):
    """Raised when a data filter cannot be translated to Qdrant."""


class QdrantDimensionError(QdrantAdapterError):
    """Raised when vectors are empty or incompatible with the Qdrant collection."""


class SqlAlchemyAdapterError(DataError):
    """Base error for direct SQLAlchemy resource adapter failures."""


class SqlAlchemyConfigError(ValueError, SqlAlchemyAdapterError):
    """Raised when a SQLAlchemy resource config cannot be mapped safely."""


class SqlAlchemyClientMissingError(SqlAlchemyAdapterError):
    """Raised when SQLAlchemy is not installed for a direct SQLAlchemy resource."""


class SqlAlchemyConnectionError(SqlAlchemyAdapterError):
    """Raised when a SQLAlchemy engine/session operation fails."""


class ElasticsearchAdapterError(DataError):
    """Base error for Elasticsearch search adapter failures."""


class ElasticsearchConfigError(ValueError, ElasticsearchAdapterError):
    """Raised when an Elasticsearch resource config cannot be mapped safely."""


class ElasticsearchClientMissingError(ElasticsearchAdapterError):
    """Raised when Elasticsearch adapter is used without an available client."""


class ElasticsearchConnectionError(ElasticsearchAdapterError):
    """Raised when an Elasticsearch operation cannot reach or use the backend."""


class ElasticsearchFilterError(ElasticsearchAdapterError):
    """Raised when a data filter cannot be translated to Elasticsearch."""


class OpenSearchAdapterError(DataError):
    """Base error for OpenSearch search adapter failures."""


class OpenSearchConfigError(ValueError, OpenSearchAdapterError):
    """Raised when an OpenSearch resource config cannot be mapped safely."""


class OpenSearchClientMissingError(OpenSearchAdapterError):
    """Raised when OpenSearch adapter is used without an available client."""


class OpenSearchConnectionError(OpenSearchAdapterError):
    """Raised when an OpenSearch operation cannot reach or use the backend."""


class OpenSearchFilterError(OpenSearchAdapterError):
    """Raised when a data filter cannot be translated to OpenSearch."""
