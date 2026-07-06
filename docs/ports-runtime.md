# muscles-data ports and runtime

## Design Rule

Do not merge all database features into one generic API. Share only:

- lifecycle;
- capabilities;
- narrow typed ports.

If a feature has different semantics across backends, keep it in adapter options
or require an explicit native-client escape hatch.

## Ports

- `VectorSearchPort` — vector search/write/delete, embeddings are computed
  elsewhere.
- `SearchIndexPort` — keyword/BM25-style search and index writes.
- `ObjectStorePort` — object/blob put/get/list/delete.
- `KeyValuePort` — cache/key-value get/set/delete/exists with TTL support.
- `LockPort` — short-lived distributed locks with owner-token validation.
- `StreamPort` — minimal publish/read/ack stream contract.
- `DocumentStorePort` — simple document DB get/upsert/find/delete.
- `SqlResourcePort` — bridge contract to SQL resources; SQL lifecycle remains in
  `muscles-sql` or a project adapter.

## Elasticsearch Search Adapter

`type: elasticsearch` is the built-in optional adapter for `SearchIndexPort`:

```python
search = runtime.require_port("search.docs", SearchIndexPort)
hits = search.search_text("postgres kafka", filters={"section": "docs"}, limit=5)
```

Config:

```yaml
data:
  resources:
    search.docs:
      type: elasticsearch
      url: ${ELASTICSEARCH_URL}
      api_key: ${ELASTICSEARCH_API_KEY}
      index: docs
      timeout: 3
      verify_certs: true
```

The adapter owns lazy client creation, index name binding, metadata filter
translation, BM25/full-text search, document upsert/delete, highlight passthrough
when requested, health checks and safe diagnostics. It does not own analyzers,
mappings, document parsing, embeddings, RAG orchestration or reranking.

Filter mapping is intentionally small and deterministic:

- scalar value -> `term` on `metadata.<field>`;
- list/tuple/set -> `terms`;
- `gt`, `gte`, `lt`, `lte` mapping -> `range`;
- `$and`, `$or`, `$not` -> boolean groups.

`search_text(..., options={"highlight": True})` requests highlights for the
configured text field and returns them on `SearchHit.highlights`.
`upsert_documents()` writes `id`, `text`, and optional `metadata`/`payload`.
`delete_documents()` accepts ids or filters.

Diagnostics redact `url`, `api_key`, password and auth fields. `data.doctor`
checks client ping and index availability, while `data.resources.list` does not
create a client. Native Elasticsearch access is available only when
`native_client: true` is set and should remain an advanced project escape hatch.

## OpenSearch Search Adapter

`type: opensearch` is the built-in optional adapter for `SearchIndexPort` over
OpenSearch:

```python
search = runtime.require_port("search.public", SearchIndexPort)
hits = search.search_text("resume facts", filters={"section": "docs"}, limit=5)
```

Config:

```yaml
data:
  resources:
    search.public:
      type: opensearch
      url: ${OPENSEARCH_URL}
      username: ${OPENSEARCH_USER}
      password: ${OPENSEARCH_PASSWORD}
      index: docs
      timeout: 3
      verify_certs: true
```

The adapter owns lazy client creation, index name binding, metadata filter
translation, BM25/full-text search, document upsert/delete, highlight passthrough
when requested, health checks and safe diagnostics. It does not own index
lifecycle automation, analyzers, mappings, document parsing, embeddings, RAG
orchestration or reranking.

Filter mapping intentionally matches the Elasticsearch adapter:

- scalar value -> `term` on `metadata.<field>`;
- list/tuple/set -> `terms`;
- `gt`, `gte`, `lt`, `lte` mapping -> `range`;
- `$and`, `$or`, `$not` -> boolean groups.

The implementation is separate from Elasticsearch because OpenSearch uses the
`opensearch-py` dependency and OpenSearch client request conventions such as
`body=...`. Framework packages still see only `SearchIndexPort`.

