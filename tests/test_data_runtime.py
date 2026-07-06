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
from muscles_data.adapters.qdrant import QdrantVectorFactory, qdrant_filter_from_mapping
from muscles_data.adapters.sqlalchemy import SqlAlchemySqlResourceFactory
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.errors import (
    DataCapabilityError,
    QdrantClientMissingError,
    QdrantConnectionError,
    QdrantDimensionError,
    QdrantFilterError,
    SqlAlchemyClientMissingError,
    SqlAlchemyConnectionError,
    SqlConnectionMissingError,
    SqlRegistryMissingError,
)
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


class FakeQdrantPoint:
    def __init__(self, point_id: str, score: float, payload: dict[str, Any]) -> None:
        self.id = point_id
        self.score = score
        self.payload = payload
        self.version = 7


class FakeQdrantQueryResult:
    def __init__(self, points: list[FakeQdrantPoint]) -> None:
        self.points = points


class FakeQdrantClient:
    def __init__(self, *, fail_health: bool = False) -> None:
        self.fail_health = fail_health
        self.queries: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.collection_checks: list[str] = []
        self.closed = False

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return FakeQdrantQueryResult(
            [
                FakeQdrantPoint("doc-1", 0.91, {"section": "docs", "title": "Qdrant"}),
                FakeQdrantPoint("doc-2", 0.42, {"section": "other"}),
            ]
        )

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return SimpleNamespace(status="completed")

    def delete(self, **kwargs):
        self.deletes.append(kwargs)
        return SimpleNamespace(status="completed")

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_checks.append(collection_name)
        if self.fail_health:
            raise TimeoutError("connection timed out")
        return collection_name == "docs"

    def close(self) -> None:
        self.closed = True


class FakeQdrantModels:
    class MatchValue:
        def __init__(self, value) -> None:
            self.value = value

    class MatchAny:
        def __init__(self, any) -> None:
            self.any = any

    class Range:
        def __init__(self, **kwargs) -> None:
            self.values = kwargs

    class FieldCondition:
        def __init__(self, *, key: str, match=None, range=None) -> None:
            self.key = key
            self.match = match
            self.range = range

    class Filter:
        def __init__(self, *, must=None, should=None, must_not=None) -> None:
            self.must = must or []
            self.should = should or []
            self.must_not = must_not or []

    class PointStruct:
        def __init__(self, *, id, vector, payload=None) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload or {}

    class PointIdsList:
        def __init__(self, *, points) -> None:
            self.points = points

    class FilterSelector:
        def __init__(self, *, filter) -> None:
            self.filter = filter


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


def _qdrant_config() -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "vector.qdrant": {
                    "type": "qdrant",
                    "url": "https://qdrant.example",
                    "api_key": "qdrant-secret",
                    "collection": "docs",
                    "timeout": 1.5,
                    "prefer_grpc": True,
                    "native_client": True,
                }
            }
        }
    }


def _sqlalchemy_config(url: str = "sqlite:///:memory:") -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "sql.local": {
                    "type": "sqlalchemy",
                    "url": url,
                    "role": "read_write",
                    "echo": False,
                    "pool_pre_ping": True,
                    "native_client": True,
                }
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


def test_sqlalchemy_resource_config_requires_url():
    assert DataConfig.from_raw(_sqlalchemy_config()).resources["sql.local"].type == "sqlalchemy"

    with pytest.raises(ValueError, match="requires url"):
        DataConfig.from_raw({"data": {"resources": {"sql.local": {"type": "sqlalchemy"}}}})


def test_qdrant_resource_config_requires_url_and_collection():
    assert DataConfig.from_raw(_qdrant_config()).resources["vector.qdrant"].type == "qdrant"

    with pytest.raises(ValueError, match="requires url"):
        DataConfig.from_raw({"data": {"resources": {"vector.qdrant": {"type": "qdrant", "collection": "docs"}}}})

    with pytest.raises(ValueError, match="requires collection"):
        DataConfig.from_raw({"data": {"resources": {"vector.qdrant": {"type": "qdrant", "url": "http://localhost:6333"}}}})


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


