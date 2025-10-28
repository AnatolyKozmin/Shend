-- 🔧 Скрипт для исправления несоответствий между interviews и time_slots

-- Проблема: В БД есть записи (interviews) на слоты, 
-- но слоты (time_slots) помечены как доступные (is_available=true)

-- ===== ШАГ 1: Найти проблемные слоты =====

SELECT 
    ts.id as slot_id,
    ts.date,
    ts.time_start,
    ts.time_end,
    ts.is_available as slot_available,
    i.id as interview_id,
    i.status as interview_status,
    i.bot_user_id
FROM time_slots ts
LEFT JOIN interviews i ON i.time_slot_id = ts.id AND i.status IN ('confirmed', 'pending')
WHERE 
    -- Слот помечен как доступный
    ts.is_available = true
    -- Но на него есть активная запись
    AND i.id IS NOT NULL
ORDER BY ts.date, ts.time_start;

-- Ожидаемый результат: список слотов, которые заняты, но помечены как свободные


-- ===== ШАГ 2: Исправить is_available для занятых слотов =====

UPDATE time_slots
SET is_available = false
WHERE id IN (
    SELECT ts.id
    FROM time_slots ts
    INNER JOIN interviews i ON i.time_slot_id = ts.id
    WHERE 
        ts.is_available = true
        AND i.status IN ('confirmed', 'pending')
);

-- Это установит is_available=false для всех слотов, на которые есть активная запись


-- ===== ШАГ 3: Освободить слоты с отменёнными записями =====

UPDATE time_slots
SET is_available = true
WHERE id IN (
    SELECT DISTINCT ts.id
    FROM time_slots ts
    LEFT JOIN interviews i ON i.time_slot_id = ts.id AND i.status IN ('confirmed', 'pending')
    WHERE 
        ts.is_available = false
        AND i.id IS NULL
);

-- Это освободит слоты, на которых нет активных записей


-- ===== ШАГ 4: Проверка результата =====

-- Слоты с несоответствиями (должно быть 0 строк):
SELECT 
    COUNT(*) as inconsistent_slots
FROM time_slots ts
LEFT JOIN interviews i ON i.time_slot_id = ts.id AND i.status IN ('confirmed', 'pending')
WHERE 
    (ts.is_available = true AND i.id IS NOT NULL)  -- Слот свободен, но есть запись
    OR 
    (ts.is_available = false AND i.id IS NULL);    -- Слот занят, но нет записи

-- Статистика по слотам:
SELECT 
    'Всего слотов' as category,
    COUNT(*) as count
FROM time_slots
UNION ALL
SELECT 
    'Доступных слотов',
    COUNT(*)
FROM time_slots
WHERE is_available = true
UNION ALL
SELECT 
    'Занятых слотов',
    COUNT(*)
FROM time_slots
WHERE is_available = false
UNION ALL
SELECT 
    'Активных записей',
    COUNT(*)
FROM interviews
WHERE status IN ('confirmed', 'pending')
UNION ALL
SELECT 
    'Отменённых записей',
    COUNT(*)
FROM interviews
WHERE status = 'cancelled';


-- ===== ШАГ 5: Найти дублирующиеся записи (если есть) =====

-- Слоты с несколькими активными записями (не должно быть):
SELECT 
    time_slot_id,
    COUNT(*) as interview_count
FROM interviews
WHERE status IN ('confirmed', 'pending')
GROUP BY time_slot_id
HAVING COUNT(*) > 1;

-- Если есть дубли, удалить старые (оставить самую свежую):
-- ВНИМАНИЕ: Выполнять только если есть дубли!
/*
DELETE FROM interviews
WHERE id IN (
    SELECT id FROM (
        SELECT 
            id,
            ROW_NUMBER() OVER (PARTITION BY time_slot_id ORDER BY created_at DESC) as rn
        FROM interviews
        WHERE status IN ('confirmed', 'pending')
    ) t
    WHERE rn > 1
);
*/

