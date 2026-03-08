"""
Payment Message Service - Envio de confirmação de pagamento via WhatsApp.

Responsável por:
- Enviar mensagem de confirmação quando pagamento é recebido (PAYMENT_RECEIVED)
- Salvar mensagem no conversation_history
- Proteção contra envio duplicado (webhook 2x)
- Fallback Leadbox → UAZAPI

Criado em: 2024-03-07
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.leadbox_push import QUEUE_BILLING, leadbox_push_silent
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message

logger = logging.getLogger(__name__)


def formatar_mensagem_confirmacao(nome_cliente: str, valor: float) -> str:
    """
    Formata mensagem de confirmação de pagamento.

    Args:
        nome_cliente: Nome completo do cliente
        valor: Valor pago

    Returns:
        Mensagem formatada
    """
    # Usar apenas primeiro nome
    primeiro_nome = nome_cliente.split()[0] if nome_cliente else "Cliente"

    return (
        f"Olá {primeiro_nome}! 😊\n\n"
        f"Confirmamos o recebimento do seu pagamento de *R$ {valor:.2f}*.\n\n"
        f"Obrigada pela confiança! Se precisar de algo, é só me chamar."
    )


async def buscar_dados_cliente(
    supabase: Any,
    customer_id: str,
    payment_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Busca dados do cliente para envio de mensagem.

    Estratégias de busca:
    1. asaas_clientes (mobile_phone, phone)
    2. billing_notifications (fallback)

    Args:
        supabase: Serviço Supabase
        customer_id: ID do cliente no Asaas
        payment_id: ID do pagamento

    Returns:
        Dict com phone e name ou None se não encontrar
    """
    phone = None
    name = None

    # 1. Buscar em asaas_clientes
    try:
        result = (
            supabase.client.table("asaas_clientes")
            .select("id, name, mobile_phone, phone")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )

        if result.data:
            cliente = result.data
            phone = cliente.get("mobile_phone") or cliente.get("phone")
            name = cliente.get("name")

            if phone:
                # Normalizar telefone
                phone = re.sub(r"\D", "", str(phone))
                if not phone.startswith("55") and len(phone) >= 10:
                    phone = f"55{phone}"

                logger.debug(f"[PAYMENT MSG] Telefone encontrado em asaas_clientes: {phone[-4:]}")
                return {"phone": phone, "name": name}

    except Exception as e:
        logger.warning(f"[PAYMENT MSG] Erro ao buscar asaas_clientes: {e}")

    # 2. Fallback: billing_notifications
    try:
        result = (
            supabase.client.table("billing_notifications")
            .select("phone, customer_name")
            .eq("payment_id", payment_id)
            .limit(1)
            .execute()
        )

        if result.data and len(result.data) > 0:
            notification = result.data[0]
            phone = notification.get("phone")
            name = notification.get("customer_name") or name

            if phone:
                phone = re.sub(r"\D", "", str(phone))
                if not phone.startswith("55") and len(phone) >= 10:
                    phone = f"55{phone}"

                logger.debug(f"[PAYMENT MSG] Telefone encontrado em billing_notifications: {phone[-4:]}")
                return {"phone": phone, "name": name}

    except Exception as e:
        logger.warning(f"[PAYMENT MSG] Erro ao buscar billing_notifications: {e}")

    logger.warning(f"[PAYMENT MSG] Telefone não encontrado para customer_id={customer_id}")
    return None


async def ja_enviou_confirmacao(
    supabase: Any,
    table_messages: str,
    phone: str,
    payment_id: str,
) -> bool:
    """
    Verifica se já enviou confirmação para esse payment_id.

    Proteção contra webhook duplicado.

    Args:
        supabase: Serviço Supabase
        table_messages: Nome da tabela de mensagens
        phone: Telefone do cliente
        payment_id: ID do pagamento

    Returns:
        True se já enviou, False caso contrário
    """
    try:
        phone_jid = f"{phone}@s.whatsapp.net"

        result = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .eq("remotejid", phone_jid)
            .limit(1)
            .execute()
        )

        if not result.data:
            return False

        lead = result.data[0]
        history = lead.get("conversation_history")

        if not history:
            return False

        messages = []
        if isinstance(history, dict):
            messages = history.get("messages", [])
        elif isinstance(history, list):
            messages = history

        # Procurar mensagem de confirmação para esse payment_id
        for msg in messages:
            if (
                msg.get("context") == "pagamento_confirmado"
                and msg.get("payment_id") == payment_id
            ):
                logger.debug(f"[PAYMENT MSG] Confirmação já enviada para payment_id={payment_id}")
                return True

        return False

    except Exception as e:
        logger.warning(f"[PAYMENT MSG] Erro ao verificar duplicata: {e}")
        return False