def test_sqlalchemy_port_is_registered_lazy_and_exposes_sessions():
    sqlalchemy = pytest.importorskip("sqlalchemy")
    runtime = DataRuntime(config=DataConfig.from_raw(_sqlalchemy_config()), catalog=DataAdapterCatalog.with_defaults())

    listed = runtime.list_resources()
    sql_resource = next(item for item in listed if item["name"] == "sql.local")
    inspected_before = runtime.inspect_resource("sql.local")

    assert sql_resource["type"] == "sqlalchemy"
    assert "sql_session" in sql_resource["capabilities"]
    assert "native_client" not in sql_resource["capabilities"]
    assert sql_resource["initialized"] is False
    assert inspected_before["initialized"] is False
    assert inspected_before["options"]["url"] == "***"
    assert DataAdapterCatalog.with_defaults().has_factory(SqlAlchemySqlResourceFactory.resource_type)

    sql = runtime.require_port("sql.local", SqlResourcePort)

    assert sql.connection_name() == "sql.local"
    assert runtime.inspect_resource("sql.local")["initialized"] is True
    with sql.session() as session:
        session.execute(sqlalchemy.text("create table notes (id integer primary key, title varchar)"))
        session.execute(sqlalchemy.text("insert into notes (title) values ('typed port')"))
        rows = session.execute(sqlalchemy.text("select title from notes")).fetchall()
        session.commit()

    assert [row[0] for row in rows] == ["typed port"]
    assert sql.session_factory() is sql.session_factory()
    native = runtime.require_resource("sql.local", DataCapability.NATIVE_CLIENT).native_client()
    assert {"engine", "session_factory"} <= set(native)
    assert sql.inspect()["details"]["backend"] == "sqlalchemy"
    assert sql.doctor()["status"] == "ok"

    assert runtime.close()["status"] == "ok"
    assert runtime.close()["status"] == "ok"


def test_sqlalchemy_adapter_redacts_dsn_and_reports_safe_failures():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            _sqlalchemy_config("missingdialect://user:secret@localhost/app")
        ),
        catalog=DataAdapterCatalog.with_defaults(),
    )

    inspected = runtime.inspect_resource("sql.local")
    assert inspected["options"]["url"] == "***"
    assert "secret" not in repr(inspected)

    doctor = runtime.doctor()
    assert doctor["status"] == "failed"
    assert "secret" not in repr(doctor)

    sql = runtime.require_port("sql.local", SqlResourcePort)
    with pytest.raises(SqlAlchemyConnectionError):
        sql.session()


def test_sqlalchemy_adapter_rejects_unknown_options_and_missing_client():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "sql.local": {
                            "type": "sqlalchemy",
                            "url": "sqlite:///:memory:",
                            "unsafe_option": True,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(),
    )

    with pytest.raises(ValueError, match="Unsupported SQLAlchemy resource options"):
        runtime.require_port("sql.local", SqlResourcePort).session()

    missing_client_runtime = DataRuntime(
        config=DataConfig.from_raw(_sqlalchemy_config()),
        catalog=DataAdapterCatalog.with_defaults(sqlalchemy_provider=lambda: None),
    )
    with pytest.raises(SqlAlchemyClientMissingError):
        missing_client_runtime.require_port("sql.local", SqlResourcePort).session()


def test_qdrant_vector_port_is_registered_lazy_and_maps_operations():
    client = FakeQdrantClient()
    catalog = DataAdapterCatalog.with_defaults(
        qdrant_client_factory=lambda _config: client,
        qdrant_models_provider=lambda: FakeQdrantModels,
    )
    runtime = DataRuntime(config=DataConfig.from_raw(_qdrant_config()), catalog=catalog)

    listed = runtime.list_resources()
    qdrant = next(item for item in listed if item["name"] == "vector.qdrant")

    assert qdrant["type"] == "qdrant"
    assert {"vector_search", "vector_write"} <= set(qdrant["capabilities"])
    assert "native_client" not in qdrant["capabilities"]
    assert client.queries == []

    vector = runtime.require_port("vector.qdrant", VectorSearchPort)
    hits = vector.search_vectors([0.1, 0.9], filters={"section": "docs", "year": {"gte": 2024}}, limit=2)
    write = vector.upsert_vectors(
        [
            {"id": "doc-1", "vector": [0.1, 0.9], "payload": {"section": "docs"}},
            {"id": "doc-2", "vector": [0.2, 0.8]},
        ],
        options={"wait": True},
    )
    deleted_ids = vector.delete_vectors(ids=["doc-2"], options={"wait": True})
    deleted_filter = vector.delete_vectors(filters={"section": ["docs", "notes"]})

    assert [hit.id for hit in hits] == ["doc-1", "doc-2"]
    assert hits[0].score == pytest.approx(0.91)
    assert hits[0].payload["section"] == "docs"
    assert hits[0].metadata["backend"] == "qdrant"
    assert hits[0].metadata["version"] == 7
    assert client.queries[0]["collection_name"] == "docs"
    assert client.queries[0]["limit"] == 2
    assert client.queries[0]["with_payload"] is True
    assert client.queries[0]["with_vectors"] is False
    assert client.queries[0]["query_filter"].must[0].key == "section"
    assert client.queries[0]["query_filter"].must[1].range.values == {"gte": 2024}
    assert write.written == 2
    assert client.upserts[0]["points"][0].id == "doc-1"
    assert client.upserts[0]["points"][0].payload == {"section": "docs"}
    assert deleted_ids.deleted == 1
    assert client.deletes[0]["points_selector"].points == ["doc-2"]
    assert deleted_filter.status == "ok"
    assert client.deletes[1]["points_selector"].filter.must[0].match.any == ["docs", "notes"]

    native = runtime.require_resource("vector.qdrant", DataCapability.NATIVE_CLIENT).native_client()
    assert native is client
    assert client.collection_checks == []


