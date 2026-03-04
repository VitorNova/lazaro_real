"""
Diana v2 - Tipos e dataclasses.

Apenas o essencial, sem over-engineering.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class DianaStatus(str, Enum):
    """Status de um prospect na campanha Diana."""

    PENDING = "pending"  # Na fila, ainda nao enviou
    SENT = "sent"  # Mensagem enviada, esperando resposta
    RESPONDED = "responded"  # Contato respondeu
    INTERESTED = "interested"  # Contato demonstrou interesse
    NOT_INTERESTED = "not_interested"  # Sem interesse
    SCHEDULED = "scheduled"  # Agendamento feito
    BLOCKED = "blocked"  # Bloqueou/pediu pra parar
    ERROR = "error"  # Erro no envio


@dataclass
class DianaProspect:
    """
    Um contato na lista de prospecao.

    Os dados vem do CSV importado. Campos conhecidos sao mapeados,
    o resto vai em dados_extras como JSONB.
    """

    id: Optional[int] = None
    agent_id: str = ""
    campanha_id: Optional[str] = None

    # Dados do contato (vem do CSV - colunas conhecidas)
    nome: Optional[str] = None
    telefone: Optional[str] = None
    telefone_formatado: Optional[str] = None  # Formato UAZAPI: 5566999887766
    remotejid: Optional[str] = None  # 5566999887766@s.whatsapp.net
    empresa: Optional[str] = None
    email: Optional[str] = None
    cargo: Optional[str] = None

    # Qualquer dado extra do CSV fica aqui
    dados_extras: Optional[Dict[str, Any]] = None

    # Status
    status: str = DianaStatus.PENDING

    # Mensagem
    mensagem_enviada: Optional[str] = None
    enviado_at: Optional[str] = None
    respondido_at: Optional[str] = None

    # Meta
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionario (para Supabase insert)."""
        return {
            "agent_id": self.agent_id,
            "campanha_id": self.campanha_id,
            "nome": self.nome,
            "telefone": self.telefone,
            "telefone_formatado": self.telefone_formatado,
            "remotejid": self.remotejid,
            "empresa": self.empresa,
            "email": self.email,
            "cargo": self.cargo,
            "dados_extras": self.dados_extras,
            "status": self.status,
            "mensagem_enviada": self.mensagem_enviada,
            "enviado_at": self.enviado_at,
            "respondido_at": self.respondido_at,
        }

    def get_template_vars(self) -> Dict[str, str]:
        """
        Retorna variaveis para substituicao no template de mensagem.

        Exemplo de template: "Oi {nome}! Vi que a {empresa} atua em {segmento}..."
        """
        vars_dict: Dict[str, str] = {
            "nome": self.nome or "",
            "empresa": self.empresa or "",
            "email": self.email or "",
            "cargo": self.cargo or "",
            "telefone": self.telefone or "",
        }

        # Adiciona dados_extras ao template
        if self.dados_extras:
            for key, value in self.dados_extras.items():
                # Normaliza key: remove espacos, lowercase
                clean_key = key.lower().replace(" ", "_").replace("-", "_")
                vars_dict[clean_key] = str(value) if value else ""

        return vars_dict


@dataclass
class DianaCampanha:
    """
    Uma campanha de disparo.

    Cada campanha tem:
    - Lista de prospects (vem do CSV)
    - System prompt (guia a IA nas respostas)
    - Mensagem inicial (template com variaveis)
    """

    id: Optional[str] = None
    agent_id: str = ""
    nome: Optional[str] = None
    system_prompt: Optional[str] = None  # Prompt que guia a conversa
    mensagem_template: Optional[str] = None  # Template da 1a mensagem

    # Status
    status: str = "active"  # active, paused, finished

    # Contadores
    total_prospects: int = 0
    total_enviados: int = 0
    total_respondidos: int = 0
    total_interessados: int = 0

    # UAZAPI
    uazapi_campaign_id: Optional[str] = None  # folder_id da UAZAPI

    # Config de disparo
    delay_min: int = 30  # segundos entre mensagens
    delay_max: int = 60

    # Meta
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionario (para Supabase insert)."""
        return {
            "agent_id": self.agent_id,
            "nome": self.nome,
            "system_prompt": self.system_prompt,
            "mensagem_template": self.mensagem_template,
            "status": self.status,
            "total_prospects": self.total_prospects,
            "total_enviados": self.total_enviados,
            "total_respondidos": self.total_respondidos,
            "total_interessados": self.total_interessados,
            "uazapi_campaign_id": self.uazapi_campaign_id,
            "delay_min": self.delay_min,
            "delay_max": self.delay_max,
        }


@dataclass
class DianaConversationMessage:
    """Uma mensagem no historico de conversa com o prospect."""

    role: str  # "user" ou "assistant"
    content: str
    timestamp: str


@dataclass
class DianaConversationHistory:
    """Historico de conversa com um prospect."""

    messages: List[DianaConversationMessage] = field(default_factory=list)

    def add_message(self, role: str, content: str, timestamp: str) -> None:
        """Adiciona mensagem ao historico."""
        self.messages.append(
            DianaConversationMessage(role=role, content=content, timestamp=timestamp)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Converte para formato JSON (para Supabase)."""
        return {
            "messages": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in self.messages
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DianaConversationHistory":
        """Cria instancia a partir de dict (do Supabase)."""
        history = cls()
        messages = data.get("messages", [])
        for m in messages:
            history.add_message(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                timestamp=m.get("timestamp", ""),
            )
        return history

    def to_gemini_format(self) -> List[Dict[str, str]]:
        """Converte para formato esperado pelo Gemini."""
        return [
            {"role": m.role, "content": m.content}
            for m in self.messages
        ]
