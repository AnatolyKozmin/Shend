# 🐛 Отладка проблемы с освобождением слотов

## 📊 Проблема

После отмены записи через бота (кнопка "❌ Отменить запись") слот не освобождается и при попытке записаться снова возникает ошибка:
```
duplicate key value violates unique constraint "interviews_time_slot_id_key"
```

## 🔍 Что добавлено

Добавлено логирование в критических местах:

### 1. При создании записи:
```python
print(f"🔒 Блокирую слот {slot.id}: is_available={slot.is_available} -> False")
slot.is_available = False
# ... commit ...
print(f"✅ Запись создана, slot_id={slot.id}, interview_id={interview.id}")
```

### 2. При отмене записи:
```python
print(f"🔓 Освобождаю слот {slot.id}: is_available={slot.is_available} -> True")
slot.is_available = True
# ... commit ...
print(f"✅ Отмена записи {interview.id} завершена, слот {interview.time_slot_id} освобождён")
```

### 3. Если слот не найден:
```python
print(f"⚠️ Слот не найден для interview {interview.id}, time_slot_id={interview.time_slot_id}")
```

## 🚀 Как тестировать

### Шаг 1: Задеплоить код с логами
```bash
# На локальной машине
cd "C:\Users\anato\OneDrive\Рабочий стол\ShaBot"
git add handlers/interview_handlers.py
git commit -m "debug: добавлено логирование для отладки слотов"
git push origin main

# На сервере
ssh root@sha
cd ~/Shend
git pull origin main
docker-compose restart bot
```

### Шаг 2: Очистить БД (начать с чистого листа)
```bash
echo "
DELETE FROM interview_messages;
DELETE FROM interviews;
UPDATE time_slots SET is_available = true;
SELECT COUNT(*) as free_slots FROM time_slots WHERE is_available = true;
SELECT COUNT(*) as interviews FROM interviews;
" | docker exec -i shend-db-1 psql -U postgres -d shabot_db
```

### Шаг 3: Тест полного цикла
```
1. Открыть бота
2. /sobes → записаться на слот
3. Смотреть логи (должно быть: 🔒 Блокирую слот ...)
4. Нажать "❌ Отменить запись"
5. Смотреть логи (должно быть: 🔓 Освобождаю слот ...)
6. Попробовать записаться снова на тот же слот
7. Должно работать без ошибок!
```

### Шаг 4: Смотреть логи в реальном времени
```bash
docker logs shend-bot-1 -f
```

Ожидаемые логи:
```
🔒 Блокирую слот 134: is_available=True -> False
✅ Запись создана, slot_id=134, interview_id=123
🔓 Освобождаю слот 134: is_available=False -> True
✅ Отмена записи 123 завершена, слот 134 освобождён
🔒 Блокирую слот 134: is_available=True -> False
✅ Запись создана, slot_id=134, interview_id=124
```

## 🔍 Что искать в логах

### ✅ Нормальное поведение:
```
🔒 Блокирую слот X: is_available=True -> False
✅ Запись создана
🔓 Освобождаю слот X: is_available=False -> True
✅ Отмена записи завершена
```

### ❌ Проблема #1: Слот уже заблокирован
```
🔒 Блокирую слот X: is_available=False -> False  ← Проблема!
```
Это значит что `is_available` уже был `False` при попытке записи.

### ❌ Проблема #2: Слот не найден
```
⚠️ Слот не найден для interview Y, time_slot_id=X
```
Это значит что слот был удалён из БД или `time_slot_id` некорректен.

### ❌ Проблема #3: Commit не срабатывает
Если вы видите:
```
🔓 Освобождаю слот X: is_available=False -> True
```
Но НЕ видите:
```
✅ Отмена записи завершена
```
Значит `commit()` упал с ошибкой. Смотрите след строки в логах на наличие трейсбека.

## 📊 SQL для проверки состояния БД

### Проверить конкретный слот:
```sql
-- Посмотреть слот и все записи на него
SELECT 
    ts.id as slot_id,
    ts.is_available,
    ts.date,
    ts.time_start,
    i.id as interview_id,
    i.status as interview_status,
    i.created_at
FROM time_slots ts
LEFT JOIN interviews i ON i.time_slot_id = ts.id
WHERE ts.id = 134  -- замените на нужный слот
ORDER BY i.created_at DESC;
```

### Найти все несоответствия:
```sql
-- Слоты помечены как свободные, но на них есть активная запись
SELECT 
    ts.id,
    ts.is_available,
    i.id as interview_id,
    i.status
FROM time_slots ts
JOIN interviews i ON i.time_slot_id = ts.id
WHERE ts.is_available = true
AND i.status IN ('confirmed', 'pending');
```

## 🔧 Временное решение (если проблема повторяется)

Если после отмены записи слот не освобождается:

```sql
-- Вручную освободить конкретный слот
UPDATE time_slots 
SET is_available = true 
WHERE id = 134;  -- замените на нужный ID

-- Или освободить все слоты без активных записей
UPDATE time_slots
SET is_available = true
WHERE id IN (
    SELECT DISTINCT ts.id
    FROM time_slots ts
    LEFT JOIN interviews i ON i.time_slot_id = ts.id AND i.status IN ('confirmed', 'pending')
    WHERE ts.is_available = false AND i.id IS NULL
);
```

## 📝 Возможные причины

1. **Exception при commit** - транзакция откатывается
2. **Слот не найден** - `time_slot_id` некорректен
3. **Race condition** - (уже исправлено через `FOR UPDATE`)
4. **Ручное удаление из БД** - удаление interview без освобождения слота

## ✅ После отладки

Когда найдём причину и исправим, **удалить логи** из продакшен-кода:

```python
# Убрать все print() из handlers/interview_handlers.py
```

---

**Готово к тестированию!** 🚀

Запусти полный цикл и пришли логи - разберёмся что не так! 🔍

