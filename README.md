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
- storage-neutral migration registration, ordering and inspection;
- typed ports:
  - `VectorSearchPort`;
  - `SearchIndexPort`;
  - `ObjectStorePort`;
  - `KeyValuePort`;
  - `LockPort`;
  - `StreamPort`;
  - `EventPublisherPort`;
  - `EventConsumerPort`;
  - `EventStorePort`;
  - `DocumentStorePort`;
  - `SqlResourcePort`;
  - `SqlTransactionPort`;
- safe `data.resources.list`, `data.resource.inspect`, `data.doctor` actions;
- in-memory adapters for tests and examples;
- the optional `type: sql` bridge contract for a project-supplied SQL registry
  provider.

It intentionally does not own:

- project business schemas;
- universal CRUD/query API;
- ORM models, repositories, Unit of Work, project-specific migrations or
  backend-specific migration executors;
- vendor clients such as SQLAlchemy, Redis, Elasticsearch, OpenSearch, Qdrant,
  PyMongo or boto3;
- RAG, document parsing, embeddings, prompts or LLM calls;
- protocol routes;
- distributed transactions across backends.

Create the `DataRuntime` and adapter catalog once at the application composition
root. Framework packages use that shared runtime (for example,
`app.resource.connect(name, PortType)`) instead of repeating resource
configuration or creating their own connections. SQL-specific implementations
are provided by `muscles-data-sql` or `muscles-data-sqlalchemy`.

See [migration documentation](docs/migrations.en.md) for package discovery,
the registry, backend-specific journals and operational limitations.

## Operation Policies

The core defines a storage-neutral policy contract. It carries request-scoped
identity and arbitrary typed-at-the-boundary attributes, describes operations
and combines mandatory predicates without introducing concepts such as users,
workspaces or permissions into data models:

```python
from muscles.data import (
    DataOperationContext,
    DataOperationKind,
    DataPolicyDecision,
    DataPolicyPipeline,
    DataPredicate,
    DataPredicateOperator,
)


class WorkspaceIsolation:
    def evaluate(self, operation):
        workspace_uid = operation.context.attributes.get("workspace_uid")
        if workspace_uid is None:
            return DataPolicyDecision(allowed=False, reason="Active workspace is required")
        return DataPolicyDecision(predicates=(
            DataPredicate("workspace_uid", DataPredicateOperator.EQ, workspace_uid),
        ))


policies = DataPolicyPipeline()
policies.register(WorkspaceIsolation())
context = DataOperationContext(
    subject_type="account",
    subject_uid="account-123",
    attributes={"workspace_uid": "workspace-456"},
)
```

An adapter or repository must explicitly accept the pipeline and translate its
predicates into the backend's native operation. It must apply read predicates
before sort/limit/ranking and apply mutation predicates inside the write query.
Unsupported predicates must fail closed. `DataRuntime.policies` is the shared
application-level registry; request context is passed separately per
repository, so mutable current-workspace state is never stored in the runtime.

The current SQL resource uses `type: native_sql` from `muscles-data-sql`
and `SqlTransactionPort`; `App` registers the adapter once and keeps database
settings in `data.resources`. The optional `type: sql` resource is a session
bridge and only works when the composition root supplies a
`SqlConnectionRegistry` through `DataAdapterCatalog.with_defaults(sql_registry_provider=...)`.
The SQL repository integration is in `muscles.data.sql.SqlRepository`. Direct SQL,
SQLAlchemy sessions and native clients bypass repository policies and must be
treated as trusted infrastructure access. Other `muscles-data` adapters can
implement the same policy contract in their own package without a core change.

## Event-driven data contract

`DataEventEnvelope` and the publish/read/ack request and result models are core
`muscles.Model` schemas. They are visible through `inspect_application` and can
be reused by protocol projections without a second DTO or schema system.

The MVP includes `EventPublisherPort`, `EventConsumerPort` and `EventStorePort`,
plus the `memory_event` adapter for tests and local examples. Event schemas
describe semantic facts; `StreamPort` remains a lower-level transport
primitive. Production transports, outbox/inbox workers and distributed
transactions remain separate extensions.

