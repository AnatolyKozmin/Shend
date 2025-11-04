"""
Экспорт записей на собеседования в Google Sheets для финфака
"""
import asyncio
from typing import Optional
from utils.google_sheets import get_google_sheets_client, _with_retries
from db.models import FinfakBooking, FinfakTimeSlot, Interviewer, Person


# ID таблицы для финфака (та же таблица что и для резерва)
FINFAK_SHEET_ID = "1c6B_bwrvA1AUkMHtlL8YnzuzZhiZP_tnoZKSvpICn_c"

# Маппинг времени на индекс столбца (B=1, C=2, ..., S=18)
TIME_TO_COLUMN = {
    "09:00": 1,   # B
    "09:45": 2,   # C
    "10:30": 3,   # D
    "11:15": 4,   # E
    "12:00": 5,   # F
    "12:45": 6,   # G
    "13:30": 7,   # H
    "14:15": 8,   # I
    "15:00": 9,   # J
    "15:45": 10,  # K
    "16:30": 11,  # L
    "17:15": 12,  # M
    "18:00": 13,  # N
    "18:45": 14,  # O
    "19:15": 15,  # P
    "20:00": 16,  # Q
    "20:45": 17,  # R
    "21:30": 18   # S
}


async def export_finfak_booking_to_sheets(
    booking: FinfakBooking,
    slot: FinfakTimeSlot,
    interviewer: Interviewer,
    person: Person
) -> bool:
    """
    Экспортирует запись на собеседование в Google Sheets.
    
    Выполняется асинхронно с задержкой для защиты от rate limiting.
    При ошибке не падает, а логирует проблему.
    
    Args:
        booking: Запись на собеседование
        slot: Временной слот
        interviewer: Собеседующий
        person: Кандидат
    
    Returns:
        bool: True если успешно, False при ошибке
    """
    # Задержка для защиты от rate limiting (2 секунды)
    await asyncio.sleep(2)
    
    try:
        print(f"\n📤 Начинаю экспорт записи в Google Sheets...")
        print(f"   Кандидат: {person.full_name}")
        print(f"   Собеседующий: {interviewer.full_name} (ID: {interviewer.interviewer_sheet_id})")
        print(f"   Время: {slot.time_start}")
        
        # 1. Экспорт в лист "финфак_записи" (матричная запись)
        success_matrix = await _export_to_finfak_matrix(
            interviewer_sheet_id=interviewer.interviewer_sheet_id,
            time_start=slot.time_start,
            candidate_name=person.full_name
        )
        
        # Небольшая задержка между запросами
        await asyncio.sleep(1)
        
        # 2. Экспорт в лист "всеобщая" (построчная запись)
        success_all = await _export_to_all_sheet(
            candidate_name=person.full_name,
            sheet_type="финфак",
            interviewer_id=interviewer.interviewer_sheet_id,
            interviewer_username=interviewer.telegram_username,
            candidate_username=person.telegram_username,
            time=slot.time_start
        )
        
        if success_matrix and success_all:
            print(f"   ✅ Экспорт успешно завершен!")
            return True
        else:
            print(f"   ⚠️ Экспорт завершен с ошибками")
            return False
    
    except Exception as e:
        print(f"   ❌ Ошибка экспорта: {e}")
        # Не падаем, просто логируем
        return False


