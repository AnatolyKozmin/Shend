"""
Парсер для новой системы резерва - листы 'резерв' и 'финфак'
"""
import gspread
from typing import List, Dict, Tuple
from datetime import datetime
import time
from utils.google_sheets import get_google_sheets_client, _with_retries


# URL таблицы с расписанием резерва
RESERV_SHEET_URL = "https://docs.google.com/spreadsheets/d/1c6B_bwrvA1AUkMHtlL8YnzuzZhiZP_tnoZKSvpICn_c/edit?gid=1703868749#gid=1703868749"
RESERV_SHEET_ID = "1c6B_bwrvA1AUkMHtlL8YnzuzZhiZP_tnoZKSvpICn_c"

# Конфигурация листов
RESERV_SHEETS = {
    "резерв": {
        "date": "2025-11-08",  # 8 ноября 2025 - Резерв
        "for_faculty": None,  # Для всех факультетов
    },
    "финфак": {
        "date": "2025-11-07",  # 7 ноября 2025 - Финфак
        "for_faculty": "Финфак",  # Только для Финфака
    }
}

# Временные слоты (столбцы B-S)
# Индекс столбца (с 1): время
TIME_SLOTS_MAP = {
    1: "09:00",   # B
    2: "09:45",   # C
    3: "10:30",   # D
    4: "11:15",   # E
    5: "12:00",   # F
    6: "12:45",   # G
    7: "13:30",   # H
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


def parse_reserv_sheets(sheet_names: List[str] = None) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    Парсит листы резерва из Google Sheets.
    
    Args:
        sheet_names: Список имен листов для парсинга. Если None - парсятся все.
    
    Returns:
        Tuple[List[Dict], Dict]: (список слотов, статистика по собеседующим)
        
    Формат слота:
    {
        'interviewer_sheet_id': 'ID из колонки T',
        'interviewer_name': 'Имя Фамилия из колонки A',
        'sheet_name': 'резерв' или 'финфак',
        'date': '2025-11-05',
        'time_start': '09:00',
        'time_end': '09:45',
        'for_faculty': None или 'Финфак'
    }
    
    Формат статистики:
    {
        'interviewer_id': {
            'name': 'Имя Фамилия',
            'sheets': {
                'резерв': {'slots': 5, 'times': ['09:00', '10:30', ...]},
                'финфак': {'slots': 3, 'times': ['14:15', '15:00', ...]}
            },
            'total': 8
        }
    }
    """
    if sheet_names is None:
        sheet_names = list(RESERV_SHEETS.keys())
    
    all_slots = []
    interviewer_stats = {}  # {interviewer_id: {name, sheets: {sheet_name: {slots, times}}, total}}
    
    try:
        client = get_google_sheets_client()
        spreadsheet = _with_retries(client.open_by_key, RESERV_SHEET_ID)
        
        print(f"\n🔄 Начинаю парсинг резерва из таблицы...")
        print(f"📋 Таблица: {RESERV_SHEET_URL}\n")
        
        for sheet_name in sheet_names:
            if sheet_name not in RESERV_SHEETS:
                print(f"⚠️ Неизвестный лист: {sheet_name}, пропускаю")
                continue
            
            config = RESERV_SHEETS[sheet_name]
            date = config['date']
            for_faculty = config['for_faculty']
            
            print(f"{'='*60}")
            print(f"📄 Парсинг листа: '{sheet_name}'")
            print(f"📅 Дата: {date}")
            print(f"🎓 Для факультета: {for_faculty if for_faculty else 'Все'}")
            print(f"{'='*60}\n")
            
            try:
                worksheet = _with_retries(spreadsheet.worksheet, sheet_name)
                time.sleep(0.5)  # Защита от rate limit
                
                # Получаем все значения листа
                all_values = _with_retries(worksheet.get_all_values)
                
                if not all_values or len(all_values) < 2:
                    print(f"⚠️ Лист '{sheet_name}' пустой или содержит только заголовок\n")
                    continue
                
                # Парсим заголовок (первая строка) - там должны быть времена
                header_row = all_values[0]
                print(f"📋 Заголовок листа (первая строка):")
                print(f"   Колонка A: '{header_row[0] if len(header_row) > 0 else 'пусто'}'")
                
                # Выводим времена из заголовка (все без сокращений)
                times_in_header = []
                for col_idx in range(1, min(19, len(header_row))):  # B-S (индексы 1-18)
                    cell_value = header_row[col_idx].strip()
                    if cell_value:
                        times_in_header.append(f"{TIME_SLOTS_MAP.get(col_idx, '?')} ({cell_value})")
                
                if times_in_header:
                    print(f"   Времена: {', '.join(times_in_header)}")
                else:
                    print(f"   ⚠️ Времена в заголовке не найдены")
                
                print(f"   Колонка T: '{header_row[19] if len(header_row) > 19 else 'пусто'}'")
                print()
                
                # Парсим строки со 2-й (индекс 1) по 25-ю (индекс 24)
                # Но если строк меньше - парсим все что есть
                start_row = 1  # Индекс 1 = строка 2 в Google Sheets
                end_row = min(25, len(all_values))  # Индекс 24 = строка 25
                
                print(f"👥 Парсинг строк {start_row + 1}-{end_row} (собеседующие):\n")
                
                rows_parsed = 0
                rows_skipped = 0
                
                for row_idx in range(start_row, end_row):
                    row = all_values[row_idx]
                    
                    # Проверяем минимальную длину строки
                    if len(row) < 20:  # Нужно минимум A + B-S (18 колонок) + T
                        print(f"   ⚠️ Строка {row_idx + 1}: пропущена (недостаточно колонок, есть {len(row)})")
                        rows_skipped += 1
                        continue
                    
                    # Колонка A - Имя и Фамилия
                    interviewer_name = row[0].strip()
                    if not interviewer_name:
                        # Пустая строка - пропускаем молча
                        rows_skipped += 1
                        continue
                    
                    # Колонка T (индекс 19) - ID собеседующего
                    interviewer_sheet_id = row[19].strip() if len(row) > 19 else ''
                    if not interviewer_sheet_id:
                        print(f"   ⚠️ Строка {row_idx + 1} ('{interviewer_name}'): пропущена (нет ID в колонке T)")
                        rows_skipped += 1
                        continue
                    
                    # Счетчик слотов и список времен для этого собеседующего
                    slots_count = 0
                    slot_times = []
                    
                    # Парсим колонки B-S (индексы 1-18)
                    for col_idx, time_start in TIME_SLOTS_MAP.items():
                        if col_idx >= len(row):
                            continue
                        
                        cell_value = row[col_idx].strip().lower()
                        
                        # Ищем "могу" в ячейке
                        if 'могу' in cell_value and 'не могу' not in cell_value:
                            time_end = get_time_end(time_start)
                            
                            all_slots.append({
                                'interviewer_sheet_id': interviewer_sheet_id,
                                'interviewer_name': interviewer_name,
                                'sheet_name': sheet_name,
                                'date': date,
                                'time_start': time_start,
                                'time_end': time_end,
                                'for_faculty': for_faculty
                            })
                            
                            slots_count += 1
                            slot_times.append(time_start)
                    
                    if slots_count > 0:
                        # Сохраняем статистику
                        if interviewer_sheet_id not in interviewer_stats:
                            interviewer_stats[interviewer_sheet_id] = {
                                'name': interviewer_name,
                                'sheets': {},
                                'total': 0
                            }
                        
                        interviewer_stats[interviewer_sheet_id]['sheets'][sheet_name] = {
                            'slots': slots_count,
                            'times': slot_times
                        }
                        interviewer_stats[interviewer_sheet_id]['total'] += slots_count
                        
                        # Выводим информацию (ВСЕ времена без сокращений)
                        times_str = ', '.join(slot_times)
                        
                        print(f"   ✅ Строка {row_idx + 1}: {interviewer_name} (ID: {interviewer_sheet_id})")
                        print(f"      Слотов: {slots_count} | Времена: {times_str}")
                        rows_parsed += 1
                    else:
                        print(f"   ⚠️ Строка {row_idx + 1} ('{interviewer_name}'): нет доступных слотов")
                        rows_skipped += 1
                
                print(f"\n📊 Итого по листу '{sheet_name}':")
                print(f"   ✅ Обработано: {rows_parsed} собеседующих")
                print(f"   ⚠️ Пропущено: {rows_skipped} строк")
                print(f"   📦 Создано слотов: {sum(1 for s in all_slots if s['sheet_name'] == sheet_name)}\n")
                
                time.sleep(0.5)  # Задержка между листами
                
            except Exception as e:
                print(f"❌ Ошибка при парсинге листа '{sheet_name}': {e}\n")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n{'='*60}")
        print(f"🎉 ПАРСИНГ ЗАВЕРШЕН")
        print(f"{'='*60}")
        print(f"📦 Всего создано слотов: {len(all_slots)}")
        print(f"👥 Собеседующих со слотами: {len(interviewer_stats)}")
        print(f"{'='*60}\n")
        
        return all_slots, interviewer_stats
    
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА при парсинге: {e}")
        import traceback
        traceback.print_exc()
        return [], {}


def format_stats_message(interviewer_stats: Dict[str, Dict]) -> str:
    """
    Форматирует статистику для вывода в Telegram.
    
    Args:
        interviewer_stats: Статистика по собеседующим
    
    Returns:
        str: Отформатированное сообщение
    """
    if not interviewer_stats:
        return "📭 Нет данных для отображения"
    
    message = "📊 СТАТИСТИКА ПО СОБЕСЕДУЮЩИМ\n\n"
    
    # Сортируем по общему количеству слотов (убывание)
    sorted_interviewers = sorted(
        interviewer_stats.items(),
        key=lambda x: x[1]['total'],
        reverse=True
    )
    
    for interviewer_id, stats in sorted_interviewers:
        name = stats['name']
        total = stats['total']
        
        message += f"👤 {name} (ID: {interviewer_id})\n"
        message += f"   📦 Всего слотов: {total}\n"
        
        for sheet_name, sheet_data in stats['sheets'].items():
            slots = sheet_data['slots']
            times = sheet_data['times']
            
            # Выводим ВСЕ времена без сокращений
            times_str = ', '.join(times)
            
            message += f"   📄 {sheet_name}: {slots} слотов\n"
            message += f"      ⏰ {times_str}\n"
        
        message += "\n"
    
    return message

