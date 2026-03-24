# ╔══════════════════════════════════════════════════════════════╗
# ║  MSG RECEBIDA — Tratar mensagem que chegou                   ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Incoming message handler module.

Extracted from mensagens.py (Phase 2.5)
Functions: extract_message_data, handle_control_command
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.domain.messaging.models.message import ExtractedMessage
from app.services.redis import RedisService
from app.services.supabase import SupabaseService

logger = logging.getLogger(__name__)


def extract_message_data(webhook_data: Dict[str, Any]) -> Optional[ExtractedMessage]:
    """
    Extrai dados relevantes da mensagem do webhook UAZAPI.

    Formato: EventType, message.chatid, message.text

    Args:
        webhook_data: Dados brutos do webhook

    Returns:
        ExtractedMessage com dados extraidos ou None se invalido
    """
    try:
        # ==================================================================
        # FORMATO UAZAPI (EventType: messages)
        # ==================================================================
        if webhook_data.get("EventType") == "messages" and webhook_data.get("message"):
            msg = webhook_data.get("message", {})

            # Ignorar mensagens enviadas pela API (evita loops)
            if msg.get("wasSentByApi", False):
                logger.debug("Mensagem enviada pela API, ignorando")
                return None

            # Extrair chatid (remoteJid)
            remotejid = msg.get("chatid", "")
            if not remotejid:
                # Fallback: tentar sender_pn
                remotejid = msg.get("sender_pn", "")

            if not remotejid:
                logger.debug("Mensagem UAZAPI sem chatid")
                return None

            # Verificar se e grupo
            chat = webhook_data.get("chat", {})
            is_group = msg.get("isGroup", False) or "@g.us" in remotejid or chat.get("wa_isGroup", False)

            # Verificar se e mensagem propria
            from_me = msg.get("fromMe", False)

            # Extrair telefone do remotejid
            phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")

            # Extrair texto - UAZAPI usa 'text' ou 'content'
            text = msg.get("text", "")
            content = msg.get("content")
            if not text and content:
                if isinstance(content, str):
                    text = content
                elif isinstance(content, dict):
                    # content pode ser dict com URL de midia
                    text = content.get("text", "") or ""

            # Detectar tipo de midia
            media_type = msg.get("mediaType") or msg.get("messageType", "")

            # Se for audio, marcar como tal (nao precisa de texto)
            if media_type in ["audio", "ptt", "AudioMessage"]:
                text = "[AUDIO]"  # Placeholder, sera substituido pela transcricao

            # Se for imagem/documento, forcar placeholder (preservar caption)
            # UAZAPI envia messageType="ImageMessage"/"DocumentMessage" (PascalCase)
            # Leadbox envia mediaType="image"/"imageMessage"/"document"/"documentMessage"
            elif media_type.lower().startswith("image") or media_type in ["image", "imageMessage"]:
                caption = text.strip() if text else ""
                text = "[Imagem recebida]" + (f" {caption}" if caption else "")
            elif media_type.lower().startswith("document") or media_type in ["document", "documentMessage"]:
                caption = text.strip() if text else ""
                text = "[document recebido]" + (f" {caption}" if caption else "")

            # Se nao tem texto, verificar tipo de midia
            if not text:
                if media_type:
                    text = f"[{media_type} recebido]"
                else:
                    logger.debug(f"Mensagem UAZAPI sem texto de {remotejid}")
                    return None

            # Dados adicionais
            message_id = msg.get("messageid", "")
            timestamp = msg.get("messageTimestamp", datetime.utcnow().timestamp() * 1000)
            push_name = msg.get("senderName", "")

            # URL da midia (Leadbox envia diretamente, UAZAPI envia em content.URL)
            media_url = msg.get("mediaUrl", "")
            if not media_url and isinstance(content, dict):
                media_url = content.get("URL", "") or content.get("url", "")

            # Instance ID - UAZAPI usa 'instanceName' no root
            instance_id = webhook_data.get("instanceName", "")

            # Token da instancia (pode ser usado para identificar agente)
            token = webhook_data.get("token", "")

            # Converter timestamp (UAZAPI envia em milissegundos)
            if isinstance(timestamp, (int, float)):
                if timestamp > 9999999999:  # Se em milissegundos
                    timestamp = timestamp / 1000
                timestamp = datetime.fromtimestamp(timestamp).isoformat()

            return ExtractedMessage(
                phone=phone,
                remotejid=remotejid,
                text=text.strip(),
                is_group=is_group,
                from_me=from_me,
                message_id=message_id,
                timestamp=timestamp,
                push_name=push_name,
                instance_id=instance_id,
                token=token,
                media_type=media_type if media_type else None,
                media_url=media_url if media_url else None,
            )

        # Formato não reconhecido
        logger.debug("Webhook não é formato UAZAPI, ignorando")
        return None

    except Exception as e:
        logger.error(f"Erro ao extrair dados da mensagem: {e}")
        return None


