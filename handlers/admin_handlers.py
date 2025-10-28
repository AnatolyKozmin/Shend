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
from db.models import CO, COResponse, Person, BotUser, Reserv


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


class ReservRassStates(StatesGroup):
    waiting_faculty = State()
    waiting_presence = State()
    waiting_text = State()


class DODepReservStates(StatesGroup):
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


@admin_router.message(Command(commands=['poter']))
async def poter_check(message: types.Message):
    """Проверка совпадений telegram_username между Reserv и BotUser по факультетам."""
    if message.from_user.id != ADMIN_ID:
        return
    
    async with async_session_maker() as session:
        # Получаем все записи из Reserv
        reserv_stmt = select(Reserv).where(Reserv.telegram_username.isnot(None))
        reserv_result = await session.execute(reserv_stmt)
        reserv_users = reserv_result.scalars().all()
        
        if not reserv_users:
            await message.answer("❌ В таблице Reserv нет пользователей с telegram_username.")
            return
        
        # Получаем все telegram_username из BotUser (приводим к lowercase)
        bot_users_stmt = select(BotUser.telegram_username).where(BotUser.telegram_username.isnot(None))
        bot_users_result = await session.execute(bot_users_stmt)
        bot_usernames = {username.lower() for (username,) in bot_users_result.fetchall() if username}
        
        # Группируем по факультетам
        faculty_stats = {}
        
        for reserv_user in reserv_users:
            faculty = reserv_user.faculty or "Без факультета"
            
            if faculty not in faculty_stats:
                faculty_stats[faculty] = {
                    "total": 0,
                    "found": 0,
                    "not_found": []
                }
            
            faculty_stats[faculty]["total"] += 1
            
            # Приводим к lowercase и проверяем
            username_lower = reserv_user.telegram_username.lower() if reserv_user.telegram_username else None
            
            if username_lower and username_lower in bot_usernames:
                faculty_stats[faculty]["found"] += 1
            else:
                faculty_stats[faculty]["not_found"].append({
                    "full_name": reserv_user.full_name,
                    "username": reserv_user.telegram_username
                })
        
        # Формируем ответ
        if not faculty_stats:
            await message.answer("В таблице Reserv нет данных для проверки.")
            return
        
        # Отправляем общую статистику
        total_reserv = sum(stats["total"] for stats in faculty_stats.values())
        total_found = sum(stats["found"] for stats in faculty_stats.values())
        total_not_found = sum(len(stats["not_found"]) for stats in faculty_stats.values())
        
        summary_text = f"📊 Общая статистика по Reserv:\n\n"
        summary_text += f"📋 Всего в Reserv: {total_reserv} чел.\n"
        summary_text += f"✅ Найдено в боте: {total_found} чел.\n"
        summary_text += f"❌ Не найдено в боте: {total_not_found} чел.\n\n"
        summary_text += "─" * 30
        
        await message.answer(summary_text)
        
        # Отправляем детальную статистику по факультетам
        for faculty, stats in sorted(faculty_stats.items()):
            faculty_text = f"🎓 {faculty}\n\n"
            faculty_text += f"📋 Всего: {stats['total']} чел.\n"
            faculty_text += f"✅ В боте: {stats['found']} чел.\n"
            faculty_text += f"❌ Не в боте: {len(stats['not_found'])} чел.\n"
            
            if stats['not_found']:
                faculty_text += f"\n👥 Список тех, кого нет в боте:\n"
                for user in stats['not_found']:
                    username_display = f"@{user['username']}" if user['username'] else "нет username"
                    faculty_text += f"• {user['full_name']} ({username_display})\n"
            
            faculty_text += "\n" + "─" * 30
            
            # Разбиваем длинные сообщения
            if len(faculty_text) > 4000:
                # Отправляем заголовок
                header = f"🎓 {faculty}\n\n"
                header += f"📋 Всего: {stats['total']} чел.\n"
                header += f"✅ В боте: {stats['found']} чел.\n"
                header += f"❌ Не в боте: {len(stats['not_found'])} чел.\n\n"
                await message.answer(header)
                
                # Отправляем список частями
                if stats['not_found']:
                    current_text = "👥 Список тех, кого нет в боте:\n"
                    for user in stats['not_found']:
                        username_display = f"@{user['username']}" if user['username'] else "нет username"
                        line = f"• {user['full_name']} ({username_display})\n"
                        
                        if len(current_text + line) > 4000:
                            await message.answer(current_text)
                            current_text = line
                        else:
                            current_text += line
                    
                    if current_text.strip():
                        await message.answer(current_text)
            else:
                await message.answer(faculty_text)


