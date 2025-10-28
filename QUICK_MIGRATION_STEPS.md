# ⚡ Быстрая инструкция по применению миграций

## 📝 Что делать СЕЙЧАС

### 1️⃣ Закоммитить изменения (ЛОКАЛЬНО)

```bash
git add .
git commit -m "Add interview booking system with Google Sheets integration"
git push
```

### 2️⃣ На сервере: Применить миграции

```bash
# Подключиться к серверу
ssh root@YOUR_SERVER

# Перейти в проект и обновить код
cd /root/Shend
git pull

# Зайти в контейнер
docker exec -it shend-bot-1 bash

# Создать миграцию
alembic revision --autogenerate -m "add interview system tables and fields"

# Применить миграцию
alembic upgrade head

# Выйти
exit

# Пересобрать и перезапустить
docker-compose build
docker-compose down
docker-compose up -d
```

### 3️⃣ Скопировать JSON credentials

```bash
# На локальной машине
scp C:\Users\anato\Downloads\sha-otbor-476513-9c6d0a1d252c.json root@YOUR_SERVER:/root/Shend/
```

### 4️⃣ Дать доступ к Google Sheets

**Email:** `sha-bot-sobes@sha-otbor-476513.iam.gserviceaccount.com`

Добавить к двум таблицам (роль: Читатель):

1. **Таблица с паролями:**  
   https://docs.google.com/spreadsheets/d/132W-Q8bZhyPbfOmJkXpfRLsOZ3l-pqHpO8vmy8hxGec
   
2. **Таблица с расписанием:**  
   https://docs.google.com/spreadsheets/d/1b89aY_hiv1qaPvE5Iuwr_lKYsvo1e3l3qtOZYSHQoQU

### 5️⃣ Протестировать

```
В Telegram:
1. /register_sobes - регистрация собеседующего
2. /sync_slots - синхронизация слотов (от админа)
```

---

## 🎯 Всё в одной команде (после git push)

```bash
ssh root@YOUR_SERVER "cd /root/Shend && git pull && docker exec -it shend-bot-1 alembic revision --autogenerate -m 'add interview system' && docker exec -it shend-bot-1 alembic upgrade head && docker-compose build && docker-compose down && docker-compose up -d"
```

---

## ✅ Готово!

После этого:
- ✅ Таблицы созданы
- ✅ Бот работает
- ✅ Можно регистрировать собеседующих
- ✅ Можно синхронизировать слоты

Используйте `APPLY_MIGRATION.md` для подробной инструкции с устранением проблем.

