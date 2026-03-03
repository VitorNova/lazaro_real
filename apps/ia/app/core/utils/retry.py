"""
Decorators de retry com backoff exponencial.

Extraido de: app/webhooks/pagamentos.py (Fase 3.2)
"""

import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def async_retry(max_retries: int = 3, initial_delay: float = 2.0, backoff_factor: float = 2.0):
    """
    Decorator para retry com backoff exponencial em funcoes async.

    Args:
        max_retries: Numero maximo de tentativas
        initial_delay: Delay inicial em segundos
        backoff_factor: Fator de multiplicacao do delay a cada retry

    Exemplo:
        @async_retry(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
        async def fetch_data():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(
                            "[%s] Tentativa %d/%d falhou: %s. Retry em %.1fs...",
                            func.__name__, attempt, max_retries, e, delay
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            "[%s] Todas as %d tentativas falharam. Ultimo erro: %s",
                            func.__name__, max_retries, e
                        )
            raise last_error
        return wrapper
    return decorator