async def salvar_no_historico(
    supabase: Any,
    table_messages: str,
    phone: str,
    mensagem: str,
    payment_id: str,
) -> bool:
    """
    Salva mensagem de confirmação no conversation_history.

    Args:
        supabase: Serviço Supabase
        table_messages: Nome da tabela de mensagens
        phone: Telefone do cliente
        mensagem: Mensagem enviada
        payment_id: ID do pagamento

    Returns:
        True se salvou, False caso contrário
    """
    try:
        phone_jid = f"{phone}@s.whatsapp.net"
        now_iso = datetime.utcnow().isoformat()

        result = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .eq("remotejid", phone_jid)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.debug(f"[PAYMENT MSG] Lead não encontrado para {phone_jid[:15]}...")
            return False

        lead = result.data[0]
        lead_id = lead["id"]
        raw_history = lead.get("conversation_history")

        if isinstance(raw_history, dict):
            messages_list = raw_history.get("messages", [])
        elif isinstance(raw_history, list):
            messages_list = raw_history
        else:
            messages_list = []

        new_message = {
            "role": "model",
            "text": mensagem,
            "timestamp": now_iso,
            "context": "pagamento_confirmado",
            "payment_id": payment_id,
        }
        messages_list.append(new_message)

        supabase.client.table(table_messages).update({
            "conversation_history": {"messages": messages_list},
        }).eq("id", lead_id).execute()

        logger.info(f"[PAYMENT MSG] Mensagem salva no conversation_history (lead_id={lead_id})")
        return True

    except Exception as e:
        logger.warning(f"[PAYMENT MSG] Erro ao salvar no histórico: {e}")
        return False


async def enviar_confirmacao_pagamento(
    supabase: Any,
    agent: Dict[str, Any],
    payment: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Envia mensagem de confirmação de pagamento via WhatsApp.

    Pipeline:
    1. Buscar dados do cliente (telefone, nome)
    2. Verificar se já enviou (proteção duplicata)
    3. Formatar mensagem
    4. Enviar via Leadbox → UAZAPI fallback
    5. Salvar no conversation_history

    Args:
        supabase: Serviço Supabase
        agent: Dados do agente (id, name, uazapi_*, table_messages)
        payment: Dados do pagamento (id, customer, value)

    Returns:
        Dict com success, message_sent, reason, error
    """
    result = {
        "success": False,
        "message_sent": False,
        "history_updated": False,
        "reason": None,
        "error": None,
    }

    payment_id = payment.get("id", "")
    customer_id = payment.get("customer", "")
    valor = payment.get("value", 0)

    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Ana")
    table_messages = agent.get("table_messages", "")

    logger.info(f"[PAYMENT MSG] Iniciando confirmação: payment_id={payment_id}, customer_id={customer_id}")

    # 1. Buscar dados do cliente
    dados_cliente = await buscar_dados_cliente(supabase, customer_id, payment_id)

    if not dados_cliente or not dados_cliente.get("phone"):
        logger.warning(f"[PAYMENT MSG] Cliente sem telefone: customer_id={customer_id}")
        result["success"] = False
        result["reason"] = "no_phone"
        return result

    phone = dados_cliente["phone"]
    nome_cliente = dados_cliente.get("name") or "Cliente"

    # 2. Verificar duplicata
    if table_messages:
        ja_enviou = await ja_enviou_confirmacao(supabase, table_messages, phone, payment_id)
        if ja_enviou:
            logger.info(f"[PAYMENT MSG] Confirmação já enviada anteriormente: payment_id={payment_id}")
            result["success"] = True
            result["message_sent"] = False
            result["reason"] = "already_sent"
            return result

    # 3. Formatar mensagem
    mensagem = formatar_mensagem_confirmacao(nome_cliente, valor)
    mensagem_assinada = sign_message(mensagem, agent_name)

    # 4. Enviar via Leadbox → UAZAPI fallback
    try:
        push_result = await leadbox_push_silent(
            phone, QUEUE_BILLING, agent_id, message=mensagem_assinada
        )

        enviado = False

        if push_result.get("success") and push_result.get("message_sent_via_push"):
            enviado = True
            logger.info(f"[PAYMENT MSG] Enviado via Leadbox PUSH: phone={phone[-4:]}")
        else:
            # Fallback UAZAPI
            uazapi_base_url = agent.get("uazapi_base_url")
            uazapi_token = agent.get("uazapi_token")

            if uazapi_base_url and uazapi_token:
                uazapi = UazapiService(base_url=uazapi_base_url, api_key=uazapi_token)
                uazapi_result = await uazapi.send_text_message(phone, mensagem_assinada)

                if uazapi_result.get("success"):
                    enviado = True
                    logger.info(f"[PAYMENT MSG] Enviado via UAZAPI fallback: phone={phone[-4:]}")
                else:
                    error_msg = uazapi_result.get("error", "Erro desconhecido")
                    logger.error(f"[PAYMENT MSG] Falha UAZAPI: {error_msg}")
                    result["error"] = error_msg
            else:
                logger.error("[PAYMENT MSG] Config UAZAPI incompleta")
                result["error"] = "Config UAZAPI incompleta"

        if enviado:
            result["success"] = True
            result["message_sent"] = True

            # 5. Salvar no histórico
            if table_messages:
                history_saved = await salvar_no_historico(
                    supabase, table_messages, phone, mensagem_assinada, payment_id
                )
                result["history_updated"] = history_saved

            logger.info(
                f"[PAYMENT MSG] Confirmação enviada: payment_id={payment_id}, "
                f"cliente={nome_cliente}, valor=R${valor:.2f}"
            )
        else:
            result["success"] = False

    except Exception as e:
        logger.error(f"[PAYMENT MSG] Exceção ao enviar: {e}")
        result["success"] = False
        result["error"] = str(e)

    return result
