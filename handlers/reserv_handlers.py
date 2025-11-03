"""
Обработчики для новой системы резерва
"""
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_, delete
from db.engine import async_session_maker
from db.models import Interviewer, BotUser, Person, ReservTimeSlot, ReservBooking
from utils.reserv_parser import parse_reserv_sheets, format_stats_message
from datetime import datetime


reserv_router = Router()

# ID администратора
ADMIN_ID = 922109605  # TODO: вынести в конфиг


@reserv_router.message(Command('parse_reserv'))
async def parse_reserv_command(message: types.Message):
    """
    Команда для парсинга листов 'резерв' и 'финфак' из Google Sheets.
    Доступна только администратору.
    
    Выводит детальную информацию о процессе парсинга и статистику.
    """
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа. Команда только для администратора.")
        return
    
    await message.answer("🔄 Начинаю парсинг листов 'резерв' и 'финфак'...\n\nЭто может занять несколько секунд...")
    
    try:
        # Парсим Google Sheets
        slots_data, interviewer_stats = parse_reserv_sheets()
        
        if not slots_data:
            await message.answer(
                "❌ Не удалось загрузить данные из Google Sheets.\n\n"
                "Проверьте:\n"
                "• Доступ к таблице\n"
                "• Наличие листов 'резерв' и 'финфак'\n"
                "• Правильность структуры таблицы"
            )
            return
        
        # Сохраняем в БД
        async with async_session_maker() as session:
            added = 0
            updated = 0
            skipped = 0
            errors = 0
            
            # Множество для отслеживания валидных слотов
            valid_slot_keys = set()  # (interviewer_id, sheet_name, date, time_start)
            touched_interviewers = {}  # {interviewer_id: sheet_names}
            
            for slot_info in slots_data:
                try:
                    # Находим собеседующего по interviewer_sheet_id
                    interviewer_stmt = select(Interviewer).where(
                        Interviewer.interviewer_sheet_id == slot_info['interviewer_sheet_id']
                    )
                    interviewer_result = await session.execute(interviewer_stmt)
                    interviewer = interviewer_result.scalars().first()
                    
                    if not interviewer:
                        # Собеседующий не зарегистрирован в системе - пропускаем
                        skipped += 1
                        continue
                    
                    # Отслеживаем какие листы затронуты для каждого собеседующего
                    if interviewer.id not in touched_interviewers:
                        touched_interviewers[interviewer.id] = set()
                    touched_interviewers[interviewer.id].add(slot_info['sheet_name'])
                    
                    # Проверяем, есть ли уже такой слот
                    existing_slot_stmt = select(ReservTimeSlot).where(
                        ReservTimeSlot.interviewer_id == interviewer.id,
                        ReservTimeSlot.sheet_name == slot_info['sheet_name'],
                        ReservTimeSlot.date == slot_info['date'],
                        ReservTimeSlot.time_start == slot_info['time_start']
                    )
                    existing_slot_result = await session.execute(existing_slot_stmt)
                    existing_slot = existing_slot_result.scalars().first()
                    
                    if existing_slot:
                        # Слот уже есть - обновляем только если он свободен
                        if existing_slot.is_available:
                            existing_slot.time_end = slot_info['time_end']
                            existing_slot.google_sheet_sync = datetime.now()
                            session.add(existing_slot)
                            updated += 1
                        else:
                            # Слот занят - не трогаем
                            skipped += 1
                    else:
                        # Создаем новый слот
                        new_slot = ReservTimeSlot(
                            interviewer_id=interviewer.id,
                            sheet_name=slot_info['sheet_name'],
                            date=slot_info['date'],
                            time_start=slot_info['time_start'],
                            time_end=slot_info['time_end'],
                            is_available=True,
                            google_sheet_sync=datetime.now()
                        )
                        session.add(new_slot)
                        added += 1
                    
                    # Добавляем ключ валидного слота
                    valid_slot_keys.add((
                        interviewer.id,
                        slot_info['sheet_name'],
                        slot_info['date'],
                        slot_info['time_start']
                    ))
                
                except Exception as e:
                    print(f"Ошибка обработки слота: {e}")
                    errors += 1
            
            # Сохраняем изменения
            await session.commit()
            
            # Очистка: удаляем устаревшие свободные слоты
            stale_deleted = 0
            try:
                for interviewer_id, sheet_names in touched_interviewers.items():
                    for sheet_name in sheet_names:
                        # Получаем все слоты этого собеседующего на этом листе
                        slots_stmt = select(ReservTimeSlot).where(
                            ReservTimeSlot.interviewer_id == interviewer_id,
                            ReservTimeSlot.sheet_name == sheet_name
                        )
                        all_slots_res = await session.execute(slots_stmt)
                        all_slots = all_slots_res.scalars().all()
                        
                        for slot in all_slots:
                            key = (interviewer_id, sheet_name, slot.date, slot.time_start)
                            if key not in valid_slot_keys:
                                # Слот отсутствует в актуальном листе
                                if slot.is_available:
                                    # Проверяем отсутствие активной записи
                                    existing_booking_stmt = select(ReservBooking).where(
                                        ReservBooking.time_slot_id == slot.id,
                                        ReservBooking.status == 'confirmed'
                                    )
                                    existing_booking_res = await session.execute(existing_booking_stmt)
                                    existing_booking = existing_booking_res.scalars().first()
                                    
                                    if not existing_booking:
                                        await session.delete(slot)
                                        stale_deleted += 1
                
                if stale_deleted > 0:
                    await session.commit()
            
            except Exception as e:
                print(f"⚠️ Ошибка очистки устаревших слотов: {e}")
            
            # Формируем сообщение со статистикой
            stats_message = (
                f"✅ Парсинг завершен!\n\n"
                f"📊 Общая статистика:\n"
                f"• Добавлено новых слотов: {added}\n"
                f"• Обновлено существующих: {updated}\n"
                f"• Пропущено (занято или нет в системе): {skipped}\n"
            )
            
            if stale_deleted > 0:
                stats_message += f"• Удалено устаревших: {stale_deleted}\n"
            
            if errors > 0:
                stats_message += f"• ⚠️ Ошибок: {errors}\n"
            
            stats_message += f"\n📋 Всего обработано: {len(slots_data)} слотов из Google Sheets\n"
            
            await message.answer(stats_message)
            
            # Отправляем детальную статистику по собеседующим
            if interviewer_stats:
                detailed_stats = format_stats_message(interviewer_stats)
                
                # Разбиваем на части если сообщение слишком длинное
                max_length = 4000
                if len(detailed_stats) <= max_length:
                    await message.answer(detailed_stats)
                else:
                    # Отправляем по частям
                    parts = []
                    current_part = "📊 СТАТИСТИКА ПО СОБЕСЕДУЮЩИМ\n\n"
                    
                    for line in detailed_stats.split('\n')[2:]:  # Пропускаем заголовок
                        if len(current_part + line + '\n') > max_length:
                            parts.append(current_part)
                            current_part = line + '\n'
                        else:
                            current_part += line + '\n'
                    
                    if current_part.strip():
                        parts.append(current_part)
                    
                    for i, part in enumerate(parts, 1):
                        header = f"📊 СТАТИСТИКА (часть {i}/{len(parts)})\n\n" if len(parts) > 1 else ""
                        await message.answer(header + part)
    
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        import traceback
        traceback.print_exc()
        
        await message.answer(
            f"❌ Произошла ошибка при парсинге:\n{str(e)}\n\n"
            "Проверьте:\n"
            "• Доступ к Google Sheets\n"
            "• Правильность credentials\n"
            "• Структуру таблицы"
        )