def test_qdrant_filter_translation_is_deterministic_and_rejects_unknown_operators():
    translated = qdrant_filter_from_mapping(
        {
            "$or": [{"section": "docs"}, {"section": "notes"}],
            "$not": {"archived": True},
            "score": {"gt": 0.5, "lte": 0.9},
        },
        models=FakeQdrantModels,
    )

    assert [condition.key for condition in translated.should] == ["section", "section"]
    assert translated.must_not[0].key == "archived"
    assert translated.must[0].key == "score"
    assert translated.must[0].range.values == {"gt": 0.5, "lte": 0.9}

    with pytest.raises(QdrantFilterError, match="Unsupported Qdrant filter operator"):
        qdrant_filter_from_mapping({"score": {"near": 1.0}}, models=FakeQdrantModels)


def test_qdrant_inspect_doctor_close_and_safe_failures():
    client = FakeQdrantClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_qdrant_config()),
        catalog=DataAdapterCatalog.with_defaults(
            qdrant_client_factory=lambda _config: client,
            qdrant_models_provider=lambda: FakeQdrantModels,
        ),
    )

    inspect_before = runtime.inspect_resource("vector.qdrant")
    assert inspect_before["initialized"] is False
    assert inspect_before["options"]["url"] == "***"
    assert inspect_before["options"]["api_key"] == "***"

    doctor = runtime.doctor()
    qdrant_checks = [check for check in doctor["checks"] if check["resource"] == "vector.qdrant"]

    assert qdrant_checks[0]["status"] == "ok"
    assert client.collection_checks == ["docs"]
    assert "qdrant-secret" not in repr(doctor)
    with pytest.raises(QdrantDimensionError, match="must not be empty"):
        runtime.require_port("vector.qdrant", VectorSearchPort).search_vectors([])
    assert runtime.close()["status"] == "ok"
    assert client.closed is True

    missing_client_runtime = DataRuntime(
        config=DataConfig.from_raw(_qdrant_config()),
        catalog=DataAdapterCatalog.with_defaults(qdrant_client_factory=lambda _config: None),
    )
    with pytest.raises(QdrantClientMissingError):
        missing_client_runtime.require_port("vector.qdrant", VectorSearchPort).search_vectors([1.0])

    failing_runtime = DataRuntime(
        config=DataConfig.from_raw(_qdrant_config()),
        catalog=DataAdapterCatalog.with_defaults(
            qdrant_client_factory=lambda _config: FakeQdrantClient(fail_health=True),
            qdrant_models_provider=lambda: FakeQdrantModels,
        ),
    )
    failing_doctor = failing_runtime.doctor()
    assert failing_doctor["status"] == "failed"
    assert [check for check in failing_doctor["checks"] if check["resource"] == "vector.qdrant"][0]["status"] == "failed"

    bad_client = FakeQdrantClient()
    bad_client.query_points = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable"))
    bad_runtime = DataRuntime(
        config=DataConfig.from_raw(_qdrant_config()),
        catalog=DataAdapterCatalog.with_defaults(
            qdrant_client_factory=lambda _config: bad_client,
            qdrant_models_provider=lambda: FakeQdrantModels,
        ),
    )
    with pytest.raises(QdrantConnectionError, match="network unavailable"):
        bad_runtime.require_port("vector.qdrant", VectorSearchPort).search_vectors([1.0])


def test_runtime_close_is_idempotent():
    runtime = DataRuntime(config=DataConfig.from_raw(_config()), catalog=DataAdapterCatalog.with_defaults())
    runtime.require_port("cache.default", KeyValuePort)

    first = runtime.close()
    second = runtime.close()

    assert first["status"] == "ok"
    assert second["status"] == "ok"


def test_data_source_does_not_import_vendor_or_ai_packages():
    source_root = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "muscles_data"
    core_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
        if path.name not in {"qdrant.py", "sqlalchemy.py"}
    )

    for marker in ("muscles_ai", "muscles_otel", "elasticsearch", "opensearch", "redis", "pymongo", "boto3"):
        assert marker not in core_text
    assert "import sqlalchemy" not in core_text
    assert "from sqlalchemy" not in core_text
    qdrant_source = source_root / "adapters" / "qdrant.py"
    assert "from qdrant_client" not in qdrant_source.read_text(encoding="utf-8")
    sqlalchemy_source = source_root / "adapters" / "sqlalchemy.py"
    assert "from sqlalchemy" not in sqlalchemy_source.read_text(encoding="utf-8")
    assert "muscles_sql" not in sqlalchemy_source.read_text(encoding="utf-8")


def test_package_public_exports():
    import muscles_data as md

    assert md.DataRuntime
    assert md.DataCapability
    assert md.VectorSearchPort
    assert md.ObjectStorePort
    assert md.SqlResourcePort
    assert DataPackage.namespace == "data"
