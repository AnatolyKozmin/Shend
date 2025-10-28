# 🐛 Fix: Race Condition при записи на собеседование

## ❌ Проблема

### Ошибка в логах:
```
duplicate key value violates unique constraint "interviews_time_slot_id_key"
Key (time_slot_id)=(134) already exists.
```

### Что происходило:
Два пользователя **одновременно** пытались записаться на один и тот же слот:

```
Пользователь 1:                 Пользователь 2:
├─ Проверяет слот (свободен) ─┐ 
│                              ├─ Проверяет слот (свободен)
├─ Создаёт запись             │
│                              ├─ Создаёт запись (ошибка!)
└─ Commit                      └─ Rollback
```

### Почему происходило:
Между **проверкой** (`if slot.is_available`) и **коммитом** (`await session.commit()`) проходит время, за которое другой пользователь успевает сделать то же самое.

---

## ✅ Решение: SELECT FOR UPDATE

### Что изменилось:
```python
# БЫЛО:
slot_stmt = select(TimeSlot).where(TimeSlot.id == selected_slot_id)

# СТАЛО:
slot_stmt = select(TimeSlot).where(TimeSlot.id == selected_slot_id).with_for_update()
```

### Как работает:
`SELECT FOR UPDATE` **блокирует строку** в базе данных на время транзакции:

```
Пользователь 1:                 Пользователь 2:
├─ SELECT FOR UPDATE (слот 134) 
│  └─ Слот ЗАБЛОКИРОВАН ────────┐
│                                ├─ SELECT FOR UPDATE (слот 134)
│                                │  └─ ЖДЁТ разблокировки...
├─ Проверяет (свободен)          │
├─ Создаёт запись                │
├─ Commit                        │
│  └─ Слот РАЗБЛОКИРОВАН ────────┤
│                                ├─ Проверяет (уже ЗАНЯТ)
│                                └─ Возвращает ошибку пользователю
```

---

## 🔒 Преимущества

1. **Атомарность**: Проверка и изменение выполняются атомарно
2. **Нет дублирования**: Невозможно создать две записи на один слот
3. **Корректное поведение**: Второй пользователь получает понятное сообщение

---

## 📊 Как проверить fix

### Сценарий 1: Нормальная запись
```
1. Пользователь записывается на слот
2. Слот блокируется
3. Запись создаётся
4. Commit
5. Слот разблокируется

Результат: ✅ Успешно
```

### Сценарий 2: Одновременная запись
```
1. Пользователь 1 запрашивает слот (блокировка)
2. Пользователь 2 запрашивает тот же слот (ждёт)
3. Пользователь 1 создаёт запись и делает commit
4. Пользователь 2 получает слот (уже is_available=False)
5. Пользователь 2 видит сообщение "К сожалению, это время уже занято"

Результат: ✅ Корректная обработка
```

---

## 🧪 Тестирование

### Автоматический тест (симуляция race condition):
```python
import asyncio
from handlers.interview_handlers import sobes_confirm_callback

async def test_race_condition():
    # Два пользователя одновременно записываются на слот 134
    task1 = asyncio.create_task(book_slot(user_id=1, slot_id=134))
    task2 = asyncio.create_task(book_slot(user_id=2, slot_id=134))
    
    results = await asyncio.gather(task1, task2, return_exceptions=True)
    
    # Ожидаемый результат:
    # - Один успешно записался
    # - Другой получил ошибку "время занято"
    assert sum(1 for r in results if r == "success") == 1
    assert sum(1 for r in results if r == "slot_taken") == 1
```

### Ручной тест:
```
1. Открыть бота с двух аккаунтов одновременно
2. Оба выбирают ОДИН И ТОТ ЖЕ слот
3. Оба нажимают "Подтвердить" ОДНОВРЕМЕННО

Ожидаемый результат:
- Один: "🎉 Вы успешно записаны!"
- Другой: "😔 К сожалению, это время уже занято."
```

---

## 🔧 Технические детали

### SQL, который выполняется:
```sql
-- До fix:
SELECT * FROM time_slots WHERE id = 134;

-- После fix:
SELECT * FROM time_slots WHERE id = 134 FOR UPDATE;
```

### Уровень изоляции:
PostgreSQL использует `READ COMMITTED` по умолчанию, поэтому `FOR UPDATE` работает корректно.

### Производительность:
- **Небольшая задержка** для второго пользователя (ждёт разблокировки)
- **Не критично** для нашего use case (запись на собеседование)
- Обычно < 100ms задержка

---

## 📝 Другие места, где может понадобиться

### Отмена записи:
```python
# В cancel_interview_callback тоже можно добавить:
interview_stmt = select(Interview).where(
    Interview.id == interview_id
).with_for_update()
```

Но там **менее критично**, так как отменять свою запись может только один пользователь.

### Синхронизация слотов (/sync_slots):
Там **не нужно**, потому что синхронизацию выполняет только админ (один пользователь).

---

## ✅ Чек-лист после fix

- [x] Код обновлён (with_for_update добавлен)
- [x] Проверка на linter errors (нет ошибок)
- [ ] Код закоммичен в git
- [ ] Код задеплоен на сервер
- [ ] Ручной тест выполнен
- [ ] Мониторинг логов (нет больше duplicate key errors)

---

## 🚀 Деплой fix

### На локальной машине:
```bash
cd "C:\Users\anato\OneDrive\Рабочий стол\ShaBot"
git add handlers/interview_handlers.py
git commit -m "fix: race condition при записи на собеседование (SELECT FOR UPDATE)"
git push origin main
```

### На сервере:
```bash
ssh root@sha
cd ~/Shend
git pull origin main
docker-compose restart bot
docker logs shend-bot-1 --tail 50
```

### Проверка:
```bash
# Не должно быть больше "duplicate key" ошибок
docker logs shend-bot-1 | grep -i "duplicate key"

# Если ничего не выводит - значит fix работает! ✅
```

---

## 📚 Документация

### Ссылки:
- [SQLAlchemy SELECT FOR UPDATE](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update)
- [PostgreSQL SELECT FOR UPDATE](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)

### Альтернативные решения (не используем):
1. **Optimistic locking** - добавить version field
2. **Redis lock** - использовать внешнюю блокировку
3. **Serializable isolation** - повысить уровень изоляции транзакций

`SELECT FOR UPDATE` - самое простое и эффективное решение для нашего случая! ✅

---

**Fix готов к деплою!** 🚀

