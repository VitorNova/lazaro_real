"""
Gerenciador de historico de conversas.

Responsavel por salvar e gerenciar o historico de mensagens
entre usuarios e o assistente no Supabase.

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.7)
"""

from datetime import datetime
from typing import Dict, List, Optional

import structlog

from app.services.supabase import ConversationHistory, SupabaseService

logger = structlog.get_logger(__name__)


class ConversationManager:
    """
    Gerencia o historico de conversas entre usuarios e assistente.

    Responsabilidades:
    - Salvar mensagens do usuario no historico
    - Salvar respostas do assistente no historico
    - Registrar interacoes de tools (function_call/function_response)
    - Persistir historico no Supabase
    """

    def __init__(self, supabase: SupabaseService):
        """
        Inicializa o gerenciador de conversas.

        Args:
            supabase: Servico Supabase para persistencia
        """
        self.supabase = supabase
        self.logger = logger.bind(component="ConversationManager")

    def save_conversation_history(
        self,
        table_messages: str,
        remotejid: str,
        user_message: str,
        assistant_message: str,
        history: Optional[ConversationHistory],
        tool_interactions: Optional[List[Dict]] = None,
    ) -> None:
        """
        Salva o historico de conversa atualizado.

        Args:
            table_messages: Nome da tabela de mensagens
            remotejid: RemoteJid do lead
            user_message: Mensagem do usuario
            assistant_message: Resposta do assistente
            history: Historico existente
            tool_interactions: Lista de function_call + function_response (opcional)
        """
        now = datetime.utcnow().isoformat()

        # Inicializar ou usar historico existente
        if history is None:
            history = {"messages": []}

        # Adicionar mensagem do usuario
        history["messages"].append({
            "role": "user",
            "parts": [{"text": user_message}],
            "timestamp": now,
        })

        # Adicionar blocos de tool interaction (se houver)
        if tool_interactions:
            for ti in tool_interactions:
                # Function call do model
                history["messages"].append({
                    "role": "model",
                    "parts": [{"function_call": ti["function_call"]}],
                    "timestamp": now,
                })
                # Function response
                history["messages"].append({
                    "role": "function",
                    "parts": [{"function_response": ti["function_response"]}],
                    "timestamp": now,
                })

        # Adicionar resposta do modelo (texto final)
        history["messages"].append({
            "role": "model",
            "parts": [{"text": assistant_message}],
            "timestamp": now,
        })

        # Salvar no Supabase
        # Esta funcao salva tanto a mensagem do usuario quanto a do modelo.
        # Passamos last_message_role="model" para atualizar Msg_model,
        # e set_user_timestamp=True para atualizar Msg_user tambem.
        self.supabase.upsert_conversation_history(
            table_messages,
            remotejid,
            history,
            last_message_role="model",
            set_user_timestamp=False,
        )

        self.logger.debug(
            "conversation_history_saved",
            remotejid=remotejid,
            table=table_messages,
            messages_count=len(history["messages"]),
        )

    def initialize_history(
        self,
        existing_history: Optional[ConversationHistory] = None,
    ) -> ConversationHistory:
        """
        Inicializa ou retorna historico existente.

        Args:
            existing_history: Historico existente ou None

        Returns:
            Historico inicializado
        """
        if existing_history is None:
            return {"messages": []}
        return existing_history

    def append_user_message(
        self,
        history: ConversationHistory,
        message: str,
        timestamp: Optional[str] = None,
    ) -> ConversationHistory:
        """
        Adiciona mensagem do usuario ao historico.

        Args:
            history: Historico atual
            message: Texto da mensagem
            timestamp: Timestamp opcional (usa UTC now se nao fornecido)

        Returns:
            Historico atualizado
        """
        ts = timestamp or datetime.utcnow().isoformat()
        history["messages"].append({
            "role": "user",
            "parts": [{"text": message}],
            "timestamp": ts,
        })
        return history

    def append_model_message(
        self,
        history: ConversationHistory,
        message: str,
        timestamp: Optional[str] = None,
    ) -> ConversationHistory:
        """
        Adiciona resposta do modelo ao historico.

        Args:
            history: Historico atual
            message: Texto da resposta
            timestamp: Timestamp opcional (usa UTC now se nao fornecido)

        Returns:
            Historico atualizado
        """
        ts = timestamp or datetime.utcnow().isoformat()
        history["messages"].append({
            "role": "model",
            "parts": [{"text": message}],
            "timestamp": ts,
        })
        return history

    def append_tool_interaction(
        self,
        history: ConversationHistory,
        function_call: Dict,
        function_response: Dict,
        timestamp: Optional[str] = None,
    ) -> ConversationHistory:
        """
        Adiciona interacao de tool (function_call + response) ao historico.

        Args:
            history: Historico atual
            function_call: Dados do function_call
            function_response: Dados do function_response
            timestamp: Timestamp opcional (usa UTC now se nao fornecido)

        Returns:
            Historico atualizado
        """
        ts = timestamp or datetime.utcnow().isoformat()

        # Function call do model
        history["messages"].append({
            "role": "model",
            "parts": [{"function_call": function_call}],
            "timestamp": ts,
        })

        # Function response
        history["messages"].append({
            "role": "function",
            "parts": [{"function_response": function_response}],
            "timestamp": ts,
        })

        return history


# Funcao standalone para compatibilidade com codigo legado
def save_conversation_history(
    supabase: SupabaseService,
    table_messages: str,
    remotejid: str,
    user_message: str,
    assistant_message: str,
    history: Optional[ConversationHistory],
    tool_interactions: Optional[List[Dict]] = None,
) -> None:
    """
    Wrapper standalone para salvar historico de conversa.

    Mantido para compatibilidade com codigo existente.
    Prefira usar ConversationManager diretamente.
    """
    manager = ConversationManager(supabase)
    manager.save_conversation_history(
        table_messages=table_messages,
        remotejid=remotejid,
        user_message=user_message,
        assistant_message=assistant_message,
        history=history,
        tool_interactions=tool_interactions,
    )
