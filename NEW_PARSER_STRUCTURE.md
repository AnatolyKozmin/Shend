# 🔄 Новая структура парсера Google Sheets

## 📋 Что изменилось

### Старая структура:
- Листы с названиями типа "29.10 / СНиМК + МЭО"
- Разные диапазоны строк для разных факультетов
- ID собеседующего в столбце W (индекс 22)

### Новая структура:
- Листы с простыми названиями: **"1", "2", "3", "4", "5", "6"**
- Все строки парсятся одинаково
- ID собеседующего в столбце **T (индекс 19)**

---

## 📊 Маппинг листов на факультеты

| Лист | Факультеты | Описание |
|------|-----------|----------|
| **"1"** | МЭО + СНиМК | Одно здание, один день |
| **"2"** | ФЭБ | |
| **"3"** | Юрфак | |
| **"4"** | ИТиАБД | |
| **"5"** | ФинФак | |
| **"6"** | НАБ + ВШУ | Одно здание, один день |

---

## 📝 Формат каждого листа

### Столбцы:
- **A**: Имя и фамилия собеседующего
- **B-S** (индексы 1-18): Временные слоты
  - `1` = собеседующий доступен
  - пусто = недоступен
- **T** (индекс 19): ID собеседующего (из регистрационной таблицы)

### Временные слоты (B-S):
```
B  = 09:00
C  = 09:45
D  = 10:30
E  = 11:15
F  = 12:00
G  = 12:45
H  = 13:30  ← ОБЕД (пропускается!)
I  = 14:15
J  = 15:00
K  = 15:45
L  = 16:30
M  = 17:15
N  = 18:00
O  = 18:45
P  = 19:15
Q  = 20:00
R  = 20:45
S  = 21:30
```

---

## 🔧 Как работает парсер

### 1. Проходит по всем листам ("1"-"6")
```python
for sheet_name in ["1", "2", "3", "4", "5", "6"]:
    worksheet = sheet.worksheet(sheet_name)
    faculties = SCHEDULE_SHEETS[sheet_name]['faculties']
```

### 2. Для каждой строки:
```python
interviewer_name = row[0]  # Столбец A
interviewer_id = row[19]   # Столбец T

if not interviewer_name or not interviewer_id:
    continue  # Пропускаем пустые строки
```

### 3. Для каждого временного слота:
```python
for col_idx in range(1, 19):  # B-S
    if row[col_idx] == "1":
        # Создаём слот в БД
        create_slot(interviewer_id, date, time_start, time_end, faculties)
```

---

## 🎯 Ключевые особенности

### 1. Множественные слоты на одно время
Если 4 собеседующих свободны в 9:00, создаётся **4 отдельных слота** в БД:
```
TimeSlot(interviewer_id=1, time_start="09:00", is_available=True)
TimeSlot(interviewer_id=2, time_start="09:00", is_available=True)
TimeSlot(interviewer_id=3, time_start="09:00", is_available=True)
TimeSlot(interviewer_id=4, time_start="09:00", is_available=True)
```

Когда кандидат записывается, занимается **только один** из них:
```
TimeSlot(interviewer_id=2, time_start="09:00", is_available=False)  ← Занят!
```

### 2. Догрузка данных
При повторном `/sync_slots`:
- ✅ Добавляются **новые** слоты
- ✅ Обновляются **свободные** слоты
- ❌ **НЕ трогаются** занятые слоты (`is_available=False`)
- ❌ **НЕ удаляются** старые слоты

### 3. Факультеты собеседующих
Факультеты **накапливаются**, не перезаписываются:
```python
# Первый sync: лист "1" (МЭО, СНиМК)
interviewer.faculties = "МЭО,СНиМК"

# Второй sync: лист "6" (НАБ, ВШУ)
interviewer.faculties = "МЭО,НАБ,СНиМК,ВШУ"  # Добавились!
```

---

## 📊 Команда /sobeser_stats

Показывает статистику по всем собеседующим:

