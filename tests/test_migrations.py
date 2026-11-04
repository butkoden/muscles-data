from threading import RLock

import pytest

from muscles.data.config import DataConfig
from muscles.data.migrations import MigrationRegistry, MigrationSource, discover_migration_modules
from muscles.data.runtime import DataRuntime


class Backend:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def upgrade(self, target="head"):
        self.calls.append(("upgrade", self.name, target))


def test_runtime_registry_runs_sources_in_dependency_order():
    calls = []
    runtime = DataRuntime(config=DataConfig.from_raw({}))
    runtime.migrations.register(MigrationSource("storage", Backend("storage", calls), ("accounts",)))
    runtime.migrations.register(MigrationSource("accounts", Backend("accounts", calls)))
    assert isinstance(runtime.migrations, MigrationRegistry)
    assert [source.name for source in runtime.migrations.ordered()] == ["accounts", "storage"]
    assert calls == []
    runtime.migrations.upgrade()
    assert calls == [("upgrade", "accounts", "head"), ("upgrade", "storage", "head")]


def test_runtime_uses_explicit_coordinated_registry():
    lock = RLock()
    registry = MigrationRegistry(execution_lock=lambda: lock)
    runtime = DataRuntime(config=DataConfig.from_raw({}), migrations=registry)
    assert runtime.migrations is registry


def test_status_plan_and_rollback_respect_applied_dependents():
    class InspectableBackend(Backend):
        def __init__(self, name, calls):
            super().__init__(name, calls)
            self.applied = True

        def status(self):
            return {"current": ["one"] if self.applied else [], "pending": []}

        def plan(self):
            return []

        def downgrade(self, target):
            self.calls.append(("downgrade", self.name, target))
            self.applied = False

    calls = []
    lock = RLock()
    registry = MigrationRegistry(execution_lock=lambda: lock)
    registry.register(MigrationSource("accounts", InspectableBackend("accounts", calls)))
    registry.register(MigrationSource("storage", InspectableBackend("storage", calls), ("accounts",)))
    assert [item["source"] for item in registry.status()] == ["accounts", "storage"]
    assert [item["source"] for item in registry.plan()] == ["accounts", "storage"]
    assert [item["source"] for item in registry.status("storage")] == ["storage"]
    assert [item["source"] for item in registry.plan("accounts")] == ["accounts"]
    assert calls == []
    with pytest.raises(ValueError, match="storage"):
        registry.downgrade("accounts", "base")
    registry.downgrade("storage", "base")
    registry.downgrade("accounts", "base")
    assert calls == [("downgrade", "storage", "base"), ("downgrade", "accounts", "base")]


def test_rollback_fails_closed_when_dependent_status_is_unavailable():
    lock = RLock()
    registry = MigrationRegistry(execution_lock=lambda: lock)
    registry.register(MigrationSource("accounts", Backend("accounts", [])))
    registry.register(MigrationSource("storage", Backend("storage", []), ("accounts",)))
    with pytest.raises(NotImplementedError):
        registry.downgrade("accounts", "base")


def test_cross_source_downgrade_requires_shared_execution_lock():
    registry = MigrationRegistry()
    registry.register(MigrationSource("accounts", Backend("accounts", [])))
    registry.register(MigrationSource("storage", Backend("storage", []), ("accounts",)))
    with pytest.raises(RuntimeError, match="lock"):
        registry.downgrade("accounts", "base")


def test_upgrade_one_source_runs_only_its_dependencies_first():
    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("accounts", Backend("accounts", calls)))
    registry.register(MigrationSource("storage", Backend("storage", calls), ("accounts",)))
    registry.register(MigrationSource("other", Backend("other", calls)))
    registry.upgrade("storage")
    assert calls == [("upgrade", "accounts", "head"), ("upgrade", "storage", "head")]


def test_upgrade_validates_all_available_plans_before_applying_any_source():
    class Inspectable(Backend):
        def plan(self):
            if self.name == "storage":
                raise ValueError("changed migration")
            return ["001"]

    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("accounts", Inspectable("accounts", calls)))
    registry.register(MigrationSource("storage", Inspectable("storage", calls), ("accounts",)))
    with pytest.raises(ValueError, match="changed"):
        registry.upgrade()
    assert calls == []


def test_upgrade_rejects_malformed_plan_before_any_write():
    class InvalidPlan(Backend):
        def plan(self):
            return [None]

    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("bad", InvalidPlan("bad", calls)))
    with pytest.raises(ValueError, match="plan"):
        registry.upgrade()
    assert calls == []


def test_unknown_or_cyclic_dependencies_are_rejected_before_execution():
    calls = []
    registry = MigrationRegistry()
    registry.register(MigrationSource("a", Backend("a", calls), ("b",)))
    with pytest.raises(ValueError, match="Unknown"):
        registry.upgrade()
    registry.register(MigrationSource("b", Backend("b", calls), ("a",)))
    with pytest.raises(ValueError, match="Cyclic"):
        registry.upgrade()
    assert calls == []


def test_discovery_loads_only_ordered_migration_modules(monkeypatch, tmp_path):
    package = tmp_path / "sample_migrations"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m002_second.py").write_text("revision = '002'\n", encoding="utf-8")
    (package / "m001_first.py").write_text("revision = '001'\n", encoding="utf-8")
    (package / "helpers.py").write_text("raise RuntimeError('must not be loaded')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert [module.revision for module in discover_migration_modules("sample_migrations")] == ["001", "002"]
    (package / "m001_first.py").write_text("revision = 'changed'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        discover_migration_modules("sample_migrations")


def test_discovery_accepts_custom_filename_pattern(monkeypatch, tmp_path):
    package = tmp_path / "custom_migrations"
    migration_package = package / "migrate"
    migration_package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (migration_package / "__init__.py").write_text("", encoding="utf-8")
    (migration_package / "0002_second.py").write_text("revision = '002'\n", encoding="utf-8")
    (migration_package / "0001_first.py").write_text("revision = '001'\n", encoding="utf-8")
    (migration_package / "helper.py").write_text(
        "raise RuntimeError('must not be loaded')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    modules = discover_migration_modules(
        "custom_migrations.migrate", pattern="000[0-9]_*.py"
    )

    assert [module.revision for module in modules] == ["001", "002"]


def test_discovery_infers_calling_package_and_migrations_directory(monkeypatch, tmp_path):
    package = tmp_path / "inferred_migrations"
    migrations = package / "migrations"
    migrations.mkdir(parents=True)
    custom_migrations = package / "migrate"
    custom_migrations.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "loader.py").write_text(
        "from muscles.data.migrations import discover_migration_modules\n"
        "def load_default():\n"
        "    return discover_migration_modules(pattern='m000[0-9]_*.py')\n"
        "def load_custom():\n"
        "    return discover_migration_modules(pattern='migrate/000[0-9]_*.py')\n",
        encoding="utf-8",
    )
    (migrations / "__init__.py").write_text("", encoding="utf-8")
    (migrations / "m0001_initial.py").write_text("revision = '001'\n", encoding="utf-8")
    (custom_migrations / "__init__.py").write_text("", encoding="utf-8")
    (custom_migrations / "0001_initial.py").write_text("revision = '001-custom'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    from importlib import import_module

    loader = import_module("inferred_migrations.loader")

    assert [module.revision for module in loader.load_default()] == ["001"]
    assert [module.revision for module in loader.load_custom()] == ["001-custom"]
