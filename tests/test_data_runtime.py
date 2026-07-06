from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from muscles import ActionDispatcher, inspect_application

from muscles_data import DataPackage, init_package
from muscles_data.adapters.memory import (
    InMemoryDocumentStoreAdapter,
    InMemoryKeyValueAdapter,
    InMemoryObjectStoreAdapter,
    InMemorySearchIndexAdapter,
    InMemoryVectorAdapter,
    SqlBridgeFactory,
)
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.errors import DataCapabilityError, SqlConnectionMissingError, SqlRegistryMissingError
from muscles_data.models import DataCapability, DataResourceConfig
from muscles_data.ports import (
    DocumentStorePort,
    KeyValuePort,
    ObjectStorePort,
    SearchIndexPort,
    SqlResourcePort,
    VectorSearchPort,
)
from muscles_data.runtime import DataRuntime


class CountingVectorFactory:
    resource_type = "counting_vector"

    def __init__(self) -> None:
        self.created = 0

    def capabilities(self, config: DataResourceConfig) -> set[DataCapability]:
        del config
        return {DataCapability.VECTOR_SEARCH, DataCapability.VECTOR_WRITE}

    def create(self, config: DataResourceConfig) -> InMemoryVectorAdapter:
        self.created += 1
        return InMemoryVectorAdapter(config)


class FakeSqlRegistry:
    def __init__(self, *, fail_inspect: bool = False) -> None:
        self.fail_inspect = fail_inspect
        self.sessions: list[str] = []
        self.factories: list[str] = []
        self.inspections: list[str] = []
        self.known = {
            "main": {
                "status": "ok",
                "connection": {
                    "name": "main",
                    "url": "postgresql://user:secret@localhost/app",
                    "safe_url": "postgresql://***@localhost/app",
                    "role": "read_write",
                },
            }
        }

    def names(self) -> list[str]:
        return sorted(self.known)

    def session_factory(self, name: str = "default"):
        self.factories.append(name)
        self._require(name)
        return f"factory:{name}"

    def session(self, name: str = "default"):
        self.sessions.append(name)
        self._require(name)
        return f"session:{name}"

    def inspect(self, name: str = "default") -> dict[str, Any]:
        self.inspections.append(name)
        self._require(name)
        if self.fail_inspect:
            return {"status": "failed", "connection": self.known[name]["connection"]}
        return dict(self.known[name])

    def _require(self, name: str) -> None:
        if name not in self.known:
            raise KeyError(f"Unknown SQL connection: {name}")


def _config() -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "vector.docs": {"type": "memory_vector"},
                "search.docs": {"type": "memory_search", "url": "https://secret.example"},
                "cache.default": {"type": "memory_kv", "token": "super-secret"},
                "objects.docs": {"type": "memory_object"},
                "mongo.content": {"type": "memory_document"},
                "native.debug": {"type": "memory_kv", "native_client": True},
                "sql.main": {"type": "sql", "connection": "main", "role": "read_write"},
                "broken.one": {"type": "missing_factory"},
            }
        }
    }


def test_config_parser_accepts_resources_and_redacts_secrets():
    config = DataConfig.from_raw(_config())

    assert sorted(config.resources) == [
        "broken.one",
        "cache.default",
        "mongo.content",
        "native.debug",
        "objects.docs",
        "search.docs",
        "sql.main",
        "vector.docs",
    ]
    assert config.resources["cache.default"].type == "memory_kv"
    assert config.resources["cache.default"].safe_options()["token"] == "***"
    assert config.resources["search.docs"].safe_options()["url"] == "***"


def test_catalog_rejects_duplicate_factory():
    catalog = DataAdapterCatalog()
    factory = CountingVectorFactory()

    catalog.register(factory)

    with pytest.raises(ValueError, match="already registered"):
        catalog.register(factory)


def test_sql_resource_config_requires_connection():
    with pytest.raises(ValueError, match="requires connection"):
        DataConfig.from_raw({"data": {"resources": {"sql.main": {"type": "sql"}}}})


