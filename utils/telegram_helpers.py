"""
Вспомогательные функции для работы с Telegram API
"""
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest


async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False) -> bool:
    """
    Безопасный вызов callback.answer() с обработкой ошибки "query too old".
    
    Args:
        callback: CallbackQuery объект
        text: Текст уведомления (опционально)
        show_alert: Показать как alert (по умолчанию False)
    
    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        await callback.answer(text=text, show_alert=show_alert)
        return True
    except TelegramBadRequest as e:
        # Игнорируем ошибку "query is too old"
        if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
            return False
        # Другие ошибки пробрасываем дальше
        raise
    except Exception:
        # Любые другие ошибки тоже игнорируем (например, timeout)
        return False

