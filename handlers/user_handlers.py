from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from db.engine import async_session_maker
from db.models import Person, BotUser
from sqlalchemy import select, func


user_router = Router()


@user_router.message(CommandStart())
async def user_start(message: types.Message):
    """При /start пытаемся связать телеграм-юзера с записью в Person по telegram_username.

    Логика:
    - взять message.from_user.id и username (если есть)
    - поискать в таблице Person запись с таким telegram_username (внутри БД предполагается формат с @, но проверим оба варианта)
    - если найдена запись Person — создать или обновить BotUser, связать person_id
    - вернуть пользователю короткое подтверждение
    """
    tg_user = message.from_user
    tg_id = tg_user.id
    raw_username = tg_user.username

    # Нормализуем username: удаляем ведущий @ (если есть) и приводим к нижнему регистру
    if raw_username:
        username = str(raw_username).strip().lstrip('@').lower()
        username_with_at = f"@{username}"
    else:
        username = None
        username_with_at = None

    async with async_session_maker() as session:
        # Попытаемся найти Person по username с @ или без
        person_stmt = None
        if username_with_at:
            person_stmt = select(Person).where(
                (Person.telegram_username == username_with_at) | (Person.telegram_username == username)
            )
        else:
            person_stmt = select(Person).where(Person.telegram_username == None)

        result = await session.execute(person_stmt)
        person = result.scalars().first()

        # Создаём или обновляем BotUser
        stmt = select(BotUser).where(BotUser.tg_id == tg_id)
        res = await session.execute(stmt)
        bot_user = res.scalars().first()

        if bot_user:
            # Обновляем username (храним в БД нормализованный вариант без @) и связь на Person при необходимости
            changed = False
            # bot_user.telegram_username в базе ожидается без @ и в нижнем регистре
            if username and bot_user.telegram_username != username:
                bot_user.telegram_username = username
                changed = True
            if person and bot_user.person_id != person.id:
                bot_user.person_id = person.id
                changed = True
            if changed:
                session.add(bot_user)
                await session.commit()
        else:
            bot_user = BotUser(tg_id=tg_id, telegram_username=username, person_id=person.id if person else None)
            session.add(bot_user)
            await session.commit()

    START_MESSAGE = (
        "Привет!\n\n"
        "Это бот «Школы Актива», здесь будет приходить рассылка важной информации, поэтому не ставь его в мьют и следи за новостями. 🤍"
    )

    # Всегда показываем приветственное сообщение
    await message.answer(text=START_MESSAGE)

    # Если найдена запись в базе — дополнительно подтверждаем связь
    if person:
        await message.answer(text=f"{person.full_name}, твоя анкета найдена !")
    else:
        await message.answer(text=(
            "Если у вас скрыт или отсутствует Telegram‑username, либо мы не нашли вашу запись в базе,\n"
            "пожалуйста, обратитесь в сообщество ША https://vk.com/schoolofactivity?from=groups"
        ))


@user_router.message(Command('get_people'))
async def get_people_by_faculty(message: types.Message):
    """Команда для получения списка людей по факультетам.
    
    Показывает:
    1. Людей, которые добавились в бота (есть в BotUser)
    2. Людей, которых нет в боте (есть в Person, но нет в BotUser) с их телеграмами
    """
    async with async_session_maker() as session:
        # Получаем всех людей с их факультетами
        people_stmt = select(Person).where(Person.faculty.isnot(None)).order_by(Person.faculty, Person.full_name)
        people_result = await session.execute(people_stmt)
        all_people = people_result.scalars().all()
        
        # Получаем всех пользователей бота с их связанными Person
        bot_users_stmt = select(BotUser).where(BotUser.person_id.isnot(None))
        bot_users_result = await session.execute(bot_users_stmt)
        bot_users = bot_users_result.scalars().all()
        
        # Создаем множество ID людей, которые есть в боте
        people_in_bot_ids = {bu.person_id for bu in bot_users}
        
        # Группируем людей по факультетам
        faculty_groups = {}
        for person in all_people:
            faculty = person.faculty or "Без факультета"
            if faculty not in faculty_groups:
                faculty_groups[faculty] = {"in_bot": [], "not_in_bot": []}
            
            if person.id in people_in_bot_ids:
                faculty_groups[faculty]["in_bot"].append(person)
            else:
                faculty_groups[faculty]["not_in_bot"].append(person)
        
        # Формируем сообщение
        if not faculty_groups:
            await message.answer("В базе данных нет людей с указанными факультетами.")
            return
        
        # Добавляем общую статистику
        total_in_bot = sum(len(groups["in_bot"]) for groups in faculty_groups.values())
        total_not_in_bot = sum(len(groups["not_in_bot"]) for groups in faculty_groups.values())
        
        # Отправляем общую статистику сначала
        stats_text = f"📊 Статистика по факультетам\n\n"
        stats_text += f"✅ В боте: {total_in_bot} чел.\n"
        stats_text += f"❌ Не в боте: {total_not_in_bot} чел.\n"
        stats_text += f"📈 Всего: {total_in_bot + total_not_in_bot} чел.\n\n"
        stats_text += "─" * 30
        
        await message.answer(stats_text)
        
        # Отправляем по факультетам отдельными сообщениями
        for faculty, groups in sorted(faculty_groups.items()):
            faculty_text = f"🎓 {faculty}\n\n"
            
            # Люди в боте
            if groups["in_bot"]:
                faculty_text += f"✅ В боте ({len(groups['in_bot'])} чел.):\n"
                for person in groups["in_bot"]:
                    faculty_text += f"• {person.full_name}\n"
                faculty_text += "\n"
            
            # Люди не в боте
            if groups["not_in_bot"]:
                faculty_text += f"❌ Не в боте ({len(groups['not_in_bot'])} чел.):\n"
                for person in groups["not_in_bot"]:
                    telegram_info = f" (@{person.telegram_username})" if person.telegram_username else " (нет телеграма)"
                    faculty_text += f"• {person.full_name}{telegram_info}\n"
                faculty_text += "\n"
            
            faculty_text += "─" * 30
            
            # Отправляем сообщение, если оно не пустое
            if faculty_text.strip() != f"🎓 {faculty}\n\n─" * 30:
                await message.answer(faculty_text)


