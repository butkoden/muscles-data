"""Explicit policy-aware wrappers for search and vector ports.

Backend adapters and native clients remain unprotected when used directly.
"""

from collections.abc import Mapping

from .errors import DataBatchWriteError, DataPolicyDeniedError, DataUnsupportedOperationError
from .models import WriteResult
from .policies import DataOperationContext, DataOperationKind, DataOperationRequest, DataPredicate, DataPredicateOperator, like_matches, like_regex_body


def _field(field):
    if not isinstance(field, str) or not field or field.startswith("$") or "." in field:
        raise DataUnsupportedOperationError("Policy search requires simple field names")
    return field


def _scalar(value):
    return type(value) in (str, int, bool)


def _user_filters(filters):
    values = dict(filters or {})
    for field, value in values.items():
        _field(field)
        if not _scalar(value):
            raise DataUnsupportedOperationError("Policy search supports scalar equality filters only")
    return tuple(DataPredicate(field, DataPredicateOperator.EQ, value) for field, value in values.items())


def _policy_filters(predicates):
    filters = []
    for predicate in predicates:
        field = _field(predicate.field)
        if predicate.operator is DataPredicateOperator.EQ and _scalar(predicate.value):
            filters.append({field: predicate.value})
        elif predicate.operator is DataPredicateOperator.NE and _scalar(predicate.value):
            filters.append({"$not": {field: predicate.value}})
        elif predicate.operator in (DataPredicateOperator.GT, DataPredicateOperator.GTE, DataPredicateOperator.LT, DataPredicateOperator.LTE) and type(predicate.value) is int:
            filters.append({field: {predicate.operator.value: predicate.value}})
        elif predicate.operator is DataPredicateOperator.IN and isinstance(predicate.value, (list, tuple)) and predicate.value and all(_scalar(value) and type(value) is type(predicate.value[0]) for value in predicate.value):
            filters.append({field: {"any": list(predicate.value)}})
        elif predicate.operator is DataPredicateOperator.LIKE:
            like_regex_body(predicate.value)
        elif predicate.operator is DataPredicateOperator.IS_NULL and type(predicate.value) is bool:
            pass
        else:
            raise DataUnsupportedOperationError("Unsupported policy search predicate or value")
    return filters


def _matches(values, predicates):
    if not isinstance(values, Mapping):
        return False
    for item in predicates:
        if item.field not in values:
            return False
        actual = values.get(item.field)
        expected = item.value
        if item.operator is DataPredicateOperator.LIKE:
            if not like_matches(actual, expected):
                return False
        elif item.operator is DataPredicateOperator.IS_NULL:
            if isinstance(actual, (list, tuple, set)) or (actual is None) is not expected:
                return False
        elif item.operator is DataPredicateOperator.IN:
            if not any(type(actual) is type(value) and actual == value for value in expected):
                return False
        elif type(actual) is not type(expected):
            return False
        elif item.operator is DataPredicateOperator.EQ and actual != expected:
            return False
        elif item.operator is DataPredicateOperator.NE and actual == expected:
            return False
        elif item.operator is DataPredicateOperator.GT and actual <= expected:
            return False
        elif item.operator is DataPredicateOperator.GTE and actual < expected:
            return False
        elif item.operator is DataPredicateOperator.LT and actual >= expected:
            return False
        elif item.operator is DataPredicateOperator.LTE and actual > expected:
            return False
    return True


