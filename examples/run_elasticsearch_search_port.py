from __future__ import annotations

"""Elasticsearch search port smoke example without a real Elasticsearch server.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_elasticsearch_search_port.py
"""

from dataclasses import asdict

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import SearchIndexPort
from muscles_data.runtime import DataRuntime


class FakeElasticsearchIndices:
    def exists(self, *, index: str) -> bool:
        return index == "docs"


class FakeElasticsearchClient:
    def __init__(self) -> None:
        self.indices = FakeElasticsearchIndices()

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
    client = FakeElasticsearchClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "search.docs": {
                            "type": "elasticsearch",
                            "url": "https://elastic.example",
                            "api_key": "elastic-secret",
                            "index": "docs",
                            "timeout": 1,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(elasticsearch_client_factory=lambda _config: client),
    )

    search = runtime.require_port("search.docs", SearchIndexPort)
    print("upsert ->", asdict(search.upsert_documents([
        {"id": "doc-1", "text": "Muscles data ports", "metadata": {"section": "docs"}},
    ])))
    print("hits ->", [hit.id for hit in search.search_text("muscles", filters={"section": "docs"}, options={"highlight": True})])
    print("delete ->", asdict(search.delete_documents(filters={"section": "docs"})))
    print("doctor ->", runtime.doctor())


if __name__ == "__main__":
    main()
