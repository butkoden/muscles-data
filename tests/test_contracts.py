from __future__ import annotations

from muscles_data.adapters.memory import InMemorySearchIndexAdapter, InMemoryVectorAdapter
from muscles_data.config import DataConfig
from muscles_data.contracts import assert_search_index_contract, assert_vector_search_contract


def test_search_index_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"search": {"type": "memory_search"}}}})
    assert_search_index_contract(lambda: InMemorySearchIndexAdapter(config.resources["search"]))


def test_vector_search_contract_uses_only_port_methods():
    config = DataConfig.from_raw({"data": {"resources": {"vector": {"type": "memory_vector"}}}})
    assert_vector_search_contract(lambda: InMemoryVectorAdapter(config.resources["vector"]))
