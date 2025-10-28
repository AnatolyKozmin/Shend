"""
Скрипт для загрузки данных из res.xlsx в таблицу Reserv
"""
import asyncio
import pandas as pd
from sqlalchemy import select
from db.engine import async_session_maker
from db.models import Reserv


async def load_reserv_from_excel():
    """Загружает данные из res.xlsx в таблицу Reserv."""
    
    # Читаем Excel файл
    try:
        df = pd.read_excel('res.xlsx')
        print(f"Прочитано {len(df)} строк из res.xlsx")
        print(f"Колонки: {df.columns.tolist()}")
    except FileNotFoundError:
        print("❌ Файл res.xlsx не найден!")
        return
    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
        return
    
    # Проверяем наличие необходимых колонок (ФИО, Факультет, telegram_username)
    required_columns = ['ФИО', 'Факультет', 'telegram_username']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        print(f"❌ Отсутствуют необходимые колонки: {missing_columns}")
        print(f"Доступные колонки: {df.columns.tolist()}")
        return
    
    async with async_session_maker() as session:
        # Очищаем таблицу перед загрузкой (опционально)
        # await session.execute(delete(Reserv))
        # await session.commit()
        
        added = 0
        skipped = 0
        errors = 0
        
        for index, row in df.iterrows():
            try:
                # Нормализуем telegram_username - приводим к lowercase и убираем @
                telegram_username = row.get('telegram_username')
                if pd.notna(telegram_username):
                    telegram_username = str(telegram_username).strip().lstrip('@').lower()
                else:
                    telegram_username = None
                
                # Используем колонку 'ФИО'
                full_name = row.get('ФИО')
                if pd.isna(full_name):
                    print(f"⚠️ Строка {index + 2}: отсутствует ФИО, пропускаем")
                    skipped += 1
                    continue
                
                # Используем колонку 'Факультет'
                faculty = row.get('Факультет')
                if pd.isna(faculty):
                    faculty = None
                
                # Курс - опциональная колонка (может не быть)
                course = None  # В res.xlsx нет колонки курс
                
                # Проверяем, есть ли уже такая запись
                if telegram_username:
                    stmt = select(Reserv).where(Reserv.telegram_username == telegram_username)
                    result = await session.execute(stmt)
                    existing = result.scalars().first()
                    
                    if existing:
                        print(f"⚠️ Строка {index + 2}: пользователь @{telegram_username} уже существует, пропускаем")
                        skipped += 1
                        continue
                
                # Создаём новую запись
                reserv = Reserv(
                    full_name=str(full_name).strip(),
                    telegram_username=telegram_username,
                    faculty=str(faculty).strip() if faculty else None,
                    course=str(course).strip() if course else None,
                    message_sent=False
                )
                
                session.add(reserv)
                added += 1
                
            except Exception as e:
                print(f"❌ Ошибка при обработке строки {index + 2}: {e}")
                errors += 1
        
        # Сохраняем все изменения
        try:
            await session.commit()
            print(f"\n✅ Загрузка завершена!")
            print(f"   Добавлено: {added}")
            print(f"   Пропущено: {skipped}")
            print(f"   Ошибок: {errors}")
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка при сохранении в БД: {e}")


if __name__ == '__main__':
    print("🚀 Запуск загрузки данных из res.xlsx в таблицу Reserv...")
    asyncio.run(load_reserv_from_excel())

