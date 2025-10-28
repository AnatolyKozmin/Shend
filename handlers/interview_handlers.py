from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, and_, or_
from db.engine import async_session_maker
from db.models import Interviewer, BotUser, TimeSlot, Interview, Person
from utils.google_sheets import find_interviewer_by_code, get_schedules_data
from datetime import datetime
import random


interview_router = Router()


class RegisterSobesStates(StatesGroup):
    waiting_code = State()
    waiting_confirmation = State()


class BookingSobesStates(StatesGroup):
    waiting_date = State()
    waiting_time = State()
    waiting_confirmation = State()


@interview_router.message(Command('register_sobes'))
async def register_sobes_start(message: types.Message, state: FSMContext):
    """Начало регистрации собеседующего."""
    tg_id = message.from_user.id
    
    # Проверяем, не зарегистрирован ли уже
    async with async_session_maker() as session:
        stmt = select(Interviewer).where(Interviewer.telegram_id == tg_id)
        result = await session.execute(stmt)
        existing = result.scalars().first()
        
        if existing:
            await message.answer(
                f"✅ Вы уже зарегистрированы как собеседующий!\n\n"
                f"ФИО: {existing.full_name}\n"
                f"ID: {existing.interviewer_sheet_id}\n\n"
                f"Используйте /my_interviews для просмотра ваших записей."
            )
            return
    
    await state.set_state(RegisterSobesStates.waiting_code)
    await message.answer(
        "🔐 Регистрация собеседующего\n\n"
        "Введите ваш код доступа (5 символов):"
    )


