# ⚠️ Обработка ошибок Telegram API

## "Query is too old" ошибка

### Что это?

Это стандартная ошибка Telegram API, которая возникает когда бот пытается ответить на callback query, который уже устарел (прошло больше 60 секунд).

```
TelegramBadRequest: Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid
```

### Причины:

1. **Медленный интернет** - пользователь нажал кнопку, но ответ пришёл слишком поздно
2. **Перезагрузка бота** - callback был создан до перезагрузки, а обработан после
3. **Долгая обработка** - обработчик выполнялся дольше 60 секунд
4. **Повторное нажатие** - пользователь несколько раз нажал на одну кнопку

### Это критично?

**Нет!** Это не ошибка в коде. Просто Telegram не может отправить всплывающее уведомление пользователю.

### Как обработано:

#### Вариант 1: Try-catch на каждый callback.answer()

```python
try:
    await callback.answer('Ответ сохранён!')
except TelegramBadRequest:
    pass  # Игнорируем ошибку "query too old"
```

#### Вариант 2: Использовать вспомогательную функцию

```python
from utils.telegram_helpers import safe_answer_callback

# Вместо:
await callback.answer('Ответ сохранён!')

# Используем:
await safe_answer_callback(callback, 'Ответ сохранён!')
```

### Где добавлена обработка:

1. ✅ `handlers/interview_handlers.py` - все callback.answer()
2. ✅ `handlers/admin_handlers.py` - handle_reserv_answer (строка 829)
3. ✅ `utils/telegram_helpers.py` - вспомогательная функция

### Другие распространённые ошибки:

#### "Message is not modified"

Возникает когда пытаемся изменить сообщение на точно такое же.

**Решение:**
```python
try:
    await message.edit_text(new_text)
except TelegramBadRequest as e:
    if "message is not modified" in str(e).lower():
        pass  # Сообщение уже такое
    else:
        raise
```

#### "Message to edit not found"

Сообщение было удалено пользователем.

**Решение:**
```python
try:
    await callback.message.edit_text(text)
except TelegramBadRequest as e:
    if "message to edit not found" in str(e).lower():
        # Отправить новое сообщение
        await callback.message.answer(text)
    else:
        raise
```

#### "Message can't be deleted"

Сообщение уже удалено или прошло 48 часов.

**Решение:**
```python
try:
    await message.delete()
except TelegramBadRequest:
    pass  # Уже удалено или нельзя удалить
```

---

## 📝 Рекомендации

1. **Всегда оборачивайте callback.answer()** в try-except
2. **Используйте `safe_answer_callback()`** для чистоты кода
3. **Не логируйте эту ошибку** - она не критична
4. **Основная функциональность должна работать** даже если callback.answer() не сработал

---

## ✅ Итог

Ошибки в логах - это нормально! Они обрабатываются корректно и не влияют на работу бота. Пользователь просто не увидит всплывающее уведомление, но все данные сохранятся правильно.

