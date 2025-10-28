# Инструкции по применению миграций на сервере

## Шаг 1: Подготовка на сервере

1. **Подключитесь к серверу по SSH:**
```bash
ssh user@your-server.com
```

2. **Перейдите в директорию проекта:**
```bash
cd /path/to/ShaBot
```

3. **Остановите бота (если он запущен в Docker):**
```bash
docker-compose down
```

## Шаг 2: Применение миграции

### Вариант A: Если используете Docker

1. **Загрузите новые файлы на сервер** (модели, миграции):
```bash
# Можно использовать git pull, если проект в репозитории
git pull origin main

# Или загрузить файлы через scp
scp -r db/ user@server:/path/to/ShaBot/
scp -r migration/ user@server:/path/to/ShaBot/
scp -r handlers/ user@server:/path/to/ShaBot/
scp -r scripts/ user@server:/path/to/ShaBot/
```

2. **Пересоберите контейнеры:**
```bash
docker-compose build
```

3. **Запустите контейнер для миграции:**
```bash
docker-compose run --rm bot alembic upgrade head
```

### Вариант B: Если НЕ используете Docker

1. **Активируйте виртуальное окружение:**
```bash
source venv/bin/activate  # для Linux/Mac
# или
venv\Scripts\activate  # для Windows
```

2. **Примените миграцию:**
```bash
alembic upgrade head
```

## Шаг 3: Загрузка данных из Excel

1. **Убедитесь, что файл res.xlsx находится в корне проекта**

2. **Установите pandas (если ещё не установлен):**
```bash
pip install pandas openpyxl
```

3. **Запустите скрипт загрузки:**

**Если используете Docker:**
```bash
docker-compose run --rm bot python scripts/load_reserv.py
```

**Если НЕ используете Docker:**
```bash
python scripts/load_reserv.py
```

## Шаг 4: Запуск бота

**Если используете Docker:**
```bash
docker-compose up -d
```

**Если НЕ используете Docker:**
```bash
python main.py
```

## Шаг 5: Проверка

1. **Проверьте, что таблица создана:**
```bash
# Подключитесь к PostgreSQL
docker exec -it shabot_db psql -U postgres -d shabot_db

# Выполните запрос
SELECT COUNT(*) FROM reserv;
\q
```

2. **Проверьте команды в боте:**
- `/poter` - проверка совпадений
- `/create_reserv_rass` - рассылка из Reserv
- `/dodep_reserv` - повторная рассылка

## Возможные проблемы

### Ошибка "relation already exists"
Если таблица уже существует:
```bash
alembic stamp head
```

### Ошибка "No such column"
Пересоздайте миграцию:
```bash
alembic revision --autogenerate -m "create reserv table"
alembic upgrade head
```

### Проблемы с кодировкой Excel
Убедитесь, что файл res.xlsx сохранён в правильной кодировке (UTF-8)

## Структура таблицы Reserv

```sql
CREATE TABLE reserv (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    course VARCHAR(128),
    faculty VARCHAR(255),
    telegram_username VARCHAR(64) UNIQUE,
    message_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## Новые команды для бота

| Команда | Описание |
|---------|----------|
| `/poter` | Проверка совпадений telegram_username между Reserv и BotUser по факультетам |
| `/create_reserv_rass` | Создание рассылки для пользователей из таблицы Reserv |
| `/dodep_reserv` | Рассылка тем из Reserv, кому ещё не отправлялось (message_sent = False) |

## Примечания

- Все telegram_username приводятся к нижнему регистру при сравнении
- Флаг `message_sent` автоматически устанавливается в `True` после успешной отправки
- Рассылки работают только для пользователей, которые есть в BotUser

