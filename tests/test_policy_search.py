import pytest

from muscles.data.errors import DataBatchWriteError, DataPolicyDeniedError, DataUnsupportedOperationError, DataWriteConflictError
from muscles.data.models import SearchHit, VectorHit, WriteResult
from muscles.data.policies import DataNonAtomicPolicyMode, DataOperationContext, DataPolicyDecision, DataPolicyPipeline, DataPredicate, DataPredicateOperator
from muscles.data.policy_search import PolicySearchIndex, PolicyVectorSearch


class Policy:
    def evaluate(self, request):
        return DataPolicyDecision(predicates=(DataPredicate("workspace", DataPredicateOperator.EQ, request.context.attributes["workspace"]),))


class Backend:
    def __init__(self):
        self.calls = []

    def search_text(self, query, filters=None, limit=10, options=None):
        self.calls.append(("text", filters, limit))
        rows = [SearchHit("good", 1, metadata={"workspace": "a"}), SearchHit("array", 1, metadata={"workspace": ["a", "b"]}), SearchHit("next", 1, metadata={"workspace": "a"})]
        offset = (options or {}).get("from_", 0)
        return rows[offset:offset + limit]

    def search_vectors(self, vector, filters=None, limit=10, options=None):
        self.calls.append(("vector", filters, limit, options))
        rows = [VectorHit("good", 1, payload={"workspace": "a"}), VectorHit("array", 1, payload={"workspace": ["a", "b"]}), VectorHit("next", 1, payload={"workspace": "a"})]
        offset = (options or {}).get("offset", 0)
        return rows[offset:offset + limit]

    def upsert_documents(self, items, options=None):
        self.calls.append(("write", items))
        return WriteResult(written=len(items))

    def delete_documents(self, ids=None, filters=None, options=None):
        self.calls.append(("delete", ids, filters))
        return WriteResult()


def test_search_applies_policy_to_backend_and_rejects_array_results():
    backend = Backend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    assert [hit.id for hit in store.search_text("hello", {"kind": "note"}, limit=2)] == ["good", "next"]
    assert backend.calls[0] == ("text", {"$and": [{"kind": "note"}, {"workspace": "a"}]}, 2)


def test_policy_search_uses_and_closes_snapshot_after_filling_results():
    class SnapshotBackend(Backend):
        def policy_search_snapshot(self, query, filters, batch_size, options):
            try:
                yield SearchHit("array", 1, metadata={"workspace": ["a", "b"]})
                yield SearchHit("valid", 1, metadata={"workspace": "a"})
                yield SearchHit("unused", 1, metadata={"workspace": "a"})
            finally:
                self.calls.append("snapshot_closed")

    backend = SnapshotBackend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    assert [hit.id for hit in store.search_text("hello", limit=1)] == ["valid"]
    assert backend.calls == ["snapshot_closed"]


def test_vector_search_requires_payload_to_validate_results():
    backend = Backend()
    store = PolicyVectorSearch(backend, "vectors", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    assert [hit.id for hit in store.search_vectors([1.0], limit=2)] == ["good", "next"]
    assert backend.calls[0][3]["with_payload"] is True
    assert len(backend.calls) == 1
    with pytest.raises(DataUnsupportedOperationError):
        store.search_vectors([1.0], options={"with_payload": False})


def test_vector_search_uses_one_bounded_candidate_snapshot():
    backend = Backend()
    store = PolicyVectorSearch(backend, "vectors", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}), max_scan=3)
    assert [hit.id for hit in store.search_vectors([1.0], limit=2)] == ["good", "next"]
    assert len(backend.calls) == 1
    assert backend.calls[0][2] == 3
    with pytest.raises(DataUnsupportedOperationError, match="pagination"):
        store.search_vectors([1.0], limit=2, options={"offset": 1})


def test_protected_writes_are_denied_before_backend_call():
    backend = Backend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    with pytest.raises(DataUnsupportedOperationError):
        store.upsert_documents([{"id": "x", "metadata": {"workspace": "a"}}])
    with pytest.raises(DataUnsupportedOperationError):
        store.delete_documents(ids=["x"])
    assert backend.calls == []


