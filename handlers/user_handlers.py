from aiogram import Router, types
from aiogram.filters import CommandStart
from db.engine import async_session_maker
from db.models import Person, BotUser
from sqlalchemy import select


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
    username = tg_user.username

    # Нормализуем username: если есть, приведём к формату с @ и без
    username_with_at = f"@{username}" if username else None

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
            # Обновляем username и связь на Person при необходимости
            changed = False
            if username and bot_user.telegram_username != username and bot_user.telegram_username != username_with_at:
                bot_user.telegram_username = username
                changed = True
            if person and bot_user.person_id != person.id:
                bot_user.person_id = person.id
                changed = True
            if changed:
                session.add(bot_user)
                await session.commit()
        else:
            bot_user = BotUser(tg_id=tg_id, telegram_username=username or username_with_at, person_id=person.id if person else None)
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
            "пожалуйста, обратитесь в сообщество ША в ВК или к админу бота @yanejettt"
        ))