def test_runtime_lazy_initialization_and_capability_mismatch():
    factory = CountingVectorFactory()
    catalog = DataAdapterCatalog()
    catalog.register(factory)
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"vector.docs": {"type": "counting_vector"}}}}
        ),
        catalog=catalog,
    )

    assert factory.created == 0
    first = runtime.require_port("vector.docs", VectorSearchPort)
    second = runtime.require_port("vector.docs", VectorSearchPort)

    assert first is second
    assert factory.created == 1
    with pytest.raises(DataCapabilityError, match="does not provide"):
        runtime.require_port("vector.docs", KeyValuePort)


def test_native_client_requires_explicit_capability_and_stays_out_of_diagnostics():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())

    native_handle = runtime.require_resource("native.debug", DataCapability.NATIVE_CLIENT)
    native_client = native_handle.native_client()

    assert native_client is not None
    with pytest.raises(DataCapabilityError):
        runtime.require_resource("cache.default", DataCapability.NATIVE_CLIENT).native_client()
    diagnostics = runtime.inspect_resource("native.debug")
    assert "native_client" not in repr(diagnostics)
    assert "super-secret" not in repr(runtime.inspect_resource("cache.default"))


def test_in_memory_vector_search_upsert_and_delete():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    vector = runtime.require_port("vector.docs", VectorSearchPort)

    write = vector.upsert_vectors(
        [
            {"id": "a", "vector": [1.0, 0.0], "payload": {"title": "alpha"}},
            {"id": "b", "vector": [0.0, 1.0], "payload": {"title": "beta"}},
        ]
    )
    hits = vector.search_vectors([0.9, 0.1], limit=1)
    deleted = vector.delete_vectors(ids=["a"])

    assert write.written == 2
    assert hits[0].id == "a"
    assert deleted.deleted == 1


def test_in_memory_search_index_operations():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    search = runtime.require_port("search.docs", SearchIndexPort)

    search.upsert_documents(
        [
            {"id": "a", "text": "PostgreSQL and Kafka", "metadata": {"section": "experience"}},
            {"id": "b", "text": "Redis cache", "metadata": {"section": "infra"}},
        ]
    )
    hits = search.search_text("kafka", limit=10)

    assert [hit.id for hit in hits] == ["a"]
    assert hits[0].metadata["section"] == "experience"
    assert search.delete_documents(ids=["a"]).deleted == 1


def test_in_memory_object_store_operations_and_key_protection():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    objects = runtime.require_port("objects.docs", ObjectStorePort)

    objects.put_object("docs/a.txt", b"hello", content_type="text/plain")
    blob = objects.get_object("docs/a.txt")
    listed = objects.list_objects(prefix="docs/")

    assert blob.content == b"hello"
    assert listed[0].key == "docs/a.txt"
    with pytest.raises(ValueError, match="unsafe object key"):
        objects.put_object("../secret.txt", b"no")
    assert objects.delete_object("docs/a.txt").deleted == 1


def test_in_memory_key_value_ttl_and_delete():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    cache = runtime.require_port("cache.default", KeyValuePort)

    cache.set("cursor", b"1", ttl_seconds=0.01)
    assert cache.get("cursor") == b"1"
    time.sleep(0.02)
    assert cache.get("cursor") is None
    cache.set("cursor", b"2")
    assert cache.exists("cursor") is True
    assert cache.delete("cursor").deleted == 1


def test_in_memory_document_store_operations():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    store = runtime.require_port("mongo.content", DocumentStorePort)

    store.upsert_document("profiles", "denis", {"name": "Denis", "role": "developer"})
    store.upsert_document("profiles", "reader", {"name": "Reader", "role": "developer"})

    assert store.get_document("profiles", "denis")["name"] == "Denis"
    assert len(store.find_documents("profiles", filters={"role": "developer"})) == 2
    assert store.delete_document("profiles", "reader").deleted == 1


