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
from muscles_data.adapters.elasticsearch import ElasticsearchSearchFactory, elasticsearch_filter_from_mapping
from muscles_data.adapters.opensearch import OpenSearchSearchFactory, opensearch_filter_from_mapping
from muscles_data.adapters.qdrant import QdrantVectorFactory, qdrant_filter_from_mapping
from muscles_data.adapters.redis import RedisDataFactory
from muscles_data.adapters.sqlalchemy import SqlAlchemySqlResourceFactory
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.errors import (
    DataCapabilityError,
    ElasticsearchClientMissingError,
    ElasticsearchConnectionError,
    ElasticsearchFilterError,
    OpenSearchClientMissingError,
    OpenSearchConnectionError,
    OpenSearchFilterError,
    QdrantClientMissingError,
    QdrantConnectionError,
    QdrantDimensionError,
    QdrantFilterError,
    RedisClientMissingError,
    RedisConfigError,
    RedisConnectionError,
    SqlAlchemyClientMissingError,
    SqlAlchemyConnectionError,
    SqlConnectionMissingError,
    SqlRegistryMissingError,
)
from muscles_data.models import DataCapability, DataResourceConfig, LockHandle
from muscles_data.ports import (
    DocumentStorePort,
    KeyValuePort,
    LockPort,
    ObjectStorePort,
    SearchIndexPort,
    SqlResourcePort,
    StreamPort,
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


class FakeElasticsearchIndices:
    def __init__(self, client: "FakeElasticsearchClient") -> None:
        self.client = client

    def exists(self, *, index: str) -> bool:
        self.client.index_checks.append(index)
        if self.client.fail_health:
            raise TimeoutError("elastic password=secret timed out")
        return index == self.client.index_name


class FakeElasticsearchClient:
    def __init__(self, *, fail_health: bool = False) -> None:
        self.fail_health = fail_health
        self.index_name = "docs"
        self.searches: list[dict[str, Any]] = []
        self.indexes: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.delete_queries: list[dict[str, Any]] = []
        self.index_checks: list[str] = []
        self.closed = False
        self.indices = FakeElasticsearchIndices(self)

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "doc-1",
                        "_score": 4.2,
                        "_source": {"text": "Muscles data ports", "metadata": {"section": "docs"}},
                        "highlight": {"text": ["<em>Muscles</em> data ports"]},
                    },
                    {
                        "_id": "doc-2",
                        "_score": 1.1,
                        "_source": {"text": "Other note", "metadata": {"section": "notes"}},
                    },
                ]
            }
        }

    def index(self, **kwargs):
        self.indexes.append(kwargs)
        return {"result": "created"}

    def delete(self, **kwargs):
        self.deletes.append(kwargs)
        return {"result": "deleted"}

    def delete_by_query(self, **kwargs):
        self.delete_queries.append(kwargs)
        return {"deleted": 3}

    def ping(self) -> bool:
        if self.fail_health:
            raise TimeoutError("elastic password=secret timed out")
        return True

    def close(self) -> None:
        self.closed = True


class FakeOpenSearchIndices:
    def __init__(self, client: "FakeOpenSearchClient") -> None:
        self.client = client

    def exists(self, *, index: str) -> bool:
        self.client.index_checks.append(index)
        if self.client.fail_health:
            raise TimeoutError("opensearch password=secret timed out")
        return index == self.client.index_name


class FakeOpenSearchClient:
    def __init__(self, *, fail_health: bool = False) -> None:
        self.fail_health = fail_health
        self.index_name = "docs"
        self.searches: list[dict[str, Any]] = []
        self.indexes: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.delete_queries: list[dict[str, Any]] = []
        self.index_checks: list[str] = []
        self.closed = False
        self.indices = FakeOpenSearchIndices(self)

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "doc-1",
                        "_score": 4.2,
                        "_source": {"text": "Muscles data ports", "metadata": {"section": "docs"}},
                        "highlight": {"text": ["<em>Muscles</em> data ports"]},
                    },
                    {
                        "_id": "doc-2",
                        "_score": 1.1,
                        "_source": {"text": "Other note", "metadata": {"section": "notes"}},
                    },
                ]
            }
        }

    def index(self, **kwargs):
        self.indexes.append(kwargs)
        return {"result": "created"}

    def delete(self, **kwargs):
        self.deletes.append(kwargs)
        return {"result": "deleted"}

    def delete_by_query(self, **kwargs):
        self.delete_queries.append(kwargs)
        return {"deleted": 3}

    def ping(self) -> bool:
        if self.fail_health:
            raise TimeoutError("opensearch password=secret timed out")
        return True

    def close(self) -> None:
        self.closed = True


