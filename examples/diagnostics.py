"""Resource capabilities, safe inspection, health and explicit native access."""
from muscles_data import DataCapability, DataConfig, DataRuntime
from muscles_data.errors import DataCapabilityError
from muscles_data.ports import KeyValuePort, VectorSearchPort


def main():
    runtime = DataRuntime(config=DataConfig.from_raw({"resources": {
        "cache": {"type": "memory_kv", "native_client": True, "api_key": "example-sensitive-value"}
    }}))
    try:
        print("before use:", runtime.list_resources())
        cache = runtime.require_port("cache", KeyValuePort)
        cache.set("example", b"value")
        inspection = runtime.inspect_resource("cache")
        assert "example-sensitive-value" not in repr(inspection)
        print("safe inspect:", inspection)
        print("health:", runtime.doctor()["status"])
        try:
            runtime.require_port("cache", VectorSearchPort)
        except DataCapabilityError:
            print("incompatible port rejected")
        native = runtime.require_resource("cache", DataCapability.NATIVE_CLIENT).native_client()
        print("native handle:", type(native).__name__)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
