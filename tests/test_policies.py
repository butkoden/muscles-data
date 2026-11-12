import pytest

from muscles.data.errors import DataPolicyDeniedError
from muscles.data.policies import (
    DataOperationContext, DataOperationKind, DataOperationRequest,
    DataPolicyDecision, DataPolicyPipeline, DataPredicate, DataPredicateOperator,
)
from muscles.data.runtime import DataRuntime
from muscles.data.config import DataConfig


def test_pipeline_combines_constraints_and_stops_on_denial():
    calls = []

    class Policy:
        def __init__(self, name, allowed=True):
            self.name, self.allowed = name, allowed

        def evaluate(self, operation):
            calls.append((self.name, operation.context.subject_uid))
            return DataPolicyDecision(allowed=self.allowed, predicates=(
                DataPredicate(self.name, DataPredicateOperator.EQ, self.name),
            ))

    operation = DataOperationRequest(DataOperationKind.READ, "items", DataOperationContext(subject_uid="user"))
    pipeline = DataPolicyPipeline((Policy("first"), Policy("second")))
    assert [item.field for item in pipeline.evaluate(operation)] == ["first", "second"]
    pipeline.register(Policy("deny", False))
    pipeline.register(Policy("never"))
    with pytest.raises(DataPolicyDeniedError):
        pipeline.evaluate(operation)
    assert calls[-1] == ("deny", "user")


def test_runtime_exposes_pipeline_and_explain_hides_values():
    class Policy:
        def evaluate(self, operation):
            return DataPolicyDecision(predicates=(DataPredicate("workspace", DataPredicateOperator.EQ, "secret"),))

    runtime = DataRuntime(config=DataConfig.from_raw({}))
    runtime.policies.register(Policy())
    operation = DataOperationRequest(DataOperationKind.READ, "items", filters=(
        DataPredicate("name", DataPredicateOperator.EQ, "private"),
    ))
    description = runtime.policies.explain(operation)
    assert [item["field"] for item in description["filters"]] == ["name", "workspace"]
    assert "private" not in str(description) and "secret" not in str(description)


def test_pipeline_rejects_invalid_policy_decisions_fail_closed():
    class Policy:
        def __init__(self, decision):
            self.decision = decision

        def evaluate(self, operation):
            return self.decision

    operation = DataOperationRequest(DataOperationKind.READ, "items")
    for decision in (DataPolicyDecision(allowed="false"), DataPolicyDecision(predicates=("not a predicate",))):
        with pytest.raises(TypeError):
            DataPolicyPipeline((Policy(decision),)).evaluate(operation)


def test_explicit_ownership_scope_requires_a_constraint_and_preserves_other_policies():
    class Policy:
        def __init__(self, decision):
            self.decision = decision
        def evaluate(self, operation):
            return self.decision

    operation = DataOperationRequest(DataOperationKind.READ, "items")
    constraint = DataPredicate("team", DataPredicateOperator.EQ, "one")
    pipeline = DataPolicyPipeline((Policy(DataPolicyDecision(predicates=(constraint,), replaces_owner_scope=True)),
                                   Policy(DataPolicyDecision(predicates=(DataPredicate("active", DataPredicateOperator.EQ, True),)))))
    decision = pipeline.evaluate_decision(operation)
    assert decision.replaces_owner_scope is True
    assert len(decision.predicates) == 2
    assert pipeline.evaluate(operation) == decision.predicates
    with pytest.raises(ValueError, match="constraint"):
        DataPolicyPipeline((Policy(DataPolicyDecision(replaces_owner_scope=True)),)).evaluate_decision(operation)
    with pytest.raises(TypeError):
        DataPolicyPipeline((Policy(DataPolicyDecision(replaces_owner_scope="yes", predicates=(constraint,))),)).evaluate_decision(operation)
    assert not DataPolicyPipeline().evaluate_decision(operation).replaces_owner_scope
    with pytest.raises(DataPolicyDeniedError):
        DataPolicyPipeline((Policy(DataPolicyDecision(predicates=(constraint,), replaces_owner_scope=True)),
                            Policy(DataPolicyDecision(allowed=False)))).evaluate_decision(operation)


def test_non_atomic_policy_mode_is_explicit_and_defaults_to_deny():
    from muscles.data.errors import DataUnsupportedOperationError
    from muscles.data.policies import DataNonAtomicPolicyMode

    strict = DataPolicyPipeline()
    with pytest.raises(DataUnsupportedOperationError):
        strict.require_atomic_write(atomic=False)
    strict.require_atomic_write(atomic=True)
    permissive = DataPolicyPipeline(non_atomic_mode=DataNonAtomicPolicyMode.ALLOW_PRECHECK)
    permissive.require_atomic_write(atomic=False)
    with pytest.raises(TypeError):
        DataPolicyPipeline(non_atomic_mode="allow_precheck")
    with pytest.raises(AttributeError):
        strict.non_atomic_mode = DataNonAtomicPolicyMode.ALLOW_PRECHECK
