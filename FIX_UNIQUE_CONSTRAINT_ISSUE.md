# 🐛 FIX: Проблема с UNIQUE constraint на time_slot_id

## ❌ Проблема

После отмены записи и попытки записаться снова на тот же слот:
```
duplicate key value violates unique constraint "interviews_time_slot_id_key"
Key (time_slot_id)=(193) already exists.
```

## 🔍 Причина

### Структура таблицы `interviews`:
```sql
CREATE TABLE interviews (
    id SERIAL PRIMARY KEY,
    time_slot_id INTEGER UNIQUE,  ← ВОТ ОНА, ПРОБЛЕМА!
    interviewer_id INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    ...
);
```

### Что происходит:
1. Пользователь записывается → создаётся `Interview` с `time_slot_id=193`, `status='confirmed'`
2. Пользователь отменяет → `Interview.status` меняется на `'cancelled'` (запись **НЕ удаляется**)
3. Пользователь пытается записаться снова → попытка создать **новую** `Interview` с `time_slot_id=193`
4. ❌ **ОШИБКА**: `UNIQUE constraint` на `time_slot_id` нарушен!

### Почему проверка не помогла:
```python
# Мы проверяем только активные записи:
existing = select(Interview).where(
    time_slot_id == 193,
    status IN ('confirmed', 'pending')  ← отменённые не попадают!
)
```

Но в БД висит **отменённая запись** с `status='cancelled'` и `time_slot_id=193`, которая нарушает UNIQUE!

---

## ✅ Решение: Удалять отменённые записи перед созданием новой

### Что изменилось:
```python
# ДОБАВЛЕНО перед созданием новой записи:

# Удаляем старые отменённые записи на этот слот
cancelled_interviews = select(Interview).where(
    Interview.time_slot_id == selected_slot_id,
    Interview.status == 'cancelled'
).all()

for cancelled in cancelled_interviews:
    print(f"🗑️ Удаляю отменённую запись {cancelled.id}")
    session.delete(cancelled)

if cancelled_interviews:
    await session.flush()  # Применяем удаление перед вставкой

# ТЕПЕРЬ можно создать новую запись
interview = Interview(time_slot_id=selected_slot_id, ...)
```

### Почему это работает:
1. **Удаляем все отменённые записи** на этот слот
2. **Flush** применяет удаление в рамках транзакции
3. **Создаём новую запись** - теперь UNIQUE constraint не нарушен
4. **Commit** сохраняет всё атомарно

---

## 🎯 Альтернативные решения (не используем)

### Вариант 1: Изменить UNIQUE constraint
```sql
-- Убрать старый constraint
ALTER TABLE interviews DROP CONSTRAINT interviews_time_slot_id_key;

-- Добавить partial UNIQUE index
CREATE UNIQUE INDEX interviews_time_slot_id_active_idx 
ON interviews (time_slot_id) 
WHERE status IN ('confirmed', 'pending');
```

**Минусы:** Нужна миграция, может сломать существующие данные.

### Вариант 2: Всегда удалять при отмене
```python
# В cancel_interview_callback:
session.delete(interview)  # вместо interview.status = 'cancelled'
```

**Минусы:** Теряем историю, нельзя посмотреть кто отменял.

### Вариант 3: Убрать UNIQUE constraint совсем
```sql
ALTER TABLE interviews DROP CONSTRAINT interviews_time_slot_id_key;
```

**Минусы:** Можно случайно создать дубли, нужна более сложная логика проверок.

---

## 📊 Как это выглядит в логах

### До fix:
```
SELECT ... WHERE status IN ('confirmed', 'pending')  ← Ничего не нашёл
🔒 Блокирую слот 193
INSERT INTO interviews ...
❌ duplicate key ... (193) already exists  ← ОШИБКА!
ROLLBACK
```

### После fix:
```
SELECT ... WHERE status IN ('confirmed', 'pending')  ← Ничего не нашёл
SELECT ... WHERE status = 'cancelled'                ← Нашёл старую запись!
🗑️ Удаляю отменённую запись 123
FLUSH (удаление применилось)
🔒 Блокирую слот 193
INSERT INTO interviews ...                           ← Успешно!
✅ Запись создана
COMMIT
```

---

## 🧪 Тестирование

### Сценарий 1: Запись → Отмена → Запись снова
```
1. /sobes → записаться на слот 193
   Ожидаемо: ✅ Запись создана, interview_id=100

2. Нажать "❌ Отменить запись"
   Ожидаемо: ✅ Отмена завершена, слот освобождён
   В БД: Interview(id=100, status='cancelled', time_slot_id=193)

3. /sobes → записаться на тот же слот 193
   Ожидаемо: 
   - 🗑️ Удаляю отменённую запись 100
   - ✅ Запись создана, interview_id=101
   В БД: Interview(id=101, status='confirmed', time_slot_id=193)
```

### Сценарий 2: Несколько отмен на один слот
```
1. Пользователь A записался → отменил
2. Пользователь B записался → отменил
3. Пользователь C записался → отменил

В БД: 3 записи со status='cancelled' на slot 193

4. Пользователь D пытается записаться
   Ожидаемо:
   - 🗑️ Удаляю отменённую запись (A)
   - 🗑️ Удаляю отменённую запись (B)
   - 🗑️ Удаляю отменённую запись (C)
   - ✅ Запись создана для D
```

---

## 📝 SQL для проверки

### Посмотреть все записи на конкретный слот:
```sql
SELECT 
    id,
    time_slot_id,
    status,
    bot_user_id,
    created_at,
    cancelled_at
FROM interviews
WHERE time_slot_id = 193
ORDER BY created_at DESC;
```

### Найти слоты с несколькими записями:
```sql
SELECT 
    time_slot_id,
    COUNT(*) as count,
    STRING_AGG(status, ', ') as statuses
FROM interviews
GROUP BY time_slot_id
HAVING COUNT(*) > 1
ORDER BY count DESC;
```

### Очистить все отменённые записи (если нужно):
```sql
DELETE FROM interviews WHERE status = 'cancelled';
```

---

## ✅ Преимущества решения

1. **Не нужна миграция** - работает с текущей схемой БД
2. **Атомарность** - всё в одной транзакции
3. **Логи** - видно когда и что удаляется
4. **Безопасность** - удаляем только отменённые записи
5. **История сохраняется** - пока запись активна, она в БД

---

## 🚀 Деплой

```bash
# На локальной машине
git add handlers/interview_handlers.py
git commit -m "fix: удаление отменённых записей перед созданием новой (UNIQUE constraint)"
git push origin main

# На сервере
ssh root@sha
cd ~/Shend
git pull origin main
docker-compose restart bot

# Тест
/sobes → записаться → отменить → записаться снова
Должно работать без ошибок! ✅
```

---

**Fix готов!** 🎯 Теперь можно записываться повторно на тот же слот после отмены! 🚀