@admin_router.message(Command(commands=['create_reserv_rass']))
async def create_reserv_rass(message: types.Message, state: FSMContext):
    """Создание рассылки для пользователей из таблицы Reserv."""
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session_maker() as session:
        # Получаем уникальные факультеты из Reserv
        stmt = select(Reserv.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]

    if not faculties:
        await message.answer('❌ Нет записей с факультетами в таблице Reserv.')
        return

    kb = InlineKeyboardBuilder()
    for f in faculties:
        kb.row(InlineKeyboardButton(text=f, callback_data=f"reserv_faculty:{f}"))
    kb = kb.as_markup()

    await state.set_state(ReservRassStates.waiting_faculty)
    await message.answer('Выберите факультет для рассылки из Reserv:', reply_markup=kb)


@admin_router.callback_query(lambda c: c.data and c.data.startswith('reserv_faculty:'))
async def reserv_faculty_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, faculty = callback.data.split(':', 1)
    await state.update_data(faculty=faculty)
    await state.set_state(ReservRassStates.waiting_presence)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text='Да (присутствие)', callback_data='reserv_presence:yes'),
        InlineKeyboardButton(text='Нет', callback_data='reserv_presence:no')
    )
    kb = kb.as_markup()

    await callback.message.answer(f'Выбран факультет: {faculty}\nЭто рассылка для присутствия?', reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(lambda c: c.data and c.data.startswith('reserv_presence:'))
async def reserv_presence_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, ans = callback.data.split(':', 1)
    is_presence = True if ans == 'yes' else False
    await state.update_data(is_presence=is_presence)
    await state.set_state(ReservRassStates.waiting_text)

    await callback.message.answer('Пришлите текст рассылки для студентов из таблицы Reserv.')
    await callback.answer()


@admin_router.message(StateFilter(ReservRassStates.waiting_text))
async def receive_reserv_text(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    faculty = data.get('faculty')
    is_presence = data.get('is_presence', False)
    text = message.text

    async with async_session_maker() as session:
        # Получаем список получателей из Reserv по факультету с username
        reserv_stmt = select(Reserv).where(
            Reserv.faculty == faculty,
            Reserv.telegram_username.isnot(None)
        )
        reserv_result = await session.execute(reserv_stmt)
        reserv_users = reserv_result.scalars().all()

        if not reserv_users:
            await message.answer(f'❌ В таблице Reserv нет пользователей факультета "{faculty}" с telegram_username.')
            await state.clear()
            return

        # Получаем соответствующих BotUser по username (приводим к lowercase)
        reserv_usernames = [ru.telegram_username.lower() for ru in reserv_users if ru.telegram_username]
        
        bot_users_stmt = select(BotUser).where(
            func.lower(BotUser.telegram_username).in_(reserv_usernames)
        )
        bot_users_result = await session.execute(bot_users_stmt)
        bot_users = bot_users_result.scalars().all()

        if not bot_users:
            await message.answer(f'❌ Не найдено ни одного пользователя из Reserv в BotUser для факультета "{faculty}".')
            await state.clear()
            return

    # Клавиатура для опроса (если нужна)
    def mk_kb(is_presence_flag: bool):
        if is_presence_flag:
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text='Да', callback_data=f'reserv_answer:yes'))
            kb.row(InlineKeyboardButton(text='Нет', callback_data=f'reserv_answer:no'))
            return kb.as_markup()
        return None

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    
    for bu in bot_users:
        try:
            if is_presence:
                reply = mk_kb(True)
                await message.bot.send_message(chat_id=bu.tg_id, text=text, reply_markup=reply)
            else:
                await message.bot.send_message(chat_id=bu.tg_id, text=text)
            sent += 1
            
            # Обновляем флаг message_sent для соответствующих записей Reserv
            async with async_session_maker() as session:
                username_lower = bu.telegram_username.lower() if bu.telegram_username else None
                if username_lower:
                    update_stmt = select(Reserv).where(
                        func.lower(Reserv.telegram_username) == username_lower
                    )
                    update_result = await session.execute(update_stmt)
                    reserv_record = update_result.scalars().first()
                    
                    if reserv_record:
                        reserv_record.message_sent = True
                        session.add(reserv_record)
                        await session.commit()
            
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception as e:
            errors += 1
            print(f"Ошибка отправки для {bu.tg_id}: {e}")

    await message.answer(
        f'✅ Рассылка из Reserv отправлена.\n'
        f'Найдено в Reserv: {len(reserv_users)}\n'
        f'Найдено в боте: {len(bot_users)}\n'
        f'Успешно отправлено: {sent}\n'
        f'Ошибок: {errors}'
    )
    await state.clear()