def test_package_registers_runtime_and_diagnostic_actions():
    app = SimpleNamespace()
    runtime = init_package(app, _config())

    assert app.container.resolve(DataRuntime) is runtime
    actions = {action["name"] for action in inspect_application(app)["actions"]}
    assert {"data.resources.list", "data.resource.inspect", "data.doctor"} <= actions

    dispatcher = ActionDispatcher(app)
    listed = dispatcher.execute("data.resources.list", {}).value
    inspected = dispatcher.execute("data.resource.inspect", {"name": "cache.default"}).value
    doctor = dispatcher.execute("data.doctor", {}).value

    assert "cache.default" in [item["name"] for item in listed["resources"]]
    assert inspected["options"]["token"] == "***"
    assert doctor["status"] == "failed"
    assert any(check["resource"] == "broken.one" for check in doctor["checks"])
    assert "super-secret" not in repr(listed)
    assert "super-secret" not in repr(doctor)


def test_sql_resource_port_delegates_to_sql_registry_without_startup_connection():
    registry = FakeSqlRegistry()
    catalog = DataAdapterCatalog.with_defaults(sql_registry_provider=lambda: registry)
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=catalog)

    listed = runtime.list_resources()
    assert "sql.main" in [item["name"] for item in listed]
    assert ["sql_session"] == [
        capability
        for item in listed
        if item["name"] == "sql.main"
        for capability in item["capabilities"]
        if capability == "sql_session"
    ]
    assert registry.sessions == []
    assert registry.inspections == []

    sql = runtime.require_port("sql.main", SqlResourcePort)

    assert sql.connection_name() == "main"
    assert sql.session() == "session:main"
    assert sql.session_factory() == "factory:main"
    inspection = sql.inspect()
    assert inspection["status"] == "ok"
    assert inspection["connection"]["url"] == "***"
    assert inspection["connection"]["safe_url"] == "postgresql://***@localhost/app"
    assert sql.doctor()["status"] == "ok"
    assert registry.sessions == ["main"]
    assert registry.factories == ["main"]


def test_sql_resource_port_reports_missing_registry_and_connection():
    missing_registry_runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())

    with pytest.raises(SqlRegistryMissingError):
        missing_registry_runtime.require_port("sql.main", SqlResourcePort).session()

    registry = FakeSqlRegistry()
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"sql.missing": {"type": "sql", "connection": "missing"}}}}
        ),
        catalog=DataAdapterCatalog.with_defaults(sql_registry_provider=lambda: registry),
    )

    sql = runtime.require_port("sql.missing", SqlResourcePort)
    with pytest.raises(SqlConnectionMissingError, match="missing"):
        sql.session()


def test_sql_doctor_handles_partial_failure_safely():
    registry = FakeSqlRegistry(fail_inspect=True)
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults(sql_registry_provider=lambda: registry))

    doctor = runtime.doctor()

    assert doctor["status"] == "failed"
    sql_checks = [check for check in doctor["checks"] if check["resource"] == "sql.main"]
    assert sql_checks[0]["status"] == "failed"
    assert "secret" not in repr(doctor)


def test_runtime_close_is_idempotent():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    runtime.require_port("cache.default", KeyValuePort)

    first = runtime.close()
    second = runtime.close()

    assert first["status"] == "ok"
    assert second["status"] == "ok"


def test_data_source_does_not_import_vendor_or_ai_packages():
    source_root = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "muscles_data"
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))

    for marker in ("muscles_ai", "muscles_otel", "qdrant", "elasticsearch", "opensearch", "redis", "pymongo", "boto3", "sqlalchemy"):
        assert marker not in source_text


def test_package_public_exports():
    import muscles_data as md

    assert md.DataRuntime
    assert md.DataCapability
    assert md.VectorSearchPort
    assert md.ObjectStorePort
    assert md.SqlResourcePort
    assert DataPackage.namespace == "data"
