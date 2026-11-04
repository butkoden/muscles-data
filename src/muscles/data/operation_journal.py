"""Durable, explicitly configured recovery records for uncertain writes."""

from contextlib import closing
from pathlib import Path
import re
import sqlite3


class SqliteOperationJournal:
    """Persist operation identities, not request payloads or credentials."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if not self.path or self.path == ":memory:" or self.path.startswith("file:"):
            raise ValueError("Operation journal requires a persistent filesystem path")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS pending_operations (
                operation_id TEXT PRIMARY KEY, resource TEXT NOT NULL,
                collection TEXT NOT NULL, document_id TEXT NOT NULL,
                operation_kind TEXT NOT NULL CHECK (operation_kind IN ('upsert', 'delete')),
                operation_type TEXT,
                scope TEXT NOT NULL DEFAULT '',
                confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(pending_operations)")}
            if "operation_kind" not in columns:
                connection.execute("ALTER TABLE pending_operations ADD COLUMN operation_kind TEXT NOT NULL DEFAULT 'upsert'")
            if "operation_type" not in columns:
                connection.execute("ALTER TABLE pending_operations ADD COLUMN operation_type TEXT")
            if "scope" not in columns:
                connection.execute("ALTER TABLE pending_operations ADD COLUMN scope TEXT NOT NULL DEFAULT ''")

    def prepare(self, resource: str, collection: str, document_id: str, operation_id: str, *, operation_kind: str = "upsert", scope: str = "") -> None:
        if any(not isinstance(value, str) or not value for value in (resource, collection, document_id)):
            raise ValueError("Operation resource, collection and document id must be nonempty strings")
        if not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise ValueError("Invalid operation id")
        if operation_kind not in ("upsert", "delete", "adopt"):
            raise ValueError("Invalid operation kind")
        if not isinstance(scope, str):
            raise ValueError("Invalid operation scope")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            base_kind = "upsert" if operation_kind == "adopt" else operation_kind
            connection.execute("INSERT INTO pending_operations (operation_id, resource, collection, document_id, operation_kind, operation_type, scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (operation_id, resource, collection, document_id, base_kind, operation_kind, scope))

    def confirm(self, operation_id: str, *, scope: str | None = None) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            sql = "UPDATE pending_operations SET confirmed = 1 WHERE operation_id = ?"
            params = (operation_id,)
            if scope is not None:
                sql += " AND scope = ?"
                params += (scope,)
            result = connection.execute(sql, params)
            if result.rowcount != 1:
                raise KeyError("Unknown operation")

    def pending(self, resource: str, *, scope: str | None = None) -> list[dict[str, str]]:
        with closing(sqlite3.connect(self.path)) as connection:
            sql = "SELECT resource, collection, document_id, operation_id, COALESCE(operation_type, operation_kind) FROM pending_operations WHERE resource = ? AND confirmed = 0"
            params = (resource,)
            if scope is not None:
                sql += " AND scope = ?"
                params += (scope,)
            rows = connection.execute(sql + " ORDER BY rowid", params).fetchall()
        return [dict(zip(("resource", "collection", "document_id", "operation_id", "operation_kind"), row)) for row in rows]
