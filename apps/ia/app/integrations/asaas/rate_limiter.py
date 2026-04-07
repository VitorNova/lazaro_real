# ╔════════════════════════════════════════════════════════════╗
# ║  LIMITE ASAAS — Maximo 30 requests por minuto              ║
# ╚════════════════════════════════════════════════════════════╝
# apps/ia/app/integrations/asaas/rate_limiter.py
"""
Rate limiter para a API Asaas.

Implementação de janela deslizante para controlar requisições.
Baseado em apps/api/src/services/asaas/client.ts RateLimiter.
"""

import asyncio
import logging
import time
from typing import List, Optional

from .types import RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_S

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter com janela deslizante.

    Limite padrão: 30 requisições por minuto (mesmo limite da API Asaas).
    Implementa espera automática quando o limite é atingido.
    """

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_S,
    ):
        """
        Inicializa o rate limiter.

        Args:
            max_requests: Número máximo de requisições permitidas na janela.
            window_seconds: Tamanho da janela em segundos.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Adquire permissão para fazer uma requisição.

        Se o limite foi atingido, aguarda até que uma slot esteja disponível.
        Thread-safe através de asyncio.Lock.
        """
        async with self._lock:
            await self._wait_if_needed()
            self._timestamps.append(time.time())

    async def _wait_if_needed(self) -> None:
        """
        Aguarda se necessário até que uma slot esteja disponível.
        """
        while True:
            now = time.time()
            cutoff = now - self.window_seconds

            # Remove timestamps fora da janela
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) < self.max_requests:
                # Temos slot disponível
                return

            # Calcula quanto tempo esperar até o timestamp mais antigo expirar
            oldest = self._timestamps[0]
            wait_time = (oldest + self.window_seconds) - now + 0.1  # +100ms de margem

            if wait_time > 0:
                logger.warning(
                    f"[Asaas] Rate limit interno atingido. "
                    f"Aguardando {wait_time:.1f}s... "
                    f"({len(self._timestamps)}/{self.max_requests} req/min)"
                )
                await asyncio.sleep(wait_time)

    def reset(self) -> None:
        """
        Reseta o rate limiter (limpa todos os timestamps).

        Útil para testes ou quando se sabe que o limite foi resetado.
        """
        self._timestamps.clear()

    @property
    def available_slots(self) -> int:
        """
        Retorna o número de slots disponíveis no momento.
        """
        now = time.time()
        cutoff = now - self.window_seconds
        active = [t for t in self._timestamps if t > cutoff]
        return max(0, self.max_requests - len(active))

    @property
    def is_rate_limited(self) -> bool:
        """
        Verifica se o rate limit está ativo no momento.
        """
        return self.available_slots == 0


# Singleton global para uso compartilhado
_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """
    Retorna a instância singleton do rate limiter.

    Isso garante que todas as instâncias de AsaasClient
    compartilhem o mesmo controle de rate limiting.
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    return _global_rate_limiter
