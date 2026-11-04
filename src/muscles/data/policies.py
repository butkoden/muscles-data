"""Backend-neutral policy contracts for controlled data operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .errors import DataPolicyDeniedError, DataUnsupportedOperationError
import re


class DataOperationKind(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    UPSERT = "upsert"


class DataNonAtomicPolicyMode(str, Enum):
    """How a policy-aware adapter handles a non-atomic protected write."""

    DENY = "deny"
    ALLOW_PRECHECK = "allow_precheck"


class DataPredicateOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    LIKE = "like"
    IS_NULL = "is_null"


def like_regex_body(pattern: str) -> str:
    """Translate the portable, case-sensitive LIKE subset to a regex body."""
    if not isinstance(pattern, str) or len(pattern) > 256:
        raise DataUnsupportedOperationError("LIKE requires a string pattern of at most 256 characters")
    parts = []
    for char in pattern:
        if char == "%":
            if not parts or parts[-1] != ".*":
                parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


def like_matches(value: object, pattern: str) -> bool:
    """Match LIKE without executing an untrusted backtracking regex locally."""
    like_regex_body(pattern)  # validate consistently with backend translation
    if not isinstance(value, str):
        return False
    text_index = pattern_index = 0
    star = -1
    retry = 0
    while text_index < len(value):
        if pattern_index < len(pattern) and (pattern[pattern_index] == "_" or pattern[pattern_index] == value[text_index] and pattern[pattern_index] != "%"):
            text_index += 1
            pattern_index += 1
        elif pattern_index < len(pattern) and pattern[pattern_index] == "%":
            star = pattern_index
            pattern_index += 1
            retry = text_index
        elif star >= 0:
            retry += 1
            text_index = retry
            pattern_index = star + 1
        else:
            return False
    return all(char == "%" for char in pattern[pattern_index:])


@dataclass(frozen=True)
class DataOperationContext:
    """Request-scoped identity and attributes consumed by data policies.

    ``attributes`` deliberately has no framework-specific keys. Applications
    may carry identity, workspace, authorization or other request context
    without making data adapters depend on those concepts.
    """

    subject_type: str | None = None
    subject_uid: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True)
class DataPredicate:
    """A portable field predicate that adapters translate to native queries."""

    field: str
    operator: DataPredicateOperator
    value: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.operator, DataPredicateOperator):
            raise TypeError("DataPredicate.operator must be a DataPredicateOperator")


@dataclass(frozen=True)
class DataOperationRequest:
    """Description of one operation before it reaches a storage adapter."""

    kind: DataOperationKind
    target: str
    context: DataOperationContext = field(default_factory=DataOperationContext)
    filters: tuple[DataPredicate, ...] = ()
    values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filters", tuple(self.filters))
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class DataPolicyDecision:
    """Additional mandatory constraints or an explicit denial."""

    allowed: bool = True
    predicates: tuple[DataPredicate, ...] = ()
    reason: str | None = None


class DataOperationPolicy(Protocol):
    """Policy implementation shared by data resources and adapters."""

    def evaluate(self, operation: DataOperationRequest) -> DataPolicyDecision: ...


class DataPolicyPipeline:
    """Combines policies as an ordered, fail-closed constraint pipeline."""

    def __init__(self, policies: tuple[DataOperationPolicy, ...] = (), *,
                 non_atomic_mode: DataNonAtomicPolicyMode = DataNonAtomicPolicyMode.DENY) -> None:
        if not isinstance(non_atomic_mode, DataNonAtomicPolicyMode):
            raise TypeError("non_atomic_mode must be a DataNonAtomicPolicyMode")
        self._policies: list[DataOperationPolicy] = list(policies)
        self._non_atomic_mode = non_atomic_mode

    @property
    def non_atomic_mode(self) -> DataNonAtomicPolicyMode:
        return self._non_atomic_mode

    def require_atomic_write(self, *, atomic: bool) -> None:
        """Gate a protected write; an allowed precheck remains the adapter's responsibility."""
        if not isinstance(atomic, bool):
            raise TypeError("atomic must be a bool")
        if not atomic and self.non_atomic_mode is not DataNonAtomicPolicyMode.ALLOW_PRECHECK:
            raise DataUnsupportedOperationError("Policy constraints cannot be enforced atomically")

    def register(self, policy: DataOperationPolicy) -> None:
        if not callable(getattr(policy, "evaluate", None)):
            raise TypeError("A data policy must implement evaluate(operation)")
        self._policies.append(policy)

    def evaluate(self, operation: DataOperationRequest) -> tuple[DataPredicate, ...]:
        predicates: list[DataPredicate] = []
        for policy in self._policies:
            decision = policy.evaluate(operation)
            if not isinstance(decision, DataPolicyDecision):
                raise TypeError("Data policies must return DataPolicyDecision")
            if not isinstance(decision.allowed, bool):
                raise TypeError("DataPolicyDecision.allowed must be a bool")
            if not decision.allowed:
                raise DataPolicyDeniedError(
                    decision.reason or f"Data operation '{operation.kind.value}' was denied"
                )
            for predicate in decision.predicates:
                if not isinstance(predicate, DataPredicate):
                    raise TypeError("Policy predicates must be DataPredicate instances")
                predicates.append(predicate)
        return tuple(predicates)

    def explain(self, operation: DataOperationRequest) -> dict[str, Any]:
        """Summarize effective constraints without exposing predicate values."""
        predicates = self.evaluate(operation)
        return {
            "operation": operation.kind.value,
            "target": operation.target,
            "filters": tuple(
                {"field": item.field, "operator": item.operator}
                for item in (*operation.filters, *predicates)
            ),
        }
