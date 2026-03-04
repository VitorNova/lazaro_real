# ==============================================================================
# REDIS TYPES
# Tipos e constantes para integracao Redis
# ==============================================================================

"""
Tipos e constantes para o servico Redis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict, Optional, Any, List


# ==============================================================================
# CONSTANTS
# ==============================================================================

# Delay padrao para buffer de mensagens (segundos)
BUFFER_DELAY_SECONDS = 14

# TTL padrao para itens no cache (segundos)
DEFAULT_TTL_SECONDS = 300

# TTL padrao para locks (segundos)
LOCK_TTL_SECONDS = 60  # Aumentado de 30s para suportar retry do Gemini

# TTL padrao para buffer (segundos)
BUFFER_TTL_SECONDS = 300


# ==============================================================================
# KEY PREFIXES
# ==============================================================================

BUFFER_KEY_PREFIX = "buffer:msg:"
LOCK_KEY_PREFIX = "lock:msg:"
PAUSE_KEY_PREFIX = "pause:"
CACHE_KEY_PREFIX = "cache:"
FAILED_SEND_KEY_PREFIX = "failed:send:"


# ==============================================================================
# TYPED DICTS
# ==============================================================================

class BufferedMessage(TypedDict, total=False):
    """Mensagem armazenada no buffer."""
    id: str
    content: str
    timestamp: int
    type: str
    # Campos de midia opcionais
    media_type: Optional[str]
    mime_type: Optional[str]
    media_url: Optional[str]
    media_key: Optional[str]
    file_sha256: Optional[str]
    file_length: Optional[int]


class OrphanBuffer(TypedDict):
    """Buffer orfao (sem lock ativo)."""
    agent_id: str
    phone: str
    message_count: int
    ttl_seconds: Optional[int]
    key: str


class LockInfo(TypedDict):
    """Informacoes sobre um lock."""
    holder: str
    ttl: int
    key: str


class BufferResult(TypedDict):
    """Resultado de operacao de buffer."""
    messages: List[str]
    count: int
    cleared: bool


class HealthStatus(TypedDict):
    """Status de saude do Redis."""
    connected: bool
    latency_ms: Optional[float]
    error: Optional[str]


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class RedisConfig:
    """Configuracao de conexao Redis."""
    url: str = "redis://localhost:6379"
    encoding: str = "utf-8"
    decode_responses: bool = True
    max_connections: int = 10
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    retry_on_timeout: bool = True

    @classmethod
    def from_url(cls, url: str) -> "RedisConfig":
        """Cria config a partir de URL."""
        return cls(url=url)

    @classmethod
    def from_env(cls, env_var: str = "REDIS_URL") -> "RedisConfig":
        """Cria config a partir de variavel de ambiente."""
        import os
        url = os.getenv(env_var, "redis://localhost:6379")
        return cls(url=url)


# ==============================================================================
# KEY GENERATORS
# ==============================================================================

def buffer_key(agent_id: str, phone: str) -> str:
    """Gera a chave do buffer de mensagens."""
    return f"{BUFFER_KEY_PREFIX}{agent_id}:{phone}"


def lock_key(agent_id: str, phone: str) -> str:
    """Gera a chave do lock de processamento."""
    return f"{LOCK_KEY_PREFIX}{agent_id}:{phone}"


def pause_key(agent_id: str, phone: str) -> str:
    """Gera a chave do controle de pausa."""
    return f"{PAUSE_KEY_PREFIX}{agent_id}:{phone}"


def failed_send_key(agent_id: str, phone: str) -> str:
    """Gera a chave para envios falhos."""
    return f"{FAILED_SEND_KEY_PREFIX}{agent_id}:{phone}"


def parse_buffer_key(key: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extrai agent_id e phone de uma chave de buffer.

    Args:
        key: Chave no formato buffer:msg:{agent_id}:{phone}

    Returns:
        Tupla (agent_id, phone) ou (None, None) se formato invalido
    """
    if not key.startswith(BUFFER_KEY_PREFIX):
        return None, None

    parts = key[len(BUFFER_KEY_PREFIX):].split(":", 1)
    if len(parts) != 2:
        return None, None

    return parts[0], parts[1]
