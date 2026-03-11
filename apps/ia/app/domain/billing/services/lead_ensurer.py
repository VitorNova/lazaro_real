"""
Lead Ensurer Service - Garantia de leads e historico de conversas para cobranca.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.5)

Funcionalidades:
- Garantir que lead existe (cria se necessario)
- Garantir que registro de mensagem existe
- Salvar mensagem no conversation_history (formato Gemini)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.utils.phone import find_message_record_by_phone, generate_phone_variants
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


def mask_phone(phone: str) -> str:
    """Mascara telefone para logs (LGPD/GDPR compliance)."""
    if not phone or len(phone) < 8:
        return "****"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


def mask_customer_name(name: str) -> str:
    """Mascara nome de cliente para logs (LGPD/GDPR compliance)."""
    if not name or len(name) < 3:
        return "***"
    return name[0] + "*" * (len(name) - 1)


def phone_to_remotejid(phone: str) -> str:
    """Converte telefone para formato remoteJid do WhatsApp."""
    cleaned = re.sub(r"\D", "", phone)
    return f"{cleaned}@s.whatsapp.net"


async def ensure_lead_exists(
    agent: Dict[str, Any],
    phone: str,
    payment: Dict[str, Any],
) -> Optional[int]:
    """
    Garante que o lead existe na tabela. Se nao existir, cria.
    Retorna o ID do lead ou None se falhar.

    Fluxo:
    1. Busca lead por remotejid ou asaas_customer_id
    2. Se encontrado, atualiza billing_context
    3. Se nao, cria novo lead com dados do pagamento
    """
    table_leads = agent.get("table_leads")
    if not table_leads:
        _log_warn(f"Agente {agent.get('name')} nao tem table_leads configurado")
        return None

    remotejid = phone_to_remotejid(phone)
    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()

    try:
        # Buscar lead existente pelo remotejid ou asaas_customer_id
        customer_id = payment.get("customer_id") or payment.get("customer", "")
        response = (
            supabase.client.table(table_leads)
            .select("id")
            .or_(f"remotejid.eq.{remotejid},asaas_customer_id.eq.{customer_id}")
            .limit(1)
            .execute()
        )

        # Montar billing_context para salvar no lead
        billing_context = {
            "customer_id": customer_id,
            "customer_name": payment.get("customer_name", ""),
            "last_billing_at": now[:10],  # YYYY-MM-DD
            "pending_amount": float(payment.get("value") or 0),
            "has_overdue": payment.get("status") == "OVERDUE",
            "last_payment_id": payment.get("id", ""),
        }

        if response.data:
            lead_id = response.data[0]["id"]
            _log(f"Lead existente encontrado: {lead_id}")
            # Atualizar lead_origin e billing_context para contexto de cobranca
            try:
                supabase.client.table(table_leads).update({
                    "lead_origin": "disparo_cobranca",
                    "billing_context": billing_context,
                    "updated_date": now,
                }).eq("id", lead_id).execute()
            except Exception as e:
                _log_warn(f"Erro ao atualizar lead_origin/billing_context: {e}")
            return lead_id

        # Lead nao existe, criar novo
        customer_name = payment.get("customer_name", "Cliente Asaas")

        new_lead = {
            "nome": customer_name,
            "telefone": phone,
            "remotejid": remotejid,
            "asaas_customer_id": customer_id,
            "pipeline_step": "cliente",
            "status": "ativo",
            "lead_origin": "disparo_cobranca",
            "billing_context": billing_context,
            "current_state": "active",
            "created_date": now,
            "updated_date": now,
        }

        result = supabase.client.table(table_leads).insert(new_lead).execute()

        if result.data:
            lead_id = result.data[0]["id"]
            _log(f"Novo lead criado: {lead_id} ({mask_customer_name(customer_name)})")
            return lead_id
        else:
            _log_error(f"Falha ao criar lead para {mask_phone(phone)}")
            return None

    except Exception as e:
        _log_error(f"Erro ao garantir lead: {e}")
        return None


async def ensure_message_record_exists(
    agent: Dict[str, Any],
    phone: str,
    lead_id: int,
    payment: Dict[str, Any],
) -> Optional[int]:
    """
    Garante que o registro de mensagem existe. Se nao existir, cria.
    Retorna o ID do registro ou None se falhar.

    IMPORTANTE: Usa variantes de telefone (com/sem 9 extra) para buscar
    registro existente. Isso resolve mismatch entre Asaas e Leadbox.

    Estrutura da tabela:
    - id (uuid)
    - creat (timestamp)
    - remotejid
    - conversation_history (JSONB)
    - Msg_model, Msg_user
    """
    table_messages = agent.get("table_messages")
    if not table_messages:
        _log_warn(f"Agente {agent.get('name')} nao tem table_messages configurado")
        return None

    remotejid = phone_to_remotejid(phone)
    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()

    try:
        # Buscar registro existente usando variantes de telefone
        # Isso resolve bug onde Asaas tem 5566996465228 e Leadbox tem 556696465228
        variants = generate_phone_variants(phone)
        or_conditions = ",".join([
            f"remotejid.eq.{v}@s.whatsapp.net"
            for v in variants
        ])

        response = (
            supabase.client.table(table_messages)
            .select("id")
            .or_(or_conditions)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]["id"]

        # Registro nao existe, criar novo
        # Inicializa com msg fake "ola" do user (padrao Gemini para contexto de billing)
        initial_history = {
            "messages": [
                {
                    "role": "user",
                    "parts": [{"text": "ola"}],
                    "timestamp": now,
                    "context": "billing",
                }
            ]
        }

        new_record = {
            "remotejid": remotejid,
            "conversation_history": initial_history,
            "creat": now,
            "Msg_user": now,
        }

        result = supabase.client.table(table_messages).insert(new_record).execute()

        if result.data:
            msg_id = result.data[0]["id"]
            _log(f"Novo registro de mensagem criado: {msg_id}")
            return msg_id
        else:
            _log_error(f"Falha ao criar registro de mensagem para {mask_phone(phone)}")
            return None

    except Exception as e:
        _log_error(f"Erro ao garantir registro de mensagem: {e}")
        return None


async def save_message_to_conversation_history(
    agent: Dict[str, Any],
    phone: str,
    message: str,
    notification_type: str,
    payment: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Salva a mensagem de cobranca no conversation_history do lead.
    Se o lead ou registro de mensagem nao existir, cria automaticamente.

    Formato Gemini:
    - role: "model" (mensagem do sistema)
    - parts: [{text: ...}] em vez de content
    - context: "billing" para identificar disparo de cobranca
    - reference_id: ID do pagamento
    """
    table_messages = agent.get("table_messages")
    if not table_messages:
        _log_warn(f"Agente {agent.get('name')} nao tem table_messages configurado")
        return

    remotejid = phone_to_remotejid(phone)
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "") if payment else ""

    try:
        supabase = get_supabase_service()

        # Se payment foi fornecido, garantir que lead e registro existam
        if payment:
            lead_id = await ensure_lead_exists(agent, phone, payment)
            if lead_id:
                await ensure_message_record_exists(agent, phone, lead_id, payment)

        # Buscar mensagem mais recente usando variantes de telefone
        # Resolve bug onde Asaas tem 5566996465228 e Leadbox tem 556696465228
        variants = generate_phone_variants(phone)
        or_conditions = ",".join([
            f"remotejid.eq.{v}@s.whatsapp.net"
            for v in variants
        ])

        response = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .or_(or_conditions)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data:
            _log_warn(f"Nenhum registro de mensagem encontrado para {remotejid}")
            return

        msg_record = response.data[0]
        history = msg_record.get("conversation_history") or {"messages": []}
        messages = history.get("messages", [])

        # Se historico vazio, adicionar msg fake do user primeiro (padrao Gemini)
        if not messages:
            messages.append({
                "role": "user",
                "parts": [{"text": "ola"}],
                "timestamp": now,
                "context": "billing",
            })

        # Adicionar mensagem do model no formato Gemini
        messages.append({
            "role": "model",
            "parts": [{"text": message}],
            "timestamp": now,
            "context": "billing",
            "reference_id": payment_id,
        })

        supabase.client.table(table_messages).update({
            "conversation_history": {"messages": messages},
            "Msg_model": now,
        }).eq("id", msg_record["id"]).execute()

        _log(f"Mensagem de cobranca salva no historico (Gemini format): {remotejid}")

    except Exception as e:
        _log_warn(f"Erro ao salvar mensagem no historico: {e}")
