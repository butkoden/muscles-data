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

The core package owns:

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
- in-memory adapters for tests and examples;
- the `type: sql` bridge to a `muscles-sql` compatible registry.

It intentionally does not own:

- project business schemas;
- universal CRUD/query API;
- ORM models, repositories, Unit of Work or migrations;
- vendor clients such as SQLAlchemy, Redis, Elasticsearch, OpenSearch, Qdrant,
  PyMongo or boto3;
- RAG, document parsing, embeddings, prompts or LLM calls;
- protocol routes;
- distributed transactions across backends.

## Configuration

Core resources work without external database packages:

```yaml
data:
  resources:
    vector.docs:
      type: memory_vector

    search.docs:
      type: memory_search

    cache.default:
      type: memory_kv

    objects.docs:
      type: memory_object

    documents.local:
      type: memory_document

    sql.main:
      type: sql
      connection: main
      role: read_write
```

External adapter packages add real backend resource types. Their config still
lives in the project, but the factory comes from the adapter package:

```yaml
data:
  resources:
    search.elastic:
      type: elasticsearch
      url: ${ELASTICSEARCH_URL}
      api_key: ${ELASTICSEARCH_API_KEY}
      index: docs

    search.public:
      type: opensearch
      url: ${OPENSEARCH_URL}
      username: ${OPENSEARCH_USER}
      password: ${OPENSEARCH_PASSWORD}
      index: docs

    cache.redis:
      type: redis
      url: ${REDIS_URL}
      namespace: app
      stream_group: workers

    vector.qdrant:
      type: qdrant
      url: ${QDRANT_URL}
      api_key: ${QDRANT_API_KEY}
      collection: docs

    mongo.content:
      type: mongodb
      url: ${MONGO_URL}
      database: content

    objects.docs:
      type: s3
      endpoint_url: ${S3_ENDPOINT}
      bucket: documents
      prefix: raw

    sql.local:
      type: sqlalchemy
      url: sqlite:///:memory:
      name: local_sqlite
```

## External Adapter Packages

The adapter packages are separate repositories and dependencies:

| Resource type | Package | Port | Example |
| --- | --- | --- | --- |
| `elasticsearch` | [`muscles-data-elasticsearch`](https://github.com/butkoden/muscles-data-elasticsearch) | `SearchIndexPort` | [`example_data_elasticsearch_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_elasticsearch_1) |
| `opensearch` | [`muscles-data-opensearch`](https://github.com/butkoden/muscles-data-opensearch) | `SearchIndexPort` | [`example_data_opensearch_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_opensearch_1) |
| `redis` | [`muscles-data-redis`](https://github.com/butkoden/muscles-data-redis) | `KeyValuePort`, `LockPort`, `StreamPort` | [`example_data_redis_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_redis_1) |
| `qdrant` | [`muscles-data-qdrant`](https://github.com/butkoden/muscles-data-qdrant) | `VectorSearchPort` | [`example_data_qdrant_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_qdrant_1) |
| `mongodb` | [`muscles-data-mongodb`](https://github.com/butkoden/muscles-data-mongodb) | `DocumentStorePort` | [`example_data_mongodb_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_mongodb_1) |
| `s3` | [`muscles-data-s3`](https://github.com/butkoden/muscles-data-s3) | `ObjectStorePort` | [`example_data_s3_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_s3_1) |
| `sqlalchemy` | [`muscles-data-sqlalchemy`](https://github.com/butkoden/muscles-data-sqlalchemy) | `SqlResourcePort` | [`example_data_sqlalchemy_1`](https://github.com/butkoden/muscular-example/tree/master/example_data_sqlalchemy_1) |

Register external factories in the project composition root:

```python
from muscles_data.catalog import DataAdapterCatalog
from muscles_data_elasticsearch import ElasticsearchSearchFactory
from muscles_data_qdrant import QdrantVectorFactory
from muscles_data_redis import RedisDataFactory

catalog = DataAdapterCatalog.with_defaults()
catalog.register(ElasticsearchSearchFactory())
catalog.register(QdrantVectorFactory())
catalog.register(RedisDataFactory())
```

`muscles-data` core does not import these packages automatically. This keeps
framework startup small and avoids pulling database SDKs into projects that do
not need them.

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
connections. Concrete adapters are created by:

- `runtime.require_port(name, PortType)`;
- `runtime.require_resource(name, capability)`;
- `runtime.doctor()` when health checks are enabled.

## SQL Resources

`type: sql` is the only real backend bridge built into core. It delegates to a
named registry owned by `muscles-sql` or by the project:

```yaml
data:
  resources:
    sql.documents:
      type: sql
      connection: documents_metadata
      role: read_write
```

```python
from muscles_data.ports import SqlResourcePort

sql = runtime.require_port("sql.documents", SqlResourcePort)
with sql.session() as session:
    ...
```

`muscles-data` does not create SQL engines, repositories, Unit of Work objects
or migrations. `session()`, `session_factory()`, `inspect()` and `doctor()`
delegate to the supplied registry.

Use `muscles-data-sqlalchemy` when a project wants direct SQLAlchemy sessions
through the same `SqlResourcePort` without using `muscles-sql`.

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

Run the core smoke examples:

```bash
PYTHONPATH=../muscles/src:src python3 examples/run_data_runtime.py
PYTHONPATH=../muscles/src:src python3 examples/run_sql_resource_port.py
```

Real backend examples live in
[`muscular-example`](https://github.com/butkoden/muscular-example) as
`example_data_[adapter]_1` packages.

Run tests:

```bash
PYTHONPATH=../muscles/src:src python3 -m pytest -q
```