Diagnostics redact `url`, password and auth fields. `data.doctor` checks client
ping and index availability, while `data.resources.list` does not create a
client. Native OpenSearch access is available only when `native_client: true` is
set and should remain an advanced project escape hatch.

## Redis Key-Value, Lock and Stream Adapter

`type: redis` is the built-in optional adapter for `KeyValuePort`, `LockPort`
and `StreamPort`:

```python
cache = runtime.require_port("cache.default", KeyValuePort)
cache.set("cursor", b"page-2", ttl_seconds=60)

lock = runtime.require_port("cache.default", LockPort)
handle = lock.acquire_lock("sync", ttl_seconds=30)
if handle is not None:
    lock.release_lock(handle)
```

Config:

```yaml
data:
  resources:
    cache.default:
      type: redis
      url: ${REDIS_URL}
      namespace: app
      timeout: 3
      stream_group: workers
```

The adapter owns lazy client creation, key namespacing, TTL key-value
operations, lock acquire/release, simple stream publish/read/ack operations,
health checks and safe diagnostics. It does not own business cache schemas, job
frameworks, consumer group lifecycle, distributed transaction guarantees or
project serialization policy.

Namespacing is deterministic:

- `cache.get("cursor")` -> `app:cursor`;
- `lock.acquire_lock("job", ...)` -> `app:lock:job`;
- `stream.publish("events", ...)` -> `app:stream:events`.

Lock acquisition uses atomic Redis `SET` with `NX` and `PX`. Release uses a Lua
compare-and-delete script, so a caller can only release the lock if the stored
token matches its `LockHandle`. Releasing an expired or replaced lock is
idempotent and returns an empty `WriteResult`.

Stream support stays intentionally narrow. `publish()` maps to `XADD`,
`read()` maps to `XREAD`, and `ack()` maps to `XACK` with `stream_group`
(default: `default`). Projects own consumer group creation, retry/dead-letter
policy and message schemas.

Diagnostics redact `url`. `data.doctor` performs `PING`, while
`data.resources.list` does not create a client. Native Redis access is
available only when `native_client: true` is set and should remain an advanced
project escape hatch.

## Qdrant Vector Adapter

`type: qdrant` is the built-in optional adapter for `VectorSearchPort`:

```python
vector = runtime.require_port("vector.docs", VectorSearchPort)
hits = vector.search_vectors([0.1, 0.9], filters={"section": "docs"}, limit=5)
```

Config:

```yaml
data:
  resources:
    vector.docs:
      type: qdrant
      url: ${QDRANT_URL}
      api_key: ${QDRANT_API_KEY}
      collection: docs
      timeout: 3
      prefer_grpc: false
```

The adapter owns lazy client creation, collection name binding, payload filter
translation, vector search, vector upsert/delete, health checks and safe
diagnostics. It does not own embeddings, RAG logic, payload schema design or
collection migrations.

Filter mapping is intentionally small and deterministic:

- scalar value -> `MatchValue`;
- list/tuple/set -> `MatchAny`;
- `gt`, `gte`, `lt`, `lte` mapping -> Qdrant `Range`;
- `$and`, `$or`, `$not` -> boolean groups.

Diagnostics redact `url` and `api_key`. `data.doctor` checks collection
availability, while `data.resources.list` does not create a client. Native
Qdrant access is available only when `native_client: true` is set and should
remain an advanced project escape hatch.

## SQLAlchemy Direct Adapter

`type: sqlalchemy` implements the same `SqlResourcePort` directly over a
SQLAlchemy engine:

```yaml
data:
  resources:
    sql.local:
      type: sqlalchemy
      url: sqlite:///:memory:
      name: local_sqlite
      pool_pre_ping: true
      native_client: false
```

The adapter imports SQLAlchemy lazily and creates the engine only when the port
is used, native access is requested or `data.doctor` runs. It supports:

- `connection_name()`;
- `session()`;
- `session_factory()`;
- `inspect()`;
- `doctor()`;
- `close()`.