class FakeRedisClient:
    def __init__(self, *, fail_ping: bool = False) -> None:
        self.fail_ping = fail_ping
        self.values: dict[str, Any] = {}
        self.sets: list[dict[str, Any]] = []
        self.deletes: list[tuple[str, ...]] = []
        self.exists_calls: list[tuple[str, ...]] = []
        self.eval_calls: list[dict[str, Any]] = []
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self.xacks: list[dict[str, Any]] = []
        self.pings = 0
        self.closed = False

    def set(self, name: str, value, **kwargs):
        self.sets.append({"name": name, "value": value, **kwargs})
        if kwargs.get("nx") and name in self.values:
            return False
        self.values[name] = value
        return True

    def get(self, name: str):
        return self.values.get(name)

    def delete(self, *names: str) -> int:
        self.deletes.append(tuple(names))
        deleted = 0
        for name in names:
            deleted += 1 if self.values.pop(name, None) is not None else 0
        return deleted

    def exists(self, *names: str) -> int:
        self.exists_calls.append(tuple(names))
        return sum(1 for name in names if name in self.values)

    def eval(self, script: str, numkeys: int, *keys_and_args):
        self.eval_calls.append({"script": script, "numkeys": numkeys, "items": keys_and_args})
        key = str(keys_and_args[0])
        expected_token = keys_and_args[1]
        if self.values.get(key) != expected_token:
            return 0
        self.values.pop(key, None)
        return 1

    def xadd(self, name: str, fields: dict[str, Any]):
        stream = self.streams.setdefault(name, [])
        message_id = f"{len(stream) + 1}-0"
        stream.append((message_id, dict(fields)))
        return message_id

    def xread(self, streams: dict[str, str], count: int | None = None, block: int | None = None):
        del block
        result = []
        for name, cursor in streams.items():
            messages = [
                (message_id, fields)
                for message_id, fields in self.streams.get(name, [])
                if _redis_message_after(message_id, cursor)
            ]
            result.append((name, messages[:count]))
        return result

    def xack(self, name: str, groupname: str, *ids: str) -> int:
        self.xacks.append({"name": name, "groupname": groupname, "ids": ids})
        known_ids = {message_id for message_id, _fields in self.streams.get(name, [])}
        return sum(1 for message_id in ids if message_id in known_ids)

    def ping(self) -> bool:
        self.pings += 1
        if self.fail_ping:
            raise TimeoutError("redis password=redis-secret timed out")
        return True

    def close(self) -> None:
        self.closed = True


def _redis_message_after(message_id: str, cursor: str) -> bool:
    if cursor in {"0", "0-0"}:
        return True
    if cursor == "$":
        return False
    return message_id > cursor


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


def _elasticsearch_config(url: str = "https://elastic.example") -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "search.elastic": {
                    "type": "elasticsearch",
                    "url": url,
                    "api_key": "elastic-secret",
                    "index": "docs",
                    "timeout": 1.5,
                    "verify_certs": True,
                    "native_client": True,
                }
            }
        }
    }


def _opensearch_config(url: str = "https://opensearch.example") -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "search.open": {
                    "type": "opensearch",
                    "url": url,
                    "username": "admin",
                    "password": "open-secret",
                    "index": "docs",
                    "timeout": 1.5,
                    "verify_certs": False,
                    "native_client": True,
                }
            }
        }
    }


