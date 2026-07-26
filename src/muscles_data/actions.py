from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, Iterator

try:
    from muscles import ActionContext
except Exception:  # pragma: no cover
    from muscles.core.core import ActionContext

try:
    from muscles import register_action  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    register_action = None


EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

RESOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
    },
    "required": ["name"],
    "additionalProperties": False,
}


def register_data_actions(app, *, transports: list[str]) -> None:
    _register_action(
        app,
        name="data.resources.list",
        description="List configured data resources without initializing backends.",
        input_schema=EMPTY_SCHEMA,
        handler=_resources_list,
        transports=transports,
    )
    _register_action(
        app,
        name="data.resource.inspect",
        description="Inspect one configured data resource without leaking secrets.",
        input_schema=RESOURCE_SCHEMA,
        handler=_resource_inspect,
        transports=transports,
    )
    _register_action(
        app,
        name="data.doctor",
        description="Run safe data resource diagnostics.",
        input_schema=EMPTY_SCHEMA,
        handler=_doctor,
        transports=transports,
    )


def _register_action(app, **kwargs):
    if register_action is not None:
        return register_action(app, **kwargs)
    from muscles.core.core import ActionContract, get_application_registry

    return get_application_registry(app).add_action(
        ActionContract(
            name=kwargs["name"],
            description=kwargs.get("description", ""),
            input_schema=kwargs.get("input_schema", None),
            output_schema=kwargs.get("output_schema", None),
            rules=kwargs.get("rules", []),
            handler_ref=kwargs.get("handler_ref", None),
            transports=kwargs.get("transports", []),
            stream_output=kwargs.get("stream_output", False),
            stream_metadata=kwargs.get("stream_metadata", None) or {},
            metadata=kwargs.get("metadata", None) or {},
            handler=kwargs.get("handler"),
        )
    )


def _runtime(context: ActionContext):
    from .runtime import DataRuntime

    container = getattr(context.application, "container", None)
    if container is None:
        raise RuntimeError("data runtime is not initialized")
    try:
        return container.resolve(DataRuntime)
    except KeyError as exc:
        raise RuntimeError("data runtime is not registered") from exc


def _resources_list(payload: dict[str, Any], context: ActionContext) -> dict[str, Any]:
    del payload
    runtime = _runtime(context)
    with _telemetry(context).span("muscles.data.resources.list", **{"data.operation": "resources.list"}):
        return {"resources": runtime.list_resources()}


def _resource_inspect(payload: dict[str, Any], context: ActionContext) -> dict[str, Any]:
    runtime = _runtime(context)
    name = payload["name"]
    with _telemetry(context).span(
        "muscles.data.resource.inspect",
        **{"data.resource.name": name, "data.operation": "resource.inspect"},
    ):
        return _serialize(runtime.inspect_resource(name))


def _doctor(payload: dict[str, Any], context: ActionContext) -> dict[str, Any]:
    del payload
    runtime = _runtime(context)
    with _telemetry(context).span("muscles.data.doctor", **{"data.operation": "doctor"}):
        return _serialize(runtime.doctor())


def _telemetry(context: ActionContext):
    try:
        from muscles import resolve_telemetry  # type: ignore[import-not-found]

        return resolve_telemetry(context.application)
    except Exception:
        return _NoopTelemetry()


def _serialize(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class _NoopTelemetry:
    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[None]:
        del name, attributes
        yield
