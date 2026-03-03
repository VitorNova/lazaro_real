"""
Maintenance Notifier Job - Notificacao de manutencao preventiva via WhatsApp.

Logica:
- Calcula proxima_manutencao DINAMICAMENTE com base em data_inicio + ciclos de 6 meses
- Nao depende da coluna proxima_manutencao (defasada/estatica)
- Se proxima_manutencao - 7 dias == hoje, envia notificacao D-7
- Executa 09:00 dias uteis (seg-sex), timezone America/Cuiaba

Calculo do proximo ciclo:
    proxima_manutencao = data_inicio + (N * 6 meses)
    Onde N e o menor inteiro tal que data_inicio + (N * 6 meses) >= hoje

Exemplo:
    data_inicio = 2024-06-15
    Hoje = 2026-02-17
    Ciclos: 2024-06-15, 2024-12-15, 2025-06-15, 2025-12-15, 2026-06-15
    Proxima manutencao = 2026-06-15
    D-7 = 2026-06-08 -> notifica quando hoje == 2026-06-08
"""

import logging
import re
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dateutil.relativedelta import relativedelta

from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import QUEUE_MAINTENANCE, leadbox_push_silent
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.utils.dias_uteis import (
    format_date_br,
    get_today_brasilia,
    is_business_day,
    is_business_hours,
)

logger = logging.getLogger(__name__)

# Estado do job (evita execucao concorrente)
_is_running = False

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


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _log(msg: str) -> None:
    logger.info(f"[MAINTENANCE JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[MAINTENANCE JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[MAINTENANCE JOB] {msg}")


def calcular_proxima_manutencao(data_inicio: date, hoje: date) -> date:
    """
    Calcula a data do proximo ciclo de manutencao preventiva (6 em 6 meses).

    Encontra o menor N inteiro >= 1 tal que:
        data_inicio + (N * 6 meses) >= hoje

    Exemplos:
        data_inicio=2024-06-15, hoje=2026-02-17 -> 2026-06-15
        data_inicio=2025-10-04, hoje=2026-02-17 -> 2026-04-04
        data_inicio=2024-06-15, hoje=2024-06-15 -> 2024-12-15 (N=1)

    Args:
        data_inicio: Data de inicio do contrato
        hoje: Data de hoje (para calculo do ciclo atual)

    Returns:
        Data do proximo ciclo de manutencao
    """
    n = 1
    while True:
        proxima = data_inicio + relativedelta(months=6 * n)
        if proxima >= hoje:
            return proxima
        n += 1


def _get_customer_phone(row: Dict[str, Any]) -> Optional[str]:
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


