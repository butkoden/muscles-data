"""Ordered migrations backed by a durable journal and an external lock."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from functools import partial
from typing import Any, Callable, Protocol

_NO_RESOURCE = object()


class MigrationStateError(RuntimeError):
    """The recorded migration state requires operator intervention."""


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    apply: Callable[[], None]
    revert: Callable[[], None] | None = None
    source_path: str | None = None

    @classmethod
    def from_module(cls, module: ModuleType, *, resource: Any = _NO_RESOURCE) -> Migration:
        path = getattr(module, "__file__", None)
        if not path or not str(path).endswith(".py"):
            raise ValueError("Migration must be backed by a Python source file")
        checksum = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        loaded_checksum = getattr(module, "__muscles_migration_checksum__", checksum)
        if loaded_checksum != checksum:
            raise MigrationStateError("Migration file changed after module discovery")
        apply = module.upgrade
        revert = getattr(module, "downgrade", None)
        if resource is not _NO_RESOURCE:
            apply = partial(apply, resource)
            revert = partial(revert, resource) if revert is not None else None
        return cls(module.revision, checksum, apply, revert, str(path))


class MigrationJournal(Protocol):
    """The caller holds an exclusive lock throughout any write operation."""

    def get(self, version: str) -> tuple[str, str] | None: ...
    def begin(self, version: str, checksum: str) -> None: ...
    def complete(self, version: str, checksum: str) -> None: ...
    def begin_revert(self, version: str, checksum: str) -> None: ...
    def remove(self, version: str, checksum: str) -> None: ...


class VersionedMigrationBackend:
    """An interrupted apply/revert requires explicit operator recovery."""

    def __init__(self, journal: MigrationJournal, migrations: list[Migration]) -> None:
        if any(not isinstance(m, Migration) or not isinstance(m.version, str) or not m.version
               or not isinstance(m.checksum, str) or not m.checksum or not callable(m.apply)
               or (m.revert is not None and not callable(m.revert)) for m in migrations):
            raise ValueError("Migrations require versions, checksums and callable operations")
        versions = [migration.version for migration in migrations]
        if versions != sorted(set(versions)):
            raise ValueError("Migration versions must be unique and ordered")
        self.journal = journal
        self.migrations = tuple(migrations)

    def _applied(self) -> list[str]:
        for migration in self.migrations:
            if migration.source_path is not None:
                try:
                    checksum = hashlib.sha256(Path(migration.source_path).read_bytes()).hexdigest()
                except OSError as exc:
                    raise MigrationStateError("A migration file is missing or unreadable") from exc
                if checksum != migration.checksum:
                    raise MigrationStateError("A migration file changed after discovery")
        versions = getattr(self.journal, "versions", None)
        if callable(versions):
            known = {migration.version for migration in self.migrations}
            if set(versions(known)) - known:
                raise MigrationStateError("An applied migration file is missing")
        applied = []
        missing = False
        for migration in self.migrations:
            state = self.journal.get(migration.version)
            if state is None:
                missing = True
            elif missing or state != (migration.checksum, "complete"):
                raise MigrationStateError(f"Migration {migration.version} has changed, is out of order or was interrupted")
            else:
                applied.append(migration.version)
        return applied

    def status(self) -> dict:
        applied = self._applied()
        return {"current": applied[-1:] if applied else [], "applied": applied,
                "pending": [m.version for m in self.migrations[len(applied):]],
                "verification": "checksums" if callable(getattr(self.journal, "versions", None)) else "registered_only"}

    def plan(self) -> list[str]:
        return self.status()["pending"]

    def upgrade(self, target: str = "head") -> None:
        versions = [m.version for m in self.migrations]
        if target != "head" and target not in versions:
            raise ValueError(f"Unknown migration target: {target}")
        applied = self._applied()
        end = len(versions) if target == "head" else versions.index(target) + 1
        if end < len(applied):
            raise ValueError("Upgrade target is older than current revision")
        for migration in self.migrations[len(applied):end]:
            self.journal.begin(migration.version, migration.checksum)
            migration.apply()
            self.journal.complete(migration.version, migration.checksum)

    def downgrade(self, target: str) -> None:
        versions = [m.version for m in self.migrations]
        if target != "base" and target not in versions:
            raise ValueError(f"Unknown migration target: {target}")
        applied = self._applied()
        end = 0 if target == "base" else versions.index(target) + 1
        if end > len(applied):
            raise ValueError("Downgrade target is not applied")
        changes = tuple(reversed(self.migrations[end:len(applied)]))
        if any(m.revert is None for m in changes):
            raise ValueError("A migration has no downgrade")
        for migration in changes:
            self.journal.begin_revert(migration.version, migration.checksum)
            migration.revert()
            self.journal.remove(migration.version, migration.checksum)