def _redis_config(url: str = "redis://:redis-secret@localhost:6379/0") -> dict[str, Any]:
    return {
        "data": {
            "resources": {
                "cache.redis": {
                    "type": "redis",
                    "url": url,
                    "namespace": "app",
                    "decode_responses": False,
                    "timeout": 1.5,
                    "stream_group": "workers",
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


def test_elasticsearch_resource_config_requires_url_and_index():
    assert DataConfig.from_raw(_elasticsearch_config()).resources["search.elastic"].type == "elasticsearch"

    with pytest.raises(ValueError, match="requires url"):
        DataConfig.from_raw({"data": {"resources": {"search.elastic": {"type": "elasticsearch", "index": "docs"}}}})

    with pytest.raises(ValueError, match="requires index"):
        DataConfig.from_raw({"data": {"resources": {"search.elastic": {"type": "elasticsearch", "url": "http://localhost:9200"}}}})


def test_opensearch_resource_config_requires_url_and_index():
    assert DataConfig.from_raw(_opensearch_config()).resources["search.open"].type == "opensearch"

    with pytest.raises(ValueError, match="requires url"):
        DataConfig.from_raw({"data": {"resources": {"search.open": {"type": "opensearch", "index": "docs"}}}})

    with pytest.raises(ValueError, match="requires index"):
        DataConfig.from_raw({"data": {"resources": {"search.open": {"type": "opensearch", "url": "http://localhost:9200"}}}})


def test_redis_resource_config_requires_url():
    assert DataConfig.from_raw(_redis_config()).resources["cache.redis"].type == "redis"

    with pytest.raises(ValueError, match="requires url"):
        DataConfig.from_raw({"data": {"resources": {"cache.redis": {"type": "redis"}}}})


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


def test_elasticsearch_search_port_is_registered_lazy_and_maps_operations():
    client = FakeElasticsearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_elasticsearch_config()),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: client),
    )

    listed = runtime.list_resources()
    elastic = next(item for item in listed if item["name"] == "search.elastic")
    inspected_before = runtime.inspect_resource("search.elastic")

    assert elastic["type"] == "elasticsearch"
    assert {"keyword_search", "document_index"} <= set(elastic["capabilities"])
    assert "native_client" not in elastic["capabilities"]
    assert elastic["initialized"] is False
    assert inspected_before["initialized"] is False
    assert inspected_before["options"]["url"] == "***"
    assert inspected_before["options"]["api_key"] == "***"
    assert DataAdapterCatalog.with_defaults().has_factory(ElasticsearchSearchFactory.resource_type)

    search = runtime.require_port("search.elastic", SearchIndexPort)
    hits = search.search_text(
        "muscles",
        filters={"section": "docs", "year": {"gte": 2024}},
        limit=2,
        options={"highlight": True},
    )
    write = search.upsert_documents(
        [
            {"id": "doc-1", "text": "Muscles data ports", "metadata": {"section": "docs"}},
            {"id": "doc-2", "text": "Other note", "payload": {"section": "notes"}},
        ],
        options={"refresh": True},
    )
    deleted_ids = search.delete_documents(ids=["doc-2"], options={"refresh": True})
    deleted_filter = search.delete_documents(filters={"section": ["docs", "notes"]})

    assert [hit.id for hit in hits] == ["doc-1", "doc-2"]
    assert hits[0].score == pytest.approx(4.2)
    assert hits[0].text == "Muscles data ports"
    assert hits[0].metadata["section"] == "docs"
    assert hits[0].highlights["text"] == ["<em>Muscles</em> data ports"]
    assert client.searches[0]["index"] == "docs"
    assert client.searches[0]["size"] == 2
    assert client.searches[0]["query"]["bool"]["must"] == [{"match": {"text": {"query": "muscles"}}}]
    assert {"term": {"metadata.section": "docs"}} in client.searches[0]["query"]["bool"]["filter"]
    assert {"range": {"metadata.year": {"gte": 2024}}} in client.searches[0]["query"]["bool"]["filter"]
    assert client.searches[0]["highlight"] == {"fields": {"text": {}}}
    assert write.written == 2
    assert client.indexes[0]["index"] == "docs"
    assert client.indexes[0]["id"] == "doc-1"
    assert client.indexes[0]["document"] == {"text": "Muscles data ports", "metadata": {"section": "docs"}}
    assert client.indexes[0]["refresh"] is True
    assert client.indexes[1]["document"]["metadata"] == {"section": "notes"}
    assert deleted_ids.deleted == 1
    assert client.deletes[0] == {"index": "docs", "id": "doc-2", "refresh": True}
    assert deleted_filter.deleted == 3
    assert client.delete_queries[0]["query"]["bool"]["filter"][0] == {"terms": {"metadata.section": ["docs", "notes"]}}

    native = runtime.require_resource("search.elastic", DataCapability.NATIVE_CLIENT).native_client()
    assert native is client
    assert client.index_checks == []


def test_elasticsearch_filter_translation_is_deterministic_and_rejects_unknown_operators():
    translated = elasticsearch_filter_from_mapping(
        {
            "$or": [{"section": "docs"}, {"section": "notes"}],
            "$not": {"archived": True},
            "score": {"gt": 0.5, "lte": 0.9},
        }
    )

    assert translated[0] == {
        "bool": {
            "should": [{"term": {"metadata.section": "docs"}}, {"term": {"metadata.section": "notes"}}],
            "minimum_should_match": 1,
        }
    }
    assert translated[1] == {"bool": {"must_not": [{"term": {"metadata.archived": True}}]}}
    assert translated[2] == {"range": {"metadata.score": {"gt": 0.5, "lte": 0.9}}}

    with pytest.raises(ElasticsearchFilterError, match="Unsupported Elasticsearch filter operator"):
        elasticsearch_filter_from_mapping({"score": {"near": 1.0}})


def test_elasticsearch_inspect_doctor_close_and_safe_failures():
    client = FakeElasticsearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_elasticsearch_config()),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: client),
    )

    inspect_before = runtime.inspect_resource("search.elastic")
    assert inspect_before["initialized"] is False
    assert inspect_before["options"]["url"] == "***"
    assert inspect_before["options"]["api_key"] == "***"

    doctor = runtime.doctor()
    elastic_checks = [check for check in doctor["checks"] if check["resource"] == "search.elastic"]

    assert elastic_checks[0]["status"] == "ok"
    assert client.index_checks == ["docs"]
    assert "elastic-secret" not in repr(doctor)
    assert runtime.close()["status"] == "ok"
    assert client.closed is True

    missing_client_runtime = DataRuntime(
        config=DataConfig.from_raw(_elasticsearch_config()),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: None),
    )
    with pytest.raises(ElasticsearchClientMissingError):
        missing_client_runtime.require_port("search.elastic", SearchIndexPort).search_text("x")

    failing_runtime = DataRuntime(
        config=DataConfig.from_raw(_elasticsearch_config("https://user:secret@elastic.example")),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: FakeElasticsearchClient(fail_health=True)),
    )
    failing_doctor = failing_runtime.doctor()
    assert failing_doctor["status"] == "failed"
    assert [check for check in failing_doctor["checks"] if check["resource"] == "search.elastic"][0]["status"] == "failed"
    assert "secret" not in repr(failing_doctor)

    bad_client = FakeElasticsearchClient()
    bad_client.search = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable"))
    bad_runtime = DataRuntime(
        config=DataConfig.from_raw(_elasticsearch_config()),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: bad_client),
    )
    with pytest.raises(ElasticsearchConnectionError, match="network unavailable"):
        bad_runtime.require_port("search.elastic", SearchIndexPort).search_text("x")


