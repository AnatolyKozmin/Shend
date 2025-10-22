"""Link BotUser -> Person by telegram_username (normalize to lower-case).

Usage:
  python -m scripts.link_botusers [--dry-run]

This script scans `bot_users` where `person_id` is NULL, normalizes `telegram_username`
(strip leading @ and lower-case), searches `people` for the same username (case-insensitive)
and sets `bot_user.person_id = person.id` when match is found.

By default the script performs changes; pass --dry-run to only report what would be linked.
"""

import asyncio
import argparse
from sqlalchemy import select, func
from db.engine import async_session_maker
from db.models import BotUser, Person


async def link_botusers(dry_run: bool = False):
    linked = 0
    skipped_no_username = 0
    not_found = 0

    async with async_session_maker() as session:
        stmt = select(BotUser).where(BotUser.person_id == None)
        res = await session.execute(stmt)
        bots = res.scalars().all()

        print(f'Найдено BotUser без связи: {len(bots)}')

        for bu in bots:
            uname = bu.telegram_username
            if not uname:
                skipped_no_username += 1
                continue

            norm = str(uname).strip().lstrip('@').lower()

            person_stmt = select(Person).where(func.lower(func.coalesce(Person.telegram_username, '')) == norm)
            person_res = await session.execute(person_stmt)
            person = person_res.scalars().first()

            if person:
                print(f'Будет связана запись BotUser(id={bu.id}, tg="{uname}") -> Person(id={person.id}, name="{person.full_name}")')
                if not dry_run:
                    bu.person_id = person.id
                    session.add(bu)
                    await session.commit()
                linked += 1
            else:
                not_found += 1

    print('--- Резюме ---')
    print(f'Связано: {linked}')
    print(f'Нет username: {skipped_no_username}')
    print(f'Не найдено соответствий: {not_found}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Не вносить изменений, только показать, что будет сделано')
    args = parser.parse_args()

    asyncio.run(link_botusers(dry_run=args.dry_run))


if __name__ == '__main__':
    main()
