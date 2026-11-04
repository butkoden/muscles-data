"""Storage-neutral migration source registration and dependency ordering."""
from dataclasses import dataclass
from contextlib import nullcontext
from fnmatch import fnmatchcase
from importlib import import_module
from importlib.util import find_spec, module_from_spec
import hashlib
from pathlib import Path
from pathlib import PurePosixPath
import pkgutil
import sys
from types import ModuleType
from typing import Callable, ContextManager, Protocol


class MigrationBackend(Protocol):
    def upgrade(self, target: str = "head") -> None: ...


def discover_migration_modules(
    package_name: str | None = None,
    *,
    pattern: str = "m[0-9]*.py",
) -> tuple[ModuleType, ...]:
    """Load matching Python migration files in name order, binding code to its checksum.

    When ``package_name`` is omitted, the calling package is used. A filename
    pattern without a directory searches its ``migrations`` subpackage; a
    directory in ``pattern`` selects that subpackage, e.g. ``migrate/000[0-9]_*.py``.
    ``package_name`` remains available for callers outside an owning package.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("A migration filename pattern is required")
    relative_pattern = PurePosixPath(pattern)
    if relative_pattern.is_absolute() or ".." in relative_pattern.parts:
        raise ValueError("Migration pattern must be a relative package path")
    filename_pattern = relative_pattern.name
    module_pattern = filename_pattern[:-3] if filename_pattern.endswith(".py") else filename_pattern
    if not module_pattern:
        raise ValueError("A migration filename pattern is required")

    if package_name is None:
        caller_package = sys._getframe(1).f_globals.get("__package__")
        if not isinstance(caller_package, str) or not caller_package:
            raise ValueError("Could not infer the calling package for migration discovery")
        package_name = caller_package
        if not relative_pattern.parent.parts:
            package_name = f"{package_name}.migrations"
    if relative_pattern.parent.parts:
        subpackage = ".".join(relative_pattern.parent.parts)
        if any(not part.isidentifier() for part in relative_pattern.parent.parts):
            raise ValueError("Migration pattern directories must be Python package names")
        package_name = f"{package_name}.{subpackage}"

    package = import_module(package_name)
    paths = getattr(package, "__path__", None)
    if paths is None:
        raise ValueError("Migration module discovery requires a Python package")
    names = sorted(
        item.name
        for item in pkgutil.iter_modules(paths)
        if not item.ispkg and fnmatchcase(item.name, module_pattern)
    )
    modules = []
    for name in names:
        qualified = f"{package_name}.{name}"
        spec = find_spec(qualified)
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            raise ValueError("Migration modules must be Python source files")
        try:
            source = Path(spec.origin).read_bytes()
        except OSError as exc:
            raise ValueError("Migration source file is unreadable") from exc
        checksum = hashlib.sha256(source).hexdigest()
        module = sys.modules.get(qualified)
        if module is not None:
            if getattr(module, "__muscles_migration_checksum__", None) != checksum:
                raise ValueError("Migration module was already imported or changed; restart the process")
        else:
            module = module_from_spec(spec)
            sys.modules[qualified] = module
            try:
                exec(compile(source, spec.origin, "exec"), module.__dict__)
                module.__muscles_migration_checksum__ = checksum
            except BaseException:
                sys.modules.pop(qualified, None)
                raise
        modules.append(module)
    return tuple(modules)


@dataclass(frozen=True)
class MigrationSource:
    name: str
    backend: MigrationBackend
    depends_on: tuple[str, ...] = ()


class MigrationRegistry:
    def __init__(self, *, execution_lock: Callable[[], ContextManager] | None = None) -> None:
        self._sources: dict[str, MigrationSource] = {}
        self._execution_lock = execution_lock

    def _locked(self):
        return self._execution_lock() if self._execution_lock is not None else nullcontext()

    def register(self, source: MigrationSource) -> None:
        name = getattr(source, "name", None)
        backend = getattr(source, "backend", None)
        dependencies = getattr(source, "depends_on", None)
        if (not isinstance(name, str) or not name or name in self._sources
                or not callable(getattr(backend, "upgrade", None))
                or not isinstance(dependencies, (tuple, list))
                or any(not isinstance(item, str) or not item for item in dependencies)):
            raise ValueError("Invalid or duplicate migration source")
        self._sources[name] = MigrationSource(name, backend, tuple(dependencies))

    def ordered(self) -> tuple[MigrationSource, ...]:
        ordered = []
        visiting, visited = set(), set()

        def visit(name):
            if name in visiting:
                raise ValueError(f"Cyclic migration dependency: {name}")
            if name in visited:
                return
            if name not in self._sources:
                raise ValueError(f"Unknown migration dependency: {name}")
            visiting.add(name)
            source = self._sources[name]
            for dependency in source.depends_on:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(source)

        for name in self._sources:
            visit(name)
        return tuple(ordered)

    def upgrade(self, name: str | None = None) -> None:
        ordered = self.ordered()
        if name is None:
            selected = {source.name for source in ordered}
        else:
            if name not in self._sources:
                raise ValueError(f"Unknown migration source: {name}")
            selected = set()

            def include(source_name):
                if source_name in selected:
                    return
                selected.add(source_name)
                for dependency in self._sources[source_name].depends_on:
                    include(dependency)

            include(name)
        with self._locked():
            for source in ordered:
                if source.name in selected:
                    plan = getattr(source.backend, "plan", None)
                    if callable(plan):
                        self._plan(source)
            for source in ordered:
                if source.name in selected:
                    source.backend.upgrade()

    @staticmethod
    def _status(source: MigrationSource) -> dict:
        method = getattr(source.backend, "status", None)
        if not callable(method):
            raise NotImplementedError(f"Migration source '{source.name}' does not support status")
        result = method()
        if (not isinstance(result, dict) or result.get("status", "ok") != "ok"
                or not isinstance(result.get("current"), list)
                or any(not isinstance(item, str) or not item for item in result["current"])):
            raise ValueError(f"Migration source '{source.name}' returned invalid status")
        return {**result, "source": source.name}

    def _selected(self, name: str | None) -> tuple[MigrationSource, ...]:
        ordered = self.ordered()
        if name is None:
            return ordered
        if name not in self._sources:
            raise ValueError(f"Unknown migration source: {name}")
        return (self._sources[name],)

    def status(self, name: str | None = None) -> list[dict]:
        return [self._status(source) for source in self._selected(name)]

    def plan(self, name: str | None = None) -> list[dict]:
        return [{"source": source.name, "pending": self._plan(source)} for source in self._selected(name)]

    @staticmethod
    def _plan(source: MigrationSource) -> list[str]:
        method = getattr(source.backend, "plan", None)
        if not callable(method):
            raise NotImplementedError(f"Migration source '{source.name}' does not support planning")
        result = method()
        if not isinstance(result, list) or any(not isinstance(item, str) or not item for item in result):
            raise ValueError(f"Migration source '{source.name}' returned invalid plan")
        return result

    def downgrade(self, name: str, target: str) -> None:
        ordered = self.ordered()
        if name not in self._sources:
            raise ValueError(f"Unknown migration source: {name}")
        if not isinstance(target, str) or not target:
            raise ValueError("A downgrade target is required")

        def depends_on(source: MigrationSource, dependency: str) -> bool:
            return any(item == dependency or depends_on(self._sources[item], dependency)
                       for item in source.depends_on)

        dependents = [source for source in ordered if source.name != name and depends_on(source, name)]
        if dependents and self._execution_lock is None:
            raise RuntimeError("Cross-source downgrade requires a shared execution lock")
        with self._locked():
            for source in dependents:
                if self._status(source)["current"]:
                    raise ValueError(f"Cannot downgrade '{name}': dependent source '{source.name}' is applied")
            method = getattr(self._sources[name].backend, "downgrade", None)
            if not callable(method):
                raise NotImplementedError(f"Migration source '{name}' does not support downgrade")
            method(target)