def test_atomic_write_checks_old_and_new_values_and_uses_version():
    class AtomicBackend(Backend):
        def policy_get_versioned(self, document_id):
            return ({"workspace": "a"}, (3, 1)) if document_id == "x" else None

        def policy_write_versioned(self, action, document_id, item, version):
            self.calls.append((action, document_id, version))

    backend = AtomicBackend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    assert store.upsert_documents([{"id": "x", "metadata": {"workspace": "a"}}]).written == 1
    assert store.upsert_documents([{"id": "new", "metadata": {"workspace": "a"}}]).written == 1
    assert store.delete_documents(ids=["x"]).deleted == 1
    assert backend.calls == [("upsert", "x", (3, 1)), ("upsert", "new", None), ("delete", "x", (3, 1))]
    with pytest.raises(DataPolicyDeniedError):
        store.upsert_documents([{"id": "x", "metadata": {"workspace": "b"}}])


def test_atomic_batch_reports_completed_and_failed_items():
    class AtomicBackend(Backend):
        def policy_get_versioned(self, document_id):
            return ({"workspace": "a"}, (3, 1))

        def policy_write_versioned(self, action, document_id, item, version):
            if document_id == "second":
                raise DataWriteConflictError("changed")
            self.calls.append(document_id)

    backend = AtomicBackend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    with pytest.raises(DataBatchWriteError) as error:
        store.upsert_documents([
            {"id": "first", "metadata": {"workspace": "a"}},
            {"id": "second", "metadata": {"workspace": "a"}},
            {"id": "third", "metadata": {"workspace": "a"}},
        ])
    assert error.value.completed_ids == ("first",)
    assert error.value.failed_id == "second"
    assert error.value.pending_ids == ("third",)
    assert isinstance(error.value.__cause__, DataWriteConflictError)
    assert backend.calls == ["first"]


def test_precheck_mode_checks_current_and_new_values_before_write():
    backend = Backend()
    backend.policy_get = lambda document_id: {"workspace": "a"} if document_id == "x" else {"workspace": "b"}
    policies = DataPolicyPipeline((Policy(),), non_atomic_mode=DataNonAtomicPolicyMode.ALLOW_PRECHECK)
    store = PolicySearchIndex(backend, "articles", policies=policies, context=DataOperationContext(attributes={"workspace": "a"}))
    store.upsert_documents([{"id": "x", "metadata": {"workspace": "a"}}])
    assert backend.calls == [("write", [{"id": "x", "metadata": {"workspace": "a"}}])]
    with pytest.raises(DataPolicyDeniedError):
        store.upsert_documents([{"id": "other", "metadata": {"workspace": "a"}}])
    with pytest.raises(DataPolicyDeniedError):
        store.upsert_documents([{"id": "x", "metadata": {"workspace": "b"}}])
    assert len(backend.calls) == 1
    with pytest.raises(DataPolicyDeniedError):
        store.delete_documents(ids=["other"])
    with pytest.raises(DataUnsupportedOperationError):
        store.delete_documents(filters={"kind": "note"})
    with pytest.raises(DataUnsupportedOperationError):
        store.upsert_documents([{"id": "x", "metadata": {"workspace": "a"}}], options={"routing": "other"})


def test_vector_precheck_uses_payload_not_irrelevant_metadata():
    backend = Backend()
    backend.policy_get = lambda document_id: {"workspace": "a"}
    policies = DataPolicyPipeline((Policy(),), non_atomic_mode=DataNonAtomicPolicyMode.ALLOW_PRECHECK)
    store = PolicyVectorSearch(backend, "vectors", policies=policies, context=DataOperationContext(attributes={"workspace": "a"}))
    with pytest.raises(DataPolicyDeniedError):
        store.upsert_vectors([{"id": "x", "metadata": {"workspace": "a"}, "payload": {"workspace": "b"}}])


def test_search_fails_closed_when_scan_limit_is_exhausted():
    backend = Backend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}), max_scan=2)
    with pytest.raises(DataUnsupportedOperationError, match="max_scan"):
        store.search_text("hello", limit=2)


def test_search_rejects_caller_pagination_when_policy_is_active():
    backend = Backend()
    store = PolicySearchIndex(backend, "articles", policies=DataPolicyPipeline((Policy(),)), context=DataOperationContext(attributes={"workspace": "a"}))
    with pytest.raises(DataUnsupportedOperationError, match="pagination"):
        store.search_text("hello", options={"from_": 20})
    assert not backend.calls


