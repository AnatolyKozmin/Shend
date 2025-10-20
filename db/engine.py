import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
load_dotenv()


engine = create_async_engine(os.getenv('DB_URL'), echo=True)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    __abstract__ = True