def _format_maintenance_message(
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


def _extract_equipamento_info(equipamentos: Any) -> Tuple[str, int]:
    """
    Extrai marca e BTUs do primeiro equipamento da lista.

    Args:
        equipamentos: Lista de equipamentos (JSONB)

    Returns:
        Tupla (marca, btus) - fallback para strings vazias se nao encontrado
    """
    if not equipamentos:
        return ("ar-condicionado", 0)

    # Pode vir como lista ou dict
    if isinstance(equipamentos, list) and len(equipamentos) > 0:
        equip = equipamentos[0]
    elif isinstance(equipamentos, dict):
        equip = equipamentos
    else:
        return ("ar-condicionado", 0)

    marca = equip.get("marca") or "ar-condicionado"
    btus = equip.get("btus") or 0

    return (str(marca), int(btus) if btus else 0)


# ============================================================================
# SUPABASE QUERY
# ============================================================================

async def fetch_contracts_for_maintenance(agent_id: str) -> List[Dict[str, Any]]:
    """
    Busca todos os contratos com data_inicio preenchida para o agente.

    Faz JOIN manual em Python pois customer_id (text) referencia asaas_clientes.id
    sem FK declarada no banco.

    Args:
        agent_id: ID do agente (tenant)

    Returns:
        Lista de contratos enriquecidos com nome e telefone do cliente
    """
    supabase = get_supabase_service()

    # 1. Buscar contratos com data_inicio
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
        _log_error(f"Erro ao buscar contratos: {e}")
        return []

    if not contracts:
        _log("Nenhum contrato encontrado")
        return []

    _log(f"Encontrados {len(contracts)} contratos com data_inicio")

    # 2. Buscar dados dos clientes (JOIN manual - sem FK declarada)
    customer_ids = list({c["customer_id"] for c in contracts if c.get("customer_id")})

    customers_by_id: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        try:
            # asaas_clientes.id e o mesmo que contract_details.customer_id
            customer_response = (
                supabase.client.table("asaas_clientes")
                .select("id, name, mobile_phone, phone")
                .in_("id", customer_ids)
                .execute()
            )
            for c in (customer_response.data or []):
                customers_by_id[c["id"]] = c
        except Exception as e:
            _log_warn(f"Erro ao buscar clientes: {e}")

    # 3. Enriquecer contratos com dados dos clientes
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
) -> None:
    """
    Registra o envio da notificacao no banco de dados.

    Atualiza:
    1. notificacao_enviada_at - timestamp do envio
    2. maintenance_status = 'notified' - para tracking no dashboard
    3. proxima_manutencao - data calculada dinamicamente (sincroniza com DB)

    Salva tambem no conversation_history para contexto da IA.

    Args:
        contract_id: ID do contrato
        proxima_manutencao: Data calculada da proxima manutencao
        customer_phone: Telefone do cliente (para buscar tabela leadbox)
        message_sent: Mensagem enviada (para salvar no historico)
    """
    supabase = get_supabase_service()
    now_iso = datetime.utcnow().isoformat()

    try:
        # 1. Atualizar contract_details
        supabase.client.table("contract_details").update({
            "notificacao_enviada_at": now_iso,
            "maintenance_status": "notified",
            "proxima_manutencao": proxima_manutencao.isoformat(),
        }).eq("id", contract_id).execute()
        _log(f"Contrato {contract_id}: status='notified', proxima_manutencao={proxima_manutencao}")
    except Exception as e:
        _log_error(f"Erro ao atualizar contract_details: {e}")

    # 2. Salvar no conversation_history para contexto da IA
    # Busca a tabela leadbox_messages_* do agente Lazaro
    try:
        # Formatar phone para busca (leadbox usa formato com @s.whatsapp.net)
        phone_jid = f"{customer_phone}@s.whatsapp.net" if customer_phone else None

        if phone_jid:
            # Buscar conversa existente para pegar conversation_history atual
            table_name = f"leadbox_messages_{AGENT_ID_LAZARO.replace('-', '_')}"

            # Buscar pelo remotejid (NÃO "jid")
            result = supabase.client.table(table_name).select(
                "id, conversation_history"
            ).eq("remotejid", phone_jid).limit(1).execute()

            if result.data and len(result.data) > 0:
                lead_id = result.data[0]["id"]
                raw_history = result.data[0].get("conversation_history")

                # NORMALIZAR FORMATO: detect_conversation_context() espera {"messages": [...]}
                if isinstance(raw_history, dict):
                    messages_list = raw_history.get("messages", [])
                elif isinstance(raw_history, list):
                    messages_list = raw_history
                else:
                    messages_list = []

                # Criar novo registro de mensagem com context de manutencao
                # IMPORTANTE: Formato compatível com detect_conversation_context()
                # - role: "model" (não "assistant") - padrão Gemini
                # - text: (não "content") - padrão do sistema
                # - context: STRING "manutencao_preventiva" (não dict)
                new_message = {
                    "role": "model",
                    "text": message_sent,
                    "timestamp": now_iso,
                    "context": "manutencao_preventiva",
                    "contract_id": contract_id,
                }

                # Append ao historico
                messages_list.append(new_message)

                # Salvar
                supabase.client.table(table_name).update({
                    "conversation_history": {"messages": messages_list},
                }).eq("id", lead_id).execute()

                _log(f"Mensagem salva no conversation_history (lead {lead_id[:8]}...)")
            else:
                _log(f"Lead nao encontrado para {phone_jid[:15]}... - mensagem nao salva no historico")

    except Exception as e:
        # Nao falhar o job se nao conseguir salvar no historico
        _log_warn(f"Erro ao salvar no conversation_history (nao critico): {e}")


