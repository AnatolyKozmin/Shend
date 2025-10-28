# 🔧 Инструкция по применению миграций

## 📋 Что нужно сделать

Применить миграции для добавления таблиц системы собеседований:
- `interviewers` - собеседующие
- `time_slots` - временные слоты
- `interviews` - записи на собеседования
- `interview_messages` - сообщения между студентом и собеседующим

## 🚀 Пошаговая инструкция

### Шаг 1: Подготовка на локальной машине

```bash
# Закоммитить все изменения
git add .
git commit -m "Add interview booking system with Google Sheets integration"
git push
```

### Шаг 2: Обновить код на сервере

```bash
# Подключиться к серверу
ssh root@YOUR_SERVER

# Перейти в директорию проекта
cd /root/Shend

# Подтянуть изменения
git pull
```

### Шаг 3: Скопировать JSON credentials (если ещё не скопирован)

```bash
# На локальной машине (в другом терминале)
scp C:\Users\anato\Downloads\sha-otbor-476513-9c6d0a1d252c.json root@YOUR_SERVER:/root/Shend/

# Или на сервере - загрузить как-то иначе
```

### Шаг 4: Создать миграцию

```bash
# Зайти в контейнер с ботом
docker exec -it shend-bot-1 bash

# Создать миграцию автоматически
alembic revision --autogenerate -m "add interview system tables and fields"

# Alembic создаст файл migration/versions/XXXX_add_interview_system_tables_and_fields.py
```

### Шаг 5: Проверить миграцию (опционально)

```bash
# Посмотреть содержимое созданной миграции
ls -la migration/versions/
cat migration/versions/XXXX_add_interview_system_tables_and_fields.py

# Должны быть операции:
# - op.create_table('interviewers', ...)
# - op.create_table('time_slots', ...)
# - op.create_table('interviews', ...)
# - op.create_table('interview_messages', ...)
```

### Шаг 6: Применить миграцию

```bash
# Применить миграцию
alembic upgrade head

# Вы должны увидеть:
# INFO  [alembic.runtime.migration] Running upgrade XXXX -> YYYY, add interview system tables and fields
```

### Шаг 7: Проверить что таблицы созданы

```bash
# Выйти из контейнера бота
exit

# Зайти в контейнер postgres
docker exec -it shend-postgres-1 psql -U shabot -d shabot

# Проверить список таблиц
\dt

# Должны быть:
# - interviewers
# - time_slots
# - interviews
# - interview_messages

# Посмотреть структуру таблиц
\d interviewers
\d time_slots
\d interviews
\d interview_messages

# Выйти из postgres
\q
```

### Шаг 8: Пересобрать и перезапустить бота

```bash
# Вернуться в директорию проекта
cd /root/Shend

# Пересобрать контейнер (установить новые зависимости: gspread, google-auth)
docker-compose build

# Перезапустить
docker-compose down
docker-compose up -d

# Проверить логи
docker-compose logs -f bot

# Должно быть: "Бот работает !"
# Ctrl+C чтобы выйти из логов
```

### Шаг 9: Дать доступ к Google Sheets

**Email сервисного аккаунта:** `sha-bot-sobes@sha-otbor-476513.iam.gserviceaccount.com`

#### Таблица 1: Пароли собеседующих
https://docs.google.com/spreadsheets/d/132W-Q8bZhyPbfOmJkXpfRLsOZ3l-pqHpO8vmy8hxGec

1. Открыть таблицу
2. Кнопка "Настройки доступа" / "Поделиться"
3. Добавить: `sha-bot-sobes@sha-otbor-476513.iam.gserviceaccount.com`
4. Роль: **Читатель**
5. Сохранить

#### Таблица 2: Расписание
https://docs.google.com/spreadsheets/d/1b89aY_hiv1qaPvE5Iuwr_lKYsvo1e3l3qtOZYSHQoQU

1. Открыть таблицу
2. Кнопка "Настройки доступа" / "Поделиться"
3. Добавить: `sha-bot-sobes@sha-otbor-476513.iam.gserviceaccount.com`
4. Роль: **Читатель**
5. Сохранить

### Шаг 10: Протестировать

#### Тест 1: Регистрация собеседующего

```
1. Открыть бота в Telegram
2. Отправить: /register_sobes
3. Ввести код из таблицы (5 цифр)
4. Подтвердить ФИО
5. Должно быть: "✅ Регистрация успешно завершена!"
```

#### Тест 2: Синхронизация слотов (от админа)

```
1. От админа (tg_id: 922109605)
2. Отправить: /sync_slots
3. Должна начаться синхронизация
4. Должна быть статистика:
   • Добавлено новых слотов: X
   • Обновлено существующих: X
   • Пропущено: X
```

#### Тест 3: Проверить БД

```bash
docker exec -it shend-postgres-1 psql -U shabot -d shabot

# Проверить собеседующих
SELECT id, full_name, telegram_id, interviewer_sheet_id FROM interviewers;

# Проверить слоты
SELECT id, interviewer_id, date, time_start, is_available FROM time_slots LIMIT 10;

\q
```

---

## 🔥 Быстрая команда (всё в одном)

Если всё настроено и нужно просто применить миграцию:

```bash
cd /root/Shend && \
git pull && \
docker exec -it shend-bot-1 alembic revision --autogenerate -m "add interview system tables and fields" && \
docker exec -it shend-bot-1 alembic upgrade head && \
docker-compose build && \
docker-compose down && \
docker-compose up -d && \
docker-compose logs -f bot
```

---

## ⚠️ Возможные проблемы

### Проблема 1: "Container not found"

**Причина:** Контейнер не запущен

**Решение:**
```bash
cd /root/Shend
docker-compose up -d
# Подождать 5 секунд
docker exec -it shend-bot-1 bash
```

### Проблема 2: "alembic: command not found"

**Причина:** Не установлены зависимости

**Решение:**
```bash
cd /root/Shend
docker-compose build
docker-compose up -d
```

### Проблема 3: "No changes detected"

**Причина:** Модели не изменились или уже есть в БД

**Решение:**
```bash
# Проверить что models.py обновлён
cat db/models.py | grep "class Interviewer"

# Если модели есть, но миграции не создаются:
# Возможно таблицы уже существуют
docker exec -it shend-postgres-1 psql -U shabot -d shabot -c "\dt"
```

### Проблема 4: "ModuleNotFoundError: No module named 'gspread'"

**Причина:** Зависимости не установлены

**Решение:**
```bash
cd /root/Shend
docker-compose build --no-cache
docker-compose up -d
```

### Проблема 5: "Error reading Google Sheets"

**Причина:** Нет доступа к таблицам или нет JSON файла

**Решение:**
1. Проверить что файл `sha-otbor-476513-9c6d0a1d252c.json` в `/root/Shend/`
2. Проверить что email добавлен в обе таблицы
3. Проверить права файла: `chmod 644 sha-otbor-476513-9c6d0a1d252c.json`

---

## ✅ Критерий успеха

После выполнения всех шагов:

- ✅ Бот запущен и работает
- ✅ В БД есть таблицы: `interviewers`, `time_slots`, `interviews`, `interview_messages`
- ✅ Команда `/register_sobes` работает
- ✅ Команда `/sync_slots` работает (для админа)
- ✅ Google Sheets читаются без ошибок

---

**Готово!** Теперь система собеседований работает! 🚀

