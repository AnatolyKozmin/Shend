import os 
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from handlers.user_handlers import user_router
from handlers.admin_handlers import admin_router
from handlers.interview_handlers import interview_router
from handlers.reserv_handlers import reserv_router


from dotenv import load_dotenv
load_dotenv()

bot = Bot(os.getenv('TOKEN'))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


dp.include_router(user_router)
dp.include_router(admin_router)
dp.include_router(interview_router)
dp.include_router(reserv_router)


async def main():
    print('Бот работает !')
    await dp.start_polling(bot)

asyncio.run(main())
