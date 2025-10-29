from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, and_, or_
from db.engine import async_session_maker
from db.models import Interviewer, BotUser, TimeSlot, Interview, Person, InterviewMessage
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


class QuestionStates(StatesGroup):
    """Состояния для системы вопросов/ответов."""
    waiting_question = State()  # Кандидат вводит вопрос
    waiting_answer = State()    # Собеседующий вводит ответ


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
                    
                    # Обновляем факультеты собеседующего (добавляем, не перезаписываем)
                    new_faculties = slot_info['faculties']
                    
                    if interviewer.faculties:
                        # Есть уже факультеты - добавляем новые
                        existing = set(interviewer.faculties.split(','))
                        existing.update(new_faculties)
                        interviewer.faculties = ','.join(sorted(existing))
                    else:
                        # Нет факультетов - просто записываем
                        interviewer.faculties = ','.join(sorted(new_faculties))
                    
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
            kb.row(InlineKeyboardButton(text="❓ Задать вопрос собеседующему", callback_data=f"ask_question:{existing_interview.id}"))
            
            await message.answer(
                f"⚠️ У вас уже есть запись на собеседование!\n\n"
                f"📅 Дата: {slot.date}\n"
                f"⏰ Время: {slot.time_start} - {slot.time_end}\n"
                f"🎓 Факультет: {existing_interview.faculty}\n\n"
                f"❗️ Записаться можно только один раз.\n"
                f"Для изменения времени обратитесь к администратору.",
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
        
        # Факультет определён - показываем доступные времена
        await show_available_times(message, session, user_faculty, state)


async def show_available_times(message: types.Message, session, user_faculty: str, state: FSMContext):
    """Показывает доступные времена для записи (дата определяется автоматически по факультету)."""
    # Ищем доступные слоты для факультета
    stmt = select(TimeSlot).join(Interviewer).where(
        TimeSlot.is_available == True,
        or_(
            Interviewer.faculties.like(f"{user_faculty},%"),
            Interviewer.faculties.like(f"%,{user_faculty},%"),
            Interviewer.faculties.like(f"%,{user_faculty}"),
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
    
    # Берём первую дату (у каждого факультета только одна дата)
    selected_date = available_slots[0].date
    
    # Фильтруем слоты только на эту дату
    slots_for_date = [s for s in available_slots if s.date == selected_date]
    
    # Группируем по времени
    times_dict = {}
    for slot in slots_for_date:
        time_key = f"{slot.time_start}-{slot.time_end}"
        if time_key not in times_dict:
            times_dict[time_key] = []
        times_dict[time_key].append(slot)
    
    # Проверяем что есть хотя бы один слот
    if not times_dict:
        await message.answer(
            f"😔 К сожалению, на данный момент нет доступных слотов для факультета {user_faculty}.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        await state.clear()
        return
    
    # Сохраняем данные в state
    await state.update_data(
        faculty=user_faculty,
        selected_date=selected_date,
        times_dict=times_dict
    )
    
    # Формируем кнопки ВЕРТИКАЛЬНО (по одной в ряд)
    kb = InlineKeyboardBuilder()
    times = sorted(times_dict.keys())
    for time_key in times:
        time_start = time_key.split('-')[0]
        kb.row(InlineKeyboardButton(
            text=f"🕐 {time_start}",
            callback_data=f"sobes_time:{time_key}"
        ))
    
    # Форматируем дату для отображения
    date_parts = selected_date.split('-')
    date_display = f"{date_parts[2]}.{date_parts[1]}.{date_parts[0]}"
    
    await message.answer(
        f"🎓 Факультет: {user_faculty}\n"
        f"📅 Дата: {date_display}\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(BookingSobesStates.waiting_time)


@interview_router.callback_query(F.data.startswith('select_faculty:'))
async def select_faculty_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора факультета."""
    _, faculty = callback.data.split(':', 1)
    
    async with async_session_maker() as session:
        await show_available_times(callback.message, session, faculty, state)
    
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
            
            # Получаем слот С БЛОКИРОВКОЙ (FOR UPDATE)
            # Это предотвращает race condition при одновременной записи
            slot_stmt = select(TimeSlot).where(TimeSlot.id == selected_slot_id).with_for_update()
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            # Проверяем что слот существует и доступен
            if not slot or not slot.is_available:
                await callback.message.edit_text(
                    "😔 К сожалению, это время уже занято.\n\n"
                    "Используйте /sobes чтобы выбрать другое время."
                )
                await state.clear()
                try:
                    await callback.answer("Время уже занято", show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Проверяем что на этот слот ещё нет активной записи
            existing_interview_stmt = select(Interview).where(
                Interview.time_slot_id == selected_slot_id,
                Interview.status.in_(['confirmed', 'pending'])
            )
            existing_interview_result = await session.execute(existing_interview_stmt)
            existing_interview = existing_interview_result.scalars().first()
            
            if existing_interview:
                # Слот уже занят, но is_available не обновился (баг в логике отмены)
                # Исправляем is_available и сообщаем пользователю
                slot.is_available = False
                await session.commit()
                
                await callback.message.edit_text(
                    "😔 К сожалению, это время уже занято.\n\n"
                    "Используйте /sobes чтобы выбрать другое время."
                )
                await state.clear()
                try:
                    await callback.answer("Время уже занято", show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Удаляем старые отменённые записи на этот слот (чтобы не нарушать UNIQUE constraint)
            # Это нужно потому что у нас UNIQUE constraint на time_slot_id, а не на (time_slot_id, status)
            cancelled_interviews_stmt = select(Interview).where(
                Interview.time_slot_id == selected_slot_id,
                Interview.status == 'cancelled'
            )
            cancelled_interviews_result = await session.execute(cancelled_interviews_stmt)
            cancelled_interviews = cancelled_interviews_result.scalars().all()
            
            if cancelled_interviews:
                for cancelled in cancelled_interviews:
                    print(f"🗑️ Удаляю отменённую запись {cancelled.id} для слота {selected_slot_id}")
                    session.delete(cancelled)
                
                await session.flush()  # Применяем удаление ПРЯМО СЕЙЧАС
                print(f"✅ Удалено {len(cancelled_interviews)} отменённых записей для слота {selected_slot_id}")
            
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
            print(f"🔒 Блокирую слот {slot.id}: is_available={slot.is_available} -> False")
            slot.is_available = False
            
            session.add(interview)
            session.add(slot)
            await session.commit()
            print(f"✅ Запись создана, slot_id={slot.id}, interview_id={interview.id}")
            
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
            
            await callback.message.edit_text(
                f"🎉 Вы успешно записаны на собеседование!\n\n"
                f"🎓 Факультет: {user_faculty}\n"
                f"📅 Дата: {date_display}\n"
                f"⏰ Время: {selected_time}\n\n"
                f"❗️ Записаться можно только один раз.\n"
                f"Для изменения времени обратитесь к администратору.",
                reply_markup=kb.as_markup()
            )
            
            # Отправляем уведомление собеседующему
            if interviewer and interviewer.telegram_id:
                try:
                    student_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
                    
                    # Используем существующий bot вместо создания нового
                    await callback.bot.send_message(
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


@interview_router.callback_query(F.data.startswith('cancel_interview:'))
async def cancel_interview_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка отмены записи на собеседование."""
    _, interview_id = callback.data.split(':', 1)
    interview_id = int(interview_id)
    
    tg_id = callback.from_user.id
    
    async with async_session_maker() as session:
        try:
            # Получаем запись
            interview_stmt = select(Interview).where(Interview.id == interview_id)
            interview_result = await session.execute(interview_stmt)
            interview = interview_result.scalars().first()
            
            if not interview:
                await callback.message.edit_text("❌ Запись не найдена.")
                try:
                    await callback.answer()
                except TelegramBadRequest:
                    pass
                return
            
            # Проверяем что это запись этого пользователя
            bot_user_stmt = select(BotUser).where(BotUser.tg_id == tg_id)
            bot_user_result = await session.execute(bot_user_stmt)
            bot_user = bot_user_result.scalars().first()
            
            if not bot_user or interview.bot_user_id != bot_user.id:
                await callback.message.edit_text("❌ Это не ваша запись.")
                try:
                    await callback.answer()
                except TelegramBadRequest:
                    pass
                return
            
            # Проверяем можно ли отменить
            if not interview.cancellation_allowed:
                await callback.message.edit_text(
                    "❌ Отмена записи больше недоступна.\n\n"
                    "Вы уже использовали возможность отмены.\n"
                    "Обратитесь к администратору для помощи."
                )
                try:
                    await callback.answer()
                except TelegramBadRequest:
                    pass
                return
            
            # Получаем слот
            slot_stmt = select(TimeSlot).where(TimeSlot.id == interview.time_slot_id)
            slot_result = await session.execute(slot_stmt)
            slot = slot_result.scalars().first()
            
            # Освобождаем слот
            if slot:
                print(f"🔓 Освобождаю слот {slot.id}: is_available={slot.is_available} -> True")
                slot.is_available = True
                session.add(slot)
            else:
                print(f"⚠️ Слот не найден для interview {interview.id}, time_slot_id={interview.time_slot_id}")
            
            # Помечаем запись как отменённую
            interview.status = 'cancelled'
            interview.cancelled_at = datetime.now()
            interview.cancellation_allowed = False  # Больше нельзя отменять
            
            session.add(interview)
            await session.commit()
            print(f"✅ Отмена записи {interview.id} завершена, слот {interview.time_slot_id} освобождён")
            
            # Уведомляем собеседующего об отмене
            interviewer_stmt = select(Interviewer).where(Interviewer.id == interview.interviewer_id)
            interviewer_result = await session.execute(interviewer_stmt)
            interviewer = interviewer_result.scalars().first()
            
            if interviewer and interviewer.telegram_id:
                try:
                    student_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
                    
                    # Форматируем дату
                    if slot:
                        date_parts = slot.date.split('-')
                        date_display = f"{date_parts[2]}.{date_parts[1]}.{date_parts[0]}"
                        time_display = f"{slot.time_start}-{slot.time_end}"
                    else:
                        date_display = "N/A"
                        time_display = "N/A"
                    
                    await callback.bot.send_message(
                        interviewer.telegram_id,
                        f"❌ Запись отменена\n\n"
                        f"👤 Кандидат: {student_name}\n"
                        f"🎓 Факультет: {interview.faculty}\n"
                        f"📅 Дата: {date_display}\n"
                        f"⏰ Время: {time_display}\n\n"
                        f"Слот снова доступен для записи."
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления об отмене: {e}")
            
            await callback.message.edit_text(
                "✅ Запись успешно отменена.\n\n"
                "Вы можете записаться на другое время через /sobes\n\n"
                "⚠️ Обратите внимание: отменить запись можно только один раз.\n"
                "При следующей записи отменить её будет нельзя."
            )
            
            try:
                await callback.answer("✅ Запись отменена")
            except TelegramBadRequest:
                pass
        
        except Exception as e:
            print(f"Ошибка при отмене записи: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при отмене записи.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            try:
                await callback.answer()
            except TelegramBadRequest:
                pass


@interview_router.callback_query(F.data.startswith('ask_question:'))
async def ask_question_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки 'Задать вопрос'."""
    interview_id = int(callback.data.split(':')[1])
    tg_id = callback.from_user.id
    
    async with async_session_maker() as session:
        # Проверяем что интервью существует и принадлежит пользователю
        stmt = select(Interview).join(BotUser).where(
            Interview.id == interview_id,
            BotUser.tg_id == tg_id
        )
        result = await session.execute(stmt)
        interview = result.scalars().first()
        
        if not interview:
            await callback.answer("❌ Запись не найдена", show_alert=True)
            return
        
        if interview.status == 'cancelled':
            await callback.answer("❌ Нельзя задать вопрос по отменённой записи", show_alert=True)
            return
    
    # Сохраняем interview_id в state
    await state.update_data(interview_id=interview_id)
    await state.set_state(QuestionStates.waiting_question)
    
    await callback.message.edit_text(
        "📝 Задайте вопрос собеседующему:\n\n"
        "Напишите ваш вопрос в следующем сообщении.\n"
        "Собеседующий получит уведомление и сможет вам ответить."
    )
    
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@interview_router.message(QuestionStates.waiting_question)
async def process_question(message: types.Message, state: FSMContext):
    """Обработка вопроса от кандидата."""
    question_text = message.text.strip()
    
    if not question_text:
        await message.answer("❌ Вопрос не может быть пустым. Попробуйте снова:")
        return
    
    if len(question_text) > 1000:
        await message.answer("❌ Вопрос слишком длинный (максимум 1000 символов). Сократите текст:")
        return
    
    data = await state.get_data()
    interview_id = data.get('interview_id')
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Получаем интервью с данными собеседующего
        stmt = select(Interview).where(Interview.id == interview_id)
        result = await session.execute(stmt)
        interview = result.scalars().first()
        
        if not interview:
            await message.answer("❌ Запись не найдена")
            await state.clear()
            return
        
        # Получаем собеседующего
        stmt = select(Interviewer).where(Interviewer.id == interview.interviewer_id)
        result = await session.execute(stmt)
        interviewer = result.scalars().first()
        
        if not interviewer:
            await message.answer("❌ Собеседующий не найден")
            await state.clear()
            return
        
        # Сохраняем сообщение в БД
        new_message = InterviewMessage(
            interview_id=interview_id,
            from_user_id=tg_id,
            to_user_id=interviewer.telegram_id,
            message_text=question_text,
            is_read=False
        )
        session.add(new_message)
        await session.commit()
        await session.refresh(new_message)
        message_db_id = new_message.id
    
    await state.clear()
    await message.answer(
        "✅ Ваш вопрос отправлен собеседующему!\n\n"
        "Вы получите уведомление, когда он ответит."
    )
    
    # Отправляем уведомление собеседующему
    try:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="💬 Ответить на вопрос",
            callback_data=f"answer_question:{message_db_id}"
        ))
        
        await message.bot.send_message(
            interviewer.telegram_id,
            f"❓ Новый вопрос от кандидата:\n\n"
            f"<b>Вопрос:</b>\n{question_text}\n\n"
            f"Нажмите кнопку ниже, чтобы ответить.",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления собеседующему: {e}")


@interview_router.callback_query(F.data.startswith('answer_question:'))
async def answer_question_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки 'Ответить на вопрос' от собеседующего."""
    message_id = int(callback.data.split(':')[1])
    tg_id = callback.from_user.id
    
    async with async_session_maker() as session:
        # Проверяем что сообщение существует и адресовано этому собеседующему
        stmt = select(InterviewMessage).where(
            InterviewMessage.id == message_id,
            InterviewMessage.to_user_id == tg_id
        )
        result = await session.execute(stmt)
        msg = result.scalars().first()
        
        if not msg:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        
        # Помечаем как прочитанное
        msg.is_read = True
        await session.commit()
    
    # Сохраняем message_id в state
    await state.update_data(message_id=message_id, question_text=msg.message_text)
    await state.set_state(QuestionStates.waiting_answer)
    
    await callback.message.edit_text(
        f"❓ Вопрос от кандидата:\n\n"
        f"<i>{msg.message_text}</i>\n\n"
        f"📝 Напишите ваш ответ в следующем сообщении:",
        parse_mode="HTML"
    )
    
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@interview_router.message(QuestionStates.waiting_answer)
async def process_answer(message: types.Message, state: FSMContext):
    """Обработка ответа от собеседующего."""
    answer_text = message.text.strip()
    
    if not answer_text:
        await message.answer("❌ Ответ не может быть пустым. Попробуйте снова:")
        return
    
    if len(answer_text) > 1000:
        await message.answer("❌ Ответ слишком длинный (максимум 1000 символов). Сократите текст:")
        return
    
    data = await state.get_data()
    original_message_id = data.get('message_id')
    question_text = data.get('question_text')
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Получаем оригинальное сообщение
        stmt = select(InterviewMessage).where(InterviewMessage.id == original_message_id)
        result = await session.execute(stmt)
        original_msg = result.scalars().first()
        
        if not original_msg:
            await message.answer("❌ Сообщение не найдено")
            await state.clear()
            return
        
        # Сохраняем ответ в БД
        answer_message = InterviewMessage(
            interview_id=original_msg.interview_id,
            from_user_id=tg_id,
            to_user_id=original_msg.from_user_id,
            message_text=answer_text,
            is_read=False
        )
        session.add(answer_message)
        await session.commit()
    
    await state.clear()
    await message.answer(
        "✅ Ваш ответ отправлен кандидату!\n\n"
        "Кандидат получит уведомление с вашим ответом."
    )
    
    # Отправляем уведомление кандидату
    try:
        await message.bot.send_message(
            original_msg.from_user_id,
            f"💬 Ответ от собеседующего:\n\n"
            f"<b>Ваш вопрос:</b>\n<i>{question_text}</i>\n\n"
            f"<b>Ответ:</b>\n{answer_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка отправки ответа кандидату: {e}")


@interview_router.message(Command('my_interviews'))
async def my_interviews_command(message: types.Message):
    """Показать список записей (для собеседующего)."""
    tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        # Проверяем, является ли пользователь собеседующим
        stmt = select(Interviewer).where(Interviewer.telegram_id == tg_id)
        result = await session.execute(stmt)
        interviewer = result.scalars().first()
        
        if not interviewer:
            await message.answer(
                "❌ Вы не зарегистрированы как собеседующий.\n\n"
                "Используйте /register_sobes для регистрации."
            )
            return
        
        # Получаем все записи собеседующего
        stmt = select(Interview).where(
            Interview.interviewer_id == interviewer.id,
            Interview.status.in_(['confirmed', 'pending'])
        ).join(TimeSlot).order_by(TimeSlot.date, TimeSlot.time_start)
        result = await session.execute(stmt)
        interviews = result.scalars().all()
        
        if not interviews:
            await message.answer(
                "📋 У вас пока нет записей на собеседования.\n\n"
                "Когда кандидаты начнут записываться, вы увидите их здесь."
            )
            return
        
        # Группируем по датам
        from collections import defaultdict
        by_date = defaultdict(list)
        
        for interview in interviews:
            # Получаем слот
            stmt = select(TimeSlot).where(TimeSlot.id == interview.time_slot_id)
            result = await session.execute(stmt)
            slot = result.scalars().first()
            
            # Получаем кандидата
            stmt = select(BotUser).where(BotUser.id == interview.bot_user_id)
            result = await session.execute(stmt)
            bot_user = result.scalars().first()
            
            # Получаем Person если есть
            person_name = "Не указано"
            if interview.person_id:
                stmt = select(Person).where(Person.id == interview.person_id)
                result = await session.execute(stmt)
                person = result.scalars().first()
                if person:
                    person_name = person.full_name
            
            by_date[slot.date].append({
                'time': f"{slot.time_start}-{slot.time_end}",
                'candidate': person_name,
                'faculty': interview.faculty or "Не указан",
                'username': f"@{bot_user.telegram_username}" if bot_user.telegram_username else "Нет username"
            })
        
        # Формируем текст
        text = f"📋 <b>Ваши записи на собеседования</b>\n\n"
        
        for date in sorted(by_date.keys()):
            text += f"📅 <b>{date}</b>\n"
            for interview in by_date[date]:
                text += (
                    f"  🕐 {interview['time']}\n"
                    f"     👤 {interview['candidate']}\n"
                    f"     🎓 {interview['faculty']}\n"
                    f"     📱 {interview['username']}\n\n"
                )
        
        text += f"<b>Всего записей:</b> {len(interviews)}"
        
        await message.answer(text, parse_mode="HTML")


@interview_router.message(Command('sobeser_stats'))
async def sobeser_stats_command(message: types.Message):
    """Статистика по всем собеседующим (для админа)."""
    ADMIN_ID = 922109605  # TODO: вынести в конфиг
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа. Команда только для администратора.")
        return
    
    async with async_session_maker() as session:
        # Получаем всех собеседующих
        stmt = select(Interviewer).where(Interviewer.is_active == True).order_by(Interviewer.full_name)
        result = await session.execute(stmt)
        interviewers = result.scalars().all()
        
        if not interviewers:
            await message.answer("📋 Нет зарегистрированных собеседующих.")
            return
        
        text = "📊 <b>Статистика по собеседующим</b>\n\n"
        
        total_slots = 0
        total_booked = 0
        total_free = 0
        
        for interviewer in interviewers:
            # Получаем все слоты собеседующего
            slots_stmt = select(TimeSlot).where(TimeSlot.interviewer_id == interviewer.id)
            slots_result = await session.execute(slots_stmt)
            slots = slots_result.scalars().all()
            
            if not slots:
                continue
            
            # Считаем статистику
            free_slots = sum(1 for s in slots if s.is_available)
            booked_slots = len(slots) - free_slots
            
            total_slots += len(slots)
            total_booked += booked_slots
            total_free += free_slots
            
            # Факультеты
            faculties_str = interviewer.faculties if interviewer.faculties else "Не указаны"
            
            text += (
                f"👤 <b>{interviewer.full_name}</b>\n"
                f"   ID: {interviewer.interviewer_sheet_id}\n"
                f"   🎓 Факультеты: {faculties_str}\n"
                f"   📊 Слотов: {len(slots)} (🟢 {free_slots} свободно, 🔴 {booked_slots} занято)\n\n"
            )
        
        text += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Итого:</b>\n"
            f"👥 Собеседующих: {len(interviewers)}\n"
            f"📊 Всего слотов: {total_slots}\n"
            f"🟢 Свободно: {total_free}\n"
            f"🔴 Занято: {total_booked}"
        )
        
        await message.answer(text, parse_mode="HTML")

