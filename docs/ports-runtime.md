# muscles-data ports and runtime

## Design Rule

Do not merge all database features into one generic API. Share only:

- lifecycle;
- capabilities;
- narrow typed ports;
- safe diagnostics;
- adapter registration.

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
  `muscles-sql`, a project registry or a registered adapter.

## Core Adapters

Core registers only lightweight adapters that have no vendor SDK dependency:

- `memory_vector` -> `VectorSearchPort`;
- `memory_search` -> `SearchIndexPort`;
- `memory_object` -> `ObjectStorePort`;
- `memory_kv` -> `KeyValuePort`, `LockPort`, `StreamPort`;
- `memory_document` -> `DocumentStorePort`;
- `sql` -> `SqlResourcePort` bridge to a supplied SQL registry.

`DataAdapterCatalog.with_defaults()` intentionally does not register
Elasticsearch, OpenSearch, Redis, Qdrant, MongoDB, S3 or SQLAlchemy. Those
factories live in separate adapter packages.

## SQL Bridge

`SqlResourcePort` exists so framework packages can ask for SQL as a named data
resource without importing SQLAlchemy or duplicating `muscles-sql`:

```python
sql = runtime.require_port("sql.main", SqlResourcePort)
with sql.session() as session:
    ...
```

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

Supported methods:

- `connection_name()`;
- `session()`;
- `session_factory()`;
- `inspect()`;
- `doctor()`.

The port delegates to the registry. It does not expose repositories, Unit of
Work, migrations, SQLAlchemy models or a universal query API.

## External Adapter Packages

Vendor adapters that pull extra dependencies live outside `muscles-data`. The
core contract stays the same: install/register an adapter package in the
project composition root, then use a typed port in framework/use-case code.

```python
from muscles_data.catalog import DataAdapterCatalog
from muscles_data_elasticsearch import ElasticsearchSearchFactory
from muscles_data_mongodb import MongoDocumentStoreFactory
from muscles_data_qdrant import QdrantVectorFactory
from muscles_data_s3 import S3ObjectStoreFactory

catalog = DataAdapterCatalog.with_defaults()
catalog.register(ElasticsearchSearchFactory())
catalog.register(MongoDocumentStoreFactory())
catalog.register(QdrantVectorFactory())
catalog.register(S3ObjectStoreFactory())
```

Current adapter packages:

| Package | Resource type | Port | Backend responsibility |
| --- | --- | --- | --- |
| [`muscles-data-elasticsearch`](https://github.com/butkoden/muscles-data-elasticsearch) | `elasticsearch` | `SearchIndexPort` | Elasticsearch full-text search, document upsert/delete, filters, highlights |
| [`muscles-data-opensearch`](https://github.com/butkoden/muscles-data-opensearch) | `opensearch` | `SearchIndexPort` | OpenSearch full-text search, document upsert/delete, filters, highlights |
| [`muscles-data-redis`](https://github.com/butkoden/muscles-data-redis) | `redis` | `KeyValuePort`, `LockPort`, `StreamPort` | Redis cache/key-value, locks and simple streams |
| [`muscles-data-qdrant`](https://github.com/butkoden/muscles-data-qdrant) | `qdrant` | `VectorSearchPort` | Qdrant vector search, vector upsert/delete and payload filters |
| [`muscles-data-mongodb`](https://github.com/butkoden/muscles-data-mongodb) | `mongodb` | `DocumentStorePort` | MongoDB document get/upsert/find/delete |
| [`muscles-data-s3`](https://github.com/butkoden/muscles-data-s3) | `s3` | `ObjectStorePort` | S3-compatible object put/get/list/delete |
| [`muscles-data-sqlalchemy`](https://github.com/butkoden/muscles-data-sqlalchemy) | `sqlalchemy` | `SqlResourcePort` | Direct SQLAlchemy engine/session factory access through the SQL port |

Executable examples live in
[`muscular-example`](https://github.com/butkoden/muscular-example) under
`example_data_[adapter]_1`.

Each adapter owns:

- vendor dependency imports;
- lazy client creation;
- backend-specific request translation;
- backend-specific config validation;
- safe diagnostics for its options;
- native-client access when `native_client: true` is set.

Core owns only the port contracts, runtime lifecycle, capability checks,
resource actions and registration mechanism.

## Lazy Runtime

`DataRuntime` parses config and keeps resource handles. Adapter factories are
known at startup, but concrete adapters are created only by:

- `runtime.require_port(name, PortType)`;
- `runtime.require_resource(name, capability)`;
- `runtime.doctor()` when health checks are enabled.

This keeps framework package startup fast and safe.

For SQL, registry resolution and health checks also remain lazy. `data.doctor`
may call SQL inspect/health behavior, but `data.resources.list` does not.

External adapters must follow the same rule: listing resources and package init
must not open database/network connections. Real clients are created only by
port operations, explicit native access or `data.doctor`.

## Diagnostics

Diagnostics are safe by default:

- options are redacted;
- native clients are not printed;
- raw query payloads and object/document/vector content are not printed;
- missing adapter factories are reported per resource without failing the whole
  diagnostic call.

Adapter packages may add backend-specific health checks, but they must not leak
credentials or raw payloads in `inspect()` or `doctor()` output.

## Native Escape Hatch

The preferred path is always a typed port. A project may explicitly request a
native/internal backend handle only when the resource declares the
`native_client` capability:

```python
from muscles_data import DataCapability

handle = runtime.require_resource("search.docs", DataCapability.NATIVE_CLIENT)
native = handle.native_client()
```

Use native access only for project-specific operations that do not belong in the
narrow port. Framework packages should not build their primary logic on native
clients.

## Project Adapters

Projects may register their own factories in `DataAdapterCatalog`:

```python
catalog = DataAdapterCatalog.with_defaults()
catalog.register(ProjectSearchFactory())
runtime = DataRuntime(config=config, catalog=catalog)
```

The factory is responsible for translating the typed port into backend-specific
client calls. Vendor dependencies remain inside the adapter module.
