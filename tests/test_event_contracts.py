from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from muscles import Model, inspect_application

from muscles_data import DataCapability, DataPackage, init_package
from muscles_data.config import DataConfig
from muscles_data.errors import DataCapabilityError
from muscles_data.models import (
    DataEventAckRequest,
    DataEventAckResult,
    DataEventEnvelope,
    DataEventPublishRequest,
    DataEventPublishResult,
    DataEventReadRequest,
    DataEventReadResult,
    DataEventSchemaRef,
)
from muscles_data.ports import EventConsumerPort, EventPublisherPort, EventStorePort
from muscles_data.runtime import DataRuntime


EVENT_SCHEMA_TYPES = (
    DataEventEnvelope,
    DataEventSchemaRef,
    DataEventPublishRequest,
    DataEventPublishResult,
    DataEventReadRequest,
    DataEventReadResult,
    DataEventAckRequest,
    DataEventAckResult,
)


def test_data_event_envelope_is_a_core_model_schema():
    assert issubclass(DataEventEnvelope, Model)

    dumped = DataEventEnvelope().dump()

    assert "DataEventEnvelope" in dumped
    assert {"id", "type", "source", "payload", "occurred_at"} <= set(
        dumped["DataEventEnvelope"]["properties"]
    )
    json.dumps(dumped)


def test_data_event_contract_schemas_are_core_models_and_serializable():
    for schema_type in EVENT_SCHEMA_TYPES:
        assert issubclass(schema_type, Model)
        json.dumps(schema_type().dump())


def test_package_registers_data_event_schemas_for_inspection():
    app = SimpleNamespace()

    init_package(app, {})
    inspected = inspect_application(app)
    schema_names = {
        name
        for schema in inspected["schemas"]
        for name in schema
    }

    assert {schema.__name__ for schema in EVENT_SCHEMA_TYPES} <= schema_names
    json.dumps(inspected["schemas"])


def test_runtime_resolves_event_ports_and_capabilities():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"events": {"type": "memory_event"}}}}
        )
    )

    assert isinstance(runtime.require_port("events", EventPublisherPort), EventPublisherPort)
    assert isinstance(runtime.require_port("events", EventConsumerPort), EventConsumerPort)
    assert isinstance(runtime.require_port("events", EventStorePort), EventStorePort)
    assert "event_publish" in runtime.list_resources()[0]["capabilities"]
    assert "event_subscribe" in runtime.list_resources()[0]["capabilities"]


def test_event_capability_mismatch_is_explicit():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"cache": {"type": "memory_kv"}}}}
        )
    )

    with pytest.raises(DataCapabilityError, match="event_publish"):
        runtime.require_port("cache", EventPublisherPort)


def test_in_memory_event_adapter_publish_read_ack_preserves_identity_and_metadata():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"events": {"type": "memory_event"}}}}
        )
    )
    publisher = runtime.require_port("events", EventPublisherPort)
    consumer = runtime.require_port("events", EventConsumerPort)

    published = publisher.publish_event(
        "documents",
        DataEventEnvelope(
            id="123e4567-e89b-42d3-a456-426614174000",
            type="document.indexed",
            source="documents.ingestion",
            subject="documents/doc-123",
            payload={"title": "A document"},
            metadata={"tenant": "demo"},
        ),
    )

    assert isinstance(published, DataEventPublishResult)
    assert published.published is True
    assert published.event_id == "123e4567-e89b-42d3-a456-426614174000"
    assert published.message_id

    read = consumer.read_events("documents", consumer="indexer")
    assert isinstance(read, DataEventReadResult)
    assert read.count == 1
    message = read.events[0]
    assert message["id"] == published.event_id
    assert message["message_id"] == published.message_id
    assert message["metadata"] == {"tenant": "demo"}

    acked = consumer.ack_event("documents", message["message_id"], consumer="indexer")
    assert isinstance(acked, DataEventAckResult)
    assert acked.acked is True
    assert consumer.read_events("documents", consumer="indexer").count == 0


def test_event_diagnostics_include_counts_but_not_raw_payload():
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {"data": {"resources": {"events": {"type": "memory_event"}}}}
        )
    )
    publisher = runtime.require_port("events", EventPublisherPort)
    publisher.publish_event(
        "documents",
        {
            "id": "event-1",
            "type": "document.indexed",
            "source": "tests",
            "payload": {"private": "do-not-expose"},
        },
    )

    diagnostics = runtime.inspect_resource("events")

    assert diagnostics["details"]["events"] == 1
    assert "do-not-expose" not in repr(diagnostics)
    assert "payload" not in repr(diagnostics)


def test_data_package_namespace_remains_unchanged():
    assert DataPackage.namespace == "data"


def test_event_contracts_are_available_from_public_package_exports():
    import muscles_data as md

    assert md.DataEventEnvelope is DataEventEnvelope
    assert md.DataEventPublishResult is DataEventPublishResult
    assert md.EventPublisherPort is EventPublisherPort
    assert md.EventConsumerPort is EventConsumerPort
    assert md.EventStorePort is EventStorePort
