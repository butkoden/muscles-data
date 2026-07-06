from __future__ import annotations

"""Qdrant vector port smoke example without a real Qdrant server.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_qdrant_vector_port.py
"""

from dataclasses import asdict

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import VectorSearchPort
from muscles_data.runtime import DataRuntime


class FakePoint:
    def __init__(self, point_id: str, score: float, payload: dict) -> None:
        self.id = point_id
        self.score = score
        self.payload = payload


class FakeQueryResult:
    def __init__(self, points: list[FakePoint]) -> None:
        self.points = points


class FakeQdrantClient:
    def query_points(self, **_kwargs):
        return FakeQueryResult([FakePoint("doc-1", 0.91, {"section": "docs"})])

    def upsert(self, **_kwargs):
        return {"status": "completed"}

    def delete(self, **_kwargs):
        return {"status": "completed"}

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name == "docs"


class FakeQdrantModels:
    class MatchValue:
        def __init__(self, value) -> None:
            self.value = value

    class MatchAny:
        def __init__(self, any) -> None:
            self.any = any

    class Range:
        def __init__(self, **kwargs) -> None:
            self.values = kwargs

    class FieldCondition:
        def __init__(self, *, key: str, match=None, range=None) -> None:
            self.key = key
            self.match = match
            self.range = range

    class Filter:
        def __init__(self, *, must=None, should=None, must_not=None) -> None:
            self.must = must or []
            self.should = should or []
            self.must_not = must_not or []

    class PointStruct:
        def __init__(self, *, id, vector, payload=None) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload or {}

    class PointIdsList:
        def __init__(self, *, points) -> None:
            self.points = points

    class FilterSelector:
        def __init__(self, *, filter) -> None:
            self.filter = filter


def main() -> None:
    client = FakeQdrantClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "vector.docs": {
                            "type": "qdrant",
                            "url": "https://qdrant.example",
                            "api_key": "qdrant-secret",
                            "collection": "docs",
                            "timeout": 1,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(
            qdrant_client_factory=lambda _config: client,
            qdrant_models_provider=lambda: FakeQdrantModels,
        ),
    )

    vector = runtime.require_port("vector.docs", VectorSearchPort)
    print("upsert ->", asdict(vector.upsert_vectors([
        {"id": "doc-1", "vector": [0.9, 0.1], "payload": {"section": "docs"}},
    ])))
    print("hits ->", [hit.id for hit in vector.search_vectors([1.0, 0.0], filters={"section": "docs"})])
    print("delete ->", asdict(vector.delete_vectors(ids=["doc-1"])))
    print("doctor ->", runtime.doctor())


if __name__ == "__main__":
    main()
