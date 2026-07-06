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

## Lazy Runtime

`DataRuntime` parses config and keeps resource handles. Adapter factories are
known at startup, but concrete adapters are created only by:

- `runtime.require_port(name, PortType)`;
- `runtime.require_resource(name, capability)`;
- `runtime.doctor()` when health checks are enabled.

This keeps framework package startup fast and safe.

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