@admin_router.message(Command(commands=['dodep_reserv']))
async def dodep_reserv_start(message: types.Message, state: FSMContext):
    """Рассылка тем из Reserv, кому ещё не отправлялось (message_sent = False)."""
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session_maker() as session:
        # Получаем уникальные факультеты из Reserv
        stmt = select(Reserv.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]

    if not faculties:
        await message.answer('❌ Нет записей с факультетами в таблице Reserv.')
        return

    kb = InlineKeyboardBuilder()
    for f in faculties:
        kb.row(InlineKeyboardButton(text=f, callback_data=f"dodep_reserv_faculty:{f}"))
    kb = kb.as_markup()

    await state.set_state(DODepReservStates.waiting_faculty)
    await message.answer('Выберите факультет для повторной рассылки (только тем, кому не отправлялось из Reserv):', reply_markup=kb)


@admin_router.callback_query(lambda c: c.data and c.data.startswith('dodep_reserv_faculty:'))
async def dodep_reserv_faculty_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer('Нет доступа', show_alert=True)
        return

    _, faculty = callback.data.split(':', 1)
    await state.update_data(faculty=faculty)
    await state.set_state(DODepReservStates.waiting_text)

    await callback.message.answer(f'Выбран факультет: {faculty}\nПришлите текст рассылки для тех, кому не отправлялось (с кнопками):')
    await callback.answer()


@admin_router.message(StateFilter(DODepReservStates.waiting_text))
async def dodep_reserv_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    faculty = data.get('faculty')
    text = message.text

    async with async_session_maker() as session:
        # Получаем пользователей из Reserv, которым ещё не отправлялось (message_sent = False)
        reserv_stmt = select(Reserv).where(
            Reserv.faculty == faculty,
            Reserv.telegram_username.isnot(None),
            Reserv.message_sent == False
        )
        reserv_result = await session.execute(reserv_stmt)
        reserv_users = reserv_result.scalars().all()

        if not reserv_users:
            await message.answer(f'✅ Всем пользователям из Reserv факультета "{faculty}" уже отправлялись сообщения.')
            await state.clear()
            return

        # Получаем соответствующих BotUser
        reserv_usernames = [ru.telegram_username.lower() for ru in reserv_users if ru.telegram_username]
        
        bot_users_stmt = select(BotUser).where(
            func.lower(BotUser.telegram_username).in_(reserv_usernames)
        )
        bot_users_result = await session.execute(bot_users_stmt)
        bot_users = bot_users_result.scalars().all()

        if not bot_users:
            await message.answer(f'❌ Не найдено пользователей из Reserv в боте для факультета "{faculty}".')
            await state.clear()
            return

    # Клавиатура с кнопками Да/Нет
    def mk_kb():
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='Да', callback_data=f'reserv_answer:yes'))
        kb.row(InlineKeyboardButton(text='Нет', callback_data=f'reserv_answer:no'))
        return kb.as_markup()

    sent = 0
    errors = 0
    PAUSE_SECONDS = 0.1
    
    for bu in bot_users:
        try:
            reply = mk_kb()
            await message.bot.send_message(chat_id=bu.tg_id, text=text, reply_markup=reply)
            sent += 1
            
            # Обновляем флаг message_sent
            async with async_session_maker() as session:
                username_lower = bu.telegram_username.lower() if bu.telegram_username else None
                if username_lower:
                    update_stmt = select(Reserv).where(
                        func.lower(Reserv.telegram_username) == username_lower
                    )
                    update_result = await session.execute(update_stmt)
                    reserv_record = update_result.scalars().first()
                    
                    if reserv_record:
                        reserv_record.message_sent = True
                        session.add(reserv_record)
                        await session.commit()
            
            await asyncio.sleep(PAUSE_SECONDS)
        except Exception as e:
            errors += 1
            print(f"Ошибка отправки для {bu.tg_id}: {e}")

    await message.answer(
        f'✅ Повторная рассылка из Reserv завершена.\n'
        f'Найдено без отправки: {len(reserv_users)}\n'
        f'Найдено в боте: {len(bot_users)}\n'
        f'Успешно отправлено: {sent}\n'
        f'Ошибок: {errors}'
    )
    await state.clear()