Allowed engine options are intentionally narrow: `echo`, `pool_pre_ping`,
`pool_size`, `max_overflow`, `connect_args` and `future`. Unknown options fail
fast with a config error so project-specific connection behavior stays explicit.

The adapter does not add repositories, Unit of Work, migrations, ORM model
registration or a generic SQL query language. A project can build those layers
on top of the SQLAlchemy session it gets from `SqlResourcePort`.

Native SQLAlchemy access is available only with `native_client: true`:

```python
native = runtime.require_resource("sql.local", DataCapability.NATIVE_CLIENT).native_client()
engine = native["engine"]
session_factory = native["session_factory"]
```

Use this only for project-specific operations that do not belong in the narrow
port. Diagnostics redact `url` and never include the native engine/session
objects.

## SQL Bridge

`SqlResourcePort` exists so framework packages can ask for SQL as a named data
resource without importing SQLAlchemy or duplicating `muscles-sql`:

```python
sql = runtime.require_port("sql.main", SqlResourcePort)
with sql.session() as session:
    ...
```

Supported methods:

- `connection_name()`;
- `session()`;
- `session_factory()`;
- `inspect()`;
- `doctor()`.

The port delegates to `SqlConnectionRegistry`. It does not expose repositories,
Unit of Work, migrations, SQLAlchemy models or a universal query API.

Config:

```yaml
data:
  resources:
    sql.main:
      type: sql
      connection: main
      role: read_write
```

`connection` is required and must point to a named connection managed by
`muscles-sql` or a compatible project registry. Diagnostics redact raw `url` and
`dsn` fields while preserving already-safe fields such as `safe_url`.

## Lazy Runtime

`DataRuntime` parses config and keeps resource handles. Adapter factories are
known at startup, but concrete adapters are created only by:

- `runtime.require_port(name, PortType)`;
- `runtime.require_resource(name, capability)`;
- `runtime.doctor()` when health checks are enabled.

This keeps framework package startup fast and safe.

For SQL, registry resolution and health checks also remain lazy. `data.doctor`
may call SQL inspect/health behavior, but `data.resources.list` does not.

For direct SQLAlchemy resources, engine creation also remains lazy. Listing and
initial package setup do not open database connections.

For Elasticsearch, the real client is also lazy. It is created only by search,
index/delete operations, explicit native access or `data.doctor`.

For OpenSearch, the real client is also lazy. It is created only by search,
index/delete operations, explicit native access or `data.doctor`.

For Redis, the real client is also lazy. It is created only by key-value, lock,
stream operations, explicit native access or `data.doctor`.

For Qdrant, the real client is also lazy. It is created only by vector
operations, explicit native access or `data.doctor`.

## Diagnostics

Diagnostics are safe by default:

- options are redacted;
- native clients are not printed;
- raw query payloads and object/document/vector content are not printed;
- missing adapter factories are reported per resource without failing the whole
  diagnostic call.

## Project Adapters

Projects may register their own factories in `DataAdapterCatalog`:

```python
catalog = DataAdapterCatalog.with_defaults()
catalog.register(ProjectSearchFactory())
runtime = DataRuntime(config=config, catalog=catalog)
```

The factory is responsible for translating the typed port into backend-specific
client calls. Vendor dependencies remain inside the adapter module.

## External Adapter Packages

Vendor adapters that would pull extra dependencies can live outside
`muscles-data`. The core contract stays the same:

```python
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.ports import DocumentStorePort
from muscles_data_mongodb import MongoDocumentStoreFactory

catalog = DataAdapterCatalog.with_defaults()
catalog.register(MongoDocumentStoreFactory())
store = runtime.require_port("mongo.content", DocumentStorePort)
```

For MongoDB, `muscles-data-mongodb` owns the PyMongo dependency, lazy client
creation, database binding, simple document operations and safe diagnostics.
`muscles-data` owns only `DocumentStorePort`, runtime capability checks and the
registration mechanism. Complex aggregations, indexes, migrations and schema
validation remain project-level concerns or explicit native-client escape
hatches.
