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

    search.docs:
      type: memory_search

    cache.default:
      type: memory_kv

    objects.docs:
      type: memory_object

    mongo.content:
      type: memory_document

    sql.main:
      type: sql
      connection: main
```

Real backend adapters are added as optional adapter modules/factories. The core
package does not import Qdrant, OpenSearch, Elasticsearch, Redis, MongoDB, S3 or
SQLAlchemy clients.

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

Run the local smoke example:

```bash
PYTHONPATH=../muscles/src:src python3 examples/run_data_runtime.py
```

Run tests:

```bash
PYTHONPATH=../muscles/src:src python3 -m pytest -q
```