@admin_router.callback_query(lambda c: c.data and c.data.startswith('reserv_answer:'))
async def handle_reserv_answer(callback: types.CallbackQuery):
    """Обработка ответов Да/Нет на рассылки из Reserv."""
    try:
        _, answer = callback.data.split(':', 1)
    except Exception:
        await callback.answer()
        return

    tg_id = callback.from_user.id

    async with async_session_maker() as session:
        # Найти bot_user
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        res = await session.execute(stmt)
        bot_user = res.scalars().first()
        
        if not bot_user:
            await callback.answer('Ваша учётная запись не связана с базой.', show_alert=True)
            return

        # Найти соответствующую запись в Reserv по telegram_username
        if bot_user.telegram_username:
            username_lower = bot_user.telegram_username.lower()
            reserv_stmt = select(Reserv).where(
                func.lower(Reserv.telegram_username) == username_lower
            )
            reserv_result = await session.execute(reserv_stmt)
            reserv_record = reserv_result.scalars().first()
            
            if reserv_record:
                # Сохраняем ответ в базу
                reserv_record.last_answer = answer
                from datetime import datetime
                reserv_record.answered_at = datetime.now()
                session.add(reserv_record)
                await session.commit()
                print(f"✅ Ответ сохранён: {bot_user.telegram_username} ({reserv_record.full_name}) → {answer}")

    # Редактируем сообщение, убираем кнопки
    try:
        answer_text = "Да ✅" if answer == "yes" else "Нет ❌"
        await callback.message.edit_text(f'{callback.message.text}\n\n→ Ваш ответ: {answer_text}')
    except Exception:
        pass

    await callback.answer('Ваш ответ сохранён. Спасибо!')


@admin_router.message(Command(commands=['get_reserv_stats']))
async def get_reserv_stats(message: types.Message):
    """Статистика ответов из рассылок Reserv по факультетам."""
    if message.from_user.id != ADMIN_ID:
        return
    
    async with async_session_maker() as session:
        # Получаем уникальные факультеты
        stmt = select(Reserv.faculty).distinct()
        res = await session.execute(stmt)
        faculties = [row[0] for row in res.all() if row[0]]
        
        if not faculties:
            await message.answer('В таблице Reserv нет данных.')
            return
        
        for faculty in sorted(faculties):
            # Статистика по факультету
            total_stmt = select(func.count(Reserv.id)).where(Reserv.faculty == faculty)
            total_res = await session.execute(total_stmt)
            total = total_res.scalar() or 0
            
            sent_stmt = select(func.count(Reserv.id)).where(
                Reserv.faculty == faculty,
                Reserv.message_sent == True
            )
            sent_res = await session.execute(sent_stmt)
            sent = sent_res.scalar() or 0
            
            yes_stmt = select(func.count(Reserv.id)).where(
                Reserv.faculty == faculty,
                Reserv.last_answer == 'yes'
            )
            yes_res = await session.execute(yes_stmt)
            yes_count = yes_res.scalar() or 0
            
            no_stmt = select(func.count(Reserv.id)).where(
                Reserv.faculty == faculty,
                Reserv.last_answer == 'no'
            )
            no_res = await session.execute(no_stmt)
            no_count = no_res.scalar() or 0
            
            # Списки ФИО ответивших
            yes_names_stmt = select(Reserv.full_name).where(
                Reserv.faculty == faculty,
                Reserv.last_answer == 'yes'
            )
            yes_names_res = await session.execute(yes_names_stmt)
            yes_names = [r[0] for r in yes_names_res.fetchall()]
            
            no_names_stmt = select(Reserv.full_name).where(
                Reserv.faculty == faculty,
                Reserv.last_answer == 'no'
            )
            no_names_res = await session.execute(no_names_stmt)
            no_names = [r[0] for r in no_names_res.fetchall()]
            
            text = (
                f"📊 Факультет: {faculty}\n\n"
                f"📋 Всего в Reserv: {total} чел.\n"
                f"📤 Отправлено рассылок: {sent} чел.\n"
                f"📊 Ответы:\n"
                f"   ✅ Да: {yes_count} чел.\n"
                f"   ❌ Нет: {no_count} чел.\n"
                f"   ⏳ Не ответили: {sent - yes_count - no_count} чел."
            )
            
            if yes_names:
                text += '\n\n✅ Ответили "Да":\n' + '\n'.join(f"• {name}" for name in yes_names)
            
            if no_names:
                text += '\n\n❌ Ответили "Нет":\n' + '\n'.join(f"• {name}" for name in no_names)
            
            text += '\n\n' + '─' * 30
            
            await message.answer(text)

