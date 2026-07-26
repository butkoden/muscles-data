from __future__ import annotations

"""SQL resource port smoke example without a real database.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_sql_resource_port.py
"""

from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import SqlResourcePort
from muscles_data.runtime import DataRuntime


class FakeSqlRegistry:
    def session(self, name: str = "default"):
        return f"session:{name}"

    def session_factory(self, name: str = "default"):
        return f"factory:{name}"

    def inspect(self, name: str = "default"):
        return {
            "status": "ok",
            "connection": {
                "name": name,
                "url": "postgresql://user:secret@localhost/app",
                "safe_url": "postgresql://***@localhost/app",
            },
        }


def main() -> None:
    registry = FakeSqlRegistry()
    catalog = DataAdapterCatalog.with_defaults(sql_registry_provider=lambda: registry)
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "sql.main": {
                            "type": "sql",
                            "connection": "main",
                            "role": "read_write",
                        }
                    }
                }
            }
        ),
        catalog=catalog,
    )

    sql = runtime.require_port("sql.main", SqlResourcePort)
    print("connection ->", sql.connection_name())
    print("session ->", sql.session())
    print("factory ->", sql.session_factory())
    print("inspect ->", sql.inspect())


if __name__ == "__main__":
    main()