def test_opensearch_search_port_is_registered_lazy_and_maps_operations():
    client = FakeOpenSearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_opensearch_config()),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: client),
    )

    listed = runtime.list_resources()
    opensearch = next(item for item in listed if item["name"] == "search.open")
    inspected_before = runtime.inspect_resource("search.open")

    assert opensearch["type"] == "opensearch"
    assert {"keyword_search", "document_index"} <= set(opensearch["capabilities"])
    assert "native_client" not in opensearch["capabilities"]
    assert opensearch["initialized"] is False
    assert inspected_before["initialized"] is False
    assert inspected_before["options"]["url"] == "***"
    assert inspected_before["options"]["password"] == "***"
    assert DataAdapterCatalog.with_defaults().has_factory(OpenSearchSearchFactory.resource_type)

    search = runtime.require_port("search.open", SearchIndexPort)
    hits = search.search_text(
        "muscles",
        filters={"section": "docs", "year": {"gte": 2024}},
        limit=2,
        options={"highlight": True},
    )
    write = search.upsert_documents(
        [
            {"id": "doc-1", "text": "Muscles data ports", "metadata": {"section": "docs"}},
            {"id": "doc-2", "text": "Other note", "payload": {"section": "notes"}},
        ],
        options={"refresh": True},
    )
    deleted_ids = search.delete_documents(ids=["doc-2"], options={"refresh": True})
    deleted_filter = search.delete_documents(filters={"section": ["docs", "notes"]})

    assert [hit.id for hit in hits] == ["doc-1", "doc-2"]
    assert hits[0].score == pytest.approx(4.2)
    assert hits[0].text == "Muscles data ports"
    assert hits[0].metadata["section"] == "docs"
    assert hits[0].highlights["text"] == ["<em>Muscles</em> data ports"]
    assert client.searches[0]["index"] == "docs"
    assert client.searches[0]["body"]["size"] == 2
    assert client.searches[0]["body"]["query"]["bool"]["must"] == [{"match": {"text": {"query": "muscles"}}}]
    assert {"term": {"metadata.section": "docs"}} in client.searches[0]["body"]["query"]["bool"]["filter"]
    assert {"range": {"metadata.year": {"gte": 2024}}} in client.searches[0]["body"]["query"]["bool"]["filter"]
    assert client.searches[0]["body"]["highlight"] == {"fields": {"text": {}}}
    assert write.written == 2
    assert client.indexes[0]["index"] == "docs"
    assert client.indexes[0]["id"] == "doc-1"
    assert client.indexes[0]["body"] == {"text": "Muscles data ports", "metadata": {"section": "docs"}}
    assert client.indexes[0]["refresh"] is True
    assert client.indexes[1]["body"]["metadata"] == {"section": "notes"}
    assert deleted_ids.deleted == 1
    assert client.deletes[0] == {"index": "docs", "id": "doc-2", "refresh": True}
    assert deleted_filter.deleted == 3
    assert client.delete_queries[0]["body"]["query"]["bool"]["filter"][0] == {"terms": {"metadata.section": ["docs", "notes"]}}

    native = runtime.require_resource("search.open", DataCapability.NATIVE_CLIENT).native_client()
    assert native is client
    assert client.index_checks == []