Diagnostics expose only safe counts and resource metadata; event payloads are
never included in `inspect` or `doctor` output.

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
      url_env: ELASTICSEARCH_URL
      api_key: !environ ELASTICSEARCH_API_KEY
      index: docs

    search.public:
      type: opensearch
      url_env: OPENSEARCH_URL
      username: !environ OPENSEARCH_USER
      password: !environ OPENSEARCH_PASSWORD
      index: docs

    cache.redis:
      type: redis
      url_env: REDIS_URL
      namespace: app
      stream_group: workers
      consumer: index-worker

    vector.qdrant:
      type: qdrant
      url_env: QDRANT_URL
      api_key: !environ QDRANT_API_KEY
      collection: docs
      vector_size: 1536
      distance: cosine

    mongo.content:
      type: mongodb
      url_env: MONGO_URL
      database: content

    objects.docs:
      type: s3
      endpoint_url: !environ S3_ENDPOINT
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
from muscles.data.catalog import DataAdapterCatalog
from muscles.data.elasticsearch import ElasticsearchSearchFactory
from muscles.data.qdrant import QdrantVectorFactory
from muscles.data.redis import RedisDataFactory

catalog = DataAdapterCatalog.with_defaults()
catalog.register(ElasticsearchSearchFactory())
catalog.register(QdrantVectorFactory())
catalog.register(RedisDataFactory())
```

`muscles-data` core does not import these packages automatically. This keeps
framework startup small and avoids pulling database SDKs into projects that do
not need them. Registration is deliberately manual: projects install and
register only the adapter packages they need.

## Runtime API

```python
from muscles.data import DataRuntime
from muscles.data.config import DataConfig
from muscles.data.catalog import DataAdapterCatalog
from muscles.data.ports import KeyValuePort, VectorSearchPort

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

vector = runtime.connect("vector.docs", VectorSearchPort)
cache = runtime.connect("cache.default", KeyValuePort)
```

Adapters are initialized lazily: package init and resource listing do not open
external connections. `connect(name, PortType)` checks capabilities, creates or
reuses the configured adapter, and returns its port; the adapter may open the
external connection on its first operation. `connect()` therefore remains lazy.
An application can keep one configured runtime at its composition root and let
packages request ports such as `app.resource.connect("database", SqlTransactionPort)`.
The lower-level methods are:

- `runtime.require_port(name, PortType)`;
- `runtime.require_resource(name, capability)`;
- `runtime.doctor()` when health checks are enabled.

## Optional SQL Session Bridge

`type: sql` delegates to a named registry supplied by the composition root.
The default catalog has no registry provider, so this resource type is
unavailable until the application explicitly supplies one. It provides
SQLAlchemy sessions through `SqlResourcePort`; the native SQL transaction
resource is provided by `muscles-data-sql`.

```yaml
data:
  resources:
    sql.documents:
      type: sql
      connection: documents_metadata
      role: read_write
```

```python
from muscles.data.ports import SqlResourcePort

sql = app.resource.connect("sql.documents", SqlResourcePort)
with sql.session() as session:
    ...
```

`connection` must name a connection in the registry passed through
`DataAdapterCatalog.with_defaults(sql_registry_provider=...)`. `muscles-data`
does not create SQL engines, repositories, Unit of Work objects or migrations.
`session()`, `session_factory()`, `inspect()` and `doctor()` delegate to the
supplied registry.

Use `muscles-data-sqlalchemy` when a project wants direct SQLAlchemy sessions
through the same `SqlResourcePort` without using `muscles-data-sql`.

## Native Escape Hatch

The preferred path is always a typed port. A project may explicitly request a
native/internal backend handle only when the resource declares the
`native_client` capability:

```python
from muscles.data import DataCapability

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

Run the real-backend integration suite locally (Docker and the optional SDKs
are required):

```bash
make data-integration-test
```

The command starts isolated Elasticsearch, OpenSearch, Qdrant, Redis,
MongoDB, MinIO and PostgreSQL containers, runs every adapter's contract and
backend lifecycle tests, and removes the containers on exit. Set
`MUSCLES_DATA_PYTHON` to use a different Python environment. The compose file
and port map are documented in
[`infra/docker-compose.integration.yml`](infra/docker-compose.integration.yml).

# Policy-aware search

Search and vector adapters can be wrapped per request using `PolicySearchIndex`
or `PolicyVectorSearch`, passing the underlying port, resource name,
`policies=runtime.policies` and an explicit `DataOperationContext`. The same
wrappers are exported from the Elasticsearch/OpenSearch and Qdrant packages.
Policy predicates support scalar `EQ`/`NE`, integer `GT`/`GTE`/`LT`/`LTE`,
nonempty homogeneous scalar `IN`, `LIKE` and `IS_NULL`; caller filters support
scalar equality. Unsupported conditions fail closed. The wrappers add supported
index conditions to the backend query and independently validate returned metadata
or payload. For `LIKE` and `IS_NULL`, search backends scan candidate results and
validate original values instead of relying on index mappings, which can conflate
null, missing and analyzed values. This may be expensive or reach `max_scan`.
Raw adapters and native clients bypass the wrappers.

