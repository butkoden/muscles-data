from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Mapping

from ..config import DataResourceConfig
from ..errors import SqlAlchemyClientMissingError, SqlAlchemyConfigError, SqlAlchemyConnectionError
from ..models import DataCapability, HealthResult, InspectResult


_ENGINE_UNSET = object()
_SESSION_FACTORY_UNSET = object()
_ALLOWED_OPTIONS = {
    "url",
    "name",
    "native_client",
    "echo",
    "pool_pre_ping",
    "pool_size",
    "max_overflow",
    "connect_args",
    "future",
}
_ENGINE_OPTIONS = {"echo", "pool_pre_ping", "pool_size", "max_overflow", "connect_args", "future"}


class SqlAlchemySqlResourceAdapter:
    resource_type = "sqlalchemy"

    def __init__(
        self,
        config: DataResourceConfig,
        *,
        sqlalchemy_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self._sqlalchemy_provider = sqlalchemy_provider
        self._sqlalchemy: Any | None = None
        self._engine: Any = _ENGINE_UNSET
        self._session_factory: Any = _SESSION_FACTORY_UNSET
        self._lock = threading.RLock()
        self.closed = False

    def connection_name(self) -> str:
        return str(self.config.options.get("name", self.config.name))

    def session(self):
        try:
            return self.session_factory()()
        except (SqlAlchemyClientMissingError, SqlAlchemyConfigError, SqlAlchemyConnectionError):
            raise
        except Exception as exc:
            raise SqlAlchemyConnectionError(self._safe_error(exc)) from exc

    def session_factory(self):
        if self._session_factory is _SESSION_FACTORY_UNSET:
            with self._lock:
                if self._session_factory is _SESSION_FACTORY_UNSET:
                    self._sqlalchemy_module()
                    try:
                        orm = importlib.import_module("sqlalchemy.orm")
                        self._session_factory = orm.sessionmaker(bind=self._engine_instance())
                    except (SqlAlchemyClientMissingError, SqlAlchemyConfigError, SqlAlchemyConnectionError):
                        raise
                    except Exception as exc:
                        raise SqlAlchemyConnectionError(self._safe_error(exc)) from exc
        return self._session_factory

    def inspect(self) -> Mapping[str, Any]:
        return asdict(
            InspectResult(
                name=self.config.name,
                type=self.config.type,
                capabilities=[],
                initialized=self._engine is not _ENGINE_UNSET,
                status="ok",
                options=self.config.safe_options(),
                details={
                    "backend": "sqlalchemy",
                    "connection": self.connection_name(),
                    "engine_initialized": self._engine is not _ENGINE_UNSET,
                },
            )
        )

    def doctor(self) -> Mapping[str, Any]:
        try:
            sqlalchemy = self._sqlalchemy_module()
            with self._engine_instance().connect() as connection:
                connection.execute(sqlalchemy.text("SELECT 1"))
        except Exception as exc:
            return {
                "status": "failed",
                "message": self._safe_error(exc),
                "details": {"backend": "sqlalchemy", "connection": self.connection_name()},
            }
        return {
            "status": "ok",
            "message": "SQLAlchemy connection is available",
            "details": {"backend": "sqlalchemy", "connection": self.connection_name()},
        }

    def health(self) -> HealthResult:
        doctor = self.doctor()
        return HealthResult(
            status=str(doctor.get("status", "failed")),
            message=doctor.get("message"),
            details=dict(doctor.get("details", {}) or {}),
        )

    def close(self) -> None:
        if self._engine is not _ENGINE_UNSET:
            dispose = getattr(self._engine, "dispose", None)
            if callable(dispose):
                dispose()
        self.closed = True

    def native_client(self):
        return {"engine": self._engine_instance(), "session_factory": self.session_factory()}

    def _engine_instance(self):
        if self._engine is _ENGINE_UNSET:
            with self._lock:
                if self._engine is _ENGINE_UNSET:
                    self._engine = self._create_engine()
        return self._engine

    def _create_engine(self):
        self._validate_options()
        sqlalchemy = self._sqlalchemy_module()
        kwargs = _engine_options(self.config.options)
        try:
            return sqlalchemy.create_engine(str(self.config.options["url"]), **kwargs)
        except Exception as exc:
            raise SqlAlchemyConnectionError(self._safe_error(exc)) from exc

    def _sqlalchemy_module(self):
        if self._sqlalchemy is None:
            module = self._sqlalchemy_provider() if self._sqlalchemy_provider else _default_sqlalchemy_module()
            if module is None:
                raise SqlAlchemyClientMissingError("Install SQLAlchemy or muscles-data[sqlalchemy] to use type=sqlalchemy")
            self._sqlalchemy = module
        return self._sqlalchemy

    def _validate_options(self) -> None:
        unknown = sorted(set(self.config.options) - _ALLOWED_OPTIONS)
        if unknown:
            names = ", ".join(unknown)
            raise SqlAlchemyConfigError(f"Unsupported SQLAlchemy resource options: {names}")
        connect_args = self.config.options.get("connect_args")
        if connect_args is not None and not isinstance(connect_args, Mapping):
            raise SqlAlchemyConfigError("SQLAlchemy connect_args must be a mapping")

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc)
        url = str(self.config.options.get("url", ""))
        if url:
            message = message.replace(url, "***")
        safe_url = self.config.safe_options().get("url")
        if isinstance(safe_url, str) and safe_url != url:
            message = message.replace(safe_url, "***")
        return message


class SqlAlchemySqlResourceFactory:
    resource_type = "sqlalchemy"

    def __init__(self, *, sqlalchemy_provider: Callable[[], Any] | None = None) -> None:
        self._sqlalchemy_provider = sqlalchemy_provider

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        native = {DataCapability.NATIVE_CLIENT} if bool(config.options.get("native_client")) else set()
        return {DataCapability.SQL_SESSION, DataCapability.HEALTHCHECK} | native

    def create(self, config: DataResourceConfig) -> SqlAlchemySqlResourceAdapter:
        return SqlAlchemySqlResourceAdapter(config, sqlalchemy_provider=self._sqlalchemy_provider)


def _engine_options(options: Mapping[str, Any]) -> dict[str, Any]:
    output = {key: options[key] for key in _ENGINE_OPTIONS if key in options}
    output.setdefault("future", True)
    return output


def _default_sqlalchemy_module():
    try:
        return importlib.import_module("sqlalchemy")
    except Exception as exc:
        raise SqlAlchemyClientMissingError("Install SQLAlchemy or muscles-data[sqlalchemy] to use type=sqlalchemy") from exc
