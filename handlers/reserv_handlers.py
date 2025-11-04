"""
Обработчики для новой системы резерва
"""
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_, delete, func
from db.engine import async_session_maker
from db.models import Interviewer, BotUser, Person, ReservTimeSlot, ReservBooking, FinfakTimeSlot, FinfakBooking
from utils.reserv_parser import parse_reserv_sheets, format_stats_message
from utils.finfak_export import export_finfak_booking_to_sheets
from utils.reserv_export import export_reserv_booking_to_sheets
from datetime import datetime
import pytz
import random
import asyncio


reserv_router = Router()

# ID администратора
ADMIN_ID = 922109605  # TODO: вынести в конфиг

# Даты собеседований
FINFAK_DATE = "2025-11-07"  # 7 ноября 2025 - Финфак
RESERV_DATE = "2025-11-08"  # 8 ноября 2025 - Резерв

# Московская временная зона
MOSCOW_TZ = pytz.timezone('Europe/Moscow')


class FinfakBookingStates(StatesGroup):
    """Состояния для записи на финфак."""
    waiting_time = State()
    waiting_confirmation = State()


class ReservBookingStates(StatesGroup):
    """Состояния для записи на резерв."""
    waiting_time = State()
    waiting_confirmation = State()


class QuestionStates(StatesGroup):
    """Состояния для отправки вопроса собеседующему."""
    waiting_question = State()