def _already_notified_this_cycle(
    contract: Dict[str, Any],
    proxima_manutencao: date,
) -> bool:
    """
    Verifica se a notificacao D-7 para este ciclo ja foi enviada.

    Compara notificacao_enviada_at com a janela do ciclo atual.
    O ciclo comeca 7 dias antes da proxima manutencao.
    Se ja enviou dentro dessa janela, pula.

    Args:
        contract: Dados do contrato
        proxima_manutencao: Data calculada do proximo ciclo

    Returns:
        True se ja notificou neste ciclo
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

        # Janela do ciclo: D-7 ate D+0 (dia da manutencao)
        window_start = proxima_manutencao - timedelta(days=NOTIFY_DAYS_BEFORE)
        window_end = proxima_manutencao

        return window_start <= sent_at <= window_end
    except Exception as e:
        _log_warn(f"Erro ao verificar notificacao_enviada_at: {e}")
        return False


# ============================================================================
# MAIN PROCESSING
# ============================================================================

async def process_maintenance_notifications(agent_id: str, agent: Dict[str, Any]) -> Dict[str, int]:
    """
    Processa notificacoes de manutencao preventiva D-7 para todos os contratos do agente.

    Para cada contrato com data_inicio:
    1. Calcula proxima_manutencao dinamicamente (N ciclos de 6 meses)
    2. Se proxima_manutencao - 7 dias == hoje, verifica se ja foi notificado
    3. Se nao foi notificado, envia mensagem e registra envio

    Args:
        agent_id: ID do agente
        agent: Dados do agente (uazapi_base_url, uazapi_token, etc.)

    Returns:
        Dict com contadores: sent, skipped, errors
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0}
    hoje = get_today_brasilia()

    contracts = await fetch_contracts_for_maintenance(agent_id)
    if not contracts:
        _log(f"Nenhum contrato para processar (agente: {agent.get('name')})")
        return stats

    agent_name = agent.get("name", "Assistente")
    _log(f"Processando {len(contracts)} contratos para agente: {agent_name}")

    # Verificar configuracao do WhatsApp
    uazapi_base_url = agent.get("uazapi_base_url")
    uazapi_token = agent.get("uazapi_token")

    if not uazapi_base_url or not uazapi_token:
        _log_error(f"Configuracao UAZAPI incompleta para agente {agent.get('name')}")
        return stats

    uazapi = UazapiService(base_url=uazapi_base_url, api_key=uazapi_token)

    for contract in contracts:
        contract_id = contract["id"]
        customer_name = contract.get("nome", "Cliente")
        data_inicio_raw = contract.get("data_inicio")

        if not data_inicio_raw:
            stats["skipped"] += 1
            continue

        # Parse data_inicio
        try:
            if isinstance(data_inicio_raw, str):
                data_inicio = date.fromisoformat(data_inicio_raw)
            elif isinstance(data_inicio_raw, date):
                data_inicio = data_inicio_raw
            else:
                _log_warn(f"Contrato {contract_id}: data_inicio invalida ({data_inicio_raw})")
                stats["skipped"] += 1
                continue
        except Exception:
            _log_warn(f"Contrato {contract_id}: erro ao parsear data_inicio ({data_inicio_raw})")
            stats["skipped"] += 1
            continue

        # Calcular proxima manutencao dinamicamente
        proxima_manutencao = calcular_proxima_manutencao(data_inicio, hoje)
        data_notificacao = proxima_manutencao - timedelta(days=NOTIFY_DAYS_BEFORE)

        # Verificar se hoje e o dia D-7
        if hoje != data_notificacao:
            # Nao e o dia de notificar este contrato
            continue

        _log(
            f"Contrato {contract_id} ({customer_name}): "
            f"data_inicio={data_inicio}, proxima_manutencao={proxima_manutencao}, "
            f"hoje={hoje} -> NOTIFICAR"
        )

        # Verificar se ja foi notificado neste ciclo
        if _already_notified_this_cycle(contract, proxima_manutencao):
            _log(f"Contrato {contract_id}: notificacao D-7 ja enviada neste ciclo, pulando")
            stats["skipped"] += 1
            continue

        # Obter telefone
        phone = _get_customer_phone(contract)
        if not phone:
            _log_warn(f"Contrato {contract_id} ({customer_name}): sem telefone valido")
            stats["skipped"] += 1
            continue

        # Extrair info do equipamento
        marca, btus = _extract_equipamento_info(contract.get("equipamentos"))

        # Endereco de instalacao
        endereco = contract.get("endereco_instalacao") or "endereco nao informado"

        # Montar mensagem
        message = _format_maintenance_message(
            template=DEFAULT_MAINTENANCE_MESSAGE,
            nome=customer_name.split()[0] if customer_name else "Cliente",
            marca=marca,
            btus=btus,
            endereco=endereco,
        )

        # Enviar via WhatsApp com dispatch inteligente
        try:
            signed = sign_message(message, agent_name)

            # DISPATCH INTELIGENTE: PUSH decide se cria ticket ou move
            push_result = await leadbox_push_silent(
                phone, QUEUE_MAINTENANCE, AGENT_ID_LAZARO, message=signed
            )

            if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
                # Ticket check falhou ou ticket já existia — enviar via UAZAPI
                result = await uazapi.send_text_message(phone, signed)
                if not result.get("success"):
                    raise ValueError(result.get("error", "Erro desconhecido"))
            else:
                result = {"success": True}

            if result.get("success"):
                _log(
                    f"Notificacao enviada: {customer_name} | "
                    f"telefone={phone[:8]}*** | "
                    f"manutencao={format_date_br(proxima_manutencao)}"
                )

                # Registrar envio no banco (com status, proxima_manutencao e conversation_history)
                await mark_notification_sent(
                    contract_id=contract_id,
                    proxima_manutencao=proxima_manutencao,
                    customer_phone=phone,
                    message_sent=message,
                )

                # Log dispatch in unified dispatch_log table
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
                    },
                )

                stats["sent"] += 1
            else:
                error_msg = result.get("error", "Erro desconhecido")
                _log_error(f"Falha ao enviar para {customer_name}: {error_msg}")

                # Log failure in unified dispatch_log table
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
                    metadata={
                        "proxima_manutencao": proxima_manutencao.isoformat(),
                        "data_inicio": str(data_inicio),
                    },
                )

                stats["errors"] += 1

        except Exception as e:
            _log_error(f"Excecao ao enviar para {customer_name} ({contract_id}): {e}")

            # Log failure in unified dispatch_log table
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


