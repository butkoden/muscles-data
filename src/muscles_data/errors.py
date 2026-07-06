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
