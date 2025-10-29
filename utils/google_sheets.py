"""
Модуль для работы с Google Sheets
"""
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict, Optional
import time


# URL таблицы с собеседующими
INTERVIEWERS_SHEET_URL = "https://docs.google.com/spreadsheets/d/132W-Q8bZhyPbfOmJkXpfRLsOZ3l-pqHpO8vmy8hxGec/edit?gid=0#gid=0"
INTERVIEWERS_SHEET_ID = "132W-Q8bZhyPbfOmJkXpfRLsOZ3l-pqHpO8vmy8hxGec"


def get_google_sheets_client():
    """Создаёт клиента для работы с Google Sheets."""
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Используем JSON файл с credentials
    # Проверяем оба возможных имени файла
    import os
    if os.path.exists('sha-otbor-476513-9c6d0a1d252c.json'):
        credentials_file = 'sha-otbor-476513-9c6d0a1d252c.json'
    elif os.path.exists('credentials.json'):
        credentials_file = 'credentials.json'
    else:
        raise FileNotFoundError("Не найден файл credentials (sha-otbor-476513-9c6d0a1d252c.json или credentials.json)")
    
    creds = Credentials.from_service_account_file(
        credentials_file,
        scopes=scope
    )
    
    client = gspread.authorize(creds)
    return client


def get_interviewers_data() -> List[Dict[str, str]]:
    """
    Читает данные собеседующих из Google Sheets.
    
    Returns:
        List[Dict]: Список словарей с данными:
        [
            {
                'full_name': 'Иванов Иван',
                'access_code': '12345',
                'interviewer_sheet_id': 'interviewer_001'
            },
            ...
        ]
    """
    try:
        client = get_google_sheets_client()
        sheet = client.open_by_key(INTERVIEWERS_SHEET_ID)
        worksheet = sheet.worksheet('лист')
        
        # Получаем все значения (начиная с A1)
        all_values = worksheet.get_all_values()
        
        interviewers = []
        for row in all_values:
            if len(row) >= 3 and row[0]:  # Проверяем что есть минимум 3 колонки и ФИО не пустое
                # Пропускаем заголовки если есть
                if row[0].lower() in ['фио', 'фамилия', 'имя']:
                    continue
                    
                interviewers.append({
                    'full_name': row[0].strip(),
                    'access_code': row[1].strip() if len(row) > 1 else '',
                    'interviewer_sheet_id': row[2].strip() if len(row) > 2 else ''
                })
        
        return interviewers
    
    except Exception as e:
        print(f"Ошибка при чтении Google Sheets: {e}")
        return []


def find_interviewer_by_code(access_code: str) -> Optional[Dict[str, str]]:
    """
    Находит собеседующего по коду доступа.
    
    Args:
        access_code: Код доступа (5 цифр)
    
    Returns:
        Dict или None: Данные собеседующего или None если не найден
    """
    interviewers = get_interviewers_data()
    
    for interviewer in interviewers:
        if interviewer['access_code'] == access_code:
            return interviewer
    
    return None


# URL таблицы с расписанием
SCHEDULE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1b89aY_hiv1qaPvE5Iuwr_lKYsvo1e3l3qtOZYSHQoQU/edit"
SCHEDULE_SHEET_ID = "1b89aY_hiv1qaPvE5Iuwr_lKYsvo1e3l3qtOZYSHQoQU"

# Маппинг листов на даты и факультеты
# Новая структура: листы "1"-"6", столбец A - имя, столбец T - ID, B-S - слоты
SCHEDULE_SHEETS = {
    "1": {
        "faculties": ["МЭО", "СНиМК"],  # Вместе в одном здании
        "date": "2024-10-29"  # Дата будет обновляться
    },
    "2": {
        "faculties": ["ФЭБ"],
        "date": "2024-10-30"
    },
    "3": {
        "faculties": ["Юрфак"],
        "date": "2024-10-31"
    },
    "4": {
        "faculties": ["ИТиАБД"],
        "date": "2024-11-01"
    },
    "5": {
        "faculties": ["ФинФак"],
        "date": "2024-11-02"
    },
    "6": {
        "faculties": ["НАБ", "ВШУ"],  # Вместе в одном здании
        "date": "2024-11-06"
    }
}

# Временные слоты (столбцы B-S)
# Индекс столбца (с 0): время
TIME_SLOTS = {
    1: "09:00",   # B
    2: "09:45",   # C
    3: "10:30",   # D
    4: "11:15",   # E
    5: "12:00",   # F
    6: "12:45",   # G
    7: "13:30",   # H - ОБЕД, пропускаем!
    8: "14:15",   # I
    9: "15:00",   # J
    10: "15:45",  # K
    11: "16:30",  # L
    12: "17:15",  # M
    13: "18:00",  # N
    14: "18:45",  # O
    15: "19:15",  # P
    16: "20:00",  # Q
    17: "20:45",  # R
    18: "21:30"   # S
}

