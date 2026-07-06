# muscles-data

Framework-level named data resources and typed ports for the Muscles ecosystem.

## Purpose

`muscles-data` gives projects one small runtime for declaring, inspecting and
resolving data backends through narrow typed ports:

```text
config -> named resource -> capability check -> lazy adapter -> typed port
```

It does not replace SQL libraries, search clients, document databases, object
storage SDKs or project repositories. Framework packages should depend on ports,
not vendor clients.

## Scope

The MVP owns:

- `DataResourceConfig` and `DataCapability`;
- `DataAdapterCatalog`;
- lazy `DataRuntime`;
- `DataResourceHandle`;
- typed ports:
  - `VectorSearchPort`;
  - `SearchIndexPort`;
  - `ObjectStorePort`;
  - `KeyValuePort`;
  - `LockPort`;
  - `StreamPort`;
  - `DocumentStorePort`;
  - `SqlResourcePort`;
- safe `data.resources.list`, `data.resource.inspect`, `data.doctor` actions;
- in-memory adapters for tests and examples.

It intentionally does not own:

- project business schemas;
- universal CRUD/query API;
- ORM models, repositories, Unit of Work or migrations;
- RAG, document parsing, embeddings, prompts or LLM calls;
- protocol routes;
- distributed transactions across backends.

## Configuration

```yaml
data:
  resources:
    vector.docs:
      type: memory_vector

    vector.qdrant:
      type: qdrant
      url: ${QDRANT_URL}
      api_key: ${QDRANT_API_KEY}
      collection: docs
      timeout: 3
      prefer_grpc: false

    search.docs:
      type: memory_search

    search.elastic:
      type: elasticsearch
      url: ${ELASTICSEARCH_URL}
      api_key: ${ELASTICSEARCH_API_KEY}
      index: docs
      timeout: 3

    cache.default:
      type: memory_kv

    objects.docs:
      type: memory_object

    mongo.content:
      type: memory_document

    sql.main:
      type: sql
      connection: main
      role: read_write

    sql.local:
      type: sqlalchemy
      url: sqlite:///:memory:
      name: local_sqlite
      native_client: false
```

Real backend adapters are added as optional adapter modules/factories. The core
package does not import OpenSearch, Elasticsearch, Redis, MongoDB, S3 or
SQLAlchemy clients at package import time. Elasticsearch, Qdrant and SQLAlchemy
support live in optional adapter modules and import their vendor clients only
when a matching resource is used.

### Qdrant Vector Resources

`type: qdrant` implements `VectorSearchPort` over a Qdrant collection:

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

Install the optional client in projects that use the real adapter:

```bash
python -m pip install 'muscles-data[qdrant]'
```

Use it through the port:

```python
from muscles_data.ports import VectorSearchPort

vector = runtime.require_port("vector.docs", VectorSearchPort)
hits = vector.search_vectors(
    [0.1, 0.9],
    filters={"section": "docs", "year": {"gte": 2024}},
    limit=10,
)
```

Capabilities are `vector_search`, `vector_write` and `healthcheck`; add
`native_client: true` only for advanced project-specific Qdrant operations.
Supported filters map deterministic payload conditions to Qdrant:

- `{"field": "value"}` -> exact match;
- `{"field": ["a", "b"]}` -> any-of match;
- `{"year": {"gte": 2024, "lt": 2026}}` -> range;
- `$and`, `$or`, `$not` -> boolean groups.

`upsert_vectors()` accepts items with `id`, `vector` and optional `payload`.
`delete_vectors()` accepts either ids or filters. The adapter does not create
embeddings, design payload schemas or manage collection migrations.

### Elasticsearch Search Resources

`type: elasticsearch` implements `SearchIndexPort` over an Elasticsearch index:

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

Install the optional client in projects that use the real adapter:

```bash
python -m pip install 'muscles-data[elasticsearch]'
```

Use it through the port:

```python
from muscles_data.ports import SearchIndexPort

search = runtime.require_port("search.docs", SearchIndexPort)
hits = search.search_text(
    "postgres kafka",
    filters={"section": "experience", "year": {"gte": 2024}},
    limit=10,
    options={"highlight": True},
)
```

Capabilities are `keyword_search`, `document_index` and `healthcheck`; add
`native_client: true` only for advanced project-specific Elasticsearch
operations. Supported filters map deterministic metadata conditions to
Elasticsearch bool filters:

- `{"field": "value"}` -> `term` on `metadata.field`;
- `{"field": ["a", "b"]}` -> `terms`;
- `{"year": {"gte": 2024, "lt": 2026}}` -> `range`;
- `$and`, `$or`, `$not` -> boolean groups.

`upsert_documents()` accepts items with `id`, `text`, and optional `metadata` or
`payload`. `delete_documents()` accepts either ids or filters. The adapter does
not own analyzers, mappings, document parsing, embeddings, RAG logic or
reranking.

### SQL Resources

`type: sql` is a bridge to named connections owned by `muscles-sql`:

```yaml
data:
  resources:
    sql.documents:
      type: sql
      connection: documents_metadata
      role: read_write
```

Use it through `SqlResourcePort`:

```python
from muscles_data import DataRuntime
from muscles_data.ports import SqlResourcePort

data = app.container.resolve(DataRuntime)
sql = data.require_port("sql.documents", SqlResourcePort)

with sql.session() as session:
    ...
```