class _PolicySearch:
    def __init__(self, adapter, target: str, *, policies, context=None, max_scan=10000):
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a nonempty resource name")
        self.adapter, self.target, self.policies = adapter, target, policies
        self.context = context or DataOperationContext()
        if type(max_scan) is not int or max_scan <= 0:
            raise ValueError("max_scan must be a positive integer")
        self.max_scan = max_scan

    def _evaluate(self, kind, filters=(), values=None):
        return self.policies.evaluate(DataOperationRequest(kind, self.target, self.context, filters, values or {}))

    def _item_values(self, values):
        payload = dict(values.get("payload") or {})
        payload.update(dict(values.get("metadata") or {}))
        return payload

    def _search_filters(self, filters):
        requested = _user_filters(filters)
        predicates = self._evaluate(DataOperationKind.READ, requested)
        additions = _policy_filters(predicates)
        if not additions:
            return filters, predicates
        return {"$and": [dict(filters or {}), *additions]}, predicates

    def _check_writes(self, kind, *, items=(), filters=None, ids=None, options=None):
        if ids is not None and filters:
            raise DataUnsupportedOperationError("Combining ids and filters is not supported by protected writes")
        requested = _user_filters(filters)
        if ids is not None:
            requested += (DataPredicate("id", DataPredicateOperator.IN, tuple(ids)),)
        checked = []
        for values in items or ({},):
            predicates = self._evaluate(kind, requested, values)
            if predicates:
                self.policies.require_atomic_write(atomic=False)
                _policy_filters(predicates)
                if options:
                    raise DataUnsupportedOperationError("Prechecked writes do not support backend options")
                get_current = getattr(self.adapter, "policy_get", None)
                if not callable(get_current):
                    raise DataUnsupportedOperationError("Backend does not support policy prechecks")
                if kind is DataOperationKind.UPSERT:
                    if "id" not in values or values.get("fields"):
                        raise DataUnsupportedOperationError("Prechecked upsert requires an id and does not support fields")
                    document_id = str(values["id"])
                    payload = self._item_values(values)
                    if not _matches(payload, predicates):
                        raise DataPolicyDeniedError("New values do not satisfy policy")
                    checked.append((document_id, predicates, True))
                else:
                    if ids is None:
                        raise DataUnsupportedOperationError("Prechecked delete requires explicit ids")
                    checked.extend((str(document_id), predicates, False) for document_id in ids)
        for document_id, predicates, may_create in checked:
            current = self.adapter.policy_get(document_id)
            if current is None and may_create:
                continue
            if current is None or not _matches(current, predicates):
                raise DataPolicyDeniedError("Existing values do not satisfy policy")

    def _collect(self, fetch, predicates, limit, options, offset_key, value_field):
        if type(limit) is not int or limit < 0 or limit > self.max_scan:
            raise ValueError("limit must be a nonnegative integer no greater than max_scan")
        if offset_key in options or "search_after" in options:
            raise DataUnsupportedOperationError("Policy search controls pagination internally")
        results, seen, offset = [], set(), 0
        while len(results) < limit:
            if offset >= self.max_scan:
                raise DataUnsupportedOperationError("Policy search exceeded max_scan before filling the result")
            size = min(limit - len(results), self.max_scan - offset)
            batch = fetch(size, {**options, offset_key: offset})
            if len(batch) > size:
                raise DataUnsupportedOperationError("Backend returned more results than requested")
            for hit in batch:
                if hit.id in seen:
                    raise DataUnsupportedOperationError("Backend pagination returned duplicate results")
                seen.add(hit.id)
                if _matches(getattr(hit, value_field), predicates):
                    results.append(hit)
            offset += len(batch)
            if len(batch) < size:
                break
        return results


