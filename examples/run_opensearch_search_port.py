from __future__ import annotations

"""OpenSearch search port smoke example without a real OpenSearch server.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_opensearch_search_port.py
"""

from dataclasses import asdict

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import SearchIndexPort
from muscles_data.runtime import DataRuntime


class FakeOpenSearchIndices:
    def exists(self, *, index: str) -> bool:
        return index == "docs"


class FakeOpenSearchClient:
    def __init__(self) -> None:
        self.indices = FakeOpenSearchIndices()

    def search(self, **_kwargs):
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "doc-1",
                        "_score": 3.2,
                        "_source": {"text": "Muscles data ports", "metadata": {"section": "docs"}},
                        "highlight": {"text": ["<em>Muscles</em> data ports"]},
                    }
                ]
            }
        }

    def index(self, **_kwargs):
        return {"result": "created"}

    def delete(self, **_kwargs):
        return {"result": "deleted"}

    def delete_by_query(self, **_kwargs):
        return {"deleted": 1}

    def ping(self) -> bool:
        return True


def main() -> None:
    client = FakeOpenSearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "search.public": {
                            "type": "opensearch",
                            "url": "https://opensearch.example",
                            "username": "admin",
                            "password": "open-secret",
                            "index": "docs",
                            "timeout": 1,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(opensearch_client_factory=lambda _config: client),
    )

    search = runtime.require_port("search.public", SearchIndexPort)
    print("upsert ->", asdict(search.upsert_documents([
        {"id": "doc-1", "text": "Muscles data ports", "metadata": {"section": "docs"}},
    ])))
    print("hits ->", [hit.id for hit in search.search_text("muscles", filters={"section": "docs"}, options={"highlight": True})])
    print("delete ->", asdict(search.delete_documents(filters={"section": "docs"})))
    print("doctor ->", runtime.doctor())


if __name__ == "__main__":
    main()