`muscles-data` does not create SQL engines, repositories, Unit of Work objects
or migrations. `session()`, `session_factory()`, `inspect()` and `doctor()`
delegate to a `muscles-sql` `SqlConnectionRegistry` supplied by the application
container or by a project adapter.

### SQLAlchemy Direct Resources

`type: sqlalchemy` is a direct adapter for projects that want a named
`SqlResourcePort` without wiring `muscles-sql` first:

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

Install the optional client in projects that use this adapter:

```bash
python -m pip install 'muscles-data[sqlalchemy]'
```

Use it through the same SQL port:

```python
import sqlalchemy
from muscles_data.ports import SqlResourcePort

sql = runtime.require_port("sql.local", SqlResourcePort)

with sql.session() as session:
    rows = session.execute(sqlalchemy.text("SELECT 1")).fetchall()
```

The adapter owns lazy SQLAlchemy engine/session-factory creation, safe
`inspect()` output, `doctor()` via `SELECT 1` and `close()` via
`Engine.dispose()`. It accepts only a small set of `create_engine()` options:
`echo`, `pool_pre_ping`, `pool_size`, `max_overflow`, `connect_args` and
`future`.

It still does not own repositories, Unit of Work, migrations, ORM models or a
universal query API. The project decides whether to use SQLAlchemy Core,
SQLAlchemy ORM or its own repository layer on top of the returned sessions.

## Runtime API

```python
from muscles_data import DataRuntime
from muscles_data.config import DataConfig
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.ports import KeyValuePort, VectorSearchPort

runtime = DataRuntime(
    config=DataConfig.from_raw({
        "data": {
            "resources": {
                "vector.docs": {"type": "memory_vector"},
                "cache.default": {"type": "memory_kv"},
            }
        }
    }),
    catalog=DataAdapterCatalog.with_defaults(),
)

vector = runtime.require_port("vector.docs", VectorSearchPort)
cache = runtime.require_port("cache.default", KeyValuePort)
```

Adapters are initialized lazily: package init and resource listing do not open
connections.

For SQL resources, `data.resources.list` and package initialization do not open
SQL connections. A SQL registry is resolved only when the SQL port is used or
when `data.doctor` runs health checks.

For SQLAlchemy resources, `data.resources.list` also remains lazy and does not
create an engine. The engine is created by `SqlResourcePort.session()`,
`session_factory()`, explicit native access or `data.doctor`.

For Elasticsearch resources, `data.resources.list` and package initialization do
not create a client. The client is created lazily on search/index/delete
operations, explicit native access or `data.doctor`.

For Qdrant resources, `data.resources.list` and package initialization do not
create a Qdrant client. The client is created lazily on vector operations,
explicit native access or `data.doctor`.

## Native Escape Hatch

The preferred path is always a typed port. A project may explicitly request a
native/internal backend handle only when the resource declares the
`native_client` capability:

```python
from muscles_data import DataCapability

handle = runtime.require_resource("cache.default", DataCapability.NATIVE_CLIENT)
native = handle.native_client()
```

This is an advanced escape hatch for project-specific operations. Framework
packages should not build their primary logic on native clients. Native handles,
credentials and raw payloads are never included in inspect/doctor output.

For SQL resources, the native handle is the underlying SQL registry/connection
API. Prefer `SqlResourcePort`; use native access only for project-specific SQL
operations that cannot be represented by the port.

For SQLAlchemy resources, native access returns a mapping with the underlying
`engine` and `session_factory`, but only when `native_client: true` is declared.
This is a project escape hatch for advanced SQLAlchemy operations; inspect and
doctor never print native objects or credentials.

For Qdrant resources, the native handle is the underlying `QdrantClient`.
Prefer `VectorSearchPort`; use native access only for backend-specific
operations that cannot be represented by the port.

For Elasticsearch resources, the native handle is the underlying Elasticsearch
client. Prefer `SearchIndexPort`; use native access only for index settings,
mappings or backend-specific operations that do not belong in the narrow port.

## Actions

- `data.resources.list` — list configured resources, capabilities and lazy init
  state without health checks.
- `data.resource.inspect` — inspect one resource with redacted options.
- `data.doctor` — validate factories and run safe health checks with partial
  failure reporting.

All actions are normal Muscles actions registered through the core action
contract. Protocol packages see them through `ActionDispatcher`; there is no
package-specific protocol routing.

## Telemetry

`muscles-data` resolves telemetry through the neutral Muscles provider. It does
not import `muscles-otel` directly.

Safe attributes are resource name/type, capability, operation, status and safe
counts. Do not add DSNs, tokens, passwords, raw query payloads, document text,
object content, vector payloads or native clients to spans.

## Examples

Run the local smoke example:

```bash
PYTHONPATH=../muscles/src:src python3 examples/run_data_runtime.py
PYTHONPATH=../muscles/src:src python3 examples/run_elasticsearch_search_port.py
PYTHONPATH=../muscles/src:src python3 examples/run_sql_resource_port.py
PYTHONPATH=../muscles/src:src python3 examples/run_sqlalchemy_resource_port.py
PYTHONPATH=../muscles/src:src python3 examples/run_qdrant_vector_port.py
```

Run tests:

```bash
PYTHONPATH=../muscles/src:src python3 -m pytest -q
```