@interview_router.message(RegisterSobesStates.waiting_code)
async def register_sobes_code(message: types.Message, state: FSMContext):
    """Обработка ввода кода доступа."""
    code = message.text.strip()
    
    # Проверяем что код не пустой
    if not code:
        await message.answer(
            "❌ Код не может быть пустым.\n\n"
            "Введите ваш код доступа:"
        )
        return
    
    # Проверяем длину кода (должен быть ровно 5 символов)
    if len(code) != 5:
        await message.answer(
            "❌ Неверный формат кода.\n\n"
            "Код должен состоять из 5 символов. Попробуйте снова:"
        )
        return
    
    # Ищем в Google Sheets
    try:
        interviewer_data = find_interviewer_by_code(code)
        
        if not interviewer_data:
            await message.answer(
                "❌ Код не найден в системе.\n\n"
                "Проверьте правильность кода или обратитесь к администратору.\n\n"
                "Введите код снова или используйте /cancel для отмены:"
            )
            return
        
        # Сохраняем данные в state
        await state.update_data(
            full_name=interviewer_data['full_name'],
            access_code=interviewer_data['access_code'],
            interviewer_sheet_id=interviewer_data['interviewer_sheet_id']
        )
        
        # Спрашиваем подтверждение
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ Да, всё верно", callback_data="confirm_interviewer:yes"),
            InlineKeyboardButton(text="❌ Нет, это не я", callback_data="confirm_interviewer:no")
        )
        
        await state.set_state(RegisterSobesStates.waiting_confirmation)
        await message.answer(
            f"🔍 Найдено!\n\n"
            f"ФИО: {interviewer_data['full_name']}\n"
            f"ID: {interviewer_data['interviewer_sheet_id']}\n\n"
            f"Это вы?",
            reply_markup=kb.as_markup()
        )
    
    except Exception as e:
        print(f"Ошибка при проверке кода: {e}")
        await message.answer(
            "❌ Произошла ошибка при проверке кода.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        await state.clear()


@interview_router.callback_query(F.data.startswith('confirm_interviewer:'))
async def confirm_interviewer(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения регистрации."""
    _, answer = callback.data.split(':', 1)
    
    if answer == 'no':
        await callback.message.edit_text(
            "❌ Регистрация отменена.\n\n"
            "Используйте /register_sobes чтобы попробовать снова."
        )
        await state.clear()
        try:
            await callback.answer()
        except TelegramBadRequest:
            pass  # Игнорируем ошибку "query too old"
        return
    
    # Получаем данные из state
    data = await state.get_data()
    full_name = data.get('full_name')
    access_code = data.get('access_code')
    interviewer_sheet_id = data.get('interviewer_sheet_id')
    
    tg_user = callback.from_user
    tg_id = tg_user.id
    username = tg_user.username
    
    # Сохраняем в БД
    async with async_session_maker() as session:
        try:
            # Проверяем ещё раз, вдруг уже есть
            stmt = select(Interviewer).where(Interviewer.telegram_id == tg_id)
            result = await session.execute(stmt)
            existing = result.scalars().first()
            
            if existing:
                await callback.message.edit_text(
                    "⚠️ Вы уже зарегистрированы!\n\n"
                    f"ФИО: {existing.full_name}"
                )
                await state.clear()
                try:
                    await callback.answer()
                except TelegramBadRequest:
                    pass  # Игнорируем ошибку "query too old"
                return
            
            # Создаём нового собеседующего
            interviewer = Interviewer(
                full_name=full_name,
                telegram_id=tg_id,
                telegram_username=username.lower() if username else None,
                interviewer_sheet_id=interviewer_sheet_id,
                access_code=access_code,
                is_active=True
            )
            
            session.add(interviewer)
            await session.commit()
            
            await callback.message.edit_text(
                "✅ Регистрация успешно завершена!\n\n"
                f"ФИО: {full_name}\n"
                f"ID: {interviewer_sheet_id}\n\n"
                "Теперь вы можете:\n"
                "• /my_interviews - посмотреть ваши записи\n\n"
                "Админ сможет назначить вам слоты для собеседований."
            )
            
            await state.clear()
            try:
                await callback.answer("✅ Регистрация завершена!")
            except TelegramBadRequest:
                pass  # Игнорируем ошибку "query too old"
        
        except Exception as e:
            print(f"Ошибка при сохранении собеседующего: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при регистрации.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()
            try:
                await callback.answer()
            except TelegramBadRequest:
                pass  # Игнорируем ошибку "query too old"


@interview_router.message(Command('cancel'))
async def cancel_registration(message: types.Message, state: FSMContext):
    """Отмена регистрации."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return
    
    await state.clear()
    await message.answer("❌ Действие отменено.")


@interview_router.message(Command('sync_slots'))
async def sync_slots(message: types.Message):
    """Синхронизация слотов из Google Sheets (только для админа)."""
    ADMIN_ID = 922109605  # TODO: вынести в конфиг
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа. Команда только для администратора.")
        return
    
    await message.answer("🔄 Начинаю синхронизацию слотов из Google Sheets...")
    
    try:
        # Получаем данные из Google Sheets
        slots_data, interviewer_stats = get_schedules_data()
        
        if not slots_data:
            await message.answer("❌ Не удалось загрузить данные из Google Sheets или таблица пуста.")
            return
        
        async with async_session_maker() as session:
            added = 0
            updated = 0
            skipped = 0
            errors = 0
            
            for slot_info in slots_data:
                try:
                    # Находим собеседующего по interviewer_sheet_id
                    interviewer_stmt = select(Interviewer).where(
                        Interviewer.interviewer_sheet_id == slot_info['interviewer_sheet_id']
                    )
                    interviewer_result = await session.execute(interviewer_stmt)
                    interviewer = interviewer_result.scalars().first()
                    
                    if not interviewer:
                        # Собеседующий не зарегистрирован - пропускаем
                        skipped += 1
                        continue
                    
                    # Обновляем факультеты собеседующего
                    faculties_str = ",".join(slot_info['faculties'])
                    if interviewer.faculties != faculties_str:
                        interviewer.faculties = faculties_str
                        session.add(interviewer)
                    
                    # Проверяем, есть ли уже такой слот
                    existing_slot_stmt = select(TimeSlot).where(
                        TimeSlot.interviewer_id == interviewer.id,
                        TimeSlot.date == slot_info['date'],
                        TimeSlot.time_start == slot_info['time_start']
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
                        # Создаём новый слот
                        new_slot = TimeSlot(
                            interviewer_id=interviewer.id,
                            date=slot_info['date'],
                            time_start=slot_info['time_start'],
                            time_end=slot_info['time_end'],
                            is_available=True,
                            google_sheet_sync=datetime.now()
                        )
                        session.add(new_slot)
                        added += 1
                
                except Exception as e:
                    print(f"Ошибка обработки слота: {e}")
                    errors += 1
            
            # Сохраняем изменения
            await session.commit()
            
            # Формируем сообщение со статистикой
            stats_message = (
                f"✅ Синхронизация завершена!\n\n"
                f"📊 Статистика:\n"
                f"• Добавлено новых слотов: {added}\n"
                f"• Обновлено существующих: {updated}\n"
                f"• Пропущено (занято или нет собеседующего): {skipped}\n"
                f"• Ошибок: {errors}\n\n"
                f"📋 Всего обработано: {len(slots_data)} слотов из Google Sheets\n"
            )
            
            # Добавляем детальную статистику по собеседующим
            if interviewer_stats:
                stats_message += f"\n👥 Слоты по собеседующим:\n"
                for interviewer_name, count in sorted(interviewer_stats.items()):
                    stats_message += f"• {interviewer_name}: {count} слотов\n"
            
            await message.answer(stats_message)
    
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
        await message.answer(
            f"❌ Произошла ошибка при синхронизации:\n{str(e)}\n\n"
            "Проверьте доступ к Google Sheets и правильность credentials."
        )


@interview_router.message(Command('sobes'))
async def sobes_start(message: types.Message, state: FSMContext):
    """Запись на собеседование."""
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Получаем BotUser
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        result = await session.execute(stmt)
        bot_user = result.scalars().first()
        
        if not bot_user:
            await message.answer(
                "❌ Вы не зарегистрированы в системе.\n\n"
                "Для записи на собеседование необходимо сначала зарегистрироваться."
            )
            return
        
        # Проверяем есть ли уже запись
        existing_stmt = select(Interview).where(
            Interview.bot_user_id == bot_user.id,
            Interview.status.in_(['confirmed', 'pending'])
        )
        existing_result = await session.execute(existing_stmt)
        existing_interview = existing_result.scalars().first()
        
        if existing_interview:
            slot_stmt = select(TimeSlot).where(TimeSlot.id == existing_interview.time_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            kb = InlineKeyboardBuilder()
            if existing_interview.cancellation_allowed:
                kb.row(InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel_interview:{existing_interview.id}"))
            kb.row(InlineKeyboardButton(text="❓ Задать вопрос собеседующему", callback_data=f"ask_question:{existing_interview.id}"))
            
            await message.answer(
                f"⚠️ У вас уже есть запись на собеседование!\n\n"
                f"📅 Дата: {slot.date}\n"
                f"⏰ Время: {slot.time_start} - {slot.time_end}\n"
                f"🎓 Факультет: {existing_interview.faculty}\n",
                reply_markup=kb.as_markup()
            )
            return
        
        # Получаем Person для определения факультета
        person = None
        if bot_user.person_id:
            person_stmt = select(Person).where(Person.id == bot_user.person_id)
            person_result = await session.execute(person_stmt)
            person = person_result.scalars().first()
        
        # Определяем факультет
        user_faculty = None
        if person and person.faculty:
            user_faculty = person.faculty.strip()
        
        if not user_faculty:
            # Показываем выбор факультетов
            faculties = ["СНиМК", "МЭО", "ФЭБ", "Юрфак", "ИТиАБД", "ФинФак", "НАБ", "ВШУ"]
            
            kb = InlineKeyboardBuilder()
            for fac in faculties:
                kb.row(InlineKeyboardButton(text=fac, callback_data=f"select_faculty:{fac}"))
            
            await message.answer(
                "🎓 Выберите ваш факультет:",
                reply_markup=kb.as_markup()
            )
            await state.set_state(BookingSobesStates.waiting_date)
            return
        
        # Факультет определён - показываем доступные даты
        await show_available_dates(message, session, user_faculty, state)


async def show_available_dates(message: types.Message, session, user_faculty: str, state: FSMContext):
    """Показывает доступные даты для записи."""
    # Ищем доступные слоты для факультета
    stmt = select(TimeSlot).join(Interviewer).where(
        TimeSlot.is_available == True,
        or_(
            Interviewer.faculties.contains(user_faculty),
            Interviewer.faculties == user_faculty
        )
    ).order_by(TimeSlot.date, TimeSlot.time_start)
    
    result = await session.execute(stmt)
    available_slots = result.scalars().all()
    
    if not available_slots:
        await message.answer(
            f"😔 К сожалению, на данный момент нет доступных слотов для факультета {user_faculty}.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        await state.clear()
        return
    
    # Группируем по датам
    dates_dict = {}
    for slot in available_slots:
        if slot.date not in dates_dict:
            dates_dict[slot.date] = []
        dates_dict[slot.date].append(slot)
    
    # Сортируем даты
    dates = sorted(dates_dict.keys())
    
    # Сохраняем факультет в state
    await state.update_data(faculty=user_faculty)
    
    # Формируем кнопки с датами
    kb = InlineKeyboardBuilder()
    for date in dates:
        # Форматируем дату красиво
        date_parts = date.split('-')
        date_str = f"{date_parts[2]}.{date_parts[1]}"
        slots_count = len(dates_dict[date])
        kb.row(InlineKeyboardButton(
            text=f"{date_str} ({slots_count} слотов)",
            callback_data=f"sobes_date:{date}"
        ))
    
    await message.answer(
        f"🎓 Факультет: {user_faculty}\n\n"
        f"📅 Выберите дату собеседования:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(BookingSobesStates.waiting_date)


@interview_router.callback_query(F.data.startswith('select_faculty:'))
async def select_faculty_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора факультета."""
    _, faculty = callback.data.split(':', 1)
    
    async with async_session_maker() as session:
        await show_available_dates(callback.message, session, faculty, state)
    
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@interview_router.callback_query(F.data.startswith('sobes_date:'))
async def sobes_date_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора даты."""
    _, selected_date = callback.data.split(':', 1)
    
    # Получаем факультет из state
    data = await state.get_data()
    user_faculty = data.get('faculty')
    
    if not user_faculty:
        await callback.message.answer("❌ Ошибка: факультет не определён. Начните заново с /sobes")
        await state.clear()
        return
    
    async with async_session_maker() as session:
        # Получаем доступные слоты на выбранную дату
        stmt = select(TimeSlot).join(Interviewer).where(
            TimeSlot.date == selected_date,
            TimeSlot.is_available == True,
            or_(
                Interviewer.faculties.contains(user_faculty),
                Interviewer.faculties == user_faculty
            )
        ).order_by(TimeSlot.time_start)
        
        result = await session.execute(stmt)
        available_slots = result.scalars().all()
        
        if not available_slots:
            await callback.message.edit_text(
                f"😔 На {selected_date} нет доступных слотов.\n\n"
                "Выберите другую дату или начните заново с /sobes"
            )
            return
        
        # Группируем по времени
        times_dict = {}
        for slot in available_slots:
            time_key = f"{slot.time_start}-{slot.time_end}"
            if time_key not in times_dict:
                times_dict[time_key] = []
            times_dict[time_key].append(slot)
        
        # Сохраняем дату в state
        await state.update_data(selected_date=selected_date, times_dict=times_dict)
        
        # Формируем кнопки по 3 в ряд
        kb = InlineKeyboardBuilder()
        times = sorted(times_dict.keys())
        for i in range(0, len(times), 3):
            row_times = times[i:i+3]
            for time_key in row_times:
                # Показываем только начало времени для краткости
                time_start = time_key.split('-')[0]
                kb.add(InlineKeyboardButton(
                    text=time_start,
                    callback_data=f"sobes_time:{time_key}"
                ))
            kb.row()
        
        # Форматируем дату для отображения
        date_parts = selected_date.split('-')
        date_display = f"{date_parts[2]}.{date_parts[1]}.{date_parts[0]}"
        
        await callback.message.edit_text(
            f"🎓 Факультет: {user_faculty}\n"
            f"📅 Дата: {date_display}\n\n"
            f"⏰ Выберите удобное время:",
            reply_markup=kb.as_markup()
        )
        
        await state.set_state(BookingSobesStates.waiting_time)
    
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@interview_router.callback_query(F.data.startswith('sobes_time:'))
async def sobes_time_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора времени."""
    _, time_key = callback.data.split(':', 1)
    
    # Получаем данные из state
    data = await state.get_data()
    user_faculty = data.get('faculty')
    selected_date = data.get('selected_date')
    times_dict = data.get('times_dict', {})
    
    if not all([user_faculty, selected_date, times_dict]):
        await callback.message.answer("❌ Ошибка: данные потеряны. Начните заново с /sobes")
        await state.clear()
        return
    
    # Получаем доступные слоты на это время
    available_slots = times_dict.get(time_key, [])
    
    if not available_slots:
        await callback.message.edit_text(
            "😔 Это время уже занято. Выберите другое время или начните заново с /sobes"
        )
        return
    
    # Выбираем случайный слот из доступных
    selected_slot_id = random.choice([s.id for s in available_slots])
    
    # Сохраняем выбор в state
    await state.update_data(selected_slot_id=selected_slot_id, selected_time=time_key)
    
    # Форматируем дату
    date_parts = selected_date.split('-')
    date_display = f"{date_parts[2]}.{date_parts[1]}.{date_parts[0]}"
    
    # Подтверждение
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="sobes_confirm:yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="sobes_confirm:no")
    )
    
    await callback.message.edit_text(
        f"✅ Подтвердите запись на собеседование:\n\n"
        f"🎓 Факультет: {user_faculty}\n"
        f"📅 Дата: {date_display}\n"
        f"⏰ Время: {time_key}\n\n"
        f"Записаться?",
        reply_markup=kb.as_markup()
    )
    
    await state.set_state(BookingSobesStates.waiting_confirmation)
    
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@interview_router.callback_query(F.data.startswith('sobes_confirm:'))
async def sobes_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения записи."""
    _, answer = callback.data.split(':', 1)
    
    if answer == 'no':
        await callback.message.edit_text(
            "❌ Запись отменена.\n\n"
            "Используйте /sobes чтобы записаться снова."
        )
        await state.clear()
        try:
            await callback.answer()
        except TelegramBadRequest:
            pass
        return
    
    # Получаем данные из state
    data = await state.get_data()
    user_faculty = data.get('faculty')
    selected_date = data.get('selected_date')
    selected_time = data.get('selected_time')
    selected_slot_id = data.get('selected_slot_id')
    
    tg_id = callback.from_user.id
    
    async with async_session_maker() as session:
        try:
            # Получаем BotUser
            bot_user_stmt = select(BotUser).where(BotUser.tg_id == tg_id)
            bot_user_result = await session.execute(bot_user_stmt)
            bot_user = bot_user_result.scalars().first()
            
            # Получаем слот
            slot_stmt = select(TimeSlot).where(TimeSlot.id == selected_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            # Проверяем что слот ещё доступен
            if not slot or not slot.is_available:
                await callback.message.edit_text(
                    "😔 К сожалению, это время уже занято.\n\n"
                    "Используйте /sobes чтобы выбрать другое время."
                )
                await state.clear()
                return
            
            # Создаём запись
            interview = Interview(
                time_slot_id=slot.id,
                interviewer_id=slot.interviewer_id,
                bot_user_id=bot_user.id,
                person_id=bot_user.person_id if bot_user.person_id else None,
                faculty=user_faculty,
                status='confirmed',
                cancellation_allowed=True  # Можно отменить 1 раз
            )
            
            # Блокируем слот
            slot.is_available = False
            
            session.add(interview)
            session.add(slot)
            await session.commit()
            
            # Получаем собеседующего для уведомления
            interviewer_stmt = select(Interviewer).where(Interviewer.id == slot.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            # Форматируем дату
            date_parts = selected_date.split('-')
            date_display = f"{date_parts[2]}.{date_parts[1]}.{date_parts[0]}"
            
            # Кнопки для кандидата
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text="❓ Задать вопрос", callback_data=f"ask_question:{interview.id}"))
            kb.row(InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel_interview:{interview.id}"))
            
            await callback.message.edit_text(
                f"🎉 Вы успешно записаны на собеседование!\n\n"
                f"🎓 Факультет: {user_faculty}\n"
                f"📅 Дата: {date_display}\n"
                f"⏰ Время: {selected_time}\n\n"
                f"❗ Отменить запись можно только один раз.\n"
                f"Будьте внимательны!",
                reply_markup=kb.as_markup()
            )
            
            # Отправляем уведомление собеседующему
            if interviewer and interviewer.telegram_id:
                try:
                    from aiogram import Bot
                    bot = Bot(token=callback.bot.token)
                    
                    student_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
                    
                    await bot.send_message(
                        interviewer.telegram_id,
                        f"📌 Новая запись на собеседование!\n\n"
                        f"👤 Кандидат: {student_name}\n"
                        f"🎓 Факультет: {user_faculty}\n"
                        f"📅 Дата: {date_display}\n"
                        f"⏰ Время: {selected_time}\n\n"
                        f"Кандидат может задать вам вопрос через бота."
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления собеседующему: {e}")
            
            await state.clear()
            
            try:
                await callback.answer("✅ Запись создана!")
            except TelegramBadRequest:
                pass
        
        except Exception as e:
            print(f"Ошибка при создании записи: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании записи.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()

