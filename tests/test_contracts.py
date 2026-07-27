from __future__ import annotations

import pytest

from muscles_data.adapters.memory import (
    InMemoryDocumentStoreAdapter,
    InMemoryKeyValueAdapter,
    InMemoryObjectStoreAdapter,
    InMemorySearchIndexAdapter,
    InMemoryVectorAdapter,
)
from muscles_data.config import DataConfig
from muscles_data.contracts import (
    assert_document_store_contract,
    assert_key_value_contract,
    assert_object_store_contract,
    assert_search_index_contract,
    assert_vector_search_contract,
)


def test_search_index_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"search": {"type": "memory_search"}}}})
    assert_search_index_contract(lambda: InMemorySearchIndexAdapter(config.resources["search"]))


def test_vector_search_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"vector": {"type": "memory_vector"}}}})
    assert_vector_search_contract(lambda: InMemoryVectorAdapter(config.resources["vector"]))


def test_vector_search_contract_requires_positive_dimension():
    config = DataConfig.from_raw({"data": {"resources": {"vector": {"type": "memory_vector"}}}})
    adapter = InMemoryVectorAdapter(config.resources["vector"])
    with pytest.raises(ValueError, match="positive"):
        assert_vector_search_contract(lambda: adapter, dimension=0)


def test_key_value_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"cache": {"type": "memory_kv"}}}})
    assert_key_value_contract(lambda: InMemoryKeyValueAdapter(config.resources["cache"]))


def test_document_store_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"documents": {"type": "memory_document"}}}})
    assert_document_store_contract(lambda: InMemoryDocumentStoreAdapter(config.resources["documents"]))


def test_object_store_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"objects": {"type": "memory_object"}}}})
    assert_object_store_contract(lambda: InMemoryObjectStoreAdapter(config.resources["objects"]))
