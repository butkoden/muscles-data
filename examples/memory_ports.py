"""Storage ports using only in-process resources; no external services."""
from muscles_data import DataConfig, DataRuntime
from muscles_data.ports import DocumentStorePort, KeyValuePort, ObjectStorePort, SearchIndexPort, VectorSearchPort


def main():
    runtime = DataRuntime(config=DataConfig.from_raw({"resources": {
        "vectors": {"type": "memory_vector"}, "search": {"type": "memory_search"},
        "objects": {"type": "memory_object"}, "cache": {"type": "memory_kv"},
        "documents": {"type": "memory_document"},
    }}))
    try:
        vectors = runtime.require_port("vectors", VectorSearchPort)
        vectors.upsert_vectors([{"id": "one", "vector": [1.0, 0.0], "payload": {"kind": "guide"}}])
        print("vector:", [hit.id for hit in vectors.search_vectors([1.0, 0.0], filters={"kind": "guide"})])
        vectors.delete_vectors(ids=["one"])

        search = runtime.require_port("search", SearchIndexPort)
        search.upsert_documents([{"id": "one", "title": "Intro", "text": "A guide to Muscles"}])
        print("text:", [hit.id for hit in search.search_text("guide")])
        search.delete_documents(ids=["one"])

        objects = runtime.require_port("objects", ObjectStorePort)
        objects.put_object("docs/intro.txt", b"hello", content_type="text/plain")
        print("object:", objects.get_object("docs/intro.txt").content.decode())
        print("objects:", [item.key for item in objects.list_objects(prefix="docs/")])
        objects.delete_object("docs/intro.txt")

        cache = runtime.require_port("cache", KeyValuePort)
        cache.set("session", b"active", ttl_seconds=60)
        print("cache:", cache.get("session"), "exists:", cache.exists("session"))
        cache.delete("session")

        documents = runtime.require_port("documents", DocumentStorePort)
        documents.upsert_document("profiles", "user-1", {"name": "Denis", "role": "developer"})
        print("document:", documents.get_document("profiles", "user-1"))
        print("find:", documents.find_documents("profiles", filters={"role": "developer"}))
        documents.delete_document("profiles", "user-1")
        print("resources:", runtime.list_resources())
        print("doctor:", runtime.doctor()["status"])
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