```
📊 Статистика по собеседующим

👤 Иванов Иван
   ID: interviewer_001
   🎓 Факультеты: МЭО,СНиМК
   📊 Слотов: 12 (🟢 8 свободно, 🔴 4 занято)

👤 Петрова Анна
   ID: interviewer_002
   🎓 Факультеты: ФЭБ
   📊 Слотов: 8 (🟢 8 свободно, 🔴 0 занято)

━━━━━━━━━━━━━━━━━━━━
Итого:
👥 Собеседующих: 15
📊 Всего слотов: 180
🟢 Свободно: 145
🔴 Занято: 35
```

---

## 🔄 Процесс синхронизации

### Шаг 1: Очистка БД (опционально)
```bash
echo "
DELETE FROM interview_messages;
DELETE FROM interviews;
DELETE FROM time_slots;
" | docker exec -i shend-db-1 psql -U postgres -d shabot_db
```

### Шаг 2: Синхронизация
```
В боте: /sync_slots
```

Что происходит:
1. Парсятся все листы "1"-"6"
2. Для каждого собеседующего:
   - Находится в БД по `interviewer_sheet_id`
   - Обновляются факультеты
   - Создаются/обновляются слоты
3. Выводится статистика

### Шаг 3: Проверка
```
В боте: /sobeser_stats
```

---

## 🎓 Показ слотов кандидатам

### Как определяется факультет:
```python
# 1. Из таблицы people
person = get_person(user_id)
faculty = person.faculty  # "МЭО"

# 2. Или выбор из списка
faculties = ["МЭО", "СНиМК", "ФЭБ", "Юрфак", ...]
```

### Какие слоты показываются:
```sql
SELECT * FROM time_slots 
JOIN interviewers ON interviewers.id = time_slots.interviewer_id
WHERE time_slots.is_available = true
AND interviewers.faculties LIKE '%МЭО%'  -- Факультет кандидата
ORDER BY time_slots.date, time_slots.time_start
```

### Группировка по времени:
Если 4 собеседующих свободны в 9:00, кандидат видит **одну** кнопку "09:00".

При нажатии **случайно выбирается** один из 4 слотов.

---

## 🐛 Обработка ошибок

### Пустые строки:
```python
if not interviewer_name or not interviewer_id:
    continue  # Пропускаем
```

### Собеседующий не зарегистрирован:
```python
if not interviewer:
    skipped += 1
    continue  # Пропускаем слот
```

### Занятый слот:
```python
if existing_slot and not existing_slot.is_available:
    skipped += 1  # Не трогаем!
```

---

## 📝 Изменённые файлы

### 1. `utils/google_sheets.py`
- Обновлён `SCHEDULE_SHEETS` (листы "1"-"6")
- Изменён индекс столбца ID: 22 → 19 (W → T)
- Упрощена логика парсинга (нет диапазонов строк)

### 2. `handlers/interview_handlers.py`
- Добавлена команда `/sobeser_stats`
- `/sync_slots` уже работал правильно (не удаляет, не трогает занятые)

### 3. `NEW_PARSER_STRUCTURE.md`
- Эта документация

---

## 🚀 Деплой

```bash
# Локально
git add utils/google_sheets.py handlers/interview_handlers.py NEW_PARSER_STRUCTURE.md
git commit -m "feat: новая структура парсера (листы 1-6, столбец T), команда /sobeser_stats"
git push origin main

# На сервере
ssh root@sha
cd ~/Shend
git pull origin main
docker-compose restart bot

# Очистить БД
echo "DELETE FROM interview_messages; DELETE FROM interviews; DELETE FROM time_slots;" | docker exec -i shend-db-1 psql -U postgres -d shabot_db

# Синхронизировать
В боте: /sync_slots

# Проверить
В боте: /sobeser_stats
```

---

## ✅ Преимущества новой структуры

1. **Проще** - листы "1"-"6" вместо длинных названий
2. **Единообразно** - все листы одинаковые
3. **Надёжнее** - нет диапазонов строк (парсим все)
4. **Гибче** - можно добавлять собеседующих без перезаписи
5. **Масштабируемо** - легко добавить лист "7", "8" и т.д.

---

**Готово к тестированию!** 🎯🚀

