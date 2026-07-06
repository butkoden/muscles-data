"""SQLAlchemy resource port smoke example with SQLite.

Run:
  PYTHONPATH=../muscles/src:src python3 examples/run_sqlalchemy_resource_port.py
"""

from __future__ import annotations

import importlib
import json
from typing import cast

from muscles_data import DataCapability
from muscles_data.catalog import DataAdapterCatalog
from muscles_data.config import DataConfig
from muscles_data.ports import SqlResourcePort
from muscles_data.runtime import DataRuntime


def run() -> dict:
    sqlalchemy = importlib.import_module("sqlalchemy")
    runtime = DataRuntime(
        config=DataConfig.from_raw(
            {
                "data": {
                    "resources": {
                        "sql.local": {
                            "type": "sqlalchemy",
                            "url": "sqlite:///:memory:",
                            "name": "local_sqlite",
                            "native_client": True,
                        }
                    }
                }
            }
        ),
        catalog=DataAdapterCatalog.with_defaults(),
    )

    initialized_before = runtime.list_resources()[0]["initialized"]
    sql = cast(SqlResourcePort, runtime.require_port("sql.local", SqlResourcePort))

    with sql.session() as session:
        session.execute(sqlalchemy.text("create table notes (id integer primary key, title varchar)"))
        session.execute(sqlalchemy.text("insert into notes (title) values (:title)"), {"title": "typed port"})
        rows = session.execute(sqlalchemy.text("select title from notes order by id")).fetchall()

    native = runtime.require_resource("sql.local", DataCapability.NATIVE_CLIENT).native_client()
    output = {
        "initialized_before": initialized_before,
        "connection_name": sql.connection_name(),
        "rows": [row[0] for row in rows],
        "native_keys": sorted(native),
        "inspect": runtime.inspect_resource("sql.local"),
        "doctor": runtime.doctor(),
    }
    runtime.close()
    return output


def main() -> None:
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
