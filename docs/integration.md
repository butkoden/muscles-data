# Data adapter integration tests

The adapter packages expose two layers of verification:

- fast unit tests, which run without external services;
- marked `integration` tests, which exercise the typed port against a real
  backend and also run the shared core contract where it applies.

From the repository root:

```bash
make data-integration-test
```

This uses `infra/docker-compose.integration.yml`. Host ports are intentionally
non-default so the stack can coexist with a developer's existing services:

| Backend | Host port |
| --- | ---: |
| Elasticsearch | 19200 |
| OpenSearch | 19201 |
| Qdrant HTTP | 16333 |
| Redis | 16389 |
| MongoDB | 17017 |
| MinIO API / console | 19000 / 19001 |
| PostgreSQL | 15433 |

The script exports the connection URLs expected by the tests and tears down
the compose project even when a test fails. To use another environment:

```bash
MUSCLES_DATA_PYTHON=/path/to/python make data-integration-test
```

The tests use unique indexes, collections, namespaces, databases and buckets,
so repeated runs do not depend on stale data. Qdrant also preserves arbitrary
public string IDs by mapping backend point IDs to stable UUIDs and storing the
original ID in an internal payload field; callers still observe the original
ID through `VectorHit.id`.
