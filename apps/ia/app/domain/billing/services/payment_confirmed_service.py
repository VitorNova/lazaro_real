"""
Servico de pagamentos confirmados/recebidos + envio de confirmacao WhatsApp.

Fluxo: webhook PAYMENT_CONFIRMED/RECEIVED → atualiza status → atualiza lead → envia msg → salva historico
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.utils.phone import generate_phone_variants
from app.core.utils.sql_escape import escape_ilike_pattern
from app.services.leadbox_push import QUEUE_BILLING, leadbox_push_silent
from app.services.whatsapp_api import UazapiService, sign_message

logger = logging.getLogger(__name__)


# ─── Busca de dados do cliente ──────────────────────────────────────────────

async def buscar_telefone_cliente(
    supabase: Any, customer_id: str, payment_id: str,
) -> Optional[str]:
    """Busca telefone normalizado (últimos 9 dígitos) para match flexível de lead."""
    dados = await buscar_dados_cliente(supabase, customer_id, payment_id)
    if dados and dados.get("phone"):
        digits = re.sub(r"\D", "", str(dados["phone"]))
        if len(digits) >= 9:
            return digits[-9:]
    return None


async def buscar_dados_cliente(
    supabase: Any, customer_id: str, payment_id: str,
) -> Optional[Dict[str, Any]]:
    """Busca phone e name do cliente em asaas_clientes → billing_notifications (fallback)."""
    for strategy in ["asaas_clientes", "billing_notifications"]:
        try:
            if strategy == "asaas_clientes":
                r = supabase.client.table("asaas_clientes").select(
                    "name, mobile_phone, phone"
                ).eq("id", customer_id).maybe_single().execute()
                if r.data:
                    phone = r.data.get("mobile_phone") or r.data.get("phone")
                    if phone:
                        phone = re.sub(r"\D", "", str(phone))
                        if not phone.startswith("55") and len(phone) >= 10:
                            phone = f"55{phone}"
                        return {"phone": phone, "name": r.data.get("name")}
            else:
                r = supabase.client.table("billing_notifications").select(
                    "phone, customer_name"
                ).eq("payment_id", payment_id).limit(1).execute()
                if r.data:
                    phone = r.data[0].get("phone")
                    if phone:
                        phone = re.sub(r"\D", "", str(phone))
                        if not phone.startswith("55") and len(phone) >= 10:
                            phone = f"55{phone}"
                        return {"phone": phone, "name": r.data[0].get("customer_name")}
        except Exception as e:
            logger.warning("[PAYMENT MSG] Erro ao buscar %s: %s", strategy, e)

    logger.warning("[PAYMENT MSG] Telefone não encontrado para customer_id=%s", customer_id)
    return None


# ─── Duplicata e historico ──────────────────────────────────────────────────

def _build_or_conditions(phone: str) -> str:
    """Gera condição OR com variantes de telefone para query Supabase."""
    variants = generate_phone_variants(phone)
    return ",".join(f"remotejid.eq.{v}@s.whatsapp.net" for v in variants)


async def ja_enviou_confirmacao(
    supabase: Any, table_messages: str, phone: str, payment_id: str,
) -> bool:
    """Verifica se já enviou confirmação para esse payment_id (proteção duplicata)."""
    try:
        r = supabase.client.table(table_messages).select(
            "id, conversation_history"
        ).or_(_build_or_conditions(phone)).limit(1).execute()

        if not r.data:
            return False

        history = r.data[0].get("conversation_history")
        if not history:
            return False

        messages = history.get("messages", []) if isinstance(history, dict) else (history if isinstance(history, list) else [])
        return any(
            m.get("context") == "pagamento_confirmado" and m.get("payment_id") == payment_id
            for m in messages
        )
    except Exception as e:
        logger.warning("[PAYMENT MSG] Erro ao verificar duplicata: %s", e)
        return False


async def salvar_no_historico(
    supabase: Any, table_messages: str, phone: str, mensagem: str, payment_id: str,
) -> bool:
    """Salva mensagem de confirmação no conversation_history do lead."""
    try:
        r = supabase.client.table(table_messages).select(
            "id, conversation_history"
        ).or_(_build_or_conditions(phone)).limit(1).execute()

        if not r.data:
            logger.debug("[PAYMENT MSG] Lead não encontrado para variantes de %s...", phone[-4:])
            return False

        lead = r.data[0]
        raw = lead.get("conversation_history")
        messages_list = raw.get("messages", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])

        messages_list.append({
            "role": "model",
            "text": mensagem,
            "timestamp": datetime.utcnow().isoformat(),
            "context": "pagamento_confirmado",
            "payment_id": payment_id,
        })

        supabase.client.table(table_messages).update({
            "conversation_history": {"messages": messages_list},
        }).eq("id", lead["id"]).execute()

        logger.info("[PAYMENT MSG] Mensagem salva no conversation_history (lead_id=%s)", lead["id"])
        return True
    except Exception as e:
        logger.warning("[PAYMENT MSG] Erro ao salvar no histórico: %s", e)
        return False


# ─── Formatacao e envio da mensagem ─────────────────────────────────────────

def formatar_mensagem_confirmacao(nome_cliente: str, valor: float) -> str:
    """Formata mensagem de confirmação de pagamento."""
    primeiro_nome = nome_cliente.split()[0] if nome_cliente else "Cliente"
    return (
        f"Olá {primeiro_nome}! 😊\n\n"
        f"Confirmamos o recebimento do seu pagamento de *R$ {valor:.2f}*.\n\n"
        f"Obrigada pela confiança! Se precisar de algo, é só me chamar."
    )


async def enviar_confirmacao_pagamento(
    supabase: Any, agent: Dict[str, Any], payment: Dict[str, Any],
) -> Dict[str, Any]:
    """Envia confirmação de pagamento via Leadbox → UAZAPI fallback, salva no histórico."""
    result = {"success": False, "message_sent": False, "history_updated": False, "reason": None, "error": None}

    payment_id = payment.get("id", "")
    customer_id = payment.get("customer", "")
    valor = payment.get("value", 0)
    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Ana")
    table_messages = agent.get("table_messages", "")

    logger.info("[PAYMENT MSG] Iniciando confirmação: payment_id=%s, customer_id=%s", payment_id, customer_id)

    # 1. Buscar telefone
    dados = await buscar_dados_cliente(supabase, customer_id, payment_id)
    if not dados or not dados.get("phone"):
        logger.warning("[PAYMENT MSG] Cliente sem telefone: customer_id=%s", customer_id)
        result["reason"] = "no_phone"
        return result

    phone = dados["phone"]
    nome = dados.get("name") or "Cliente"

    # 2. Duplicata
    if table_messages and await ja_enviou_confirmacao(supabase, table_messages, phone, payment_id):
        logger.info("[PAYMENT MSG] Confirmação já enviada: payment_id=%s", payment_id)
        result["success"] = True
        result["reason"] = "already_sent"
        return result

    # 3. Formatar e enviar
    mensagem = sign_message(formatar_mensagem_confirmacao(nome, valor), agent_name)

    try:
        enviado = False
        push = await leadbox_push_silent(phone, QUEUE_BILLING, agent_id, message=mensagem)

        if push.get("success") and push.get("message_sent_via_push"):
            enviado = True
            logger.info("[PAYMENT MSG] Enviado via Leadbox PUSH: phone=%s", phone[-4:])
        else:
            url, token = agent.get("uazapi_base_url"), agent.get("uazapi_token")
            if url and token:
                uazapi_result = await UazapiService(base_url=url, api_key=token).send_text_message(phone, mensagem)
                if uazapi_result.get("success"):
                    enviado = True
                    logger.info("[PAYMENT MSG] Enviado via UAZAPI fallback: phone=%s", phone[-4:])
                else:
                    result["error"] = uazapi_result.get("error", "Erro desconhecido")

        if enviado:
            result["success"] = True
            result["message_sent"] = True
            if table_messages:
                result["history_updated"] = await salvar_no_historico(supabase, table_messages, phone, mensagem, payment_id)
            logger.info("[PAYMENT MSG] Confirmação enviada: payment_id=%s, cliente=%s", payment_id, nome)
        else:
            result["success"] = False
    except Exception as e:
        logger.error("[PAYMENT MSG] Exceção ao enviar: %s", e)
        result["error"] = str(e)

    return result


# ─── Processamento de eventos webhook ───────────────────────────────────────

async def processar_pagamento_confirmado(
    supabase: Any, payment: Dict[str, Any], agent_id: Optional[str],
) -> None:
    """Processa PAYMENT_CONFIRMED — atualiza status para CONFIRMED."""
    payment_id = payment.get("id", "")
    if agent_id:
        try:
            supabase.client.table("asaas_cobrancas").update({
                "status": "CONFIRMED",
                "payment_date": payment.get("paymentDate"),
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)


async def processar_pagamento_recebido(
    supabase: Any, payment: Dict[str, Any], agent_id: Optional[str],
) -> None:
    """Processa PAYMENT_RECEIVED — atualiza status, lead e envia confirmação."""
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # 1. Atualizar asaas_cobrancas
    if agent_id:
        try:
            cobranca = supabase.client.table("asaas_cobrancas").select(
                "ia_cobrou"
            ).eq("id", payment_id).eq("agent_id", agent_id).limit(1).execute()

            update = {"status": "RECEIVED", "payment_date": payment.get("paymentDate"), "updated_at": now}

            if cobranca.data and cobranca.data[0].get("ia_cobrou"):
                update["ia_recebeu"] = True
                update["ia_recebeu_at"] = now
                try:
                    notif = supabase.client.table("billing_notifications").select(
                        "notification_type, days_from_due"
                    ).eq("payment_id", payment_id).eq("status", "sent").order(
                        "sent_at", desc=True
                    ).limit(1).execute()
                    if notif.data:
                        update["ia_recebeu_step"] = notif.data[0].get("notification_type")
                        update["ia_recebeu_days_from_due"] = notif.data[0].get("days_from_due")
                except Exception as e:
                    logger.warning("[ASAAS WEBHOOK] Erro ao buscar step: %s", e)

            supabase.client.table("asaas_cobrancas").update(update).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    # 2. Marcar billing_notifications como paid
    try:
        supabase.client.table("billing_notifications").update({
            "status": "paid", "updated_at": now,
        }).eq("payment_id", payment_id).execute()
    except Exception as e:
        logger.debug("[ASAAS WEBHOOK] Erro ao atualizar billing_notifications: %s", e)

    # 3. Atualizar lead
    customer_id = payment.get("customer", "")
    if agent_id and customer_id:
        try:
            await atualizar_lead_pagamento(supabase, agent_id, customer_id, payment_id, payment_value=value)
        except Exception as e:
            logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead: %s", e)

    # 4. Enviar confirmação WhatsApp
    if agent_id:
        try:
            agent_r = supabase.client.table("agents").select(
                "id, name, uazapi_base_url, uazapi_token, table_leads, table_messages"
            ).eq("id", agent_id).maybe_single().execute()

            if agent_r.data:
                confirm = await enviar_confirmacao_pagamento(supabase, agent_r.data, payment)
                if confirm.get("message_sent"):
                    logger.info("[ASAAS WEBHOOK] Confirmação enviada: payment_id=%s", payment_id)
                elif confirm.get("reason") == "already_sent":
                    logger.debug("[ASAAS WEBHOOK] Confirmação já enviada: payment_id=%s", payment_id)
                else:
                    logger.warning("[ASAAS WEBHOOK] Não enviou confirmação: payment_id=%s, reason=%s",
                                   payment_id, confirm.get("reason") or confirm.get("error"))
        except Exception as e:
            logger.error("[ASAAS WEBHOOK] Erro ao enviar confirmação: %s", e)


# ─── Atualização de lead ────────────────────────────────────────────────────

async def atualizar_lead_pagamento(
    supabase: Any, agent_id: str, customer_id: str, payment_id: str, payment_value: float = 0,
) -> None:
    """Atualiza lead quando pagamento é recebido (vincula customer, pipeline=cliente)."""
    if not agent_id or not customer_id:
        return

    now = datetime.utcnow().isoformat()

    # Buscar table_leads
    try:
        agent_r = supabase.client.table("agents").select("table_leads").eq("id", agent_id).maybe_single().execute()
        if not agent_r.data or not agent_r.data.get("table_leads"):
            logger.warning("[ASAAS WEBHOOK] table_leads não encontrado: agent_id=%s", agent_id[:8])
            return
        table_leads = agent_r.data["table_leads"]
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao buscar table_leads: %s", e)
        return

    lead = None

    # 1. Por asaas_customer_id
    try:
        r = supabase.client.table(table_leads).select(
            "id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at"
        ).eq("asaas_customer_id", customer_id).limit(1).execute()
        if r.data:
            lead = r.data[0]
    except Exception:
        pass

    # 2. Por CPF/telefone do cliente Asaas
    if not lead:
        try:
            cr = supabase.client.table("asaas_clientes").select(
                "cpf_cnpj, mobile_phone"
            ).eq("id", customer_id).eq("agent_id", agent_id).maybe_single().execute()

            if cr.data:
                cpf = re.sub(r'\D', '', cr.data.get("cpf_cnpj") or "")
                if len(cpf) in [11, 14] and not lead:
                    r = supabase.client.table(table_leads).select(
                        "id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at"
                    ).eq("cpf_cnpj", cpf).limit(1).execute()
                    if r.data:
                        lead = r.data[0]

                phone = re.sub(r'\D', '', cr.data.get("mobile_phone") or "")
                if len(phone) >= 10 and not lead:
                    suffix = phone[-11:] if len(phone) >= 11 else phone
                    r = supabase.client.table(table_leads).select(
                        "id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at"
                    ).ilike("remotejid", f"%{escape_ilike_pattern(suffix)}%").limit(1).execute()
                    if r.data:
                        lead = r.data[0]
        except Exception as e:
            logger.warning("[ASAAS WEBHOOK] Erro ao buscar cliente/lead: %s", e)

    if not lead:
        logger.warning("[ASAAS WEBHOOK] Lead não encontrado para customer_id=%s", customer_id)
        return

    # Atualizar
    update_data = {
        "asaas_customer_id": customer_id,
        "pipeline_step": "cliente",
        "venda_realizada": "true",
        "journey_stage": "cliente",
        "updated_date": now,
    }
    if not lead.get("converted_at"):
        update_data["converted_at"] = now
    if not lead.get("first_payment_at"):
        update_data["first_payment_at"] = now
        logger.info("[CONVERSAO] Primeiro pagamento! Lead %s -> R$ %.2f", lead["id"], payment_value)

    try:
        supabase.client.table(table_leads).update(update_data).eq("id", lead["id"]).execute()
        logger.info("[ASAAS WEBHOOK] Lead atualizado: id=%s, nome=%s, pipeline: %s -> cliente",
                     lead["id"], (lead.get("nome") or "?")[:20], lead.get("pipeline_step", ""))
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead id=%s: %s", lead["id"], e)
