"""Publish, consume, acknowledge and load semantic data events in memory."""
from muscles_data import DataConfig, DataEventEnvelope, DataRuntime
from muscles_data.ports import EventConsumerPort, EventPublisherPort, EventStorePort


def main():
    runtime = DataRuntime(config=DataConfig.from_raw({"resources": {"events": {"type": "memory_event"}}}))
    try:
        publisher = runtime.require_port("events", EventPublisherPort)
        consumer = runtime.require_port("events", EventConsumerPort)
        store = runtime.require_port("events", EventStorePort)
        result = publisher.publish_event("documents", DataEventEnvelope(
            id="123e4567-e89b-42d3-a456-426614174000", type="document.indexed",
            source="example", subject="documents/doc-1", payload={"title": "Guide"},
        ))
        batch = consumer.read_events("documents", consumer="indexer", limit=10)
        print("published:", result.event_id, "read:", batch.count)
        for message in batch.events:
            print("event:", message["type"], message["payload"])
            print("acknowledged:", consumer.ack_event("documents", message["message_id"], consumer="indexer").acked)
        store.append_event("audit", {"type": "document.updated", "source": "example", "payload": {"id": "doc-1"}})
        print("journal:", store.load_events("audit").count)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
