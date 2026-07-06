from __future__ import annotations

"""Redis data port smoke example without a real Redis server.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_redis_data_port.py
"""

from dataclasses import asdict
from typing import Any

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import KeyValuePort, LockPort, StreamPort
from muscles_data.runtime import DataRuntime


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def set(self, name: str, value, **kwargs):
        if kwargs.get("nx") and name in self.values:
            return False
        self.values[name] = value
        return True

    def get(self, name: str):
        return self.values.get(name)

    def delete(self, *names: str) -> int:
        deleted = 0
        for name in names:
            deleted += 1 if self.values.pop(name, None) is not None else 0
        return deleted

    def exists(self, *names: str) -> int:
        return sum(1 for name in names if name in self.values)

    def eval(self, _script: str, _numkeys: int, key: str, expected_token: str):
        if self.values.get(key) != expected_token:
            return 0
        self.values.pop(key, None)
        return 1

    def xadd(self, name: str, fields: dict[str, Any]):
        stream = self.streams.setdefault(name, [])
        message_id = f"{len(stream) + 1}-0"
        stream.append((message_id, dict(fields)))
        return message_id

    def xread(self, streams: dict[str, str], count: int | None = None):
        output = []
        for name, cursor in streams.items():
            messages = [
                (message_id, fields)
                for message_id, fields in self.streams.get(name, [])
                if cursor in {"0", "0-0"} or message_id > cursor
            ]
            output.append((name, messages[:count]))
        return output

    def xack(self, name: str, _groupname: str, *ids: str) -> int:
        known = {message_id for message_id, _fields in self.streams.get(name, [])}
        return sum(1 for message_id in ids if message_id in known)

    def ping(self) -> bool:
        return True


def main() -> None:
    client = FakeRedisClient()
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "cache.default": {
                            "type": "redis",
                            "url": "redis://:redis-secret@localhost:6379/0",
                            "namespace": "demo",
                            "stream_group": "workers",
                            "timeout": 1,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(redis_client_factory=lambda _config: client),
    )

    cache = runtime.require_port("cache.default", KeyValuePort)
    print("set ->", asdict(cache.set("cursor", b"page-2", ttl_seconds=30)))
    print("get ->", cache.get("cursor").decode("utf-8") if cache.get("cursor") else None)

    lock = runtime.require_port("cache.default", LockPort)
    handle = lock.acquire_lock("sync", ttl_seconds=30)
    print("lock ->", handle is not None)
    print("release ->", asdict(lock.release_lock(handle)))

    stream = runtime.require_port("cache.default", StreamPort)
    print("publish ->", asdict(stream.publish("events", {"kind": "cursor.updated"})))
    messages = stream.read("events", limit=10)
    print("read ->", asdict(messages))
    print("ack ->", asdict(stream.ack("events", messages.cursor or "0-0")))
    print("doctor ->", runtime.doctor())


if __name__ == "__main__":
    main()
