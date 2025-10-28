from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from db.engine import async_session_maker
from db.models import Interviewer, BotUser, TimeSlot
from utils.google_sheets import find_interviewer_by_code, get_schedules_data
from datetime import datetime


interview_router = Router()


class RegisterSobesStates(StatesGroup):
    waiting_code = State()
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
        "Введите ваш код доступа (5 цифр):"
    )


@interview_router.message(RegisterSobesStates.waiting_code)
async def register_sobes_code(message: types.Message, state: FSMContext):
    """Обработка ввода кода доступа."""
    code = message.text.strip()
    
    # Проверяем формат кода
    if not code.isdigit() or len(code) != 5:
        await message.answer(
            "❌ Неверный формат кода.\n\n"
            "Код должен состоять из 5 цифр. Попробуйте снова:"
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
        await callback.answer()
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
                await callback.answer()
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
            await callback.answer("✅ Регистрация завершена!")
        
        except Exception as e:
            print(f"Ошибка при сохранении собеседующего: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при регистрации.\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.clear()
            await callback.answer()


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
        slots_data = get_schedules_data()
        
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
            
            await message.answer(
                f"✅ Синхронизация завершена!\n\n"
                f"📊 Статистика:\n"
                f"• Добавлено новых слотов: {added}\n"
                f"• Обновлено существующих: {updated}\n"
                f"• Пропущено (занято или нет собеседующего): {skipped}\n"
                f"• Ошибок: {errors}\n\n"
                f"📋 Всего обработано: {len(slots_data)} слотов из Google Sheets"
            )
    
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
        await message.answer(
            f"❌ Произошла ошибка при синхронизации:\n{str(e)}\n\n"
            "Проверьте доступ к Google Sheets и правильность credentials."
        )