# ============================================================================
# FETCH AGENT
# ============================================================================

async def get_maintenance_agent() -> Optional[Dict[str, Any]]:
    """
    Busca o agente configurado para notificacoes de manutencao.

    Por enquanto hardcoded para o agente Lazaro (Alugar Ar).
    Futuramente pode ser generalizado para buscar por configuracao.

    Returns:
        Dados do agente ou None se nao encontrado
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
        _log_error(f"Erro ao buscar agente: {e}")
        return None


# ============================================================================
# JOB ENTRY POINTS
# ============================================================================

async def run_maintenance_notifier_job() -> Dict[str, Any]:
    """
    Entry point principal do job de notificacao de manutencao.

    Executa verificacoes de seguranca:
    - Evita execucao concorrente
    - So roda em dias uteis
    - So roda em horario comercial (8h-18h, Cuiaba = America/Sao_Paulo -1h)

    Returns:
        Status e estatisticas da execucao
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    hoje = get_today_brasilia()

    # So executa em dias uteis
    if not is_business_day(hoje):
        _log("Hoje nao e dia util, pulando execucao")
        return {"status": "skipped", "reason": "not_business_day"}

    # Horario comercial: 8h-18h Brasilia
    if not is_business_hours(8, 18):
        _log("Fora do horario comercial, pulando execucao")
        return {"status": "skipped", "reason": "outside_business_hours"}

    _is_running = True
    _log(f"Iniciando job de manutencao preventiva (hoje={hoje})")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0}

    try:
        agent = await get_maintenance_agent()

        if not agent:
            _log_warn(f"Agente {AGENT_ID_LAZARO} nao encontrado ou inativo")
            return {"status": "skipped", "reason": "agent_not_found"}

        _log(f"Agente: {agent.get('name')} ({agent['id'][:8]}...)")

        agent_stats = await process_maintenance_notifications(agent["id"], agent)
        total_stats["sent"] += agent_stats["sent"]
        total_stats["skipped"] += agent_stats["skipped"]
        total_stats["errors"] += agent_stats["errors"]

        _log(
            f"Job finalizado: {total_stats['sent']} enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no job de manutencao: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


async def _force_run_maintenance_notifier() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    hoje = get_today_brasilia()
    _log(f"=== EXECUCAO FORCADA (hoje={hoje}) ===")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0}

    try:
        agent = await get_maintenance_agent()

        if not agent:
            _log_warn(f"Agente {AGENT_ID_LAZARO} nao encontrado ou inativo")
            return {"status": "skipped", "reason": "agent_not_found"}

        agent_stats = await process_maintenance_notifications(agent["id"], agent)
        total_stats["sent"] += agent_stats["sent"]
        total_stats["skipped"] += agent_stats["skipped"]
        total_stats["errors"] += agent_stats["errors"]

        _log(
            f"=== Job forcado finalizado: {total_stats['sent']} enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no job forcado: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_maintenance_notifier_running() -> bool:
    """Verifica se o job esta rodando."""
    return _is_running


async def test_maintenance_notification(phone: str = "556697194084") -> Dict[str, Any]:
    """
    Envia notificacao de teste para um numero especifico.
    APENAS PARA DEBUG/TESTES.

    Tambem salva no conversation_history para testar injecao de prompt.

    Args:
        phone: Numero de telefone (sem @s.whatsapp.net)

    Returns:
        Dict com resultado do envio
    """
    # Remover sufixo se presente
    phone = phone.replace("@s.whatsapp.net", "")

    _log(f"=== TESTE DE MANUTENCAO para {phone} ===")

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

        # Mensagem de teste
        message = _format_maintenance_message(
            template=DEFAULT_MAINTENANCE_MESSAGE,
            nome="TESTE",
            marca="Teste Marca",
            btus="12000",
            endereco="Endereco de Teste, 123",
        )

        signed = sign_message(message, agent_name)
        _log(f"Mensagem completa:\n{signed}")

        # Enviar via PUSH + fallback UAZAPI
        push_result = await leadbox_push_silent(
            phone, QUEUE_MAINTENANCE, AGENT_ID_LAZARO, message=signed
        )

        _log(f"Push result: {push_result}")

        if push_result.get("ticket_check_failed"):
            _log("PUSH falhou na verificacao de ticket, usando UAZAPI direto...")
            result = await uazapi.send_text_message(phone, signed)
            if not result.get("success"):
                return {"success": False, "error": result.get("error")}
            result["via"] = "uazapi_fallback"
        elif not push_result.get("message_sent_via_push"):
            _log("Ticket existia, PUSH moveu fila, usando UAZAPI...")
            result = await uazapi.send_text_message(phone, signed)
            if not result.get("success"):
                return {"success": False, "error": result.get("error")}
            result["via"] = "uazapi"
        else:
            result = {"success": True, "via": "push"}

        # ================================================================
        # SALVAR NO CONVERSATION_HISTORY PARA TESTAR INJECAO DE PROMPT
        # ================================================================
        context_saved = False
        try:
            supabase = get_supabase_service()
            phone_jid = f"{phone}@s.whatsapp.net"
            table_name = agent.get("table_messages")
            now_iso = datetime.utcnow().isoformat()

            if not table_name:
                _log_warn("table_messages nao encontrado no agente")
                raise ValueError("table_messages nao configurado")

            # Buscar lead pelo telefone
            lead_result = supabase.client.table(table_name).select(
                "id, conversation_history"
            ).eq("remotejid", phone_jid).limit(1).execute()

            if lead_result.data and len(lead_result.data) > 0:
                lead_id = lead_result.data[0]["id"]
                raw_history = lead_result.data[0].get("conversation_history")

                # Normalizar formato
                if isinstance(raw_history, dict):
                    messages_list = raw_history.get("messages", [])
                elif isinstance(raw_history, list):
                    messages_list = raw_history
                else:
                    messages_list = []

                # Adicionar mensagem com contexto de manutencao
                new_message = {
                    "role": "model",
                    "text": signed,
                    "timestamp": now_iso,
                    "context": "manutencao_preventiva",
                    "contract_id": "TEST-CONTRACT-ID",
                }
                messages_list.append(new_message)

                # Salvar
                supabase.client.table(table_name).update({
                    "conversation_history": {"messages": messages_list},
                }).eq("id", lead_id).execute()

                context_saved = True
                _log(f"Contexto salvo no conversation_history (lead {str(lead_id)[:8]}...)")
            else:
                _log(f"Lead nao encontrado para {phone_jid} - contexto NAO salvo")

        except Exception as e:
            _log_warn(f"Erro ao salvar contexto (nao critico): {e}")

        _log(f"=== TESTE CONCLUIDO: {result} | context_saved={context_saved} ===")
        return {"success": True, "result": result, "phone": phone, "context_saved": context_saved}

    except Exception as e:
        _log_error(f"Erro no teste: {e}")
        return {"success": False, "error": str(e)}