The portable `LIKE` subset is case-sensitive: `%` matches any sequence, `_`
matches one character, and other characters (including backslash) are literal.
Patterns are limited to 256 characters. `IS_NULL` takes a boolean: `True` matches
explicit null, `False` matches a present non-null value. Missing fields and
arrays match neither. SQL dialect collation and escape behavior may differ.

Some search backends treat array members or normalized terms as equal to a
scalar. The second validation rejects non-exact results. Elasticsearch and
OpenSearch use a point-in-time snapshot and `search_after` to fetch additional
pages. The snapshot is released on success or failure. Protected vector search
fetches up to `max_scan` candidates in one backend request and filters them in
memory; it does not issue offset-based follow-up queries. This prevents ordering
changes between pages within one request, but does not provide a database snapshot
or guarantee the exact nearest neighbours of an approximate search. `max_scan`
bounds candidates; reaching it without enough matches raises an error. Caller
pagination and custom sort options are rejected for protected text searches.

Elasticsearch and OpenSearch protect writes with sequence-number and primary-term
preconditions, or create-only semantics for new ids. A concurrent change raises
`DataWriteConflictError`; do not retry without re-reading and re-evaluating the
policy. Batch writes are not a transaction. If a later item fails after earlier
writes succeeded, `DataBatchWriteError` reports `completed_ids`, `failed_id` and
`pending_ids`; the failed item's outcome may be unknown after a transport error.
MongoDB uses its atomic document path. Qdrant 1.17+ can use managed conditional
upserts with operation markers when the resource explicitly sets
`policy_atomic_managed: true`. Every cluster node must support the feature and
every writer must rotate or remove the reserved marker on every change. This
invariant does not hold for arbitrary native or external writers. Existing points
without a managed marker cannot be updated through the atomic path. Older servers
and clients reject protected writes by default.

Qdrant's acknowledgement does not say whether a condition matched. After a
conditional upsert, the adapter reads the point with consistency `all`; the
operation is confirmed only when its unique marker is present. Otherwise it
raises `DataWriteOutcomeUnknownError` carrying `document_id` and `operation_id`.
`PolicyVectorSearch.confirm_upsert(document_id, operation_id)` returns `True` if
the marker is observed, otherwise `None`; a mismatch cannot prove failure because
a later write might already have replaced the marker. Do not retry blindly.
Protected deletes use a conditional tombstone rather than physical deletion:
managed searches hide those points, and `confirm_delete` checks the tombstone's
operation marker. Tombstones retain their payload and vector and cannot be
overwritten by protected upsert. Native Qdrant readers and external clients can
still see or change them, so they must follow the same managed-reader and writer
rules; the library cannot enforce those rules in other processes. Public raw
writes and native-client access through a managed resource are blocked.

For recovery after process restart, create `SqliteOperationJournal(path)` on
persistent storage and pass it to `QdrantVectorFactory(operation_journal=journal)`.
The journal stores operation identifiers before writes; `reconcile_pending()`
confirms matching markers and leaves the rest pending. It stores identifiers but
not payloads or credentials. Use a protected, persistent location with reliable
SQLite locking, retained across restarts; do not share a path across unrelated
deployments. Records are scoped to resource, collection and a hash of the
configured endpoint; `policy_journal_scope` can distinguish deployments sharing
one endpoint. A crash before sending the write also leaves a pending record, and
no transaction spans SQLite and Qdrant, so a mismatch remains unknown.

Existing unmarked points may be prepared one by one with
`protected_vectors.adopt_existing(id, expected_fields={...}, maintenance_confirmed=True)`
while **all other writers are stopped**. The method checks policy and expected
scalar fields and conditionally adds the marker without replacing payload or
vector. It cannot prove that external writers are stopped or compare arbitrary
vectors, so the maintenance window is an operator-enforced precondition. It
does not automatically scan or change a collection. Protected deletion leaves a
tombstone; recreating the same id is rejected and no automatic purge is performed.

`DataNonAtomicPolicyMode.ALLOW_PRECHECK` explicitly enables a
read-before-write check where no atomic path is implemented. It is **not atomic**:
concurrent writes can invalidate the check, so it is unsuitable as a security
boundary against concurrent changes. Backend options, upsert `fields`, and
filtered deletes are rejected in protected writes.
