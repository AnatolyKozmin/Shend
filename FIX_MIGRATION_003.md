# 🔧 Исправление миграции 003 для сервера

## Проблема

На сервере много миграций, включая merge-миграции. Нужно правильно привязать миграцию `003` к актуальному head.

## Решение

### Вариант 1: Проверить текущие heads и привязать к одному из них

```bash
# На сервере
cd /root/Shend

# Посмотреть все head ревизии
docker-compose exec bot alembic heads

# Посмотреть текущую версию
docker-compose exec bot alembic current

# Посмотреть историю
docker-compose exec bot alembic history --verbose
```

### Вариант 2: Найти последнюю миграцию и привязать к ней

Нужно найти последнюю миграцию (самую новую) и изменить `down_revision` в миграции `003`.

Сначала проверьте, какая миграция является последней:

```bash
# Посмотреть содержимое последних миграций
docker-compose exec bot cat migration/versions/89351deb7f87_add_interview_system_tables_and_fields.py | grep -E "revision|down_revision"
docker-compose exec bot cat migration/versions/b9105000ee89_add_reserv_time_slots_and_bookings.py | grep -E "revision|down_revision"
docker-compose exec bot cat migration/versions/6a2e6d09ae2f_split_reserv_and_finfak_tables.py | grep -E "revision|down_revision"
```

### Вариант 3: Использовать merge (рекомендуется)

Создать merge-миграцию, которая объединит все heads:

```bash
# На сервере
cd /root/Shend

# Создать merge миграцию
docker-compose exec bot alembic merge heads -m "merge heads before uchastniki"

# Это создаст новую merge миграцию, например: xxxxx_merge_heads.py

# Затем изменить миграцию 003, чтобы она ссылалась на эту merge миграцию
# В файле 003_create_uchastniki_table.py изменить:
# down_revision = 'xxxxx'  # где xxxxx - revision ID merge миграции
```

### Вариант 4: Применить напрямую к конкретному head (быстрое решение)

Если нужно быстро, можно применить миграцию напрямую:

```bash
# Найти один из heads
docker-compose exec bot alembic heads

# Применить все heads
docker-compose exec bot alembic upgrade heads

# Затем создать таблицу вручную через SQL (если миграция 003 не применяется)
docker-compose exec db psql -U postgres -d shabot_db -c "
CREATE TABLE IF NOT EXISTS uchastniki (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    course VARCHAR(128),
    faculty VARCHAR(255),
    telegram_username VARCHAR(64),
    tg_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_uchastniki_telegram_username UNIQUE (telegram_username)
);
CREATE INDEX IF NOT EXISTS ix_uchastniki_id ON uchastniki(id);
"

# Пометить миграцию как применённую
docker-compose exec bot alembic stamp 003
```

## Рекомендуемый подход

1. **Сначала проверьте текущее состояние:**
   ```bash
   docker-compose exec bot alembic current
   docker-compose exec bot alembic heads
   ```

2. **Создайте merge миграцию:**
   ```bash
   docker-compose exec bot alembic merge heads -m "merge before uchastniki"
   ```

3. **Обновите миграцию 003 на сервере:**
   - Найдите revision ID созданной merge миграции
   - Измените `down_revision` в `003_create_uchastniki_table.py` на этот ID

4. **Примените миграцию:**
   ```bash
   docker-compose exec bot alembic upgrade head
   ```

## Быстрое решение (если нужно срочно)

Если нужно быстро создать таблицу без исправления миграций:

```bash
# Создать таблицу напрямую
docker-compose exec db psql -U postgres -d shabot_db << EOF
CREATE TABLE IF NOT EXISTS uchastniki (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    course VARCHAR(128),
    faculty VARCHAR(255),
    telegram_username VARCHAR(64),
    tg_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_uchastniki_telegram_username UNIQUE (telegram_username)
);
CREATE INDEX IF NOT EXISTS ix_uchastniki_id ON uchastniki(id);
EOF

# Проверить
docker-compose exec db psql -U postgres -d shabot_db -c "\d uchastniki"
```

После этого можно запускать импорт данных.

