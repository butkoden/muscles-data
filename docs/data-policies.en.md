# Data policies and object lifecycle events

This guide describes `muscles-data` contracts for restricting access to objects and adding behavior without coupling packages. The library has no built-in concept of users, workspaces, or database schemas; the application supplies those meanings.

## How the pieces fit

1. The application authenticates the user and verifies access to the selected data scope.
2. Each request receives a `DataOperationContext` containing the subject and trusted scope attributes.
3. A package declares its stable object type in the shared `DataRuntime`.
4. An independent module registers a policy and, when needed, creation and deletion handlers.
5. A repository that supports those contracts enforces them during the operation.

**Important:** a context and a registered policy do not protect raw database access on their own. Protection requires an adapter that actually applies the policy. An empty `DataPolicyPipeline` does not restrict access. Authentication, scope membership checks, and creation of trusted request context are the application's responsibility.

## Request context and object type

```python
from muscles.data.policies import DataOperationContext

# The subject and scope come from a verified session; the application has
# already checked that the subject may use this scope.
context = DataOperationContext(
    subject_type="user",
    subject_uid="user-1",
    attributes={"scope_id": "scope-1"},
)

# At package installation time; runtime is the application's shared DataRuntime.
runtime.register_object_type("documents", "demo:document", owner_field="owner_uid")
```

`attributes` is an immutable mapping; create a new context for each request. Do not store the current scope in global `DataRuntime` state or trust a scope ID merely because it was supplied over HTTP. `target` identifies an adapter resource or table, while `object_type` is a stable domain type. `owner_field` is metadata for composition and migrations; it does not automatically enforce ownership.

Inspect declarations with `runtime.object_type_for_target("documents")` or `runtime.registered_object_types()`. A conflicting re-registration raises `ValueError`.

## A policy backed by a link table

A policy receives a `DataOperationRequest` with `kind`, `target`, `context`, `filters`, `values`, and an optional `object_type`. Return a `DataPolicyDecision` with mandatory predicates or an explicit denial. Multiple policies combine restrictions with **AND**; any denial raises `DataPolicyDeniedError`.

```python
from muscles.data.policies import (
    DataOperationKind, DataPolicyDecision, DataPredicate,
    DataPredicateOperator, DataRelatedExists,
)

class ScopePolicy:
    def evaluate(self, operation):
        if operation.object_type != "demo:document":
            return DataPolicyDecision()  # This module does not own other types.
        scope = operation.context.attributes.get("scope_id")
        if not operation.context.subject_uid or not scope:
            return DataPolicyDecision(allowed=False, reason="An authorized scope is required")
        if operation.kind is DataOperationKind.UPSERT:
            return DataPolicyDecision(allowed=False, reason="Use create or update")
        if operation.kind is DataOperationKind.CREATE:
            return DataPolicyDecision()  # The link is created after the object.
        return DataPolicyDecision(predicates=(DataPredicate(
            "uid", DataPredicateOperator.RELATED_EXISTS,
            DataRelatedExists("scope_links", "object_uid", {
                "scope_id": scope, "object_type": "demo:document",
            }),
        ),))

runtime.policies.register(ScopePolicy())
```

`RELATED_EXISTS` requires the object's `uid` to match `object_uid` in `scope_links`, with the remaining link fields matching the supplied filters. An object may have several links to different scopes. The table, its indexes, and verification that the subject can use the scope are application responsibilities.

A future link cannot be required on `CREATE`: it does not exist yet. Validate the scalar values of a new object as needed and create its link through a lifecycle event in the same transaction. This example denies `UPSERT`: the SQL adapter also checks upsert predicates on the create branch, where `RELATED_EXISTS` is unsupported. If a module is disabled, its missing policy does **not** automatically restrict access to the owner. Register an owner policy or another mandatory control separately.

`DataPolicyDecision.replaces_owner_scope` explicitly tells an adapter that separately implements owner restriction that the policy is authorized to replace it. The flag does not filter data by itself, and the pipeline requires at least one accompanying predicate. `NativePolicyRepository` does not add an owner restriction automatically.

### Diagnostics and non-atomic writes

`runtime.policies.explain(operation)` evaluates the policy and returns the operation type, target, and field names with operators, without predicate values. An explicit denial still raises `DataPolicyDeniedError`; an explanation does not execute an operation or replace adapter enforcement.

For adapters that call `DataPolicyPipeline.require_atomic_write`, the default mode denies a protected write when its condition cannot be enforced atomically. `DataNonAtomicPolicyMode.ALLOW_PRECHECK` explicitly relaxes this: data can change between a precheck and a write. Enable it only when the application accepts that risk; the flag does not make an arbitrary adapter atomic or replace a transaction.

## Transactional object events

`runtime.object_lifecycle` synchronously dispatches `ObjectLifecycleEvent`: action `created` or `deleted`, object type and ID, and operation context. A participating adapter invokes handlers **inside the write transaction**. Several independent modules can handle the same object.

```python
def on_object_change(transaction, event):
    if event.object_type != "demo:document":
        return
    if event.action == "created":
        # INSERT a link using event.object_uid and
        # event.context.attributes["scope_id"] on this same transaction.
        ...
    elif event.action == "deleted":
        # DELETE all links for (event.object_type, event.object_uid).
        ...

runtime.object_lifecycle.register(on_object_change)
```

An exception from a handler aborts the transaction: neither the object nor its associated writes should be committed. Do not open a separate transaction to write the link. Filter handlers by object type and parameterize SQL. Deleting a missing object does not emit an event. Reads and updates do not emit lifecycle events; `upsert` emits a creation event only on insertion. These guarantees apply to an adapter that actually invokes `emit_object_event`.

This is not `EventPublisherPort` or a message queue: the event is not delivered asynchronously or persisted as a journal, and handlers should not make network calls. External delivery requires a separate reliable design, such as an application-owned outbox.

## Verification and boundaries

- Use trusted request context for every operation and create appropriate database constraints and indexes.
- Check access to **both** objects before creating a relationship.
- Verify that lists, pagination, aggregates, joined records, and writes enforce policies before returning or modifying data.
- Test denial from another scope and rollback when a handler fails.
- If the module registering a policy is disabled, provide a separate owner policy: an empty pipeline is open.
- Existing objects and links are not migrated automatically. The application owns the migration and module rollout order.

For a runnable SQL example and commands, see the `muscles-data-sql` guide `docs/data-policies.en.md`. Other storage adapters support only the capabilities they explicitly implement.
