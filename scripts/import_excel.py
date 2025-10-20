"""Импорт данных из Excel (.xlsx) в таблицу Person.

Usage:
  python scripts/import_excel.py path/to/file.xlsx

Требования:
  pip install openpyxl

Скрипт пытается автоматически сопоставить заголовки колонок (рус/англ):
  - ФИО (fio, full_name, name)
  - Курс (course)
  - Факультет (faculty)
  - Телеграм / Telegram / username (с @ или без)

Правила:
  - username нормализуется (удаляется ведущий @) и приводится к нижнему регистру.
  - Если username уже есть в БД — запись пропускается.
  - Если username пустой, используется комбинация (full_name, faculty, course) для определения дублей внутри БД и в файле; дубликаты в файле пропускаются (берём первое вхождение).

Скрипт использует асинхронный sessionmaker из `db.engine` и модель `Person` из `db.models`.
"""

import sys
import asyncio
import pathlib
from typing import Optional

try:
    import openpyxl
except Exception as e:
    print('Ошибка: модуль openpyxl не установлен. Установите: pip install openpyxl')
    raise

from db.engine import async_session_maker
from db.models import Person
from sqlalchemy import text


def detect_columns(header_row):
    """Возвращает mapping col_index->field_name"""
    mapping = {}
    for idx, cell in enumerate(header_row, start=1):
        if cell.value is None:
            continue
        h = str(cell.value).strip().lower()
        if 'фио' in h or 'фамилия' in h or 'имя' in h or 'full' in h:
            mapping['full_name'] = idx
        elif 'курс' in h or 'course' in h:
            mapping['course'] = idx
        elif 'фак' in h or 'faculty' in h:
            mapping['faculty'] = idx
        elif 'телег' in h or 'telegram' in h or 'username' in h or 'tg' in h:
            mapping['telegram_username'] = idx
    return mapping


def normalize_username(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith('@'):
        s = s[1:]
    return s.lower()


async def import_excel(file_path: str):
    wb = openpyxl.load_workbook(file_path, read_only=True)
    sheet = wb.active

    # Данные идут без заголовков; фиксированный порядок колонок:
    # 1 - ФИО, 2 - Курс, 3 - Факультет, 4 - tg_username
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        print('Файл пустой')
        return

    # Подгружаем существующие значения из БД для ускорения проверок
    async with async_session_maker() as session:
        res = await session.execute(text("SELECT telegram_username, lower(full_name), lower(coalesce(faculty, '')), lower(coalesce(course, '')) FROM people"))
        rows_db = res.fetchall()

    existing_usernames = set()
    existing_composites = set()
    for r in rows_db:
        db_username = r[0]
        if db_username:
            existing_usernames.add(str(db_username).lstrip('@').lower())
        fn = r[1] or ''
        fac = r[2] or ''
        co = r[3] or ''
        existing_composites.add((fn, fac, co))

    to_add = []
    seen_in_file = set()
    skipped_existing_db = 0
    skipped_duplicates_in_file = 0


    for r in rows:
        # r is a tuple of cell values; fixed positions
        full_name = r[0] if len(r) >= 1 else None
        if not full_name:
            # пропускаем пустые строки
            continue
        full_name_s = str(full_name).strip()

        course = r[1] if len(r) >= 2 else None
        course_s = str(course).strip() if course else ''

        faculty = r[2] if len(r) >= 3 else None
        faculty_s = str(faculty).strip() if faculty else ''

        tg_raw = r[3] if len(r) >= 4 else None
        tg_norm = normalize_username(tg_raw)

        key = tg_norm if tg_norm else (full_name_s.lower(), faculty_s.lower(), course_s.lower())
        if key in seen_in_file:
            skipped_duplicates_in_file += 1
            continue
        seen_in_file.add(key)

        # Пропускаем, если username уже в БД
        if tg_norm and tg_norm in existing_usernames:
            skipped_existing_db += 1
            continue

        # Пропускаем если composite уже в БД
        composite = (full_name_s.lower(), faculty_s.lower(), course_s.lower())
        if composite in existing_composites:
            skipped_existing_db += 1
            continue

        p = Person(full_name=full_name_s, course=course_s or None, faculty=faculty_s or None, telegram_username=tg_norm)
        to_add.append(p)

        # пометим как существующее, чтобы предотвратить дубликаты следующими строками
        if tg_norm:
            existing_usernames.add(tg_norm)
        existing_composites.add(composite)

    if not to_add:
        print(f'Ничего не добавлено. Пропущено по базе: {skipped_existing_db}, дубликаты в файле: {skipped_duplicates_in_file}')
        return

    async with async_session_maker() as session:
        session.add_all(to_add)
        await session.commit()

    print(f'Импорт завершён. Добавлено: {len(to_add)}. Пропущено по базе: {skipped_existing_db}. Дубликатов в файле: {skipped_duplicates_in_file}')


def main():
    if len(sys.argv) < 2:
        # По умолчанию ищем файл Persons.xlsx в корне проекта
        path = 'user_data.xlsx'
        print(f'Путь к файлу не указан. Попытка использовать: {path}')
    else:
        path = sys.argv[1]
    p = pathlib.Path(path)
    if not p.exists():
        print('Файл не найден:', path)
        return
    asyncio.run(import_excel(str(p)))


if __name__ == '__main__':
    main()
