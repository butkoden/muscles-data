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
- `DocumentStorePort` — simple document DB get/upsert/find/delete.
- `SqlResourcePort` — bridge contract to SQL resources; SQL lifecycle remains in
  `muscles-sql` or a project adapter.

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
