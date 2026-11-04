"""Policy-filtered search and an explicit non-atomic check with an in-memory fake."""

from muscles_data import DataNonAtomicPolicyMode, DataOperationContext, DataPolicyDecision, DataPolicyPipeline, DataPredicate, DataPredicateOperator, PolicySearchIndex
from muscles_data.models import SearchHit, WriteResult


class WorkspacePolicy:
    def evaluate(self, operation):
        return DataPolicyDecision(predicates=(DataPredicate(
            "workspace", DataPredicateOperator.EQ, operation.context.attributes["workspace"],
        ),))


class ExampleSearch:
    def __init__(self):
        self.documents = {"1": {"workspace": "alpha"}, "2": {"workspace": "beta"}}

    def search_text(self, query, filters=None, limit=10, options=None):
        # Real adapters apply the passed filters in the backend before pagination.
        hits = [SearchHit(key, 1.0, metadata=value) for key, value in self.documents.items()
                if value["workspace"] == "alpha"]
        start = (options or {}).get("from_", 0)
        return hits[start:start + limit]

    def policy_get(self, document_id):
        return self.documents.get(document_id)

    def upsert_documents(self, items, options=None):
        for item in items:
            self.documents[item["id"]] = dict(item["metadata"])
        return WriteResult(written=len(items))


def main():
    policies = DataPolicyPipeline(
        (WorkspacePolicy(),), non_atomic_mode=DataNonAtomicPolicyMode.ALLOW_PRECHECK,
    )
    search = PolicySearchIndex(
        ExampleSearch(), "articles", policies=policies,
        context=DataOperationContext(subject_uid="user-1", attributes={"workspace": "alpha"}),
    )
    print([hit.id for hit in search.search_text("example")])
    # This opt-in check is non-atomic; use an atomic backend for security boundaries.
    search.upsert_documents([{"id": "1", "metadata": {"workspace": "alpha"}}])


if __name__ == "__main__":
    main()