def test_opensearch_filter_translation_is_deterministic_and_rejects_unknown_operators():
    translated = opensearch_filter_from_mapping(
        {
            "$or": [{"section": "docs"}, {"section": "notes"}],
            "$not": {"archived": True},
            "score": {"gt": 0.5, "lte": 0.9},
        }
    )

    assert translated[0] == {
        "bool": {
            "should": [{"term": {"metadata.section": "docs"}}, {"term": {"metadata.section": "notes"}}],
            "minimum_should_match": 1,
        }
    }
    assert translated[1] == {"bool": {"must_not": [{"term": {"metadata.archived": True}}]}}
    assert translated[2] == {"range": {"metadata.score": {"gt": 0.5, "lte": 0.9}}}

    with pytest.raises(OpenSearchFilterError, match="Unsupported OpenSearch filter operator"):
        opensearch_filter_from_mapping({"score": {"near": 1.0}})


def test_opensearch_inspect_doctor_close_and_safe_failures():
    client = FakeOpenSearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_opensearch_config()),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: client),
    )

    inspect_before = runtime.inspect_resource("search.open")
    assert inspect_before["initialized"] is False
    assert inspect_before["options"]["url"] == "***"
    assert inspect_before["options"]["password"] == "***"

    doctor = runtime.doctor()
    opensearch_checks = [check for check in doctor["checks"] if check["resource"] == "search.open"]

    assert opensearch_checks[0]["status"] == "ok"
    assert client.index_checks == ["docs"]
    assert "open-secret" not in repr(doctor)
    assert runtime.close()["status"] == "ok"
    assert client.closed is True

    missing_client_runtime = DataRuntime(
        config=DataConfig.from_raw(_opensearch_config()),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: None),
    )
    with pytest.raises(OpenSearchClientMissingError):
        missing_client_runtime.require_port("search.open", SearchIndexPort).search_text("x")

    failing_runtime = DataRuntime(
        config=DataConfig.from_raw(_opensearch_config("https://user:secret@opensearch.example")),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: FakeOpenSearchClient(fail_health=True)),
    )
    failing_doctor = failing_runtime.doctor()
    assert failing_doctor["status"] == "failed"
    assert [check for check in failing_doctor["checks"] if check["resource"] == "search.open"][0]["status"] == "failed"
    assert "secret" not in repr(failing_doctor)

    bad_client = FakeOpenSearchClient()
    bad_client.search = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable"))
    bad_runtime = DataRuntime(
        config=DataConfig.from_raw(_opensearch_config()),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: bad_client),
    )
    with pytest.raises(OpenSearchConnectionError, match="network unavailable"):
        bad_runtime.require_port("search.open", SearchIndexPort).search_text("x")


