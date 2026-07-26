from __future__ import annotations

"""Small muscles-data runtime smoke example.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_data_runtime.py
"""

from types import SimpleNamespace

from muscles import ActionDispatcher

from muscles_data import init_package
from muscles_data.ports import KeyValuePort, ObjectStorePort, SearchIndexPort, VectorSearchPort
from muscles_data.runtime import DataRuntime


def main() -> None:
    app = SimpleNamespace()
    runtime = init_package(
        app,
        {
            "data": {
                "resources": {
                    "vector.docs": {"type": "memory_vector"},
                    "search.docs": {"type": "memory_search"},
                    "cache.default": {"type": "memory_kv"},
                    "objects.docs": {"type": "memory_object"},
                }
            }
        },
    )
    assert isinstance(runtime, DataRuntime)

    vector = runtime.require_port("vector.docs", VectorSearchPort)
    vector.upsert_vectors([{"id": "doc-1", "vector": [1.0, 0.0], "payload": {"title": "Intro"}}])
    print("vector ->", [hit.id for hit in vector.search_vectors([1.0, 0.1])])

    search = runtime.require_port("search.docs", SearchIndexPort)
    search.upsert_documents([{"id": "doc-1", "text": "Muscles data ports"}])
    print("search ->", [hit.id for hit in search.search_text("ports")])

    cache = runtime.require_port("cache.default", KeyValuePort)
    cache.set("cursor", b"42")
    print("cache ->", cache.get("cursor").decode("utf-8"))

    objects = runtime.require_port("objects.docs", ObjectStorePort)
    objects.put_object("docs/readme.txt", b"hello", content_type="text/plain")
    print("objects ->", [item.key for item in objects.list_objects(prefix="docs/")])

    dispatcher = ActionDispatcher(app)
    print("resources ->", dispatcher.execute("data.resources.list", {}).value)
    print("doctor ->", dispatcher.execute("data.doctor", {}).value)


if __name__ == "__main__":
    main()