# Длительность слота в минутах
SLOT_DURATION = 45


def get_time_end(time_start: str) -> str:
    """Вычисляет время окончания слота."""
    hours, minutes = map(int, time_start.split(':'))
    total_minutes = hours * 60 + minutes + SLOT_DURATION
    end_hours = total_minutes // 60
    end_minutes = total_minutes % 60
    return f"{end_hours:02d}:{end_minutes:02d}"


def get_schedules_data() -> tuple[List[Dict[str, any]], Dict[str, int]]:
    """
    Читает расписание слотов из Google Sheets (листы "1"-"6").
    
    Формат каждого листа:
    - Столбец A: Имя и фамилия собеседующего
    - Столбец T (индекс 19): ID собеседующего
    - Столбцы B-S (индексы 1-18): Временные слоты (1 = доступен, пусто = недоступен)
    
    Returns:
        tuple: (список слотов, статистика по собеседующим)
        - List[Dict]: Список слотов
        - Dict[str, int]: Статистика {interviewer_name: количество_слотов}
    """
    all_slots = []
    interviewer_stats = {}  # Статистика по собеседующим
    
    try:
        client = get_google_sheets_client()
        sheet = client.open_by_key(SCHEDULE_SHEET_ID)
        
        print("🔄 Начинаю парсинг расписания из Google Sheets...")
        
        # Проходим по всем листам
        for sheet_name, info in SCHEDULE_SHEETS.items():
            date = info['date']
            faculties = info['faculties']
            faculties_str = ', '.join(faculties)
            
            try:
                print(f"\n📋 Обрабатываю лист '{sheet_name}': {faculties_str}")
                worksheet = sheet.worksheet(sheet_name)
                time.sleep(1)  # Защита от rate limit Google API
                
                # Получаем все значения листа
                all_values = worksheet.get_all_values()
                
                # Проходим по всем строкам (пропускаем заголовок если есть)
                for row_idx, row in enumerate(all_values):
                    if len(row) < 20:  # Минимум должно быть A + B-S + T (20 колонок)
                        continue
                    
                    interviewer_name = row[0].strip()  # Колонка A
                    if not interviewer_name:  # Пустая строка - пропускаем
                        continue
                    
                    # Пропускаем заголовки
                    if interviewer_name.lower() in ['имя', 'фио', 'собеседующий', 'время', 'name']:
                        continue
                    
                    interviewer_sheet_id = row[19].strip() if len(row) > 19 else ''  # Колонка T (индекс 19)
                    if not interviewer_sheet_id:  # Нет ID - пропускаем
                        print(f"    ⚠️ Пропущен '{interviewer_name}' (строка {row_idx + 1}): нет ID в колонке T")
                        continue
                    
                    # Счётчик слотов для этого собеседующего
                    slots_count = 0
                    
                    # Проходим по временным слотам (B-S, индексы 1-18)
                    for col_idx, time_start in TIME_SLOTS.items():
                        # Пропускаем обед (13:30)
                        if time_start == "13:30":
                            continue
                        
                        if col_idx >= len(row):
                            continue
                        
                        cell_value = str(row[col_idx]).strip()
                        
                        # Если в ячейке "1" - слот доступен
                        if cell_value == "1":
                            time_end = get_time_end(time_start)
                            
                            all_slots.append({
                                'interviewer_sheet_id': interviewer_sheet_id,
                                'interviewer_name': interviewer_name,
                                'date': date,
                                'time_start': time_start,
                                'time_end': time_end,
                                'faculties': faculties  # Список факультетов для этого листа
                            })
                            
                            slots_count += 1
                    
                    # Сохраняем статистику
                    if slots_count > 0:
                        key = f"{interviewer_name} ({interviewer_sheet_id})"
                        interviewer_stats[key] = interviewer_stats.get(key, 0) + slots_count
                        print(f"    ✅ {interviewer_name}: {slots_count} слотов")
                
                time.sleep(0.5)  # Небольшая задержка между листами
                
            except Exception as e:
                print(f"⚠️ Ошибка при чтении листа '{sheet_name}': {e}")
                continue
        
        print(f"\n📊 Всего загружено слотов: {len(all_slots)}")
        print(f"👥 Собеседующих с слотами: {len(interviewer_stats)}")
        
        return all_slots, interviewer_stats
    
    except Exception as e:
        print(f"❌ Ошибка при чтении расписания: {e}")
        return [], {}