def test_redis_data_port_is_registered_lazy_and_maps_kv_lock_stream_operations():
    client = FakeRedisClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_redis_config()),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: client),
    )

    listed = runtime.list_resources()
    redis_resource = next(item for item in listed if item["name"] == "cache.redis")
    inspected_before = runtime.inspect_resource("cache.redis")

    assert redis_resource["type"] == "redis"
    assert {"key_value", "cache", "lock", "stream"} <= set(redis_resource["capabilities"])
    assert "native_client" not in redis_resource["capabilities"]
    assert redis_resource["initialized"] is False
    assert inspected_before["initialized"] is False
    assert inspected_before["options"]["url"] == "***"
    assert DataAdapterCatalog.with_defaults().has_factory(RedisDataFactory.resource_type)

    cache = runtime.require_port("cache.redis", KeyValuePort)
    write = cache.set("cursor", b"cursor-1", ttl_seconds=2.5)

    assert write.written == 1
    assert client.sets[0]["name"] == "app:cursor"
    assert client.sets[0]["value"] == b"cursor-1"
    assert client.sets[0]["px"] == 2500
    assert cache.get("cursor") == b"cursor-1"
    assert cache.exists("cursor") is True
    assert cache.delete("cursor").deleted == 1
    assert client.deletes[-1] == ("app:cursor",)

    lock = runtime.require_port("cache.redis", LockPort)
    handle = lock.acquire_lock("daily-job", ttl_seconds=5)

    assert isinstance(handle, LockHandle)
    assert client.sets[-1]["name"] == "app:lock:daily-job"
    assert client.sets[-1]["nx"] is True
    assert client.sets[-1]["px"] == 5000
    assert lock.acquire_lock("daily-job", ttl_seconds=5) is None
    assert lock.release_lock(LockHandle(name="daily-job", token="wrong", expires_at=0)).deleted == 0
    released = lock.release_lock(handle)
    assert released.deleted == 1
    assert "redis.call('get'" in client.eval_calls[-1]["script"]

    stream = runtime.require_port("cache.redis", StreamPort)
    published = stream.publish("events", {"kind": "created", "count": 1})
    read = stream.read("events", limit=10)
    acked = stream.ack("events", "1-0")

    assert published.written == 1
    assert read.cursor == "1-0"
    assert read.messages == [
        {"stream": "events", "id": "1-0", "fields": {"kind": "created", "count": 1}}
    ]
    assert acked.matched == 1
    assert client.xacks[-1] == {"name": "app:stream:events", "groupname": "workers", "ids": ("1-0",)}

    native = runtime.require_resource("cache.redis", DataCapability.NATIVE_CLIENT).native_client()
    assert native is client
    assert client.pings == 0


