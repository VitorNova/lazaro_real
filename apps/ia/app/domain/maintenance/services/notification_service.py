"""
Notification Service - Logica de notificacao de manutencao preventiva D-7.

Extraido de jobs/notificar_manutencoes.py na Fase 3 da refatoracao.
Responsabilidades:
- Calculo de ciclos de manutencao (6 em 6 meses)
- Formatacao de mensagens
- Envio via WhatsApp (PUSH + UAZAPI fallback)
- Registro de envios no banco
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta

from app.core.utils.dias_uteis import format_date_br, get_today_brasilia
from app.core.utils.phone import find_message_record_by_phone, generate_phone_variants
from app.domain.leads.services.lead_availability import check_lead_availability
from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import QUEUE_MAINTENANCE, leadbox_push_silent
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.billing.dispatcher import get_leadbox_phone

logger = logging.getLogger(__name__)

# ID do agente Lazaro (Alugar Ar)
AGENT_ID_LAZARO = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Quantos dias antes da manutencao notificar
NOTIFY_DAYS_BEFORE = 7

# Template padrao da mensagem de manutencao
DEFAULT_MAINTENANCE_MESSAGE = (
    "Ola {nome}! Aqui e a ANA da Alugar Ar.\n\n"
    "Esta chegando a hora da manutencao preventiva do seu ar-condicionado!\n"
    "*Equipamento:* {marca} {btus} BTUs\n"
    "*Endereco:* {endereco}\n\n"
    "A manutencao e gratuita e esta inclusa no seu contrato.\n\n"
    "Quer agendar? Me fala um dia e horario de preferencia!"
)


def calcular_proxima_manutencao(data_inicio: date, hoje: date) -> date:
    """
    Calcula a data do proximo ciclo de manutencao preventiva (6 em 6 meses).

    Encontra o menor N inteiro >= 1 tal que:
        data_inicio + (N * 6 meses) >= hoje
    """
    n = 1
    while True:
        proxima = data_inicio + relativedelta(months=6 * n)
        if proxima >= hoje:
            return proxima
        n += 1


def get_customer_phone(row: Dict[str, Any]) -> Optional[str]:
    """Obtem e normaliza telefone do cliente para envio via WhatsApp."""
    phone = row.get("mobile_phone") or row.get("phone")
    if not phone:
        return None

    cleaned = re.sub(r"\D", "", str(phone))

    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    if len(cleaned) < 12 or len(cleaned) > 13:
        return None

    return cleaned


def format_maintenance_message(
    template: str,
    nome: str,
    marca: str,
    btus: int,
    endereco: str,
) -> str:
    """Formata a mensagem de manutencao substituindo variaveis."""
    msg = template
    msg = re.sub(r"\{nome\}", nome, msg, flags=re.IGNORECASE)
    msg = re.sub(r"\{marca\}", marca, msg, flags=re.IGNORECASE)
    msg = re.sub(r"\{btus\}", str(btus), msg, flags=re.IGNORECASE)
    msg = re.sub(r"\{endereco\}", endereco, msg, flags=re.IGNORECASE)
    return msg


def extract_equipamento_info(equipamentos: Any) -> Tuple[str, int]:
    """
    Extrai marca e BTUs do primeiro equipamento da lista.

    Returns:
        Tupla (marca, btus) - fallback para strings vazias se nao encontrado
    """
    if not equipamentos:
        return ("ar-condicionado", 0)

    if isinstance(equipamentos, list) and len(equipamentos) > 0:
        equip = equipamentos[0]
    elif isinstance(equipamentos, dict):
        equip = equipamentos
    else:
        return ("ar-condicionado", 0)

    marca = equip.get("marca") or "ar-condicionado"
    btus = equip.get("btus") or 0

    return (str(marca), int(btus) if btus else 0)


async def fetch_contracts_for_maintenance(agent_id: str) -> List[Dict[str, Any]]:
    """
    Busca todos os contratos com data_inicio preenchida para o agente.

    Faz JOIN manual em Python pois customer_id (text) referencia asaas_clientes.id
    sem FK declarada no banco.
    """
    supabase = get_supabase_service()

    try:
        response = (
            supabase.client.table("contract_details")
            .select(
                "id, customer_id, data_inicio, endereco_instalacao, equipamentos, "
                "notificacao_enviada_at, maintenance_status"
            )
            .eq("agent_id", agent_id)
            .not_.is_("data_inicio", "null")
            .execute()
        )
        contracts = response.data or []
    except Exception as e:
        logger.error(f"[MAINTENANCE] Erro ao buscar contratos: {e}")
        return []

    if not contracts:
        logger.info("[MAINTENANCE] Nenhum contrato encontrado")
        return []

    logger.info(f"[MAINTENANCE] Encontrados {len(contracts)} contratos com data_inicio")

    # Buscar dados dos clientes (JOIN manual)
    customer_ids = list({c["customer_id"] for c in contracts if c.get("customer_id")})

    customers_by_id: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        try:
            customer_response = (
                supabase.client.table("asaas_clientes")
                .select("id, name, mobile_phone, phone")
                .in_("id", customer_ids)
                .execute()
            )
            for c in (customer_response.data or []):
                customers_by_id[c["id"]] = c
        except Exception as e:
            logger.warning(f"[MAINTENANCE] Erro ao buscar clientes: {e}")

    # Enriquecer contratos com dados dos clientes
    result = []
    for contract in contracts:
        customer_id = contract.get("customer_id", "")
        cliente = customers_by_id.get(customer_id, {})

        result.append({
            **contract,
            "nome": cliente.get("name") or "Cliente",
            "mobile_phone": cliente.get("mobile_phone"),
            "phone": cliente.get("phone"),
        })

    return result


async def mark_notification_sent(
    contract_id: str,
    proxima_manutencao: date,
    customer_phone: str,
    message_sent: str,
    table_messages: str = None,
    customer_id: str = None,
) -> None:
    """
    Registra o envio da notificacao no banco de dados.

    Atualiza contract_details e salva no conversation_history para contexto da IA.

    IMPORTANTE: Usa find_message_record_by_phone() para buscar lead com variantes
    de telefone (com/sem 9 extra). Isso resolve o bug onde telefone Asaas difere
    do Leadbox (ex: 5591989650040 vs 559189650040).
    """
    supabase = get_supabase_service()
    now_iso = datetime.utcnow().isoformat()

    try:
        supabase.client.table("contract_details").update({
            "notificacao_enviada_at": now_iso,
            "maintenance_status": "notified",
            "proxima_manutencao": proxima_manutencao.isoformat(),
        }).eq("id", contract_id).execute()
        logger.info(f"[MAINTENANCE] Contrato {contract_id}: status='notified'")
    except Exception as e:
        logger.error(f"[MAINTENANCE] Erro ao atualizar contract_details: {e}")

    # Salvar no conversation_history para contexto da IA
    try:
        if not customer_phone:
            logger.warning(f"[MAINTENANCE] Sem telefone para salvar contexto")
            return

        # Usar table_messages do agent se disponivel, senao fallback
        if table_messages:
            table_name = table_messages
        else:
            # Fallback para Ana (padrao historico)
            table_name = "leadbox_messages_Ana_14e6e5ce"

        # Usar find_message_record_by_phone para buscar com variantes de telefone
        # Isso resolve mismatch entre Asaas (5591989650040) e Leadbox (559189650040)
        lead_record = find_message_record_by_phone(
            supabase=supabase,
            table_messages=table_name,
            phone=customer_phone,
            customer_id=customer_id,
        )

        if lead_record:
            # Lead existe - UPDATE no historico existente
            lead_id = lead_record["id"]
            raw_history = lead_record.get("conversation_history")

            if isinstance(raw_history, dict):
                messages_list = raw_history.get("messages", [])
            elif isinstance(raw_history, list):
                messages_list = raw_history
            else:
                messages_list = []

            new_message = {
                "role": "model",
                "parts": [{"text": message_sent}],
                "timestamp": now_iso,
                "context": "manutencao_preventiva",
                "contract_id": contract_id,
            }
            messages_list.append(new_message)

            supabase.client.table(table_name).update({
                "conversation_history": {"messages": messages_list},
            }).eq("id", lead_id).execute()

            logger.info(
                f"[MAINTENANCE] Mensagem salva no conversation_history "
                f"(lead {str(lead_id)[:8]}..., context=manutencao_preventiva)"
            )
        else:
            # Lead NAO existe - INSERT novo registro com contexto
            # Bug fix 2026-03-16: Criar registro quando lead nao existe
            # Estrutura: msg fake "ola" (user) + msg manutencao (model)
            # Regra Gemini: primeira mensagem deve ser role="user"
            masked_phone = customer_phone[:8] + "***" if customer_phone else "N/A"
            logger.info(
                f"[MAINTENANCE] Lead nao encontrado para {masked_phone} | "
                f"customer_id={customer_id} | CRIANDO novo registro"
            )

            # Converter telefone para remotejid (formato WhatsApp)
            cleaned_phone = re.sub(r"\D", "", customer_phone)
            remotejid = f"{cleaned_phone}@s.whatsapp.net"

            # Construir conversation_history com mensagem fake + mensagem real
            # Regra Gemini: primeira mensagem DEVE ser role="user"
            initial_messages = [
                {
                    "role": "user",
                    "parts": [{"text": "ola"}],
                    "timestamp": now_iso,
                    "context": "manutencao_preventiva",
                },
                {
                    "role": "model",
                    "parts": [{"text": message_sent}],
                    "timestamp": now_iso,
                    "context": "manutencao_preventiva",
                    "contract_id": contract_id,
                },
            ]

            new_record = {
                "remotejid": remotejid,
                "conversation_history": {"messages": initial_messages},
                "creat": now_iso,
                "Msg_model": now_iso,
            }

            result = supabase.client.table(table_name).insert(new_record).execute()

            if result.data:
                new_id = result.data[0].get("id", "unknown")
                logger.info(
                    f"[MAINTENANCE] Novo registro criado: {str(new_id)[:8]}... | "
                    f"context=manutencao_preventiva | contract_id={contract_id[:8]}..."
                )
            else:
                logger.error(
                    f"[MAINTENANCE] Falha ao criar registro para {masked_phone}"
                )

    except Exception as e:
        logger.warning(f"[MAINTENANCE] Erro ao salvar no conversation_history: {e}")


def already_notified_this_cycle(
    contract: Dict[str, Any],
    proxima_manutencao: date,
) -> bool:
    """
    Verifica se a notificacao D-7 para este ciclo ja foi enviada.
    """
    notificacao_enviada_at = contract.get("notificacao_enviada_at")
    if not notificacao_enviada_at:
        return False

    try:
        if isinstance(notificacao_enviada_at, str):
            sent_at = datetime.fromisoformat(notificacao_enviada_at.replace("Z", "+00:00")).date()
        elif isinstance(notificacao_enviada_at, datetime):
            sent_at = notificacao_enviada_at.date()
        else:
            return False

        window_start = proxima_manutencao - timedelta(days=NOTIFY_DAYS_BEFORE)
        window_end = proxima_manutencao

        return window_start <= sent_at <= window_end
    except Exception as e:
        logger.warning(f"[MAINTENANCE] Erro ao verificar notificacao_enviada_at: {e}")
        return False


async def get_maintenance_agent() -> Optional[Dict[str, Any]]:
    """
    Busca o agente configurado para notificacoes de manutencao.
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("agents")
            .select("id, name, uazapi_base_url, uazapi_token, uazapi_instance_id, table_leads, table_messages")
            .eq("id", AGENT_ID_LAZARO)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        agents = response.data or []
        return agents[0] if agents else None
    except Exception as e:
        logger.error(f"[MAINTENANCE] Erro ao buscar agente: {e}")
        return None


