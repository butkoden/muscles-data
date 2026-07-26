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


class DataConfigurationError(DataError):
    """Raised when a resource configuration is incomplete or invalid."""


class DataConnectionError(DataError):
    """Raised when a backend cannot be reached or used."""


class DataAuthenticationError(DataConnectionError):
    """Raised when a backend rejects configured credentials."""


class DataTimeoutError(DataConnectionError):
    """Raised when a backend operation exceeds its timeout."""


class DataResourceMissingError(DataError):
    """Raised when a backend resource such as an index is missing."""


class DataSchemaMismatchError(DataError):
    """Raised when a backend schema cannot satisfy the port contract."""


class DataUnsupportedOperationError(DataError):
    """Raised when a backend does not support a requested port operation."""


class DataVectorDimensionError(DataSchemaMismatchError):
    """Raised when a vector does not match the configured backend dimension."""