class PolicySearchIndex(_PolicySearch):
    def _atomic_documents(self, kind, *, items=None, ids=None, filters=None, options=None):
        get_version = getattr(self.adapter, "policy_get_versioned", None)
        write_version = getattr(self.adapter, "policy_write_versioned", None)
        if not callable(get_version) or not callable(write_version):
            return None
        if ids is not None and filters:
            raise DataUnsupportedOperationError("Combining ids and filters is not supported by protected writes")
        requested = _user_filters(filters)
        if ids is not None:
            requested += (DataPredicate("id", DataPredicateOperator.IN, tuple(ids)),)
        entries = list(items) if items is not None else [None] if ids is None else list(ids)
        evaluated = []
        for entry in entries:
            values = entry if kind is DataOperationKind.UPSERT else {}
            predicates = self._evaluate(kind, requested, values)
            evaluated.append((entry, predicates))
        if not any(predicates for _, predicates in evaluated):
            if kind is DataOperationKind.UPSERT:
                return self.adapter.upsert_documents(items, options=options)
            return self.adapter.delete_documents(ids=ids, filters=filters, options=options)
        if options or (kind is DataOperationKind.DELETE and ids is None):
            raise DataUnsupportedOperationError("Atomic protected writes require ids and do not support backend options")
        staged, seen = [], set()
        for entry, predicates in evaluated:
            if kind is DataOperationKind.UPSERT:
                if "id" not in entry or entry.get("fields"):
                    raise DataUnsupportedOperationError("Atomic upsert requires an id and does not support fields")
                document_id = str(entry["id"])
                _policy_filters(predicates)
                if predicates and not _matches(self._item_values(entry), predicates):
                    raise DataPolicyDeniedError("New values do not satisfy policy")
            else:
                document_id = str(entry)
                _policy_filters(predicates)
            if document_id in seen:
                raise DataUnsupportedOperationError("Duplicate ids are not supported by atomic protected writes")
            seen.add(document_id)
            current = get_version(document_id)
            if current is None:
                if kind is DataOperationKind.DELETE:
                    raise DataPolicyDeniedError("Existing values do not satisfy policy")
                version = None
            else:
                values, version = current
                if predicates and not _matches(values, predicates):
                    raise DataPolicyDeniedError("Existing values do not satisfy policy")
            staged.append((document_id, entry, version))
        action = "upsert" if kind is DataOperationKind.UPSERT else "delete"
        completed = []
        for index, (document_id, entry, version) in enumerate(staged):
            try:
                write_version(action, document_id, entry if items is not None else None, version)
            except Exception as exc:
                if not completed:
                    raise
                raise DataBatchWriteError(
                    completed_ids=tuple(completed), failed_id=document_id,
                    pending_ids=tuple(item[0] for item in staged[index + 1:]),
                ) from exc
            completed.append(document_id)
        return WriteResult(written=len(staged), matched=len(staged)) if items is not None else WriteResult(deleted=len(staged), matched=len(staged))

    def search_text(self, query, filters=None, limit=10, options=None):
        effective, predicates = self._search_filters(filters)
        if not predicates:
            return self.adapter.search_text(query, filters=effective, limit=limit, options=options)
        snapshot = getattr(self.adapter, "policy_search_snapshot", None)
        if callable(snapshot):
            if type(limit) is not int or limit < 0 or limit > self.max_scan:
                raise ValueError("limit must be a nonnegative integer no greater than max_scan")
            if not limit:
                return []
            selected, seen = [], set()
            iterator = snapshot(query, effective, min(limit, 1000), dict(options or {}))
            try:
                for hit in iterator:
                    if len(seen) >= self.max_scan:
                        raise DataUnsupportedOperationError("Policy search exceeded max_scan before filling the result")
                    if hit.id in seen:
                        raise DataUnsupportedOperationError("Backend snapshot returned duplicate results")
                    seen.add(hit.id)
                    if _matches(hit.metadata, predicates):
                        selected.append(hit)
                        if len(selected) == limit:
                            break
            finally:
                iterator.close()
            return selected
        return self._collect(lambda size, opts: self.adapter.search_text(query, filters=effective, limit=size, options=opts),
                             predicates, limit, dict(options or {}), "from_", "metadata")

    def upsert_documents(self, items, options=None):
        result = self._atomic_documents(DataOperationKind.UPSERT, items=items, options=options)
        if result is not None:
            return result
        self._check_writes(DataOperationKind.UPSERT, items=items, options=options)
        return self.adapter.upsert_documents(items, options=options)

    def delete_documents(self, ids=None, filters=None, options=None):
        result = self._atomic_documents(DataOperationKind.DELETE, ids=ids, filters=filters, options=options)
        if result is not None:
            return result
        self._check_writes(DataOperationKind.DELETE, filters=filters, ids=ids, options=options)
        return self.adapter.delete_documents(ids=ids, filters=filters, options=options)


