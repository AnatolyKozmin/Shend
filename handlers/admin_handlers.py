from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
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


class AllRassStates(StatesGroup):
    waiting_text = State()


class DODepStates(StatesGroup):
    waiting_faculty = State()
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

    kb = InlineKeyboardBuilder()
    for f in faculties:
        kb.row(InlineKeyboardButton(text=f, callback_data=f"co_faculty:{f}"))
    kb = kb.as_markup()

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

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text='Да (присутствие)', callback_data='co_presence:yes'),
        InlineKeyboardButton(text='Нет', callback_data='co_presence:no')
    )
    kb = kb.as_markup()

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
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='Да', callback_data=f'co_answer:{campaign_id}:yes'))
        kb.row(InlineKeyboardButton(text='Нет', callback_data=f'co_answer:{campaign_id}:no'))
        return kb.as_markup()

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    for bu in recipients:
        try:
            # Если это рассылка НЕ для присутствия — отправляем просто текст без inline-кнопок
            if is_presence:
                reply = mk_kb(campaign.id)
                await message.bot.send_message(chat_id=bu.tg_id, text=text, reply_markup=reply)
            else:
                await message.bot.send_message(chat_id=bu.tg_id, text=text)
            sent += 1
            # Небольшая пауза между отправками, чтобы снизить риск достижения лимитов
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception:
            # Любая ошибка отправки учитывается как ошибка — админ увидит количество
            errors += 1

    await message.answer(f'Рассылка отправлена. Найдено: {len(recipients)}, успешно отправлено: {sent}, ошибок: {errors}')
    await state.clear()


@admin_router.message(Command(commands=['dodep']))
async def dodep_start(message: types.Message, state: FSMContext):
    # рассылка тем, кто НЕ ответил по факультету (отправка новым/неотвеченным)
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session_maker() as session:
        stmt = select(Person.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]

    if not faculties:
        await message.answer('Нет записей с факультетами в базе.')
        return

    kb = InlineKeyboardBuilder()
    for f in faculties:
        kb.row(InlineKeyboardButton(text=f, callback_data=f"dodep_faculty:{f}"))
    kb = kb.as_markup()

    await state.set_state(DODepStates.waiting_faculty)
    await message.answer('Выберите факультет для повторной рассылки (только тем, кто не ответил):', reply_markup=kb)


@admin_router.callback_query(lambda c: c.data and c.data.startswith('dodep_faculty:'))
async def dodep_faculty_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, faculty = callback.data.split(':', 1)
    await state.update_data(faculty=faculty)
    await state.set_state(DODepStates.waiting_text)

    await callback.message.answer(f'Выбран факультет: {faculty}\nПришлите текст рассылки для тех, кто не ответил:')
    await callback.answer()


@admin_router.message(StateFilter(DODepStates.waiting_text))
async def dodep_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    faculty = data.get('faculty')
    text = message.text

    async with async_session_maker() as session:
        # создаём кампанию
        campaign = CO(admin_id=message.from_user.id, faculty=faculty, is_presence=True, text=text)
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)

        # subquery: bot_user ids who already have a response for any campaign of this faculty
        subq = select(COResponse.bot_user_id).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty).distinct()

        # получатели: BotUser связанный с Person данного факультета и НЕ в subq
        stmt = select(BotUser).join(Person, BotUser.person_id == Person.id).where(Person.faculty == faculty, ~BotUser.id.in_(subq))
        res = await session.execute(stmt)
        recipients = res.scalars().all()

    if not recipients:
        await message.answer('Нет пользователей без ответов для выбранного факультета.')
        await state.clear()
        return

    def mk_kb(campaign_id: int):
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='Да', callback_data=f'co_answer:{campaign_id}:yes'))
        kb.row(InlineKeyboardButton(text='Нет', callback_data=f'co_answer:{campaign_id}:no'))
        return kb.as_markup()

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    for bu in recipients:
        try:
            reply = mk_kb(campaign.id)
            await message.bot.send_message(chat_id=bu.tg_id, text=text, reply_markup=reply)
            sent += 1
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception:
            errors += 1

    await message.answer(f'Повторная рассылка завершена. Найдено без ответов: {len(recipients)}, успешно отправлено: {sent}, ошибок: {errors}')
    await state.clear()



@admin_router.message(Command(commands=['create_all_rass', 'creare_all_rass']))
async def create_all_rass(message: types.Message, state: FSMContext):
    # команда для рассылки ВСЕМ записанным в базе пользователям (без кнопок)
    if message.from_user.id != ADMIN_ID:
        return

    await state.set_state(AllRassStates.waiting_text)
    await message.answer('Пришлите текст распространения, который нужно разослать ВСЕМ пользователям (без кнопок).')


@admin_router.message(StateFilter(AllRassStates.waiting_text))
async def receive_all_text(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text

    async with async_session_maker() as session:
        stmt = select(BotUser)
        res = await session.execute(stmt)
        recipients = res.scalars().all()

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    for bu in recipients:
        try:
            await message.bot.send_message(chat_id=bu.tg_id, text=text)
            sent += 1
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception:
            errors += 1

    await message.answer(f'Рассылка всем завершена. Найдено в базе: {len(recipients)}, успешно отправлено: {sent}, ошибок: {errors}')
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

    # Попытаемся отредактировать исходное сообщение: убрать кнопки и показать подтверждение
    try:
        # edit_message_text заменит текст и уберёт клавиатуру (reply_markup=None)
        await callback.message.edit_text('Ответ записан !')
    except Exception:
        # Если не удалось отредактировать (например, сообщение удалено), просто игнорируем
        pass

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

            # количество тех, кто НЕ ответил: связанные BotUser у этого факультета без записи в COResponse для этой факультеты
            # считаем связанных BotUser
            total_stmt = select(func.count(BotUser.id)).join(Person, BotUser.person_id == Person.id).where(Person.faculty == faculty)
            total_res = await session.execute(total_stmt)
            total_linked = total_res.scalar() or 0

            # те, у кого есть ответы (yes или no) для этой факультеты
            answered_stmt = select(func.count(func.distinct(COResponse.bot_user_id))).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty)
            answered_res = await session.execute(answered_stmt)
            answered_count = answered_res.scalar() or 0

            not_answered = total_linked - answered_count

            # Списки ФИО (или фамилий) проголосовавших 'yes' и 'no'
            # Получаем full_name из Person через BotUser
            yes_names = []
            no_names = []

            yes_names_stmt = select(Person.full_name).join(BotUser, BotUser.person_id == Person.id).join(COResponse, COResponse.bot_user_id == BotUser.id).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty, COResponse.answer == 'yes')
            yes_names_res = await session.execute(yes_names_stmt)
            yes_names = [r[0] for r in yes_names_res.fetchall() if r[0]]

            no_names_stmt = select(Person.full_name).join(BotUser, BotUser.person_id == Person.id).join(COResponse, COResponse.bot_user_id == BotUser.id).join(CO, COResponse.campaign_id == CO.id).where(CO.faculty == faculty, COResponse.answer == 'no')
            no_names_res = await session.execute(no_names_stmt)
            no_names = [r[0] for r in no_names_res.fetchall() if r[0]]

            text = (
                f"Факультет: {faculty}\n"
                f"Получателей (связанных с ботом): {recipients}\n"
                f"Ответы — Да: {yes_count}, Нет: {no_count}"
            )

            if yes_names:
                text += '\n\nПоставили "Да":\n' + '\n'.join(yes_names)
            if no_names:
                text += '\n\nПоставили "Нет":\n' + '\n'.join(no_names)
            await message.answer(text)
