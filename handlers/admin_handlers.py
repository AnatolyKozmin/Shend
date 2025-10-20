from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.state import StateFilter
import asyncio
from sqlalchemy import select, func
from db.engine import async_session_maker
from db.models import CO, COResponse, Person, BotUser


admin_router = Router()

ADMIN_ID = 922109605


class COCreateStates(StatesGroup):
    waiting_faculty = State()
    waiting_presence = State()
    waiting_text = State()


@admin_router.message(Command(commands=['create_rass']))
async def create_rass(message: types.Message, state: FSMContext):
    # только админ
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session_maker() as session:
        stmt = select(Person.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]

    if not faculties:
        await message.answer('Нет записей с факультетами в базе.')
        return

    kb = InlineKeyboardMarkup()
    for f in faculties:
        kb.add(InlineKeyboardButton(text=f, callback_data=f"co_faculty:{f}"))

    await state.set_state(COCreateStates.waiting_faculty)
    await message.answer('Выберите факультет для рассылки:', reply_markup=kb)


@admin_router.callback_query(lambda c: c.data and c.data.startswith('co_faculty:'))
async def faculty_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, faculty = callback.data.split(':', 1)
    await state.update_data(faculty=faculty)
    await state.set_state(COCreateStates.waiting_presence)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Да (присутствие)', callback_data='co_presence:yes'),
         InlineKeyboardButton(text='Нет', callback_data='co_presence:no')]
    ])

    await callback.message.answer(f'Выбран факультет: {faculty}\nЭто рассылка для присутствия?', reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(lambda c: c.data and c.data.startswith('co_presence:'))
async def presence_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, ans = callback.data.split(':', 1)
    is_presence = True if ans == 'yes' else False
    await state.update_data(is_presence=is_presence)
    await state.set_state(COCreateStates.waiting_text)

    await callback.message.answer('Пришлите текст рассылки, который нужно отправить студентам факультета.')
    await callback.answer()


@admin_router.message(StateFilter(COCreateStates.waiting_text))
async def receive_text(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    faculty = data.get('faculty')
    is_presence = data.get('is_presence', False)
    text = message.text

    # Сохраняем кампанию
    async with async_session_maker() as session:
        campaign = CO(admin_id=message.from_user.id, faculty=faculty, is_presence=is_presence, text=text)
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)

        # Получаем список получателей: BotUser связанный с Person данного факультета
        stmt = select(BotUser).join(Person, BotUser.person_id == Person.id).where(Person.faculty == faculty)
        res = await session.execute(stmt)
        recipients = res.scalars().all()

    # Клавиатура для опроса
    def mk_kb(campaign_id: int):
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(text='Да', callback_data=f'co_answer:{campaign_id}:yes'))
        kb.add(InlineKeyboardButton(text='Нет', callback_data=f'co_answer:{campaign_id}:no'))
        return kb

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    for bu in recipients:
        try:
            await message.bot.send_message(chat_id=bu.tg_id, text=text, reply_markup=mk_kb(campaign.id))
            sent += 1
            # Небольшая пауза между отправками, чтобы снизить риск достижения лимитов
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception:
            # Любая ошибка отправки учитывается как ошибка — админ увидит количество
            errors += 1

    await message.answer(f'Рассылка отправлена. Найдено: {len(recipients)}, успешно отправлено: {sent}, ошибок: {errors}')
    await state.clear()


@admin_router.callback_query(lambda c: c.data and c.data.startswith('co_answer:'))
async def handle_answer(callback: types.CallbackQuery):
    # Студент нажал Да/Нет
    try:
        _, campaign_id_str, answer = callback.data.split(':', 2)
        campaign_id = int(campaign_id_str)
    except Exception:
        await callback.answer()
        return

    tg_id = callback.from_user.id

    async with async_session_maker() as session:
        # найти bot_user
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        res = await session.execute(stmt)
        bot_user = res.scalars().first()
        if not bot_user:
            await callback.answer('Ваша учётная запись не связана с базой.', show_alert=True)
            return

        # проверить есть ли уже ответ для этой кампании от этого пользователя
        stmt2 = select(COResponse).where(COResponse.campaign_id == campaign_id, COResponse.bot_user_id == bot_user.id)
        res2 = await session.execute(stmt2)
        resp = res2.scalars().first()
        if resp:
            resp.answer = answer
            session.add(resp)
            await session.commit()
        else:
            new = COResponse(campaign_id=campaign_id, bot_user_id=bot_user.id, answer=answer)
            session.add(new)
            await session.commit()

    await callback.answer('Ваш ответ сохранён. Спасибо!')


@admin_router.message(Command(commands=['get_stats']))
async def get_stats(message: types.Message):
    """Отчёт по всем факультетам: количество получателей и уникальные ответы Да/Нет."""
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session_maker() as session:
        stmt = select(Person.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]

        if not faculties:
            await message.answer('В базе нет факультетов для отчёта.')
            return

        for faculty in faculties:
            # сколько связанных BotUser у этого факультета
            rec_stmt = select(func.count(BotUser.id)).join(Person, BotUser.person_id == Person.id).where(Person.faculty == faculty)
            rec_res = await session.execute(rec_stmt)
            recipients = rec_res.scalar() or 0

            # уникальные ответы 'yes'
            yes_stmt = select(func.count(func.distinct(COResponse.bot_user_id))).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty, COResponse.answer == 'yes')
            yes_res = await session.execute(yes_stmt)
            yes_count = yes_res.scalar() or 0

            # уникальные ответы 'no'
            no_stmt = select(func.count(func.distinct(COResponse.bot_user_id))).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty, COResponse.answer == 'no')
            no_res = await session.execute(no_stmt)
            no_count = no_res.scalar() or 0

            text = (
                f"Факультет: {faculty}\n"
                f"Получателей (связанных с ботом): {recipients}\n"
                f"Ответы — Да: {yes_count}, Нет: {no_count}"
            )

            await message.answer(text)
