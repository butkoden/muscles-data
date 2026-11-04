"""Run one real adapter against a disposable service; see examples/README.md.

External examples require --allow-writes and use a fresh UUID namespace.
They may create indices, collections or streams that remain after the run.
"""
import argparse
import os
from uuid import uuid4

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import (
    DocumentStorePort, KeyValuePort, LockPort, ObjectStorePort,
    SearchIndexPort, SqlResourcePort, StreamPort, VectorSearchPort,
)
from muscles_data.runtime import DataRuntime


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} to use this example")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("redis", "qdrant", "elasticsearch", "opensearch", "mongodb", "s3", "sqlalchemy"))
    parser.add_argument("--allow-writes", action="store_true", help="allow creation of data in the chosen test service")
    args = parser.parse_args()
    if args.backend != "sqlalchemy" and not args.allow_writes:
        parser.error("external examples create data: use an isolated test service and pass --allow-writes")

    tag = "muscles_example_" + uuid4().hex[:12]
    catalog = DataAdapterCatalog.with_defaults()
    if args.backend == "redis":
        from muscles_data_redis import RedisDataFactory
        required_env("REDIS_URL")
        catalog.register(RedisDataFactory())
        options = {"type": "redis", "url_env": "REDIS_URL", "namespace": tag,
                   "stream_group": tag, "consumer": "example"}
    elif args.backend == "qdrant":
        from muscles_data_qdrant import QdrantVectorFactory
        required_env("QDRANT_URL")
        catalog.register(QdrantVectorFactory())
        options = {"type": "qdrant", "url_env": "QDRANT_URL", "collection": tag, "vector_size": 2}
    elif args.backend in ("elasticsearch", "opensearch"):
        env_name = "ELASTICSEARCH_URL" if args.backend == "elasticsearch" else "OPENSEARCH_URL"
        required_env(env_name)
        if args.backend == "elasticsearch":
            from muscles_data_elasticsearch import ElasticsearchSearchFactory
            catalog.register(ElasticsearchSearchFactory())
        else:
            from muscles_data_opensearch import OpenSearchSearchFactory
            catalog.register(OpenSearchSearchFactory())
        options = {"type": args.backend, "url_env": env_name, "index": tag}
    elif args.backend == "mongodb":
        from muscles_data_mongodb import MongoDocumentStoreFactory
        required_env("MONGODB_URL")
        catalog.register(MongoDocumentStoreFactory())
        options = {"type": "mongodb", "url_env": "MONGODB_URL", "database": required_env("MONGODB_EXAMPLE_DATABASE")}
    elif args.backend == "s3":
        from muscles_data_s3 import S3ObjectStoreFactory
        catalog.register(S3ObjectStoreFactory())
        options = {"type": "s3", "endpoint_url": required_env("S3_ENDPOINT"),
                   "bucket": required_env("S3_BUCKET"), "prefix": tag}
    else:
        from muscles_data_sqlalchemy import SqlAlchemySqlResourceFactory
        catalog.register(SqlAlchemySqlResourceFactory())
        options = {"type": "sqlalchemy", "url": "sqlite:///:memory:"}

    runtime = DataRuntime(config=DataConfig.from_raw({"resources": {"example": options}}), catalog=catalog)
    try:
        if args.backend == "redis":
            cache = runtime.require_port("example", KeyValuePort)
            lock = runtime.require_port("example", LockPort)
            stream = runtime.require_port("example", StreamPort)
            cache.set("greeting", b"hello", ttl_seconds=60)
            print("cache:", cache.get("greeting"))
            handle = lock.acquire_lock("work", ttl_seconds=30)
            if handle is None:
                raise RuntimeError("Could not acquire the example lock")
            try:
                published = stream.publish("events", {"kind": "created"})
                messages = stream.read("events", limit=10).messages
                if not messages or not published.message_id:
                    raise RuntimeError("Redis stream did not return the published message")
                print("stream:", messages)
                stream.ack("events", published.message_id)
            finally:
                lock.release_lock(handle)
                cache.delete("greeting")
        elif args.backend == "qdrant":
            vector = runtime.require_port("example", VectorSearchPort)
            result = vector.upsert_vectors([{"id": "one", "vector": [1.0, 0.0], "payload": {"kind": "guide"}}], options={"wait": True})
            hits = vector.search_vectors([1.0, 0.0])
            if result.status != "ok" or not hits:
                raise RuntimeError("Qdrant did not return the written vector")
            print("hits:", [hit.id for hit in hits])
            vector.delete_vectors(ids=["one"], options={"wait": True})
        elif args.backend in ("elasticsearch", "opensearch"):
            search = runtime.require_port("example", SearchIndexPort)
            result = search.upsert_documents([{"id": "one", "title": "Intro", "text": "Muscles guide"}], options={"refresh": "wait_for"})
            hits = search.search_text("guide")
            if result.status != "ok" or not hits:
                raise RuntimeError("The search backend did not return the indexed document")
            print("hits:", [hit.id for hit in hits])
            search.delete_documents(ids=["one"], options={"refresh": "wait_for"})
        elif args.backend == "mongodb":
            documents = runtime.require_port("example", DocumentStorePort)
            documents.upsert_document(tag, "one", {"title": "Guide", "kind": "example"})
            print("document:", documents.get_document(tag, "one"))
            print("find:", documents.find_documents(tag, filters={"kind": "example"}))
            documents.delete_document(tag, "one")
        elif args.backend == "s3":
            objects = runtime.require_port("example", ObjectStorePort)
            objects.put_object("guide.txt", b"hello", content_type="text/plain")
            print("object:", objects.get_object("guide.txt").content)
            print("list:", [item.key for item in objects.list_objects()])
            objects.delete_object("guide.txt")
        else:
            from sqlalchemy import text
            sql = runtime.require_port("example", SqlResourcePort)
            with sql.session() as session:
                print("SQLAlchemy session:", session.execute(text("SELECT :value"), {"value": 42}).scalar_one())
        print("resource:", tag, "doctor:", runtime.doctor()["status"])
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
