# Примеры Muscles Data и SQL

Примеры охватывают публичные порты ядра, диагностику, события, SQL, политики и
адаптеры-сателлиты. Рабочий каталог для команд ниже — `projects/libraries`.
Локальные сценарии используют данные в памяти и не требуют внешних сервисов.
`search_policies.py` показывает явно разрешённую предварительную проверку:
она неатомарна, и между проверкой и записью данные могут измениться. Для защиты
от конкурентного доступа нужен backend с атомарной проверкой условия.
В политиках `DataPredicate("name", DataPredicateOperator.LIKE, "team_%")`
сопоставляет строку с шаблоном, а `DataPredicate("deleted_at",
DataPredicateOperator.IS_NULL, True)` требует явно присутствующий `null`.
В Elasticsearch, OpenSearch и Qdrant эти два условия проверяются по исходным
значениям кандидатов и могут потребовать полного просмотра до `max_scan`.

Для атомарного upsert Qdrant 1.17+ ресурс должен быть настроен с
`policy_atomic_managed: true`; все узлы и все пути записи должны соблюдать
инвариант маркера, описанный в README библиотеки. Неопределённый результат
можно уточнить, не выполняя повторную запись:

```python
from muscles_data.errors import DataWriteOutcomeUnknownError

try:
    protected_vectors.upsert_vectors(items)
except DataWriteOutcomeUnknownError as error:
    confirmed = protected_vectors.confirm_upsert(error.document_id, error.operation_id)
    # True подтверждает запись; None означает, что результат всё ещё неизвестен.
```

Для сохранения неопределённых операций между перезапусками передайте в фабрику
явный журнал: `QdrantVectorFactory(operation_journal=SqliteOperationJournal(path))`.
После перезапуска вызовите `protected_vectors.reconcile_pending()`; неясные
записи останутся в журнале. Удаление в управляемом режиме — мягкое: payload и
вектор сохраняются, а обычный поиск скрывает точку. Перевод существующих точек:
`protected_vectors.adopt_existing(id, expected_fields={...}, maintenance_confirmed=True)`
только при остановленных внешних писателях. Библиотека не может проверить, что
внешние сервисы действительно остановлены и соблюдают инвариант маркера.

## Без внешних сервисов

| Пример | Возможности |
| --- | --- |
| `muscles-data/examples/memory_ports.py` | Векторы, текстовый поиск, объекты, кеш с TTL, документы и диагностика |
| `muscles-data/examples/events.py` | Публикация, чтение, подтверждение и журнал событий |
| `muscles-data/examples/diagnostics.py` | Возможности, безопасная диагностика, ошибки и доступ к native-клиенту |
| `muscles-data/examples/search_policies.py` | Контекст и политика поиска, неатомарная предварительная проверка записи |
| `muscles-data/examples/run_data_runtime.py` | Инициализация пакета и вызовы Muscles actions |
| `muscles-data/examples/run_sql_resource_port.py` | SQL-мост с тестовым реестром |
| `muscles-data-sql/examples/native_resources.py` | Несколько ресурсов и собственная фабрика драйвера |
| `muscles-data-sql/examples/queries_and_mapper.py` | SQL JOIN и агрегация, `ModelMapper`, откат транзакции |
| `muscles-data-sql/examples/repository_policies.py` | Контекст запроса и политики SQL-репозитория; нужен SQLAlchemy |
| `muscles-data-mongodb/examples/run_mongodb_document_store.py` | MongoDB-порт с тестовым клиентом, без сервера |
| `muscles-data-s3/examples/run_s3_object_store.py` | S3-порт с тестовым клиентом, без сервера |

Например, из `projects/libraries`:

```bash
export PYTHONPATH="muscles/src:muscles-data/src:muscles-data-sql/src"
python3 muscles-data/examples/memory_ports.py
python3 muscles-data/examples/events.py
python3 muscles-data/examples/diagnostics.py
python3 muscles-data/examples/search_policies.py
python3 muscles-data/examples/run_data_runtime.py
python3 muscles-data/examples/run_sql_resource_port.py
python3 muscles-data-sql/examples/native_resources.py
python3 muscles-data-sql/examples/queries_and_mapper.py
python3 muscles-data-sql/examples/repository_policies.py
```

Для двух примеров с тестовыми клиентами добавьте в `PYTHONPATH` соответственно
`muscles-data-mongodb/src` или `muscles-data-s3/src`. Для SQL-примера политик
нужны зависимости `muscles-data-sql[legacy]`.

## Адаптеры и реальные сервисы

`backend_adapters.py` показывает конкретные пакеты через одни и те же порты:

| Аргумент | Дополнительный пакет | Переменные окружения | Операции |
| --- | --- | --- | --- |
| `redis` | `muscles-data-redis` | `REDIS_URL` | Кеш, TTL, блокировка, stream publish/read/ack |
| `qdrant` | `muscles-data-qdrant` | `QDRANT_URL` | Запись, поиск и удаление вектора |
| `elasticsearch` | `muscles-data-elasticsearch` | `ELASTICSEARCH_URL` | Запись, поиск и удаление документа индекса |
| `opensearch` | `muscles-data-opensearch` | `OPENSEARCH_URL` | Запись, поиск и удаление документа индекса |
| `mongodb` | `muscles-data-mongodb` | `MONGODB_URL`, `MONGODB_EXAMPLE_DATABASE` | Запись, поиск, чтение и удаление документа |
| `s3` | `muscles-data-s3` | `S3_ENDPOINT`, `S3_BUCKET` | Запись, чтение, список и удаление объекта |
| `sqlalchemy` | `muscles-data-sqlalchemy` | — | Сессия SQLAlchemy с SQLite в памяти |

Для каждого внешнего примера установите соответствующий пакет с его драйвером
или добавьте каталог его `src` в `PYTHONPATH`. Для S3 нужны также учётные данные
в стандартном механизме boto3; bucket должен существовать. Секреты не помещайте
в код и не выводите в терминал. Примеры поисковых систем рассчитаны на локальный
тестовый сервис; при авторизации настройте фабрику согласно README адаптера.

**Используйте только изолированный тестовый сервис.** Внешние сценарии требуют
`--allow-writes`: они создают записи, случайный индекс, коллекцию или Redis
stream. Созданные записи удаляются при успешном выполнении, но пустые индексы,
коллекции и потоки остаются; при ошибке могут остаться и записи. Имена с префиксом
`muscles_example_` печатаются для ручной очистки. Сценарий не удаляет базы,
bucket, индексы или коллекции.

Пример с локально доступными исходниками:

```bash
export PYTHONPATH="muscles/src:muscles-data/src:muscles-data-redis/src"
export REDIS_URL="redis://127.0.0.1:6379/0"
python3 muscles-data/examples/backend_adapters.py redis --allow-writes
```

Для другого backend замените пакет в `PYTHONPATH`, переменные и аргумент;
`sqlalchemy` работает без `--allow-writes` и без сервера. Формат параметров и
поддержка фильтров зависят от конкретного backend. `memory_kv` не предоставляет
`LockPort` и `StreamPort`; эти операции показаны в Redis-примере. Семантические
event-порты и Redis Stream — разные контракты. Прямой SQL не применяет политики.
MySQL и MariaDB пока не имеют готовых драйверов в `muscles-data-sql`; добавить свой
драйвер можно через `SqlDriverCatalog`.

При локальной проверке Qdrant-клиента фильтр с заполненным `must` и пустым
`should` вернул пустой результат, хотя вектор подходил под условие. Поэтому
пример Qdrant пока показывает поиск без фильтра; поведение реального сервера в
этой проверке не устанавливалось.
