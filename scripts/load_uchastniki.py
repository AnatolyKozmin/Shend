"""
Скрипт для загрузки данных из uchast.xlsx в таблицу Uchastnik.

Скрипт:
1. Читает данные из uchast.xlsx
2. Проверяет, есть ли участник уже в таблице BotUser (по telegram_username)
3. Если есть - добавляет tg_id в новую таблицу
4. Если нет - добавляет участника без tg_id

Usage:
    python scripts/load_uchastniki.py [--update]
    
    --update: Обновляет существующие записи вместо пропуска
"""
import asyncio
import sys
import pandas as pd
from sqlalchemy import select, func
from db.engine import async_session_maker
from db.models import Uchastnik, BotUser


def normalize_username(raw):
    """Нормализует username: убирает @ и приводит к lowercase."""
    if pd.isna(raw) or not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith('@'):
        s = s[1:]
    return s.lower()


async def load_uchastniki_from_excel(update_existing=False):
    """Загружает данные из uchast.xlsx в таблицу Uchastnik.
    
    Args:
        update_existing: Если True, обновляет существующие записи вместо пропуска
    """
    
    # Читаем Excel файл
    try:
        # Пробуем прочитать с заголовками
        df = pd.read_excel('uchast.xlsx')
        
        # Проверяем, есть ли правильные заголовки
        if 'ФИО' not in df.columns:
            # Если заголовков нет, читаем заново без заголовков
            print("⚠️ Заголовки не найдены, читаю без заголовков...")
            # Предполагаем порядок: ФИО, Курс, Факультет, telegram_username
            df = pd.read_excel('uchast.xlsx', header=None, names=['ФИО', 'Курс', 'Факультет', 'telegram_username'])
        
        print(f"✅ Прочитано {len(df)} строк из uchast.xlsx")
        print(f"📋 Колонки: {df.columns.tolist()}")
    except FileNotFoundError:
        print("❌ Файл uchast.xlsx не найден!")
        print("💡 Убедитесь, что файл находится в корне проекта")
        return
    except Exception as e:
        print(f"❌ Ошибка при чтении файла: {e}")
        return
    
    # Проверяем наличие необходимых колонок
    required_columns = ['ФИО']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        print(f"❌ Отсутствуют необходимые колонки: {missing_columns}")
        print(f"📋 Доступные колонки: {df.columns.tolist()}")
        return
    
    async with async_session_maker() as session:
        # Получаем все существующие BotUser для быстрой проверки
        bot_users_stmt = select(BotUser).where(BotUser.telegram_username.isnot(None))
        bot_users_result = await session.execute(bot_users_stmt)
        bot_users = bot_users_result.scalars().all()
        
        # Создаём словарь для быстрого поиска: username -> tg_id
        username_to_tg_id = {}
        for bu in bot_users:
            if bu.telegram_username:
                norm_username = normalize_username(bu.telegram_username)
                if norm_username:
                    username_to_tg_id[norm_username] = bu.tg_id
        
        print(f"📊 Найдено {len(username_to_tg_id)} пользователей в BotUser для сопоставления")
        
        added = 0
        updated = 0
        skipped = 0
        errors = 0
        linked_with_bot = 0  # Сколько участников связано с BotUser
        
        for index, row in df.iterrows():
            try:
                # Получаем ФИО (обязательное поле)
                full_name = row.get('ФИО')
                if pd.isna(full_name):
                    print(f"⚠️ Строка {index + 2}: отсутствует ФИО, пропускаем")
                    skipped += 1
                    continue
                
                full_name = str(full_name).strip()
                
                # Получаем опциональные поля
                course = row.get('Курс') if 'Курс' in df.columns else None
                if pd.isna(course):
                    course = None
                else:
                    course = str(course).strip()
                
                faculty = row.get('Факультет') if 'Факультет' in df.columns else None
                if pd.isna(faculty):
                    faculty = None
                else:
                    faculty = str(faculty).strip()
                
                telegram_username = row.get('telegram_username') if 'telegram_username' in df.columns else None
                telegram_username_norm = normalize_username(telegram_username)
                
                # Проверяем, есть ли уже такая запись
                existing = None
                
                # Проверка по telegram_username (если есть)
                if telegram_username_norm:
                    stmt = select(Uchastnik).where(
                        func.lower(Uchastnik.telegram_username) == telegram_username_norm
                    )
                    result = await session.execute(stmt)
                    existing = result.scalars().first()
                    
                    if existing:
                        if update_existing:
                            # Обновляем существующую запись
                            print(f"🔄 Строка {index + 2}: обновляю существующую запись для '{full_name}'")
                            existing.full_name = full_name
                            existing.course = course or None
                            existing.faculty = faculty or None
                            existing.telegram_username = telegram_username_norm
                            
                            # Проверяем, есть ли в BotUser
                            if telegram_username_norm in username_to_tg_id:
                                existing.tg_id = username_to_tg_id[telegram_username_norm]
                                linked_with_bot += 1
                            
                            session.add(existing)
                            updated += 1
                            continue
                        else:
                            print(f"⚠️ Строка {index + 2}: пользователь с telegram @{telegram_username_norm} уже существует, пропускаем")
                            skipped += 1
                            continue
                
                # Проверка по ФИО (если username не было или не нашли)
                if not existing:
                    stmt_name = select(Uchastnik).where(Uchastnik.full_name == full_name)
                    result_name = await session.execute(stmt_name)
                    existing = result_name.scalars().first()
                    
                    if existing:
                        if update_existing:
                            # Обновляем существующую запись
                            print(f"🔄 Строка {index + 2}: обновляю существующую запись для '{full_name}'")
                            existing.course = course or None
                            existing.faculty = faculty or None
                            existing.telegram_username = telegram_username_norm
                            
                            # Проверяем, есть ли в BotUser
                            if telegram_username_norm and telegram_username_norm in username_to_tg_id:
                                existing.tg_id = username_to_tg_id[telegram_username_norm]
                                linked_with_bot += 1
                            
                            session.add(existing)
                            updated += 1
                            continue
                        else:
                            print(f"⚠️ Строка {index + 2}: пользователь с ФИО '{full_name}' уже существует, пропускаем")
                            skipped += 1
                            continue
                
                # Создаём новую запись
                tg_id = None
                if telegram_username_norm and telegram_username_norm in username_to_tg_id:
                    tg_id = username_to_tg_id[telegram_username_norm]
                    linked_with_bot += 1
                
                uchastnik = Uchastnik(
                    full_name=full_name,
                    telegram_username=telegram_username_norm,
                    faculty=faculty or None,
                    course=course or None,
                    tg_id=tg_id
                )
                
                session.add(uchastnik)
                added += 1
                
                if tg_id:
                    print(f"✅ Строка {index + 2}: добавлен '{full_name}' с tg_id={tg_id}")
                else:
                    print(f"✅ Строка {index + 2}: добавлен '{full_name}' (без tg_id)")
                
            except Exception as e:
                print(f"❌ Ошибка при обработке строки {index + 2}: {e}")
                import traceback
                traceback.print_exc()
                errors += 1
        
        # Сохраняем все изменения
        try:
            await session.commit()
            print(f"\n{'='*50}")
            print(f"✅ Загрузка завершена!")
            print(f"{'='*50}")
            print(f"📊 Статистика:")
            print(f"   ✅ Добавлено новых: {added}")
            print(f"   🔄 Обновлено: {updated}")
            print(f"   ⏭️  Пропущено: {skipped}")
            print(f"   🔗 Связано с BotUser: {linked_with_bot}")
            print(f"   ❌ Ошибок: {errors}")
            print(f"   📈 Всего обработано: {added + updated + skipped}")
            print(f"{'='*50}")
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка при сохранении в БД: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Загрузка участников из uchast.xlsx')
    parser.add_argument('--update', '-u', action='store_true', 
                       help='Обновлять существующие записи вместо пропуска')
    args = parser.parse_args()
    
    if args.update:
        print("🚀 Запуск загрузки данных из uchast.xlsx в таблицу Uchastnik (режим обновления)...")
        print("💡 Существующие записи будут обновлены")
    else:
        print("🚀 Запуск загрузки данных из uchast.xlsx в таблицу Uchastnik...")
        print("💡 Существующие записи будут пропущены")
        print("💡 Для обновления используйте: python scripts/load_uchastniki.py --update")
    
    print()
    asyncio.run(load_uchastniki_from_excel(update_existing=args.update))