class PolicyVectorSearch(_PolicySearch):
    def _item_values(self, values):
        return dict(values.get("payload") or {})

    def confirm_upsert(self, document_id: str, operation_id: str) -> bool | None:
        confirm = getattr(self.adapter, "policy_confirm_upsert", None)
        if not callable(confirm):
            raise DataUnsupportedOperationError("Backend cannot confirm a policy write")
        return confirm(document_id, operation_id)

    def confirm_delete(self, document_id: str, operation_id: str) -> bool | None:
        confirm = getattr(self.adapter, "policy_confirm_delete", None)
        if not callable(confirm):
            raise DataUnsupportedOperationError("Backend cannot confirm a policy deletion")
        return confirm(document_id, operation_id)

    def reconcile_pending(self) -> list[dict]:
        reconcile = getattr(self.adapter, "policy_reconcile_pending", None)
        if not callable(reconcile):
            raise DataUnsupportedOperationError("Backend cannot reconcile pending writes")
        return reconcile()

    def adopt_existing(self, document_id: str, *, expected_fields: Mapping, maintenance_confirmed: bool) -> None:
        """Attach a policy marker during a maintenance window with writers stopped."""
        if maintenance_confirmed is not True:
            raise DataUnsupportedOperationError("Adoption requires a maintenance window with writers stopped")
        if not isinstance(expected_fields, Mapping) or not expected_fields:
            raise ValueError("Adoption requires nonempty expected fields")
        fields = dict(expected_fields)
        for field, value in fields.items():
            _field(field)
            if value is not None and not _scalar(value):
                raise DataUnsupportedOperationError("Adoption accepts scalar expected fields only")
        supported = getattr(self.adapter, "policy_atomic_supported", None)
        adopt = getattr(self.adapter, "policy_adopt_existing", None)
        get_current = getattr(self.adapter, "policy_get", None)
        if not callable(supported) or not callable(adopt) or not callable(get_current) or not supported():
            raise DataUnsupportedOperationError("Backend does not support managed adoption")
        current = get_current(str(document_id))
        if current is None or any(field not in current or type(current[field]) is not type(value) or current[field] != value for field, value in fields.items()):
            raise DataPolicyDeniedError("Existing values do not match the adoption snapshot")
        requested = tuple(DataPredicate(field, DataPredicateOperator.EQ, value) for field, value in fields.items())
        predicates = self._evaluate(DataOperationKind.UPDATE, requested)
        _policy_filters(predicates)
        if predicates and not _matches(current, predicates):
            raise DataPolicyDeniedError("Existing values do not satisfy policy")
        for predicate in predicates:
            fields[predicate.field] = current[predicate.field]
        adopt(str(document_id), fields)

    def search_vectors(self, vector, filters=None, limit=10, options=None):
        effective, predicates = self._search_filters(filters)
        options = dict(options or {})
        if predicates:
            if options.get("with_payload", True) is not True:
                raise DataUnsupportedOperationError("Policy vector search requires full payload")
            options["with_payload"] = True
        if not predicates:
            return self.adapter.search_vectors(vector, filters=effective, limit=limit, options=options)
        if type(limit) is not int or limit < 0 or limit > self.max_scan:
            raise ValueError("limit must be a nonnegative integer no greater than max_scan")
        if "offset" in options:
            raise DataUnsupportedOperationError("Policy search controls pagination internally")
        if not limit:
            return []
        candidates = self.adapter.search_vectors(vector, filters=effective, limit=self.max_scan, options=options)
        if len(candidates) > self.max_scan:
            raise DataUnsupportedOperationError("Backend returned more results than requested")
        seen, results = set(), []
        for hit in candidates:
            if hit.id in seen:
                raise DataUnsupportedOperationError("Backend returned duplicate vector results")
            seen.add(hit.id)
            if _matches(hit.payload, predicates):
                results.append(hit)
                if len(results) == limit:
                    return results
        if len(candidates) == self.max_scan:
            raise DataUnsupportedOperationError("Policy search exceeded max_scan before filling the result")
        return results

    def upsert_vectors(self, items, options=None):
        supported = getattr(self.adapter, "policy_atomic_supported", None)
        if callable(supported) and callable(getattr(self.adapter, "policy_get_atomic", None)) and callable(getattr(self.adapter, "policy_atomic_upsert", None)):
            evaluated = [(item, self._evaluate(DataOperationKind.UPSERT, values=item)) for item in items]
            if not any(predicates for _, predicates in evaluated):
                return self.adapter.upsert_vectors(items, options=options)
            if supported():
                if options:
                    raise DataUnsupportedOperationError("Atomic protected writes do not support backend options")
                staged, seen = [], set()
                for item, predicates in evaluated:
                    if "id" not in item or item.get("fields"):
                        raise DataUnsupportedOperationError("Atomic upsert requires an id and does not support fields")
                    document_id = str(item["id"])
                    if document_id in seen:
                        raise DataUnsupportedOperationError("Duplicate ids are not supported by atomic protected writes")
                    seen.add(document_id)
                    _policy_filters(predicates)
                    if predicates and not _matches(self._item_values(item), predicates):
                        raise DataPolicyDeniedError("New values do not satisfy policy")
                    current = self.adapter.policy_get_atomic(document_id)
                    if current is None:
                        marker = None
                        expected = {}
                    else:
                        values, marker = current
                        if predicates and not _matches(values, predicates):
                            raise DataPolicyDeniedError("Existing values do not satisfy policy")
                        expected = {predicate.field: values[predicate.field] for predicate in predicates}
                    staged.append((document_id, item, marker, expected))
                completed = []
                for index, (document_id, item, marker, expected) in enumerate(staged):
                    try:
                        self.adapter.policy_atomic_upsert(item, marker, expected)
                    except Exception as exc:
                        if not completed:
                            raise
                        raise DataBatchWriteError(completed_ids=tuple(completed), failed_id=document_id,
                                                  pending_ids=tuple(entry[0] for entry in staged[index + 1:])) from exc
                    completed.append(document_id)
                return WriteResult(written=len(staged), matched=len(staged))
        self._check_writes(DataOperationKind.UPSERT, items=items, options=options)
        return self.adapter.upsert_vectors(items, options=options)

    def delete_vectors(self, ids=None, filters=None, options=None):
        supported = getattr(self.adapter, "policy_atomic_supported", None)
        delete = getattr(self.adapter, "policy_atomic_delete", None)
        get_current = getattr(self.adapter, "policy_get_atomic", None)
        if callable(supported) and callable(delete) and callable(get_current):
            if ids is not None and filters:
                raise DataUnsupportedOperationError("Combining ids and filters is not supported by protected writes")
            requested = _user_filters(filters)
            if ids is not None:
                requested += (DataPredicate("id", DataPredicateOperator.IN, tuple(ids)),)
            predicates = self._evaluate(DataOperationKind.DELETE, requested)
            if not predicates:
                return self.adapter.delete_vectors(ids=ids, filters=filters, options=options)
            if supported():
                if ids is None or options:
                    raise DataUnsupportedOperationError("Atomic protected deletion requires ids and no backend options")
                _policy_filters(predicates)
                staged, seen = [], set()
                for item_id in ids:
                    document_id = str(item_id)
                    if document_id in seen:
                        raise DataUnsupportedOperationError("Duplicate ids are not supported by protected writes")
                    seen.add(document_id)
                    current = get_current(document_id)
                    if current is None or not _matches(current[0], predicates):
                        raise DataPolicyDeniedError("Existing values do not satisfy policy")
                    values, marker = current
                    staged.append((document_id, marker, {predicate.field: values[predicate.field] for predicate in predicates}))
                completed = []
                for index, (document_id, marker, expected) in enumerate(staged):
                    try:
                        delete(document_id, marker, expected)
                    except Exception as exc:
                        if not completed:
                            raise
                        raise DataBatchWriteError(completed_ids=tuple(completed), failed_id=document_id,
                                                  pending_ids=tuple(entry[0] for entry in staged[index + 1:])) from exc
                    completed.append(document_id)
                return WriteResult(deleted=len(staged), matched=len(staged))
        self._check_writes(DataOperationKind.DELETE, filters=filters, ids=ids, options=options)
        return self.adapter.delete_vectors(ids=ids, filters=filters, options=options)
