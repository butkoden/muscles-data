"""Reusable contract checks for authors of ``muscles-data`` adapters.

The checks deliberately use only the public port methods.  Adapter projects can
call them from their own pytest suite with a factory that returns an isolated
port instance, without importing a vendor SDK into this package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .models import LockHandle
from .ports import DocumentStorePort, KeyValuePort, LockPort, ObjectStorePort, SearchIndexPort, StreamPort, VectorSearchPort


def assert_search_index_contract(make_port: Callable[[], SearchIndexPort]) -> None:
    port = make_port()
    written = port.upsert_documents(
        [
            {"id": "contract-a", "title": "Alpha", "text": "alpha document", "metadata": {"status": "ready"}},
            {"id": "contract-b", "title": "Beta", "text": "beta document", "metadata": {"status": "draft"}},
        ],
        options={"refresh": "wait_for"},
    )
    assert written.written == 2
    hits = port.search_text("alpha", filters={"status": "ready"}, limit=10)
    assert hits and hits[0].id == "contract-a"
    assert hits[0].text == "alpha document"
    assert getattr(hits[0], "title", None) == "Alpha"
    assert port.delete_documents(ids=["contract-a"], options={"refresh": "wait_for"}).deleted == 1


def assert_vector_search_contract(make_port: Callable[[], VectorSearchPort], *, dimension: int = 2) -> None:
    if dimension < 1:
        raise ValueError("Vector contract dimension must be positive")
    first = [1.0] + [0.0] * (dimension - 1)
    second = [0.0, 1.0] + [0.0] * (dimension - 2) if dimension > 1 else [1.0]
    port = make_port()
    written = port.upsert_vectors(
        [
            {"id": "contract-a", "vector": first, "payload": {"status": "ready"}},
            {"id": "contract-b", "vector": second, "payload": {"status": "draft"}},
        ],
        options={"wait": True},
    )
    assert written.written == 2
    hits = port.search_vectors(first, filters={"status": "ready"}, limit=10)
    assert hits and hits[0].id == "contract-a"
    assert float(hits[0].score) >= 0.0
    assert port.delete_vectors(ids=["contract-a"], options={"wait": True}).deleted == 1


def assert_lock_contract(make_port: Callable[[], LockPort]) -> None:
    port = make_port()
    handle = port.acquire_lock("contract-lock", ttl_seconds=30)
    assert isinstance(handle, LockHandle)
    assert port.acquire_lock("contract-lock", ttl_seconds=30) is None
    wrong_owner = replace(handle, token=f"wrong-{handle.token}")
    assert port.release_lock(wrong_owner).deleted == 0
    assert port.release_lock(handle).deleted == 1
    assert port.acquire_lock("contract-lock", ttl_seconds=30) is not None


def assert_stream_contract(make_port: Callable[[], StreamPort]) -> None:
    port = make_port()
    published = port.publish("contract-stream", {"kind": "created", "value": 1})
    assert published.written == 1
    result = port.read("contract-stream", limit=10)
    assert result.messages
    message = result.messages[0]
    assert message["fields"] == {"kind": "created", "value": 1}
    assert message["envelope"]["version"] == 1
    assert port.ack("contract-stream", message["id"]).matched == 1


def assert_key_value_contract(make_port: Callable[[], KeyValuePort]) -> None:
    port = make_port()
    assert port.get("contract-key") is None
    assert port.set("contract-key", b"value").written == 1
    assert port.exists("contract-key") is True
    assert port.get("contract-key") == b"value"
    assert port.delete("contract-key").deleted == 1
    assert port.exists("contract-key") is False


def assert_document_store_contract(make_port: Callable[[], DocumentStorePort]) -> None:
    port = make_port()
    document = {"title": "Contract document", "status": "ready"}
    assert port.upsert_document("contract", "document-a", document).written == 1
    assert port.get_document("contract", "document-a") == document
    found = port.find_documents("contract", filters={"status": "ready"}, limit=10)
    assert found == [document]
    assert port.delete_document("contract", "document-a").deleted == 1
    assert port.get_document("contract", "document-a") is None


def assert_object_store_contract(make_port: Callable[[], ObjectStorePort]) -> None:
    port = make_port()
    content = b"contract object"
    assert port.put_object(
        "contract/object.txt",
        content,
        content_type="text/plain",
        metadata={"kind": "contract"},
    ).written == 1
    blob = port.get_object("contract/object.txt")
    assert blob.content == content
    assert blob.content_type == "text/plain"
    assert blob.metadata == {"kind": "contract"}
    listed = port.list_objects(prefix="contract", limit=10)
    assert [item.key for item in listed] == ["contract/object.txt"]
    assert port.delete_object("contract/object.txt").deleted == 1


def assert_sql_resource_contract(make_port: Callable[[], Any]) -> None:
    port = make_port()
    assert port.connection_name()
    assert callable(port.session_factory())
    session = port.session()
    close = getattr(session, "close", None)
    if callable(close):
        close()
    assert port.inspect().get("status") in {None, "ok"}
    assert port.doctor().get("status") == "ok"


__all__ = [
    "assert_document_store_contract",
    "assert_lock_contract",
    "assert_key_value_contract",
    "assert_object_store_contract",
    "assert_search_index_contract",
    "assert_sql_resource_contract",
    "assert_stream_contract",
    "assert_vector_search_contract",
]