@pytest.mark.parametrize(("operator", "expected", "values", "accepted"), [
    (DataPredicateOperator.LIKE, "a_%", ["abc", "a", "Axx", ["abc"], None], ["abc"]),
    (DataPredicateOperator.LIKE, "a.b", ["a.b", "axb"], ["a.b"]),
    (DataPredicateOperator.IS_NULL, True, [None, "present", [None]], [None]),
    (DataPredicateOperator.IS_NULL, False, [None, "present", [None]], ["present"]),
])
def test_like_and_is_null_are_checked_on_original_values(operator, expected, values, accepted):
    class Policy:
        def evaluate(self, request):
            return DataPolicyDecision(predicates=(DataPredicate("field", operator, expected),))

    class ValuesBackend(Backend):
        def search_text(self, query, filters=None, limit=10, options=None):
            start = (options or {}).get("from_", 0)
            all_hits = [SearchHit(str(index), 1, metadata={"field": value}) for index, value in enumerate(values)]
            all_hits.append(SearchHit("missing", 1, metadata={}))
            return all_hits[start:start + limit]

    store = PolicySearchIndex(ValuesBackend(), "items", policies=DataPolicyPipeline((Policy(),)))
    assert [hit.metadata["field"] for hit in store.search_text("", limit=10)] == accepted


def test_like_and_null_reject_invalid_arguments():
    from muscles.data.policy_search import _policy_filters
    for predicate in (
        DataPredicate("field", DataPredicateOperator.LIKE, 42),
        DataPredicate("field", DataPredicateOperator.IS_NULL, None),
        DataPredicate("field", DataPredicateOperator.LIKE, "x" * 257),
    ):
        with pytest.raises(DataUnsupportedOperationError):
            _policy_filters((predicate,))


@pytest.mark.parametrize(("operator", "value", "current", "replacement"), [
    (DataPredicateOperator.LIKE, "a_%", "abc", "abcd"),
    (DataPredicateOperator.IS_NULL, True, None, None),
    (DataPredicateOperator.IS_NULL, False, "existing", "replacement"),
])
def test_precheck_validates_like_and_null_on_current_and_replacement(operator, value, current, replacement):
    class Policy:
        def evaluate(self, request):
            return DataPolicyDecision(predicates=(DataPredicate("field", operator, value),))

    backend = Backend()
    backend.policy_get = lambda document_id: {"field": current}
    store = PolicySearchIndex(backend, "items", policies=DataPolicyPipeline(
        (Policy(),), non_atomic_mode=DataNonAtomicPolicyMode.ALLOW_PRECHECK,
    ))
    store.upsert_documents([{"id": "x", "metadata": {"field": replacement}}])
    assert len(backend.calls) == 1
    backend.policy_get = lambda document_id: {}
    with pytest.raises(DataPolicyDeniedError):
        store.upsert_documents([{"id": "x", "metadata": {"field": replacement}}])


@pytest.mark.parametrize(("operator", "value", "expected"), [
    (DataPredicateOperator.GT, 3, {"score": {"gt": 3}}),
    (DataPredicateOperator.GTE, 3, {"score": {"gte": 3}}),
    (DataPredicateOperator.LT, 3, {"score": {"lt": 3}}),
    (DataPredicateOperator.LTE, 3, {"score": {"lte": 3}}),
    (DataPredicateOperator.IN, [2, 3], {"score": {"any": [2, 3]}}),
    (DataPredicateOperator.NE, 3, {"$not": {"score": 3}}),
])
def test_policy_search_translates_supported_predicates(operator, value, expected):
    class ScorePolicy:
        def evaluate(self, request):
            return DataPolicyDecision(predicates=(DataPredicate("score", operator, value),))

    class ScoreBackend(Backend):
        def search_text(self, query, filters=None, limit=10, options=None):
            self.calls.append((filters, limit))
            return [] if (options or {}).get("from_", 0) else [SearchHit("one", 1, metadata={"score": 3})]

    backend = ScoreBackend()
    store = PolicySearchIndex(backend, "scores", policies=DataPolicyPipeline((ScorePolicy(),)))
    hits = store.search_text("test", limit=1)
    assert [item.id for item in hits] == (["one"] if operator in (DataPredicateOperator.GTE, DataPredicateOperator.LTE, DataPredicateOperator.IN) else [])
    assert backend.calls[0][0]["$and"][-1] == expected
