#!/bin/bash
# Скрипт для применения миграции на сервере

echo "🚀 Применение миграции Reserv на сервере"
echo "=========================================="

# Шаг 1: Остановка бота
echo "1. Остановка бота..."
docker-compose down

# Шаг 2: Применение миграции
echo "2. Применение миграции..."
docker-compose run --rm bot alembic upgrade head

# Шаг 3: Загрузка данных (если нужно)
echo "3. Загрузить данные из res.xlsx? (y/n)"
read -r answer
if [ "$answer" = "y" ]; then
    echo "   Загрузка данных..."
    docker-compose run --rm bot python scripts/load_reserv.py
fi

# Шаг 4: Запуск бота
echo "4. Запуск бота..."
docker-compose up -d

echo "✅ Готово! Бот запущен."
echo ""
echo "Проверьте команды:"
echo "  /poter - проверка совпадений"
echo "  /create_reserv_rass - рассылка из Reserv"
echo "  /dodep_reserv - повторная рассылка"