def test_redis_inspect_doctor_close_and_safe_failures():
    client = FakeRedisClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(_redis_config()),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: client),
    )

    inspect_before = runtime.inspect_resource("cache.redis")
    assert inspect_before["initialized"] is False
    assert inspect_before["options"]["url"] == "***"

    doctor = runtime.doctor()
    redis_checks = [check for check in doctor["checks"] if check["resource"] == "cache.redis"]

    assert redis_checks[0]["status"] == "ok"
    assert client.pings == 1
    assert "redis-secret" not in repr(doctor)
    assert runtime.close()["status"] == "ok"
    assert client.closed is True

    missing_client_runtime = DataRuntime(
        config=DataConfig.from_raw(_redis_config()),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: None),
    )
    with pytest.raises(RedisClientMissingError):
        missing_client_runtime.require_port("cache.redis", KeyValuePort).get("cursor")

    failing_runtime = DataRuntime(
        config=DataConfig.from_raw(_redis_config()),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: FakeRedisClient(fail_ping=True)),
    )
    failing_doctor = failing_runtime.doctor()
    assert failing_doctor["status"] == "failed"
    assert [check for check in failing_doctor["checks"] if check["resource"] == "cache.redis"][0]["status"] == "failed"
    assert "redis-secret" not in repr(failing_doctor)

    bad_client = FakeRedisClient()
    bad_client.get = lambda _name: (_ for _ in ()).throw(RuntimeError("redis://:redis-secret@localhost unavailable"))
    bad_runtime = DataRuntime(
        config=DataConfig.from_raw(_redis_config()),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: bad_client),
    )
    with pytest.raises(RedisConnectionError):
        bad_runtime.require_port("cache.redis", KeyValuePort).get("cursor")

    unsupported_runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"cache.redis": {"type": "redis", "url": "redis://localhost", "unsafe": True}}}}
        ),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: FakeRedisClient()),
    )
    with pytest.raises(RedisConfigError, match="Unsupported Redis resource options"):
        unsupported_runtime.require_port("cache.redis", KeyValuePort).get("cursor")


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
        if path.name not in {"elasticsearch.py", "opensearch.py", "qdrant.py", "redis.py", "sqlalchemy.py"}
    )

    for marker in ("muscles_ai", "muscles_otel", "pymongo", "boto3"):
        assert marker not in core_text
    assert "opensearchpy" not in core_text
    assert "import redis" not in core_text
    assert "from redis" not in core_text
    assert "import elasticsearch" not in core_text
    assert "from elasticsearch" not in core_text
    assert "import sqlalchemy" not in core_text
    assert "from sqlalchemy" not in core_text
    elasticsearch_source = source_root / "adapters" / "elasticsearch.py"
    assert "from elasticsearch" not in elasticsearch_source.read_text(encoding="utf-8")
    opensearch_source = source_root / "adapters" / "opensearch.py"
    assert "from opensearchpy" not in opensearch_source.read_text(encoding="utf-8")
    qdrant_source = source_root / "adapters" / "qdrant.py"
    assert "from qdrant_client" not in qdrant_source.read_text(encoding="utf-8")
    redis_source = source_root / "adapters" / "redis.py"
    assert "from redis" not in redis_source.read_text(encoding="utf-8")
    sqlalchemy_source = source_root / "adapters" / "sqlalchemy.py"
    assert "from sqlalchemy" not in sqlalchemy_source.read_text(encoding="utf-8")
    assert "muscles_sql" not in sqlalchemy_source.read_text(encoding="utf-8")


def test_package_public_exports():
    import muscles_data as md

    assert md.DataRuntime
    assert md.DataCapability
    assert md.VectorSearchPort
    assert md.ObjectStorePort
    assert md.LockPort
    assert md.StreamPort
    assert md.SqlResourcePort
    assert DataPackage.namespace == "data"