async def handle_control_command(
    supabase: SupabaseService,
    redis: RedisService,
    phone: str,
    remotejid: str,
    command: str,
    agent_id: str,
    table_leads: str,
    table_messages: str,
) -> Optional[str]:
    """
    Processa comandos de controle (/p, /a, /r).

    Comandos:
    - /p ou /pausar: Pausa o bot para o lead
    - /a ou /ativar: Reativa o bot para o lead
    - /r ou /reset ou /reiniciar: Limpa historico de conversa

    Args:
        supabase: Instância do SupabaseService
        redis: Instância do RedisService
        phone: Telefone do lead
        remotejid: RemoteJid completo
        command: Comando recebido
        agent_id: ID do agente
        table_leads: Nome da tabela de leads
        table_messages: Nome da tabela de mensagens

    Returns:
        Mensagem de resposta ou None se nao for comando
    """
    cmd = command.lower().strip()

    # Comando PAUSAR
    if cmd in ["/p", "/pausar", "/pause"]:
        logger.info(f"Comando PAUSAR recebido de {phone}")

        # Pausar no Supabase
        supabase.set_lead_paused(table_leads, remotejid, paused=True, reason="Comando /p do usuario")

        # Pausar no Redis (sem TTL - permanente ate /a)
        await redis.pause_set(agent_id, phone)

        return "Bot pausado. Envie /a para reativar."

    # Comando ATIVAR
    if cmd in ["/a", "/ativar", "/activate"]:
        logger.info(f"Comando ATIVAR recebido de {phone}")

        # Reativar no Supabase (pausar_ia)
        supabase.set_lead_paused(table_leads, remotejid, paused=False)

        # Limpar Atendimento_Finalizado e restaurar responsavel para AI
        supabase.update_lead_by_remotejid(
            table_leads,
            remotejid,
            {"Atendimento_Finalizado": "false", "responsavel": "AI"},
        )

        # Reativar no Redis
        await redis.pause_clear(agent_id, phone)

        return "Bot reativado. Estou de volta!"

    # Comando RESET
    if cmd in ["/r", "/reset", "/reiniciar", "/restart"]:
        logger.info(f"Comando RESET completo recebido de {phone}")

        # 1. Limpar historico de conversa no Supabase
        supabase.clear_conversation_history(table_messages, remotejid)

        # 2. Limpar buffer e pause no Redis
        await redis.buffer_clear(agent_id, phone)
        await redis.pause_clear(agent_id, phone)

        # 3. Reativar no Supabase (pausar_ia)
        supabase.set_lead_paused(table_leads, remotejid, paused=False)

        # 4. Resetar lead completamente no Supabase
        supabase.update_lead_by_remotejid(
            table_leads,
            remotejid,
            {
                "Atendimento_Finalizado": "false",
                "responsavel": "AI",
                "status": "open",
                "paused_by": None,
                "paused_at": None,
                "resumed_at": None,
                "transfer_reason": None,
                "pipeline_step": "novo",
                "ultimo_intent": None,
            },
        )

        return "Lead resetado. Podemos comecar uma nova conversa!"

    return None
