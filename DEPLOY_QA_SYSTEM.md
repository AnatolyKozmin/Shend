# 🚀 Деплой системы вопросов/ответов

## 📋 Что было сделано

### 1. Код
- ✅ Добавлена FSM для вопросов/ответов (`QuestionStates`)
- ✅ Обработчик "Задать вопрос" (`ask_question_callback`)
- ✅ Обработчик ввода вопроса (`process_question`)
- ✅ Обработчик "Ответить на вопрос" (`answer_question_callback`)
- ✅ Обработчик ввода ответа (`process_answer`)
- ✅ Команда `/my_interviews` для собеседующих
- ✅ Импорт `InterviewMessage` в handlers

### 2. База данных
- ✅ Таблица `interview_messages` уже создана в миграции
- ✅ Связи настроены корректно

### 3. Документация
- ✅ `INTERVIEW_QA_SYSTEM.md` - описание системы
- ✅ `TESTING_QA_SYSTEM.md` - инструкция по тестированию
- ✅ `BOT_COMMANDS_LIST.md` - обновлён список команд
- ✅ `DEPLOY_QA_SYSTEM.md` - эта инструкция

---

## 🎯 Пошаговая инструкция деплоя

### Шаг 1: Коммит и пуш (на локальной машине)
```bash
cd "C:\Users\anato\OneDrive\Рабочий стол\ShaBot"

# Проверить изменения
git status

# Добавить все файлы
git add .

# Сделать коммит
git commit -m "feat: добавлена система вопросов/ответов для собеседований

- Кандидаты могут задавать вопросы собеседующим
- Собеседующие получают уведомления и могут отвечать
- Добавлена команда /my_interviews для просмотра записей
- Валидация сообщений (макс 1000 символов)
- Сохранение всех сообщений в БД
- Обновлена документация"

# Запушить в репозиторий
git push origin main
```

### Шаг 2: Пулл на сервере
```bash
# Подключиться к серверу
ssh root@sha

# Перейти в директорию проекта
cd ~/Shend

# Забэкапить текущую версию (на всякий случай)
cp -r handlers handlers_backup_$(date +%Y%m%d_%H%M%S)

# Получить изменения
git pull origin main

# Проверить что файлы обновились
ls -la handlers/interview_handlers.py
```

### Шаг 3: Проверка миграций
```bash
# База данных уже должна быть готова, но проверим
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "\d interview_messages"

# Если таблицы нет (не должно быть, но на всякий случай):
# docker-compose exec bot alembic upgrade head
```

### Шаг 4: Перезапуск бота
```bash
# Остановить контейнеры
docker-compose down

# Запустить заново (пересоберёт если нужно)
docker-compose up -d

# Проверить логи
docker logs shend-bot-1 --tail 50 -f

# Должно быть что-то типа:
# INFO:aiogram:Bot started successfully
# No errors
```

### Шаг 5: Быстрая проверка
```bash
# Проверить что бот жив
curl -s https://api.telegram.org/bot<TOKEN>/getMe

# Проверить таблицу interviewers
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "SELECT id, full_name, telegram_id FROM interviewers LIMIT 3;"

# Проверить таблицу interview_messages (должна быть пустая)
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "SELECT COUNT(*) FROM interview_messages;"
```

---

## 🧪 Быстрый тест функционала

### Тест 1: Команда /my_interviews
```
1. Открыть бота как собеседующий (кто уже зарегистрирован)
2. Отправить: /my_interviews
3. Должен вывести список записей или сообщение "У вас пока нет записей"
```

### Тест 2: Задать вопрос
```
1. Открыть бота как кандидат
2. /sobes → выбрать время → записаться
3. Нажать "❓ Задать вопрос"
4. Ввести текст вопроса
5. Проверить что собеседующий получил уведомление
```

### Тест 3: Ответить на вопрос
```
1. Открыть бота как собеседующий
2. Нажать "💬 Ответить на вопрос" в уведомлении
3. Ввести ответ
4. Проверить что кандидат получил уведомление с ответом
```

---

## 🐛 Troubleshooting

### Проблема: Бот не запускается
```bash
# Смотрим логи
docker logs shend-bot-1 --tail 100

# Если есть ошибки импорта:
docker-compose build bot --no-cache
docker-compose up -d
```

### Проблема: Кнопки не работают
```bash
# Проверяем обработчики в коде
docker exec -it shend-bot-1 grep -n "ask_question:" /app/handlers/interview_handlers.py

# Должно быть две строки:
# - callback_data=f"ask_question:{interview_id}"
# - F.data.startswith('ask_question:')
```

### Проблема: Не сохраняются сообщения
```bash
# Проверяем таблицу
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "SELECT * FROM interview_messages ORDER BY created_at DESC LIMIT 5;"

# Проверяем права
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "\dt interview_messages"
```

### Проблема: TelegramBadRequest
```bash
# Смотрим логи на наличие "query too old"
docker logs shend-bot-1 | grep -i "TelegramBadRequest"

# Это нормально, но не должно ломать функционал
# У нас есть try-except блоки
```

---

## 📊 Мониторинг после деплоя

### Первые 30 минут
```bash
# Следить за логами в реальном времени
docker logs shend-bot-1 -f

# Ctrl+C для выхода
```

### Первый день
```bash
# Проверять статистику каждые 2-3 часа
docker exec -it shend-db-1 psql -U postgres -d shabot_db -c "
SELECT 
    COUNT(*) as total_messages,
    COUNT(DISTINCT interview_id) as interviews_with_messages,
    COUNT(CASE WHEN is_read = true THEN 1 END) as read_messages
FROM interview_messages;"
```

### Полезные SQL запросы
```sql
-- Последние 10 сообщений
SELECT 
    id,
    interview_id,
    from_user_id,
    to_user_id,
    LEFT(message_text, 50) as message,
    is_read,
    created_at
FROM interview_messages
ORDER BY created_at DESC
LIMIT 10;

-- Самые активные интервью (больше всего сообщений)
SELECT 
    interview_id,
    COUNT(*) as message_count
FROM interview_messages
GROUP BY interview_id
ORDER BY message_count DESC
LIMIT 5;

-- Процент прочитанных сообщений
SELECT 
    ROUND(100.0 * COUNT(CASE WHEN is_read = true THEN 1 END) / COUNT(*), 2) as read_percentage
FROM interview_messages;
```

---

## ✅ Чек-лист финального деплоя

### Перед деплоем
- [ ] Код закоммичен и запушен
- [ ] Миграции готовы
- [ ] Документация обновлена
- [ ] Протестировано локально (если возможно)

### Деплой
- [ ] Код получен на сервере (git pull)
- [ ] Бот перезапущен
- [ ] Логи проверены (нет критических ошибок)
- [ ] Быстрый тест выполнен

### После деплоя
- [ ] Мониторинг логов первые 30 мин
- [ ] Тест всех сценариев из TESTING_QA_SYSTEM.md
- [ ] Обратная связь от пользователей
- [ ] Документация отправлена админам/собеседующим

---

## 🎉 Успех!

Если все чек-листы пройдены, система готова к использованию! 🚀

### Что дальше?

1. **Обучение пользователей:**
   - Отправить инструкцию собеседующим
   - Объяснить кандидатам про вопросы
   - Провести демо если нужно

2. **Сбор метрик:**
   - Сколько вопросов задано
   - Средняя скорость ответа
   - Удовлетворённость пользователей

3. **Улучшения (опционально):**
   - История переписки
   - Массовые ответы (FAQ)
   - Статистика по вопросам

---

**Удачного деплоя!** 💪

