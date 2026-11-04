# Resource migrations

`muscles-data` owns the storage-neutral `MigrationRegistry`, `MigrationSource`
and migration-module discovery contract. A project composition root creates and
configures one registry, registers each source with its backend, and makes the
registry available to its migration CLI. The registry orders sources by
`depends_on`; it does not create database connections. Backend packages own
connection creation, journals and backend-specific execution semantics.
Discovery imports package and migration modules; their top-level code must not
connect, mutate data or run migrations.

The owner package can keep Python modules named `m0001_*.py`, `m0002_*.py` in a
migration subpackage. `discover_migration_modules(pattern=...)` infers the owner
package from the calling module. A pattern without a directory searches the
`migrations` subpackage, for example `pattern="m000[0-9]_*.py"`. To select another
directory, include it in the pattern: `pattern="migrate/000[0-9]_*.py"`. Only
matching files are loaded. An explicit `package_name` remains available for
callers outside the owner package. Discovery binds executed source bytes to their
checksum and rejects modules imported elsewhere or changed afterwards; restart
the process after edits. Version order is lexicographic, so use zero-padded
revisions. See
`muscles-data-sql/examples/native_migrations.py` for an executable SQLite example.

`muscles-data` exposes registry operations but does not prescribe a universal
CLI. An application may provide `status`, `plan`, `upgrade` and `downgrade`
commands around its configured registry. Source upgrades include dependencies.
Downgrade requires an explicit source and target, and an applied dependent
prevents it. `status` and `plan` do not execute migrations or create journals,
but connect to existing databases. Available plans are checked before any
source is upgraded; a backend without `plan` cannot be preflighted. Review
plans, backups, permissions and compatibility before mutating data.

The Muscles registry builder creates a `NativeSqlMigrationSourceBackend` for
each discovered source. It owns migration connections and delegates transactional
execution to `NativeSqlMigrationBackend`; standalone low-level integrations may
construct sources directly. Packages do not create `SqlDatabase` instances.
For Muscles applications, `build_native_sql_migration_registry(packages,
database_url)` centralizes registration: it discovers each installed package's
`migrate` directory, creates sources from package namespaces, and derives ordering
from package `dependencies`. Packages need no registration methods or separate
migration dependency map.
Native SQL migrations use one transaction for DDL and journal updates, with
SQLite `BEGIN IMMEDIATE` or PostgreSQL transaction advisory locking. Each module
declares `revision`, `dialects`, `upgrade(tx)` and optionally `downgrade(tx)`;
`NativeSqlMigration.from_module` hashes its Python source. Changed, missing,
unknown or out-of-order migrations block execution. The backend supports only
transactional operations on SQLite and PostgreSQL. All SQL sources use the shared
`muscles_data_migrations` journal. For a database
previously managed by another migration mechanism, verify its schema and
establish the initial journal state explicitly before running initial `CREATE
TABLE` migrations.

For MongoDB/Redis modules, `Migration.from_module(module, resource=client)`
passes the explicit resource to `upgrade(resource)` and `downgrade(resource)`.
With independently imported modules, the backend cannot prove that loaded code
matched the file at import time; use discovery and immutable release artifacts.

Registry writes use a shared `SqlMigrationExecutionLock` for the configured
database resource. PostgreSQL uses a session advisory lock and SQLite uses a
shared `flock` file beside the database. Every competing runner must use the
same coordinator and registry; direct backend calls bypass it. Sources on
different resources need an application-provided cross-resource coordinator.
Without one, cross-resource upgrade is not atomic and downgrade of a source with
dependents is blocked. Status is a snapshot.

Redis and MongoDB migration backends live in their respective adapter packages;
`muscles-migrations` provides compatibility imports with optional backend extras.
Their non-transactional journals persist `running`/`reverting` on interruption
and stop automatic retries. Locks do not expire: confirm the runner has stopped
and inspect data before manual recovery. Redis journals use a dedicated prefix;
unattributable legacy records stop processing until manually reconciled.

Test migrations against isolated real backends, including concurrency,
interruptions, drift, dependency order, upgrades and downgrades. Separate
resources do not participate in one distributed transaction.