async def _export_to_finfak_matrix(
    interviewer_sheet_id: str,
    time_start: str,
    candidate_name: str
) -> bool:
    """
    Экспортирует запись в лист "финфак_записи" (матричная таблица).
    
    Находит строку по ID собеседующего (колонка T),
    находит столбец по времени (B-S),
    записывает ФИО кандидата.
    """
    try:
        # Получаем клиента и открываем таблицу
        client = get_google_sheets_client()
        spreadsheet = _with_retries(client.open_by_key, FINFAK_SHEET_ID)
        
        # Открываем лист "финфак_записи"
        try:
            worksheet = _with_retries(spreadsheet.worksheet, "финфак_записи")
        except Exception as e:
            print(f"      ⚠️ Лист 'финфак_записи' не найден: {e}")
            return False
        
        # Получаем все значения листа
        all_values = _with_retries(worksheet.get_all_values)
        
        if not all_values or len(all_values) < 2:
            print(f"      ⚠️ Лист 'финфак_записи' пустой")
            return False
        
        # Ищем строку с нужным собеседующим (по колонке T, индекс 19)
        target_row = None
        for row_idx, row in enumerate(all_values):
            if len(row) > 19:
                cell_value = row[19].strip()
                if cell_value == interviewer_sheet_id:
                    target_row = row_idx + 1  # +1 потому что нумерация с 1
                    break
        
        if not target_row:
            print(f"      ⚠️ Собеседующий с ID '{interviewer_sheet_id}' не найден в таблице")
            return False
        
        # Находим столбец по времени
        column_index = TIME_TO_COLUMN.get(time_start)
        
        if not column_index:
            print(f"      ⚠️ Неизвестное время: {time_start}")
            return False
        
        # Преобразуем индекс столбца в букву (1=B, 2=C, ...)
        # A=0, B=1, C=2, но нам нужно B=1 в нашем маппинге
        # Значит column_index уже правильный для формулы (B=1)
        column_letter = chr(ord('A') + column_index)  # A + 1 = B
        
        # Формируем адрес ячейки (например, "B5")
        cell_address = f"{column_letter}{target_row}"
        
        print(f"      📍 Записываю в ячейку {cell_address}")
        
        # Записываем ФИО кандидата
        _with_retries(worksheet.update, cell_address, [[candidate_name]])
        
        print(f"      ✅ Запись в 'финфак_записи' успешна")
        return True
    
    except Exception as e:
        print(f"      ❌ Ошибка записи в 'финфак_записи': {e}")
        import traceback
        traceback.print_exc()
        return False


async def _export_to_all_sheet(
    candidate_name: str,
    sheet_type: str,
    interviewer_id: str,
    interviewer_username: Optional[str],
    candidate_username: Optional[str],
    time: str
) -> bool:
    """
    Экспортирует запись в лист "всеобщая" (построчная таблица).
    
    Добавляет строку с информацией о записи.
    """
    try:
        # Получаем клиента и открываем таблицу
        client = get_google_sheets_client()
        spreadsheet = _with_retries(client.open_by_key, FINFAK_SHEET_ID)
        
        # Открываем лист "всеобщая"
        try:
            worksheet = _with_retries(spreadsheet.worksheet, "всеобщая")
        except Exception:
            # Если листа нет - создаем
            print(f"      📋 Создаю лист 'всеобщая'...")
            worksheet = _with_retries(spreadsheet.add_worksheet, title="всеобщая", rows=1000, cols=10)
            
            # Добавляем заголовки
            headers = [
                "ФИО кандидата",
                "Тип",
                "ID проводящего",
                "Username проводящего",
                "Username кандидата",
                "Время"
            ]
            _with_retries(worksheet.update, 'A1', [headers])
            
            # Форматируем заголовок
            _with_retries(worksheet.format, 'A1:F1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
            })
        
        # Форматируем username'ы
        interviewer_username_str = f"@{interviewer_username}" if interviewer_username else "не указан"
        if interviewer_username and interviewer_username.startswith('@'):
            interviewer_username_str = interviewer_username
        
        candidate_username_str = f"@{candidate_username}" if candidate_username else "не указан"
        if candidate_username and candidate_username.startswith('@'):
            candidate_username_str = candidate_username
        
        # Формируем строку для добавления
        row_data = [
            candidate_name,
            sheet_type,
            interviewer_id,
            interviewer_username_str,
            candidate_username_str,
            time
        ]
        
        print(f"      📍 Добавляю строку в 'всеобщая'")
        
        # Добавляем строку
        _with_retries(worksheet.append_row, row_data, value_input_option='RAW')
        
        print(f"      ✅ Запись в 'всеобщая' успешна")
        return True
    
    except Exception as e:
        print(f"      ❌ Ошибка записи в 'всеобщая': {e}")
        import traceback
        traceback.print_exc()
        return False

