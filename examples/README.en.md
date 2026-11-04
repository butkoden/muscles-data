# Muscles Data and SQL examples

Run commands from `projects/libraries`. Local examples use in-memory data:
The search policy example explicitly opts into a non-atomic precheck: data can
change between the check and the write. Use atomic enforcement when concurrent
access must be part of the security boundary.
`DataPredicate("name", DataPredicateOperator.LIKE, "team_%")` matches a
portable pattern; `DataPredicate("deleted_at", DataPredicateOperator.IS_NULL,
True)` requires an explicitly present null. Search backends validate these two
conditions against candidate source values and may scan up to `max_scan`.
Qdrant 1.17+ managed upserts require the explicit `policy_atomic_managed: true`
resource option and the managed-writer invariant documented in the library
README. Catch `DataWriteOutcomeUnknownError` and call
`protected_vectors.confirm_upsert(error.document_id, error.operation_id)`:
`True` confirms the marker, while `None` leaves the outcome unknown.
For restart recovery, pass `SqliteOperationJournal(path)` to
`QdrantVectorFactory(operation_journal=...)` and call `reconcile_pending()`.
Managed delete uses a retained tombstone; `adopt_existing` attaches markers to
legacy points only during an operator-enforced maintenance window.

- `muscles-data/examples/memory_ports.py`: vectors, search, objects, cache, documents and diagnostics.
- `muscles-data/examples/events.py`: event publishing, reading, acknowledgement and journal.
- `muscles-data/examples/diagnostics.py`: capabilities, safe diagnostics, errors and native access.
- `muscles-data/examples/search_policies.py`: search policies and an opt-in non-atomic write precheck.
- `muscles-data/examples/run_data_runtime.py`: package initialization and actions.
- `muscles-data/examples/run_sql_resource_port.py`: SQL bridge using a fake registry.
- `muscles-data-sql/examples/native_resources.py`: two resources and a custom driver factory.
- `muscles-data-sql/examples/queries_and_mapper.py`: JOIN, aggregate, model mapping and rollback.
- `muscles-data-sql/examples/repository_policies.py`: request-scoped repository policies; requires SQLAlchemy.
- `muscles-data-mongodb/examples/run_mongodb_document_store.py` and
  `muscles-data-s3/examples/run_s3_object_store.py`: adapters using fake clients.

```bash
export PYTHONPATH="muscles/src:muscles-data/src:muscles-data-sql/src"
python3 muscles-data/examples/memory_ports.py
python3 muscles-data/examples/events.py
python3 muscles-data/examples/diagnostics.py
python3 muscles-data/examples/search_policies.py
python3 muscles-data-sql/examples/queries_and_mapper.py
python3 muscles-data-sql/examples/repository_policies.py
```

Add the corresponding adapter `src` directory to `PYTHONPATH` for fake-client
examples. For repository policies install `muscles-data-sql[legacy]` dependencies.

`muscles-data/examples/backend_adapters.py` supports these real backends:

| Argument | Package | Required environment |
| --- | --- | --- |
| `redis` | `muscles-data-redis` | `REDIS_URL` |
| `qdrant` | `muscles-data-qdrant` | `QDRANT_URL` |
| `elasticsearch` | `muscles-data-elasticsearch` | `ELASTICSEARCH_URL` |
| `opensearch` | `muscles-data-opensearch` | `OPENSEARCH_URL` |
| `mongodb` | `muscles-data-mongodb` | `MONGODB_URL`, `MONGODB_EXAMPLE_DATABASE` |
| `s3` | `muscles-data-s3` | `S3_ENDPOINT`, `S3_BUCKET`, boto3 credentials |
| `sqlalchemy` | `muscles-data-sqlalchemy` | None: uses in-memory SQLite |

Install the relevant adapter and its driver, or add its `src` directory to
`PYTHONPATH`. S3 requires an existing bucket. Search examples assume a local
test service; configure authentication as documented by the adapter when needed.

**Use an isolated test service.** External examples require `--allow-writes`.
They create uniquely named indices, collections or streams. Individual records
are deleted on success, but empty backend resources remain, and failed runs may
leave records. Names prefixed `muscles_example_` are printed for manual cleanup;
the script does not delete databases, buckets, indices or collections.

```bash
export PYTHONPATH="muscles/src:muscles-data/src:muscles-data-redis/src"
export REDIS_URL="redis://127.0.0.1:6379/0"
python3 muscles-data/examples/backend_adapters.py redis --allow-writes
```

Replace the package, environment and argument for another backend. The
`sqlalchemy` option needs neither a server nor `--allow-writes`. `memory_kv`
does not implement locks or streams; the Redis example covers those ports.
Semantic events and Redis streams have distinct contracts. Raw SQL bypasses
repository policies.
MySQL and MariaDB do not yet have built-in `muscles-data-sql` drivers; register a
project driver using `SqlDriverCatalog`.

In a local Qdrant client check, a filter containing a nonempty `must` and an
empty `should` returned no match for a matching vector. The Qdrant example
therefore uses unfiltered search; this check did not establish server behavior.
