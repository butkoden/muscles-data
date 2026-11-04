import pytest
import sqlite3

from muscles.data.operation_journal import SqliteOperationJournal


def test_pending_operation_survives_reopen_and_can_be_confirmed(tmp_path):
    path = tmp_path / "operations.sqlite"
    journal = SqliteOperationJournal(path)
    journal.prepare("vectors", "points", "doc-1", "a" * 32)
    recovered = SqliteOperationJournal(path)
    assert recovered.pending("vectors") == [{"resource": "vectors", "collection": "points", "document_id": "doc-1", "operation_id": "a" * 32, "operation_kind": "upsert"}]
    recovered.confirm("a" * 32)
    assert SqliteOperationJournal(path).pending("vectors") == []


def test_journal_rejects_volatile_storage_and_duplicate_tokens(tmp_path):
    with pytest.raises(ValueError):
        SqliteOperationJournal(":memory:")
    journal = SqliteOperationJournal(tmp_path / "operations.sqlite")
    journal.prepare("r", "c", "d", "b" * 32)
    with pytest.raises(sqlite3.IntegrityError):
        journal.prepare("r", "c", "d", "b" * 32)


def test_journal_reads_legacy_schema_and_preserves_old_pending_records(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE pending_operations (operation_id TEXT PRIMARY KEY, resource TEXT NOT NULL, collection TEXT NOT NULL, document_id TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO pending_operations (operation_id, resource, collection, document_id) VALUES (?, ?, ?, ?)", ("a" * 32, "r", "c", "d"))
    journal = SqliteOperationJournal(path)
    assert journal.pending("r")[0]["operation_kind"] == "upsert"


def test_journal_keeps_backends_separate(tmp_path):
    journal = SqliteOperationJournal(tmp_path / "operations.sqlite")
    journal.prepare("r", "c", "1", "a" * 32, scope="one")
    journal.prepare("r", "c", "2", "b" * 32, scope="two")
    assert [item["document_id"] for item in journal.pending("r", scope="one")] == ["1"]
    assert [item["document_id"] for item in journal.pending("r", scope="two")] == ["2"]
    with pytest.raises(KeyError):
        journal.confirm("a" * 32, scope="two")
    assert len(journal.pending("r", scope="one")) == 1