async def process_maintenance_notifications(
    agent_id: str,
    agent: Dict[str, Any],
    hoje: Optional[date] = None,
) -> Dict[str, int]:
    """
    Processa notificacoes de manutencao preventiva D-7 para todos os contratos.
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0, "queue_errors": 0}
    if hoje is None:
        hoje = get_today_brasilia()

    contracts = await fetch_contracts_for_maintenance(agent_id)
    if not contracts:
        logger.info(f"[MAINTENANCE] Nenhum contrato para processar")
        return stats

    agent_name = agent.get("name", "Assistente")
    logger.info(f"[MAINTENANCE] Processando {len(contracts)} contratos")

    uazapi_base_url = agent.get("uazapi_base_url")
    uazapi_token = agent.get("uazapi_token")

    if not uazapi_base_url or not uazapi_token:
        logger.error(f"[MAINTENANCE] Configuracao UAZAPI incompleta")
        return stats

    uazapi = UazapiService(base_url=uazapi_base_url, api_key=uazapi_token)

    for contract in contracts:
        contract_id = contract["id"]
        customer_name = contract.get("nome", "Cliente")
        data_inicio_raw = contract.get("data_inicio")

        if not data_inicio_raw:
            stats["skipped"] += 1
            continue

        try:
            if isinstance(data_inicio_raw, str):
                data_inicio = date.fromisoformat(data_inicio_raw)
            elif isinstance(data_inicio_raw, date):
                data_inicio = data_inicio_raw
            else:
                stats["skipped"] += 1
                continue
        except Exception:
            stats["skipped"] += 1
            continue

        proxima_manutencao = calcular_proxima_manutencao(data_inicio, hoje)
        data_notificacao = proxima_manutencao - timedelta(days=NOTIFY_DAYS_BEFORE)

        if hoje != data_notificacao:
            continue

        logger.info(
            f"[MAINTENANCE] Contrato {contract_id} ({customer_name}): "
            f"proxima_manutencao={proxima_manutencao} -> NOTIFICAR"
        )

        if already_notified_this_cycle(contract, proxima_manutencao):
            logger.info(f"[MAINTENANCE] Contrato {contract_id}: ja notificado neste ciclo")
            stats["skipped"] += 1
            continue

        phone = get_customer_phone(contract)
        if not phone:
            logger.warning(f"[MAINTENANCE] Contrato {contract_id}: sem telefone valido")
            stats["skipped"] += 1
            continue

        marca, btus = extract_equipamento_info(contract.get("equipamentos"))
        endereco = contract.get("endereco_instalacao") or "endereco nao informado"

        message = format_maintenance_message(
            template=DEFAULT_MAINTENANCE_MESSAGE,
            nome=customer_name.split()[0] if customer_name else "Cliente",
            marca=marca,
            btus=btus,
            endereco=endereco,
        )

        # Verificar disponibilidade ANTES de disparar
        available, reason = await check_lead_availability(
            agent=agent,
            phone=phone,
            agent_id=agent_id,
        )

        if not available:
            logger.info({
                "event": "maintenance_deferred",
                "contract_id": contract_id,
                "reason": reason,
            })

            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_deferred(
                phone=phone,
                job_type="maintenance",
                reason=reason,
                context={
                    "contract_id": contract_id,
                    "customer_name": customer_name,
                    "notification_type": "d7",
                    "message": message,
                    "proxima_manutencao": proxima_manutencao.isoformat(),
                },
                reference_id=contract_id,
            )

            stats["skipped"] += 1
            continue

        try:
            signed = sign_message(message, agent_name)

            push_result = await leadbox_push_silent(
                phone, QUEUE_MAINTENANCE, AGENT_ID_LAZARO, message=signed
            )

            if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
                result = await uazapi.send_text_message(phone, signed)
                if not result.get("success"):
                    raise ValueError(result.get("error", "Erro desconhecido"))
            else:
                result = {"success": True}

            # Verificar se houve problema na confirmação de fila
            queue_confirmation_failed = push_result.get("queue_confirmation_failed", False)
            if queue_confirmation_failed:
                logger.warning(
                    f"[MAINTENANCE] PUT de confirmação de fila FALHOU para {customer_name} | "
                    f"telefone={phone[:8]}*** | ticket pode estar na fila errada"
                )
                stats["queue_errors"] += 1

            if result.get("success"):
                logger.info(
                    f"[MAINTENANCE] Notificacao enviada: {customer_name} | "
                    f"telefone={phone[:8]}*** | manutencao={format_date_br(proxima_manutencao)}"
                )

                # Normalizar telefone antes de salvar (evita duplicatas)
                # O Asaas pode ter telefone diferente do Leadbox (ex: 5566992028039 vs 556692028039)
                normalized_phone = await get_leadbox_phone(
                    agent.get("handoff_triggers", {}),
                    phone,
                )

                await mark_notification_sent(
                    contract_id=contract_id,
                    proxima_manutencao=proxima_manutencao,
                    customer_phone=normalized_phone,
                    message_sent=message,
                    table_messages=agent.get("table_messages"),
                    customer_id=contract.get("customer_id"),
                )

                dispatch_logger = get_dispatch_logger()
                await dispatch_logger.log_dispatch(
                    job_type="maintenance",
                    agent_id=agent_id,
                    reference_id=contract_id,
                    phone=phone,
                    notification_type="reminder_7d",
                    message_text=message,
                    status="sent",
                    reference_table="contract_details",
                    customer_id=contract.get("customer_id"),
                    customer_name=customer_name,
                    days_from_due=-NOTIFY_DAYS_BEFORE,
                    metadata={
                        "proxima_manutencao": proxima_manutencao.isoformat(),
                        "data_inicio": str(data_inicio),
                        "marca": marca,
                        "btus": btus,
                        "endereco": endereco,
                        "queue_confirmation_failed": queue_confirmation_failed,
                    },
                )

                stats["sent"] += 1
            else:
                error_msg = result.get("error", "Erro desconhecido")
                logger.error(f"[MAINTENANCE] Falha ao enviar para {customer_name}: {error_msg}")

                dispatch_logger = get_dispatch_logger()
                await dispatch_logger.log_failure(
                    job_type="maintenance",
                    agent_id=agent_id,
                    reference_id=contract_id,
                    phone=phone,
                    notification_type="reminder_7d",
                    error_message=error_msg,
                    message_text=message,
                    reference_table="contract_details",
                    customer_id=contract.get("customer_id"),
                    customer_name=customer_name,
                    days_from_due=-NOTIFY_DAYS_BEFORE,
                )

                stats["errors"] += 1

        except Exception as e:
            logger.error(f"[MAINTENANCE] Excecao ao enviar para {customer_name}: {e}")

            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_failure(
                job_type="maintenance",
                agent_id=agent_id,
                reference_id=contract_id,
                phone=phone,
                notification_type="reminder_7d",
                error_message=str(e),
                message_text=message,
                reference_table="contract_details",
                customer_id=contract.get("customer_id"),
                customer_name=customer_name,
                days_from_due=-NOTIFY_DAYS_BEFORE,
            )

            stats["errors"] += 1

    return stats


async def test_maintenance_notification(phone: str = "556697194084") -> Dict[str, Any]:
    """
    Envia notificacao de teste para um numero especifico.
    APENAS PARA DEBUG/TESTES.
    """
    phone = phone.replace("@s.whatsapp.net", "")
    logger.info(f"[MAINTENANCE] === TESTE para {phone} ===")

    try:
        agent = await get_maintenance_agent()
        if not agent:
            return {"success": False, "error": "Agente nao encontrado"}

        agent_name = agent.get("name", "Ana")
        uazapi_base_url = agent.get("uazapi_base_url")
        uazapi_token = agent.get("uazapi_token")

        if not uazapi_base_url or not uazapi_token:
            return {"success": False, "error": "Config UAZAPI incompleta"}

        uazapi = UazapiService(base_url=uazapi_base_url, api_key=uazapi_token)

        message = format_maintenance_message(
            template=DEFAULT_MAINTENANCE_MESSAGE,
            nome="TESTE",
            marca="Teste Marca",
            btus="12000",
            endereco="Endereco de Teste, 123",
        )

        signed = sign_message(message, agent_name)

        push_result = await leadbox_push_silent(
            phone, QUEUE_MAINTENANCE, AGENT_ID_LAZARO, message=signed
        )

        if push_result.get("ticket_check_failed"):
            result = await uazapi.send_text_message(phone, signed)
            if not result.get("success"):
                return {"success": False, "error": result.get("error")}
            result["via"] = "uazapi_fallback"
        elif not push_result.get("message_sent_via_push"):
            result = await uazapi.send_text_message(phone, signed)
            if not result.get("success"):
                return {"success": False, "error": result.get("error")}
            result["via"] = "uazapi"
        else:
            result = {"success": True, "via": "push"}

        # Salvar no conversation_history para testar injecao de prompt
        context_saved = False
        try:
            supabase = get_supabase_service()
            table_name = agent.get("table_messages")
            now_iso = datetime.utcnow().isoformat()

            if table_name:
                # Usar find_message_record_by_phone para buscar com variantes
                lead_record = find_message_record_by_phone(
                    supabase=supabase,
                    table_messages=table_name,
                    phone=phone,
                )

                if lead_record:
                    lead_id = lead_record["id"]
                    raw_history = lead_record.get("conversation_history")

                    if isinstance(raw_history, dict):
                        messages_list = raw_history.get("messages", [])
                    elif isinstance(raw_history, list):
                        messages_list = raw_history
                    else:
                        messages_list = []

                    new_message = {
                        "role": "model",
                        "parts": [{"text": signed}],
                        "timestamp": now_iso,
                        "context": "manutencao_preventiva",
                        "contract_id": "TEST-CONTRACT-ID",
                    }
                    messages_list.append(new_message)

                    supabase.client.table(table_name).update({
                        "conversation_history": {"messages": messages_list},
                    }).eq("id", lead_id).execute()

                    context_saved = True
                    logger.info(f"[MAINTENANCE] Contexto salvo (lead {str(lead_id)[:8]}...)")

        except Exception as e:
            logger.warning(f"[MAINTENANCE] Erro ao salvar contexto: {e}")

        logger.info(f"[MAINTENANCE] === TESTE CONCLUIDO: {result} ===")
        return {"success": True, "result": result, "phone": phone, "context_saved": context_saved}

    except Exception as e:
        logger.error(f"[MAINTENANCE] Erro no teste: {e}")
        return {"success": False, "error": str(e)}
