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
from .ports import LockPort, SearchIndexPort, StreamPort, VectorSearchPort


def assert_search_index_contract(make_port: Callable[[], SearchIndexPort]) -> None:
    port = make_port()
    written = port.upsert_documents(
        [
            {"id": "contract-a", "title": "Alpha", "text": "alpha document", "metadata": {"status": "ready"}},
            {"id": "contract-b", "title": "Beta", "text": "beta document", "metadata": {"status": "draft"}},
        ]
    )
    assert written.written == 2
    hits = port.search_text("alpha", filters={"status": "ready"}, limit=10)
    assert hits and hits[0].id == "contract-a"
    assert hits[0].text == "alpha document"
    assert getattr(hits[0], "title", None) == "Alpha"
    assert port.delete_documents(ids=["contract-a"]).deleted == 1


def assert_vector_search_contract(make_port: Callable[[], VectorSearchPort]) -> None:
    port = make_port()
    written = port.upsert_vectors(
        [
            {"id": "contract-a", "vector": [1.0, 0.0], "payload": {"status": "ready"}},
            {"id": "contract-b", "vector": [0.0, 1.0], "payload": {"status": "draft"}},
        ]
    )
    assert written.written == 2
    hits = port.search_vectors([1.0, 0.0], filters={"status": "ready"}, limit=10)
    assert hits and hits[0].id == "contract-a"
    assert float(hits[0].score) >= 0.0
    assert port.delete_vectors(ids=["contract-a"]).deleted == 1


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


__all__ = [
    "assert_lock_contract",
    "assert_search_index_contract",
    "assert_stream_contract",
    "assert_vector_search_contract",
]