async def _parse_sheet_common(message: types.Message, sheet_name: str):
    """
    Общая функция для парсинга листа.
    
    Args:
        message: Сообщение от пользователя
        sheet_name: Имя листа для парсинга ('резерв' или 'финфак')
    """
    # Определяем модели для каждого листа
    if sheet_name == "резерв":
        TimeSlotModel = ReservTimeSlot
        BookingModel = ReservBooking
    elif sheet_name == "финфак":
        TimeSlotModel = FinfakTimeSlot
        BookingModel = FinfakBooking
    else:
        await message.answer(f"❌ Неизвестный лист: {sheet_name}")
        return
    
    await message.answer(f"🔄 Начинаю парсинг листа '{sheet_name}'...\n\nЭто может занять несколько секунд...")
    
    try:
        # Парсим указанный лист
        slots_data, interviewer_stats = parse_reserv_sheets(sheet_names=[sheet_name])
        
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
            valid_slot_keys = set()  # (interviewer_id, date, time_start)
            touched_interviewers = set()  # {interviewer_id}
            
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
                    
                    # Отслеживаем затронутых собеседующих
                    touched_interviewers.add(interviewer.id)
                    
                    # Проверяем, есть ли уже такой слот
                    existing_slot_stmt = select(TimeSlotModel).where(
                        TimeSlotModel.interviewer_id == interviewer.id,
                        TimeSlotModel.date == slot_info['date'],
                        TimeSlotModel.time_start == slot_info['time_start']
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
                        new_slot = TimeSlotModel(
                            interviewer_id=interviewer.id,
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
                for interviewer_id in touched_interviewers:
                    # Получаем все слоты этого собеседующего
                    slots_stmt = select(TimeSlotModel).where(
                        TimeSlotModel.interviewer_id == interviewer_id
                    )
                    all_slots_res = await session.execute(slots_stmt)
                    all_slots = all_slots_res.scalars().all()
                    
                    for slot in all_slots:
                        key = (interviewer_id, slot.date, slot.time_start)
                        if key not in valid_slot_keys:
                            # Слот отсутствует в актуальном листе
                            if slot.is_available:
                                # Проверяем отсутствие активной записи
                                existing_booking_stmt = select(BookingModel).where(
                                    BookingModel.time_slot_id == slot.id,
                                    BookingModel.status == 'confirmed'
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


@reserv_router.message(Command('parse_reserv'))
async def parse_reserv_command(message: types.Message):
    """
    Команда для парсинга листа 'резерв' из Google Sheets.
    Доступна только администратору.
    
    Выводит детальную информацию о процессе парсинга и статистику.
    """
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа. Команда только для администратора.")
        return
    
    await _parse_sheet_common(message, "резерв")


@reserv_router.message(Command('parse_finfak'))
async def parse_finfak_command(message: types.Message):
    """
    Команда для парсинга листа 'финфак' из Google Sheets.
    Доступна только администратору.
    
    Выводит детальную информацию о процессе парсинга и статистику.
    """
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа. Команда только для администратора.")
        return
    
    await _parse_sheet_common(message, "финфак")


# ========================================
# ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ
# ========================================

@reserv_router.message(Command('finfak'))
async def finfak_booking_start(message: types.Message, state: FSMContext):
    """
    Команда для записи на собеседование для Финфака.
    Доступна только студентам факультета "Финфак".
    """
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Получаем BotUser
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        result = await session.execute(stmt)
        bot_user = result.scalars().first()
        
        if not bot_user:
            await message.answer(
                "❌ Вы не зарегистрированы в системе. \n\n"
                "Используйте /start для регистрации или напишите @yanejettt"
            )
            return
        
        # Получаем Person для проверки факультета
        person = None
        if bot_user.person_id:
            person_stmt = select(Person).where(Person.id == bot_user.person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
        
        # Проверяем факультет
        if not person or not person.faculty or person.faculty.strip() != "Финфак":
            await message.answer(
                "❌ Запись на собеседование доступна только для студентов факультета \"Финфак\".\n\n"
                "Если это ошибка, обратитесь к администратору @yanejettt"
            )
            return
        
        # Проверяем, есть ли уже запись
        existing_stmt = select(FinfakBooking).where(
            FinfakBooking.bot_user_id == bot_user.id,
            FinfakBooking.status == 'confirmed'
        )
        existing_result = await session.execute(existing_stmt)
        existing_booking = existing_result.scalars().first()
        
        if existing_booking:
            # Получаем информацию о записи
            slot_stmt = select(FinfakTimeSlot).where(FinfakTimeSlot.id == existing_booking.time_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            interviewer_stmt = select(Interviewer).where(Interviewer.id == existing_booking.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            await message.answer(
                f"⚠️ У вас уже есть запись на собеседование!\n\n"
                f"📆 Дата: 07.11.2025\n"
                f"⏰ Время: {slot.time_start if slot else 'неизвестно'}\n\n"
                f"❗️ Записаться можно только один раз."
            )
            return
        
        # Показываем доступные слоты
        await show_finfak_slots(message, session, bot_user, person, state)


async def show_finfak_slots(message: types.Message, session, bot_user: BotUser, person: Person, state: FSMContext):
    """Показывает доступные временные слоты для записи на Финфак."""
    
    # Получаем текущее время в Москве
    now_moscow = datetime.now(MOSCOW_TZ)
    current_date = now_moscow.date().isoformat()
    current_time = now_moscow.time()
    
    # Получаем все доступные слоты
    stmt = select(FinfakTimeSlot).where(
        FinfakTimeSlot.is_available == True,
        FinfakTimeSlot.date == FINFAK_DATE
    ).order_by(FinfakTimeSlot.time_start)
    
    result = await session.execute(stmt)
    all_slots = result.scalars().all()
    
    if not all_slots:
        await message.answer(
            "😔 К сожалению, на данный момент нет доступных слотов.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        return
    
    # Группируем слоты по времени и считаем количество
    time_slots_count = {}
    time_slots_ids = {}
    
    for slot in all_slots:
        time_key = slot.time_start
        
        # Если это день собеседований, пропускаем прошедшие времена
        if current_date == FINFAK_DATE:
            try:
                slot_time = datetime.strptime(slot.time_start, "%H:%M").time()
                if slot_time <= current_time:
                    continue  # Пропускаем прошедшее время
            except:
                pass
        
        if time_key not in time_slots_count:
            time_slots_count[time_key] = 0
            time_slots_ids[time_key] = []
        
        time_slots_count[time_key] += 1
        time_slots_ids[time_key].append(slot.id)
    
    # Убираем времена с нулевым количеством слотов
    available_times = {k: v for k, v in time_slots_count.items() if v > 0}
    
    if not available_times:
        await message.answer(
            "😔 К сожалению, все слоты на сегодня уже заняты или прошли.\n\n"
            "Обратитесь к администратору для получения дополнительной информации."
        )
        return
    
    # Сохраняем данные в state
    await state.update_data(
        time_slots_ids=time_slots_ids,
        person_id=person.id,
        bot_user_id=bot_user.id
    )
    
    # Формируем кнопки (вертикально, одна под другой)
    kb = InlineKeyboardBuilder()
    
    for time_key in sorted(available_times.keys()):
        kb.row(InlineKeyboardButton(
            text=f"🕐 {time_key}",
            callback_data=f"finfak_time:{time_key}"
        ))
    
    await message.answer(
        f"📅 Запись на собеседование - Финфак\n"
        f"📆 Дата: 07.11.2025\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(FinfakBookingStates.waiting_time)


@reserv_router.callback_query(F.data.startswith('finfak_time:'))
async def finfak_time_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора времени для Финфака."""
    _, time_key = callback.data.split(':', 1)
    
    # Получаем данные из state
    data = await state.get_data()
    time_slots_ids = data.get('time_slots_ids', {})
    person_id = data.get('person_id')
    bot_user_id = data.get('bot_user_id')
    
    if not all([time_slots_ids, person_id, bot_user_id]):
        await callback.message.answer("❌ Ошибка: данные потеряны. Начните заново с /finfak")
        await state.clear()
        return
    
    # Получаем ID доступных слотов на это время
    available_slot_ids = time_slots_ids.get(time_key, [])
    
    if not available_slot_ids:
        await callback.message.edit_text(
            "😔 Это время уже занято. Выберите другое время или начните заново с /finfak"
        )
        return
    
    # Выбираем СЛУЧАЙНЫЙ слот из доступных
    selected_slot_id = random.choice(available_slot_ids)
    
    # Сохраняем выбор в state
    await state.update_data(
        selected_slot_id=selected_slot_id,
        selected_time=time_key
    )
    
    # Подтверждение
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="finfak_confirm:yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="finfak_confirm:no")
    )
    
    await callback.message.edit_text(
        f"✅ Подтвердите запись на собеседование:\n\n"
        f"📆 Дата: 07.11.2025\n"
        f"⏰ Время: {time_key}\n"
        f"🎓 Факультет: Финфак\n\n"
        f"Записаться?",
        reply_markup=kb.as_markup()
    )
    
    await state.set_state(FinfakBookingStates.waiting_confirmation)
    
    try:
        await callback.answer()
    except:
        pass


@reserv_router.callback_query(F.data.startswith('finfak_confirm:'))
async def finfak_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения записи на Финфак."""
    _, answer = callback.data.split(':', 1)
    
    if answer == 'no':
        await callback.message.edit_text(
            "❌ Запись отменена.\n\n"
            "Используйте /finfak чтобы записаться снова."
        )
        await state.clear()
        try:
            await callback.answer()
        except:
            pass
        return
    
    # Получаем данные из state
    data = await state.get_data()
    selected_slot_id = data.get('selected_slot_id')
    selected_time = data.get('selected_time')
    person_id = data.get('person_id')
    bot_user_id = data.get('bot_user_id')
    
    if not all([selected_slot_id, selected_time, person_id, bot_user_id]):
        await callback.message.edit_text("❌ Ошибка: данные потеряны. Начните заново с /finfak")
        await state.clear()
        return
    
    # Сохраняем запись в БД
    async with async_session_maker() as session:
        try:
            # Получаем слот еще раз (проверяем доступность)
            slot_stmt = select(FinfakTimeSlot).where(
                FinfakTimeSlot.id == selected_slot_id,
                FinfakTimeSlot.is_available == True
            )
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            if not slot:
                await callback.message.edit_text(
                    "😔 К сожалению, это время уже занято.\n\n"
                    "Попробуйте выбрать другое время с /finfak"
                )
                await state.clear()
                return
            
            # Получаем собеседующего
            interviewer_stmt = select(Interviewer).where(Interviewer.id == slot.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            # Получаем данные кандидата
            person_stmt = select(Person).where(Person.id == person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
            
            # Создаем запись
            booking = FinfakBooking(
                time_slot_id=slot.id,
                interviewer_id=slot.interviewer_id,
                bot_user_id=bot_user_id,
                person_id=person_id,
                status='confirmed'
            )
            session.add(booking)
            
            # Помечаем слот как занятый
            slot.is_available = False
            session.add(slot)
            
            # Flush для получения ID
            await session.flush()
            booking_id = booking.id
            
            await session.commit()
            
            # Refresh объектов для использования вне сессии
            await session.refresh(booking)
            await session.refresh(slot)
            await session.refresh(interviewer)
            await session.refresh(person)
            
            # Кнопка "Задать вопрос"
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(
                text="❓ Задать вопрос собеседующему",
                callback_data=f"ask_finfak:{booking_id}"
            ))
            
            # Отправляем подтверждение кандидату
            await callback.message.edit_text(
                f"✅ Запись успешно создана!\n\n"
                f"📆 Дата: 07.11.2025\n"
                f"⏰ Время: {selected_time}\n\n"
                f"До встречи на собеседовании!",
                reply_markup=kb.as_markup()
            )
            
            # Отправляем уведомление собеседующему
            if interviewer and interviewer.telegram_id:
                try:
                    # Получаем бота из callback
                    bot = callback.bot
                    
                    candidate_username = person.telegram_username if person and person.telegram_username else "не указан"
                    if candidate_username and not candidate_username.startswith('@'):
                        candidate_username = f"@{candidate_username}"
                    
                    notification_text = (
                        f"📌 Новая запись на собеседование!\n\n"
                        f"👤 Кандидат: {person.full_name if person else 'Неизвестен'}\n"
                        f"📱 Telegram: {candidate_username}\n"
                        f"🎓 Факультет: Финфак\n"
                        f"📅 Дата: 07.11.2025\n"
                        f"⏰ Время: {slot.time_start} - {slot.time_end}\n"
                    )
                    
                    await bot.send_message(interviewer.telegram_id, notification_text)
                except Exception as e:
                    print(f"Ошибка отправки уведомления собеседующему: {e}")
        
            # Экспорт в Google Sheets (асинхронно, с задержкой)
            # Запускаем ВНЕ сессии, чтобы не было проблем с detached объектами
            asyncio.create_task(
                export_finfak_booking_to_sheets(booking, slot, interviewer, person)
            )
            
            await state.clear()
            try:
                await callback.answer("✅ Запись создана!")
            except:
                pass
        
        except Exception as e:
            print(f"Ошибка при создании записи: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании записи.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()


# ========================================
# КОМАНДА /RESERV (ДЛЯ ВСЕХ ФАКУЛЬТЕТОВ)
# ========================================

@reserv_router.message(Command('reserv'))
async def reserv_booking_start(message: types.Message, state: FSMContext):
    """
    Команда для записи на собеседование (резерв).
    Доступна для всех студентов, независимо от факультета.
    """
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Получаем BotUser
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        result = await session.execute(stmt)
        bot_user = result.scalars().first()
        
        if not bot_user:
            await message.answer(
                "❌ Вы не зарегистрированы в системе.\n\n"
                "Используйте /start для регистрации."
            )
            return
        
        # Получаем Person (для ФИО)
        person = None
        if bot_user.person_id:
            person_stmt = select(Person).where(Person.id == bot_user.person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
        
        if not person:
            await message.answer(
                "❌ Ваши данные не найдены в системе.\n\n"
                "Обратитесь к администратору @yanejettt"
            )
            return
        
        # Проверяем, есть ли уже запись
        existing_stmt = select(ReservBooking).where(
            ReservBooking.bot_user_id == bot_user.id,
            ReservBooking.status == 'confirmed'
        )
        existing_result = await session.execute(existing_stmt)
        existing_booking = existing_result.scalars().first()
        
        if existing_booking:
            # Получаем информацию о записи
            slot_stmt = select(ReservTimeSlot).where(ReservTimeSlot.id == existing_booking.time_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            interviewer_stmt = select(Interviewer).where(Interviewer.id == existing_booking.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            await message.answer(
                f"⚠️ У вас уже есть запись на собеседование!\n\n"
                f"📆 Дата: 08.11.2025\n"
                f"⏰ Время: {slot.time_start if slot else 'неизвестно'}\n\n"
                f"❗️ Записаться можно только один раз."
            )
            return
        
        # Показываем доступные слоты
        await show_reserv_slots(message, session, bot_user, person, state)


async def show_reserv_slots(message: types.Message, session, bot_user: BotUser, person: Person, state: FSMContext):
    """Показывает доступные временные слоты для записи на резерв."""
    
    # Получаем текущее время в Москве
    now_moscow = datetime.now(MOSCOW_TZ)
    current_date = now_moscow.date().isoformat()
    current_time = now_moscow.time()
    
    # Получаем все доступные слоты
    stmt = select(ReservTimeSlot).where(
        ReservTimeSlot.is_available == True,
        ReservTimeSlot.date == RESERV_DATE
    ).order_by(ReservTimeSlot.time_start)
    
    result = await session.execute(stmt)
    all_slots = result.scalars().all()
    
    if not all_slots:
        await message.answer(
            "😔 К сожалению, на данный момент нет доступных слотов.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        return
    
    # Группируем слоты по времени и считаем количество
    time_slots_count = {}
    time_slots_ids = {}
    
    for slot in all_slots:
        time_key = slot.time_start
        
        # Если это день собеседований, пропускаем прошедшие времена
        if current_date == RESERV_DATE:
            try:
                slot_time = datetime.strptime(slot.time_start, "%H:%M").time()
                if slot_time <= current_time:
                    continue  # Пропускаем прошедшее время
            except:
                pass
        
        if time_key not in time_slots_count:
            time_slots_count[time_key] = 0
            time_slots_ids[time_key] = []
        
        time_slots_count[time_key] += 1
        time_slots_ids[time_key].append(slot.id)
    
    # Убираем времена с нулевым количеством слотов
    available_times = {k: v for k, v in time_slots_count.items() if v > 0}
    
    if not available_times:
        await message.answer(
            "😔 К сожалению, все слоты на сегодня уже заняты или прошли.\n\n"
            "Обратитесь к администратору для получения дополнительной информации."
        )
        return
    
    # Сохраняем данные в state
    await state.update_data(
        time_slots_ids=time_slots_ids,
        person_id=person.id,
        bot_user_id=bot_user.id
    )
    
    # Формируем кнопки (вертикально, одна под другой)
    kb = InlineKeyboardBuilder()
    
    for time_key in sorted(available_times.keys()):
        kb.row(InlineKeyboardButton(
            text=f"🕐 {time_key}",
            callback_data=f"reserv_time:{time_key}"
        ))
    
    await message.answer(
        f"📅 Запись на собеседование - Резерв\n"
        f"📆 Дата: 08.11.2025\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(ReservBookingStates.waiting_time)


@reserv_router.callback_query(F.data.startswith('reserv_time:'))
async def reserv_time_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора времени для резерва."""
    _, time_key = callback.data.split(':', 1)
    
    # Получаем данные из state
    data = await state.get_data()
    time_slots_ids = data.get('time_slots_ids', {})
    person_id = data.get('person_id')
    bot_user_id = data.get('bot_user_id')
    
    if not all([time_slots_ids, person_id, bot_user_id]):
        await callback.message.answer("❌ Ошибка: данные потеряны. Начните заново с /reserv")
        await state.clear()
        return
    
    # Получаем ID доступных слотов на это время
    available_slot_ids = time_slots_ids.get(time_key, [])
    
    if not available_slot_ids:
        await callback.message.edit_text(
            "😔 Это время уже занято. Выберите другое время или начните заново с /reserv"
        )
        return
    
    # Выбираем СЛУЧАЙНЫЙ слот из доступных
    selected_slot_id = random.choice(available_slot_ids)
    
    # Сохраняем выбор в state
    await state.update_data(
        selected_slot_id=selected_slot_id,
        selected_time=time_key
    )
    
    # Подтверждение
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="reserv_confirm:yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="reserv_confirm:no")
    )
    
    await callback.message.edit_text(
        f"✅ Подтвердите запись на собеседование:\n\n"
        f"📆 Дата: 08.11.2025\n"
        f"⏰ Время: {time_key}\n"
        f"📋 Тип: Резерв\n\n"
        f"Записаться?",
        reply_markup=kb.as_markup()
    )
    
    await state.set_state(ReservBookingStates.waiting_confirmation)
    
    try:
        await callback.answer()
    except:
        pass


@reserv_router.callback_query(F.data.startswith('reserv_confirm:'))
async def reserv_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения записи на резерв."""
    _, answer = callback.data.split(':', 1)
    
    if answer == 'no':
        await callback.message.edit_text(
            "❌ Запись отменена.\n\n"
            "Используйте /reserv чтобы записаться снова."
        )
        await state.clear()
        try:
            await callback.answer()
        except:
            pass
        return
    
    # Получаем данные из state
    data = await state.get_data()
    selected_slot_id = data.get('selected_slot_id')
    selected_time = data.get('selected_time')
    person_id = data.get('person_id')
    bot_user_id = data.get('bot_user_id')
    
    if not all([selected_slot_id, selected_time, person_id, bot_user_id]):
        await callback.message.edit_text("❌ Ошибка: данные потеряны. Начните заново с /reserv")
        await state.clear()
        return
    
    # Сохраняем запись в БД
    async with async_session_maker() as session:
        try:
            # Получаем слот еще раз (проверяем доступность)
            slot_stmt = select(ReservTimeSlot).where(
                ReservTimeSlot.id == selected_slot_id,
                ReservTimeSlot.is_available == True
            )
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            if not slot:
                await callback.message.edit_text(
                    "😔 К сожалению, это время уже занято.\n\n"
                    "Попробуйте выбрать другое время с /reserv"
                )
                await state.clear()
                return
            
            # Получаем собеседующего
            interviewer_stmt = select(Interviewer).where(Interviewer.id == slot.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            # Получаем данные кандидата
            person_stmt = select(Person).where(Person.id == person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
            
            # Создаем запись
            booking = ReservBooking(
                time_slot_id=slot.id,
                interviewer_id=slot.interviewer_id,
                bot_user_id=bot_user_id,
                person_id=person_id,
                status='confirmed'
            )
            session.add(booking)
            
            # Помечаем слот как занятый
            slot.is_available = False
            session.add(slot)
            
            # Flush для получения ID
            await session.flush()
            booking_id = booking.id
            
            await session.commit()
            
            # Refresh объектов для использования вне сессии
            await session.refresh(booking)
            await session.refresh(slot)
            await session.refresh(interviewer)
            await session.refresh(person)
            
            # Кнопка "Задать вопрос"
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(
                text="❓ Задать вопрос собеседующему",
                callback_data=f"ask_reserv:{booking_id}"
            ))
            
            # Отправляем подтверждение кандидату
            await callback.message.edit_text(
                f"✅ Запись успешно создана!\n\n"
                f"📆 Дата: 08.11.2025\n"
                f"⏰ Время: {selected_time}\n\n"
                f"До встречи на собеседовании!",
                reply_markup=kb.as_markup()
            )
            
            # Отправляем уведомление собеседующему
            if interviewer and interviewer.telegram_id:
                try:
                    # Получаем бота из callback
                    bot = callback.bot
                    
                    candidate_username = person.telegram_username if person and person.telegram_username else "не указан"
                    if candidate_username and not candidate_username.startswith('@'):
                        candidate_username = f"@{candidate_username}"
                    
                    notification_text = (
                        f"📌 Новая запись на собеседование!\n\n"
                        f"👤 Кандидат: {person.full_name if person else 'Неизвестен'}\n"
                        f"📱 Telegram: {candidate_username}\n"
                        f"📋 Тип: Резерв\n"
                        f"📅 Дата: 08.11.2025\n"
                        f"⏰ Время: {slot.time_start} - {slot.time_end}\n"
                    )
                    
                    await bot.send_message(interviewer.telegram_id, notification_text)
                except Exception as e:
                    print(f"Ошибка отправки уведомления собеседующему: {e}")
        
            # Экспорт в Google Sheets (асинхронно, с задержкой)
            # Запускаем ВНЕ сессии, чтобы не было проблем с detached объектами
            asyncio.create_task(
                export_reserv_booking_to_sheets(booking, slot, interviewer, person)
            )
            
            await state.clear()
            try:
                await callback.answer("✅ Запись создана!")
            except:
                pass
        
        except Exception as e:
            print(f"Ошибка при создании записи: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании записи.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()


# ========================================
# ВОПРОСЫ СОБЕСЕДУЮЩЕМУ
# ========================================

@reserv_router.callback_query(F.data.startswith('ask_finfak:'))
async def ask_finfak_question(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки 'Задать вопрос' для финфака."""
    _, booking_id = callback.data.split(':', 1)
    
    try:
        booking_id = int(booking_id)
    except:
        await callback.answer("❌ Ошибка: неверный ID записи")
        return
    
    # Сохраняем ID записи и тип в state
    await state.update_data(
        booking_id=booking_id,
        booking_type="finfak"
    )
    
    await callback.message.answer(
        "❓ Задайте ваш вопрос собеседующему:\n\n"
        "Напишите ваш вопрос в следующем сообщении."
    )
    
    await state.set_state(QuestionStates.waiting_question)
    
    try:
        await callback.answer()
    except:
        pass


@reserv_router.callback_query(F.data.startswith('ask_reserv:'))
async def ask_reserv_question(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки 'Задать вопрос' для резерва."""
    _, booking_id = callback.data.split(':', 1)
    
    try:
        booking_id = int(booking_id)
    except:
        await callback.answer("❌ Ошибка: неверный ID записи")
        return
    
    # Сохраняем ID записи и тип в state
    await state.update_data(
        booking_id=booking_id,
        booking_type="reserv"
    )
    
    await callback.message.answer(
        "❓ Задайте ваш вопрос собеседующему:\n\n"
        "Напишите ваш вопрос в следующем сообщении."
    )
    
    await state.set_state(QuestionStates.waiting_question)
    
    try:
        await callback.answer()
    except:
        pass


@reserv_router.message(QuestionStates.waiting_question)
async def process_question(message: types.Message, state: FSMContext):
    """Обработка вопроса от кандидата."""
    question_text = message.text
    
    if not question_text or len(question_text.strip()) == 0:
        await message.answer("❌ Пожалуйста, напишите ваш вопрос текстом.")
        return
    
    if len(question_text) > 1000:
        await message.answer("❌ Вопрос слишком длинный. Максимум 1000 символов.")
        return
    
    # Получаем данные из state
    data = await state.get_data()
    booking_id = data.get('booking_id')
    booking_type = data.get('booking_type')
    
    if not booking_id or not booking_type:
        await message.answer("❌ Ошибка: данные потеряны. Попробуйте снова.")
        await state.clear()
        return
    
    # Получаем информацию о записи
    async with async_session_maker() as session:
        try:
            # Определяем модели в зависимости от типа
            if booking_type == "finfak":
                BookingModel = FinfakBooking
                TimeSlotModel = FinfakTimeSlot
                booking_type_name = "Финфак"
                booking_date = "07.11.2025"
            else:  # reserv
                BookingModel = ReservBooking
                TimeSlotModel = ReservTimeSlot
                booking_type_name = "Резерв"
                booking_date = "08.11.2025"
            
            # Получаем запись
            booking_stmt = select(BookingModel).where(BookingModel.id == booking_id)
            booking_result = await session.execute(booking_stmt)
            booking = booking_result.scalars().first()
            
            if not booking:
                await message.answer("❌ Запись не найдена.")
                await state.clear()
                return
            
            # Получаем слот
            slot_stmt = select(TimeSlotModel).where(TimeSlotModel.id == booking.time_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            # Получаем собеседующего
            interviewer_stmt = select(Interviewer).where(Interviewer.id == booking.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            # Получаем данные кандидата
            person_stmt = select(Person).where(Person.id == booking.person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
            
            if not interviewer or not interviewer.telegram_id:
                await message.answer("❌ Не удалось отправить вопрос: данные собеседующего не найдены.")
                await state.clear()
                return
            
            # Форматируем username кандидата
            candidate_username = person.telegram_username if person and person.telegram_username else "не указан"
            if candidate_username != "не указан" and not candidate_username.startswith('@'):
                candidate_username = f"@{candidate_username}"
            
            # Отправляем вопрос собеседующему
            notification_text = (
                f"❓ Вопрос от кандидата:\n\n"
                f"👤 ФИО: {person.full_name if person else 'Неизвестен'}\n"
                f"📱 Telegram: {candidate_username}\n"
                f"📋 Тип: {booking_type_name}\n"
                f"📅 Дата: {booking_date}\n"
                f"⏰ Время записи: {slot.time_start if slot else 'неизвестно'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💬 Вопрос:\n{question_text}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Вы можете ответить кандидату напрямую в Telegram: {candidate_username}"
            )
            
            bot = message.bot
            await bot.send_message(interviewer.telegram_id, notification_text)
            
            # Подтверждение кандидату
            await message.answer(
                "✅ Ваш вопрос отправлен собеседующему!\n\n"
                "Собеседующий свяжется с вами в Telegram для ответа."
            )
            
            await state.clear()
        
        except Exception as e:
            print(f"Ошибка отправки вопроса: {e}")
            import traceback
            traceback.print_exc()
            
            await message.answer(
                "❌ Произошла ошибка при отправке вопроса.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()
