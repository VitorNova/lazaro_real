"""
================================================================================
CÓDIGO COMPLETO DO DISPARO DE MANUTENÇÃO - LAZARO V2
================================================================================

Este arquivo contém TODO o código relacionado ao disparo de manutenção preventiva,
consolidado em um único arquivo para facilitar a leitura e análise.

Arquivos originais:
1. apps/ia/app/jobs/notificar_manutencoes.py (linhas 1-672)
2. apps/ia/app/services/leadbox_push.py (linhas 673-918)
3. apps/ia/app/services/manutencao_slots.py (linhas 919-1210)
4. apps/ia/app/services/whatsapp_api.py (linhas 1211-2612)
5. apps/ia/app/utils/dias_uteis.py (linhas 2613-2769)
6. apps/ia/app/tools/manutencao.py (linhas 2770-3541)
7. apps/ia/app/main.py - trechos relevantes (linhas 3542-3700)

================================================================================
"""


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 1: apps/ia/app/jobs/notificar_manutencoes.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

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

from app.services.leadbox_push import QUEUE_MAINTENANCE, leadbox_push_silent
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService
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
            signed_message = f"*{agent_name.title()}:*\n{message}"

            # DISPATCH INTELIGENTE: PUSH decide se cria ticket ou move
            push_result = await leadbox_push_silent(
                phone, QUEUE_MAINTENANCE, AGENT_ID_LAZARO, message=signed_message
            )

            if not push_result.get("message_sent_via_push"):
                # Ticket já existia — PUSH só moveu de fila, enviar via UAZAPI
                result = await uazapi.send_text_message(phone, signed_message)
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
                stats["sent"] += 1
            else:
                error_msg = result.get("error", "Erro desconhecido")
                _log_error(f"Falha ao enviar para {customer_name}: {error_msg}")
                stats["errors"] += 1

        except Exception as e:
            _log_error(f"Excecao ao enviar para {customer_name} ({contract_id}): {e}")
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
            .select("id, name, uazapi_base_url, uazapi_token, uazapi_instance_id")
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


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 2: apps/ia/app/services/leadbox_push.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
Leadbox Dispatch - Roteia ticket para fila correta de forma inteligente.

Lógica híbrida:
- Se ticket JÁ EXISTE: PUT /tickets/{id} move pra fila certa (caller envia via UAZAPI)
- Se ticket NÃO EXISTE: POST PUSH com body (cria ticket + envia mensagem numa tacada só)

Isso evita mensagem vazia e mensagem duplicada nos dois cenários.
"""

import asyncio
import time
import logging
from typing import Any, Dict, Optional

import httpx

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


# IDs das filas no Leadbox (Lazaro)
QUEUE_BILLING = 544      # Fila de cobrança
QUEUE_MAINTENANCE = 545  # Fila de manutenção
QUEUE_GENERIC = 537      # Fila genérica (onde tickets caem por padrão)


async def leadbox_push_silent(
    phone: str,
    queue_id: int,
    agent_id: str,
    message: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Dispatch inteligente pro Leadbox.

    Args:
        phone: Telefone do cliente
        queue_id: ID da fila no Leadbox (544=billing, 545=manutenção)
        agent_id: ID do agente no Supabase
        message: Mensagem a enviar (usada se precisar criar ticket via PUSH)
        user_id: ID do usuário para atribuir (opcional)

    Returns:
        Dict com:
            success: bool
            ticket_existed: bool - True se ticket já existia
            ticket_id: int|None - ID do ticket
            message_sent_via_push: bool - True se PUSH já enviou a mensagem
    """
    result = {
        "success": False,
        "ticket_existed": False,
        "ticket_id": None,
        "message_sent_via_push": False,
    }

    supabase = get_supabase_service()
    clean_phone = _format_phone(phone)

    try:
        # Buscar config do Leadbox no agente
        agent_result = supabase.client.table("agents").select(
            "handoff_triggers"
        ).eq("id", agent_id).limit(1).execute()

        if not agent_result.data:
            logger.warning(f"[LEADBOX PUSH] Agente {agent_id} não encontrado")
            return result

        handoff = agent_result.data[0].get("handoff_triggers") or {}
        api_url = handoff.get("api_url")
        api_uuid = handoff.get("api_uuid")
        api_token = handoff.get("api_token")

        if not api_url or not api_uuid or not api_token:
            logger.warning("[LEADBOX PUSH] Config incompleta (api_url/api_uuid/api_token)")
            return result

        if not handoff.get("enabled"):
            logger.debug("[LEADBOX PUSH] Leadbox desabilitado no agente")
            return result

        # Buscar userId da fila nos dispatch_departments (se não informado)
        if user_id is None:
            dispatch_depts = handoff.get("dispatch_departments") or {}
            for dept_key, dept in dispatch_depts.items():
                if dept.get("queueId") == queue_id:
                    user_id = dept.get("userId")
                    break

        base_url = api_url.rstrip('/')
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # ================================================================
        # PASSO 1: Buscar ticket existente do contato
        # ================================================================
        ticket_id = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Buscar contato pelo telefone
                contact_resp = await client.get(
                    f"{base_url}/contacts",
                    params={"searchParam": clean_phone, "limit": 1},
                    headers=headers,
                )
                contact_resp.raise_for_status()
                contact_data = contact_resp.json()

                contacts = contact_data.get("contacts", contact_data if isinstance(contact_data, list) else [])
                contact = contacts[0] if contacts else None

                if contact and contact.get("id"):
                    contact_id = contact["id"]
                    # Buscar tickets abertos do contato
                    tickets_resp = await client.get(
                        f"{base_url}/tickets",
                        params={"contactId": contact_id, "status": "open,pending", "limit": 10},
                        headers=headers,
                    )
                    tickets_resp.raise_for_status()
                    tickets_data = tickets_resp.json()

                    tickets = tickets_data.get("tickets", tickets_data if isinstance(tickets_data, list) else [])
                    if isinstance(tickets, list):
                        # Procurar qualquer ticket aberto (não precisa ser da fila específica)
                        for t in tickets:
                            if t.get("status") in ("open", "pending"):
                                ticket_id = t.get("id")
                                break

                    if ticket_id:
                        logger.debug(f"[LEADBOX PUSH] Ticket existente encontrado: {ticket_id}")

        except Exception as e:
            logger.warning(f"[LEADBOX PUSH] Erro ao buscar ticket existente: {e}")
            # Continua — vai tentar via PUSH

        # ================================================================
        # PASSO 2: Decidir estratégia
        # ================================================================
        if ticket_id:
            # CENÁRIO 1: Ticket existe → PUT para mover de fila
            # Caller envia mensagem via UAZAPI (sem duplicar)
            result["ticket_existed"] = True
            result["message_sent_via_push"] = False

            put_url = f"{base_url}/tickets/{ticket_id}"
            put_payload: Dict[str, Any] = {"queueId": queue_id}
            if user_id:
                put_payload["userId"] = user_id

            async with httpx.AsyncClient(timeout=10) as client:
                put_resp = await client.put(put_url, json=put_payload, headers=headers)
                put_resp.raise_for_status()

            result["ticket_id"] = ticket_id
            result["success"] = True
            logger.info(
                f"[LEADBOX PUSH] PUT ok (ticket existia): ticketId={ticket_id} -> "
                f"queueId={queue_id}, userId={user_id}"
            )

        else:
            # CENÁRIO 2: Sem ticket → POST PUSH com body (cria + envia)
            # Caller NÃO envia via UAZAPI (PUSH já envia)
            result["ticket_existed"] = False
            result["message_sent_via_push"] = True

            external_key = f"push-{int(time.time())}"
            payload: Dict[str, Any] = {
                "number": clean_phone,
                "externalKey": external_key,
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Incluir body pra não enviar mensagem vazia
            if message:
                payload["body"] = message

            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            push_url = f"{base_url}/v1/api/external/{api_uuid}/?token={api_token}"
            logger.debug(f"[LEADBOX PUSH] POST PUSH {push_url[:60]}... payload keys={list(payload.keys())}")

            async with httpx.AsyncClient(timeout=15) as client:
                push_resp = await client.post(push_url, json=payload, headers=headers)
                push_resp.raise_for_status()
                push_data = push_resp.json()

            ticket_id = (
                push_data.get("ticketId")
                or push_data.get("ticket", {}).get("id")
                or push_data.get("message", {}).get("ticketId")
            )

            result["ticket_id"] = ticket_id
            result["success"] = True

            logger.info(
                f"[LEADBOX PUSH] PUSH ok (ticket novo): phone={clean_phone[:8]}***, "
                f"queueId={queue_id}, ticketId={ticket_id}"
            )

            # PUT pra garantir fila (PUSH pode ignorar forceTicketToDepartment)
            if ticket_id:
                await asyncio.sleep(2)
                try:
                    put_url = f"{base_url}/tickets/{ticket_id}"
                    put_payload = {"queueId": queue_id}
                    if user_id:
                        put_payload["userId"] = user_id

                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.put(put_url, json=put_payload, headers=headers)

                    logger.info(f"[LEADBOX PUSH] PUT confirmação: ticketId={ticket_id} -> queueId={queue_id}")
                except Exception as e:
                    logger.warning(f"[LEADBOX PUSH] PUT falhou (não-crítico): {e}")

        return result

    except httpx.HTTPStatusError as e:
        logger.warning(f"[LEADBOX PUSH] HTTP {e.response.status_code}: {e.response.text[:100]}")
        return result
    except Exception as e:
        logger.warning(f"[LEADBOX PUSH] Erro: {e}")
        return result


def _format_phone(phone: str) -> str:
    """Formata telefone para o padrão Leadbox (apenas dígitos, com 55)."""
    clean = phone.replace("@s.whatsapp.net", "").replace("@c.us", "").replace("@lid", "")
    clean = "".join(filter(str.isdigit, clean))
    if len(clean) == 10 or len(clean) == 11:
        clean = f"55{clean}"
    return clean


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 3: apps/ia/app/services/manutencao_slots.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
Servico de controle de slots de manutencao preventiva.

Regra de negocio:
- Maximo 1 manutencao por manha (08:00-12:00) por dia
- Maximo 1 manutencao por tarde (14:00-18:00) por dia

Usa a tabela `schedules` existente com service_name='manutencao_preventiva'
para armazenar e consultar agendamentos.
"""

import logging
from datetime import date, datetime, time
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

# Timezone padrao do Lazaro (Cuiaba/MT)
TIMEZONE_LAZARO = ZoneInfo("America/Cuiaba")

# Agent ID padrao do Lazaro
AGENT_ID_LAZARO = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Definicao dos periodos
PERIODOS = {
    "manha": {
        "hora_inicio": time(8, 0),
        "hora_fim": time(12, 0),
        "label": "Manhã (08h-12h)",
    },
    "tarde": {
        "hora_inicio": time(14, 0),
        "hora_fim": time(18, 0),
        "label": "Tarde (14h-18h)",
    },
}

# Identificador de servico na tabela schedules
SERVICE_NAME = "manutencao_preventiva"


def _get_periodo_from_hora(hora_inicio: time) -> Optional[str]:
    """Identifica o periodo com base na hora de inicio."""
    if hora_inicio == PERIODOS["manha"]["hora_inicio"]:
        return "manha"
    if hora_inicio == PERIODOS["tarde"]["hora_inicio"]:
        return "tarde"
    return None


def verificar_slot(
    data: date,
    periodo: str,
    agent_id: str = AGENT_ID_LAZARO,
) -> bool:
    """
    Verifica se o slot de manutencao esta disponivel.

    Args:
        data: Data do agendamento (objeto date)
        periodo: 'manha' ou 'tarde'
        agent_id: ID do agente (default: Lazaro)

    Returns:
        True se o slot esta disponivel, False se ja esta ocupado.
    """
    if periodo not in PERIODOS:
        logger.error(f"Periodo invalido: {periodo}. Use 'manha' ou 'tarde'.")
        return False

    try:
        supabase = get_supabase_service()
        config = PERIODOS[periodo]

        # Constroi o timestamp de inicio do periodo na timezone do Lazaro
        # Ex: 2026-02-20 08:00:00-04:00 para manha
        hora_inicio = config["hora_inicio"]
        dt_inicio = datetime(
            data.year, data.month, data.day,
            hora_inicio.hour, hora_inicio.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        hora_fim = config["hora_fim"]
        dt_fim = datetime(
            data.year, data.month, data.day,
            hora_fim.hour, hora_fim.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        # Busca agendamentos de manutencao no slot especifico
        # Slot ocupado = existe registro com:
        #   - mesmo agent_id
        #   - service_name = 'manutencao_preventiva'
        #   - scheduled_at = hora exata do inicio do periodo
        #   - status != 'cancelled' (valores: scheduled, confirmed, completed, no_show)
        response = supabase.client.from_("schedules").select(
            "id, scheduled_at, status"
        ).eq(
            "agent_id", agent_id
        ).eq(
            "service_name", SERVICE_NAME
        ).eq(
            "scheduled_at", dt_inicio.isoformat()
        ).neq(
            "status", "cancelled"
        ).execute()

        count = len(response.data) if response.data else 0

        if count > 0:
            logger.info(
                f"Slot {periodo} do dia {data} OCUPADO "
                f"(agent {agent_id}): {count} agendamento(s)"
            )
            return False

        logger.info(
            f"Slot {periodo} do dia {data} DISPONIVEL (agent {agent_id})"
        )
        return True

    except Exception as e:
        logger.error(
            f"Erro ao verificar slot {periodo} em {data}: {e}",
            exc_info=True
        )
        # Em caso de erro, retorna False (nao confirma slot por seguranca)
        return False


def listar_slots_disponiveis(
    data: date,
    agent_id: str = AGENT_ID_LAZARO,
) -> Dict[str, Any]:
    """
    Lista a disponibilidade dos slots de um dia.

    Args:
        data: Data a consultar (objeto date)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        Dict com:
            - manha: True se disponivel, False se ocupado
            - tarde: True se disponivel, False se ocupado
            - data: Data consultada (YYYY-MM-DD)
            - algum_disponivel: True se ao menos um slot esta livre
    """
    manha_ok = verificar_slot(data, "manha", agent_id)
    tarde_ok = verificar_slot(data, "tarde", agent_id)

    resultado = {
        "data": data.isoformat(),
        "manha": manha_ok,
        "tarde": tarde_ok,
        "algum_disponivel": manha_ok or tarde_ok,
    }

    logger.info(
        f"Slots em {data}: manha={'OK' if manha_ok else 'OCUPADO'}, "
        f"tarde={'OK' if tarde_ok else 'OCUPADO'}"
    )
    return resultado


def registrar_agendamento(
    data: date,
    periodo: str,
    contract_id: str,
    cliente_nome: str,
    telefone: str,
    agent_id: str = AGENT_ID_LAZARO,
) -> Dict[str, Any]:
    """
    Registra um agendamento de manutencao no slot especificado.

    Antes de registrar, verifica novamente se o slot ainda esta disponivel
    (prevencao de race condition).

    Args:
        data: Data do agendamento
        periodo: 'manha' ou 'tarde'
        contract_id: ID do contrato no Supabase
        cliente_nome: Nome do cliente
        telefone: Telefone do cliente (remote_jid)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        Dict com:
            - sucesso: True/False
            - agendamento_id: UUID do agendamento criado (se sucesso)
            - mensagem: Mensagem de status
            - slot_ocupado: True se o slot ja estava ocupado
    """
    if periodo not in PERIODOS:
        return {
            "sucesso": False,
            "agendamento_id": None,
            "mensagem": f"Periodo invalido: '{periodo}'. Use 'manha' ou 'tarde'.",
            "slot_ocupado": False,
        }

    try:
        # Verificacao dupla - evita race condition
        disponivel = verificar_slot(data, periodo, agent_id)
        if not disponivel:
            logger.warning(
                f"Tentativa de agendamento em slot ocupado: "
                f"{data} {periodo} (agent {agent_id})"
            )
            return {
                "sucesso": False,
                "agendamento_id": None,
                "mensagem": (
                    f"O slot de {PERIODOS[periodo]['label']} "
                    f"em {data.strftime('%d/%m/%Y')} ja esta ocupado."
                ),
                "slot_ocupado": True,
            }

        config = PERIODOS[periodo]
        hora_inicio = config["hora_inicio"]
        hora_fim = config["hora_fim"]

        dt_inicio = datetime(
            data.year, data.month, data.day,
            hora_inicio.hour, hora_inicio.minute,
            tzinfo=TIMEZONE_LAZARO
        )
        dt_fim = datetime(
            data.year, data.month, data.day,
            hora_fim.hour, hora_fim.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        supabase = get_supabase_service()

        registro = {
            "agent_id": agent_id,
            "remote_jid": telefone,
            "customer_name": cliente_nome,
            "scheduled_at": dt_inicio.isoformat(),
            "ends_at": dt_fim.isoformat(),
            "service_name": SERVICE_NAME,
            "status": "scheduled",
            "notes": f"contract_id={contract_id} | periodo={periodo}",
        }

        response = supabase.client.from_("schedules").insert(registro).execute()

        if not response.data or len(response.data) == 0:
            logger.error(
                f"Falha ao inserir agendamento no banco: {response}"
            )
            return {
                "sucesso": False,
                "agendamento_id": None,
                "mensagem": "Erro ao registrar agendamento no banco de dados.",
                "slot_ocupado": False,
            }

        agendamento_id = response.data[0]["id"]
        logger.info(
            f"Agendamento registrado: {agendamento_id} | "
            f"{data} {periodo} | {cliente_nome} | contract={contract_id}"
        )

        return {
            "sucesso": True,
            "agendamento_id": agendamento_id,
            "mensagem": (
                f"Manutencao agendada para {data.strftime('%d/%m/%Y')} "
                f"no periodo da {PERIODOS[periodo]['label']}."
            ),
            "slot_ocupado": False,
        }

    except Exception as e:
        logger.error(
            f"Erro ao registrar agendamento {data} {periodo}: {e}",
            exc_info=True
        )
        return {
            "sucesso": False,
            "agendamento_id": None,
            "mensagem": f"Erro interno ao registrar agendamento: {str(e)}",
            "slot_ocupado": False,
        }


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 4: apps/ia/app/services/whatsapp_api.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
UazapiService - Servico de integracao com UAZAPI para WhatsApp.

Este servico gerencia:
- Envio de mensagens de texto
- Envio de mensagens de midia (imagem, audio, video, documento)
- Marcacao de mensagens como lidas
- Verificacao de status da instancia
- Typing indicators (digitando...)
"""

import asyncio
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Union

import httpx

from app.config import settings

# Configurar logging
logger = logging.getLogger(__name__)


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class MediaType(str, Enum):
    """Tipos de midia suportados pela UAZAPI."""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"


class MessageResponse(TypedDict):
    """Resposta de envio de mensagem."""
    success: bool
    message_id: Optional[str]
    error: Optional[str]


class InstanceStatus(TypedDict):
    """Status da instancia UAZAPI."""
    connected: bool
    phone_number: Optional[str]
    instance_id: str
    status: str
    battery: Optional[int]
    plugged: Optional[bool]


class SendTextPayload(TypedDict):
    """Payload para envio de texto."""
    phone: str
    message: str


class SendMediaPayload(TypedDict, total=False):
    """Payload para envio de midia."""
    phone: str
    media: str  # URL da midia
    caption: Optional[str]
    type: str  # image, audio, video, document


class ChunkedSendResult(TypedDict):
    """Resultado agregado do envio de mensagem chunked."""
    all_success: bool
    success_count: int
    total_chunks: int
    failed_chunks: List[int]
    results: List[MessageResponse]
    first_error: Optional[str]


# ============================================================================
# UAZAPI SERVICE
# ============================================================================

class UazapiService:
    """
    Servico para integracao com UAZAPI (WhatsApp API).

    Gerencia:
    - Envio de mensagens (texto e midia)
    - Leitura de mensagens
    - Status da instancia
    - Typing indicators

    Exemplo de uso:
        service = UazapiService()
        await service.send_text_message("5511999999999", "Ola!")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0
    ):
        """
        Inicializa o cliente UAZAPI.

        Args:
            base_url: URL base da API UAZAPI (default: settings.uazapi_base_url)
            api_key: API key para autenticacao (default: settings.uazapi_api_key)
            timeout: Timeout para requisicoes em segundos (default: 30)
        """
        self.base_url = (base_url or settings.uazapi_base_url).rstrip("/")
        self.api_key = api_key or settings.uazapi_api_key
        self.timeout = timeout

        if not self.base_url:
            raise ValueError(
                "UAZAPI_BASE_URL e obrigatorio. "
                "Defina a variavel de ambiente ou passe como parametro."
            )

        if not self.api_key:
            raise ValueError(
                "UAZAPI_API_KEY e obrigatorio. "
                "Defina a variavel de ambiente ou passe como parametro."
            )

        # Headers padrao para todas as requisicoes
        # UAZAPI usa header 'token' para autenticacao (nao Bearer)
        self._headers = {
            "token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.info(f"UazapiService inicializado com base_url: {self.base_url}")

    # ========================================================================
    # HTTP CLIENT
    # ========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa uma requisicao HTTP para a UAZAPI.

        Args:
            method: Metodo HTTP (GET, POST, PUT, DELETE)
            endpoint: Endpoint da API (sem a base_url)
            data: Dados para enviar no body (JSON)
            params: Parametros de query string

        Returns:
            Resposta da API como dicionario

        Raises:
            httpx.HTTPStatusError: Se a resposta for um erro HTTP
            httpx.RequestError: Se houver erro de conexao
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        logger.debug(f"UAZAPI Request: {method} {url}")
        if data:
            logger.debug(f"UAZAPI Payload: {data}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    params=params
                )

                # Log da resposta
                logger.debug(f"UAZAPI Response: {response.status_code}")

                # Levantar excecao para erros HTTP
                response.raise_for_status()

                # Tentar parsear JSON
                try:
                    return response.json()
                except Exception:
                    # Algumas respostas podem nao ser JSON
                    return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"UAZAPI HTTP Error: {e.response.status_code} - {e.response.text}"
                )
                raise

            except httpx.RequestError as e:
                logger.error(f"UAZAPI Request Error: {e}")
                raise

    async def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao GET."""
        return await self._request("GET", endpoint, params=params)

    async def _post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao POST."""
        return await self._request("POST", endpoint, data=data)

    async def _put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao PUT."""
        return await self._request("PUT", endpoint, data=data)

    # ========================================================================
    # PHONE NUMBER FORMATTING
    # ========================================================================

    def _format_phone(self, phone: str) -> str:
        """
        Formata o numero de telefone para o padrao UAZAPI.

        Remove caracteres especiais e adiciona codigo do pais se necessario.

        Args:
            phone: Numero de telefone (pode conter @s.whatsapp.net, @lid, etc)

        Returns:
            Numero formatado (apenas digitos)
        """
        # Remover sufixos do WhatsApp
        clean = phone.replace("@s.whatsapp.net", "").replace("@lid", "")

        # Remover caracteres nao-numericos
        clean = "".join(filter(str.isdigit, clean))

        # Adicionar codigo do Brasil se necessario
        if len(clean) == 10 or len(clean) == 11:
            clean = f"55{clean}"

        return clean

    # ========================================================================
    # SEND MESSAGES
    # ========================================================================

    async def send_text_message(
        self,
        phone: str,
        text: str,
        delay: Optional[int] = None,
        link_preview: bool = True
    ) -> MessageResponse:
        """
        Envia uma mensagem de texto via WhatsApp com retry para erros transientes.

        Args:
            phone: Numero de telefone do destinatario
            text: Texto da mensagem
            delay: Delay em milissegundos antes de enviar (simula digitacao)
            link_preview: Se deve mostrar preview de links (default: True)

        Returns:
            MessageResponse com status do envio

        Retry Policy:
            - 3 tentativas com backoff 1s, 2s, 4s
            - Apenas para erros transientes: timeout, 500, 502, 503, 504, connection error
            - NÃO faz retry para: 401, 400, 403, 404 (erros permanentes)

        Example:
            response = await service.send_text_message(
                phone="5511999999999",
                text="Ola! Como posso ajudar?"
            )
        """
        MAX_RETRIES = 3
        BACKOFF_DELAYS = [1.0, 2.0, 4.0]
        RETRIABLE_STATUS_CODES = {500, 502, 503, 504, 429}

        formatted_phone = self._format_phone(phone)

        # UAZAPI v2 usa 'number' e 'text' (nao 'phone' e 'message')
        payload: Dict[str, Any] = {
            "number": formatted_phone,
            "text": text,
            "linkPreview": link_preview,
        }

        if delay:
            payload["delay"] = delay

        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                if attempt > 0:
                    logger.info(f"[UAZAPI RETRY] Tentativa {attempt + 1}/{MAX_RETRIES + 1} para {formatted_phone}")

                logger.debug(f"[UAZAPI] Enviando texto para {formatted_phone}")
                logger.debug(f"[UAZAPI] URL: {self.base_url}/send/text")

                response = await self._post("/send/text", payload)

                logger.debug(f"[UAZAPI] Resposta: {response}")

                # Extrair message_id da resposta
                message_id = None
                if isinstance(response, dict):
                    message_id = response.get("key", {}).get("id") or response.get("id")

                logger.info(f"Mensagem enviada com sucesso. ID: {message_id}")

                return {
                    "success": True,
                    "message_id": message_id,
                    "error": None
                }

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_msg = f"HTTP {status_code}: {e.response.text}"
                last_error = error_msg

                # Verificar se é erro retriable
                if status_code in RETRIABLE_STATUS_CODES:
                    if attempt < MAX_RETRIES:
                        delay_seconds = BACKOFF_DELAYS[attempt]
                        logger.warning(
                            f"[UAZAPI RETRY] Erro transiente {status_code} para {formatted_phone}. "
                            f"Aguardando {delay_seconds}s antes de retry..."
                        )
                        await asyncio.sleep(delay_seconds)
                        continue
                    else:
                        logger.error(
                            f"[UAZAPI SEND FAIL] phone={formatted_phone} tentativas={MAX_RETRIES + 1} "
                            f"erro={status_code} (esgotou retries)"
                        )
                else:
                    # Erro permanente (401, 400, 403, 404) - não fazer retry
                    logger.error(
                        f"[UAZAPI SEND FAIL] phone={formatted_phone} erro_permanente={status_code} "
                        f"(sem retry para este tipo de erro)"
                    )
                    return {
                        "success": False,
                        "message_id": None,
                        "error": error_msg
                    }

            except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as e:
                error_msg = f"Connection error: {type(e).__name__}: {str(e)}"
                last_error = error_msg

                if attempt < MAX_RETRIES:
                    delay_seconds = BACKOFF_DELAYS[attempt]
                    logger.warning(
                        f"[UAZAPI RETRY] Erro de conexão para {formatted_phone}. "
                        f"Aguardando {delay_seconds}s antes de retry..."
                    )
                    await asyncio.sleep(delay_seconds)
                    continue
                else:
                    logger.error(
                        f"[UAZAPI SEND FAIL] phone={formatted_phone} tentativas={MAX_RETRIES + 1} "
                        f"erro=connection_error (esgotou retries)"
                    )

            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"[UAZAPI SEND FAIL] phone={formatted_phone} erro_inesperado={error_msg}")
                # Erro desconhecido - não fazer retry
                return {
                    "success": False,
                    "message_id": None,
                    "error": error_msg
                }

        # Se chegou aqui, esgotou todas as tentativas
        return {
            "success": False,
            "message_id": None,
            "error": last_error or "Esgotou tentativas de envio"
        }

    async def send_typing(
        self,
        phone: str,
        duration: int = 3000
    ) -> bool:
        """
        Envia indicador de digitacao (typing...).

        Args:
            phone: Numero de telefone do destinatario
            duration: Duracao em milissegundos (default: 3000)

        Returns:
            True se enviado com sucesso, False caso contrario
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /message/presence com 'presence' e 'delay'
            payload = {
                "number": formatted_phone,
                "presence": "composing",
                "delay": duration,
            }

            logger.debug(f"[UAZAPI] Enviando typing para {formatted_phone}")
            logger.debug(f"[UAZAPI] URL: {self.base_url}/message/presence")
            logger.debug(f"[UAZAPI] Payload: {payload}")

            response = await self._post("/message/presence", payload)
            logger.debug(f"[UAZAPI] Typing resposta: {response}")

            return True

        except Exception as e:
            logger.error(f"Erro ao enviar typing: {e}")
            return False


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 5: apps/ia/app/utils/dias_uteis.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
Business Days Utility - Calculo de dias uteis considerando feriados brasileiros.

Portado de agnes-agent/src/utils/business-days.ts
"""

from datetime import date, datetime, timedelta
from typing import List

import pytz

# Timezone de Brasilia
TZ_BRASILIA = pytz.timezone("America/Sao_Paulo")

# Feriados nacionais fixos do Brasil (mes, dia)
FIXED_HOLIDAYS = [
    (1, 1),    # Confraternizacao Universal
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independencia do Brasil
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamacao da Republica
    (12, 25),  # Natal
]


def get_easter_date(year: int) -> date:
    """Calcula a data da Pascoa usando o algoritmo de Meeus/Jones/Butcher."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_mobile_holidays(year: int) -> List[date]:
    """Retorna feriados moveis baseados na Pascoa."""
    easter = get_easter_date(year)
    holidays = []

    # Carnaval (segunda e terca antes da Quarta de Cinzas)
    carnival_monday = easter - timedelta(days=48)
    carnival_tuesday = easter - timedelta(days=47)
    holidays.extend([carnival_monday, carnival_tuesday])

    # Sexta-feira Santa (2 dias antes da Pascoa)
    good_friday = easter - timedelta(days=2)
    holidays.append(good_friday)

    # Corpus Christi (60 dias apos a Pascoa)
    corpus_christi = easter + timedelta(days=60)
    holidays.append(corpus_christi)

    return holidays


def get_holidays_for_year(year: int) -> List[date]:
    """Retorna todos os feriados de um ano especifico."""
    holidays = []

    # Feriados fixos
    for month, day in FIXED_HOLIDAYS:
        holidays.append(date(year, month, day))

    # Feriados moveis
    holidays.extend(get_mobile_holidays(year))

    return holidays


def is_holiday(d: date) -> bool:
    """Verifica se uma data e feriado."""
    holidays = get_holidays_for_year(d.year)
    return d in holidays


def is_weekend(d: date) -> bool:
    """Verifica se uma data e fim de semana (sabado ou domingo)."""
    return d.weekday() in (5, 6)  # 5=sabado, 6=domingo


def is_business_day(d: date) -> bool:
    """Verifica se uma data e dia util (nao e fim de semana nem feriado)."""
    return not is_weekend(d) and not is_holiday(d)


def add_business_days(d: date, days: int) -> date:
    """Adiciona N dias uteis a uma data."""
    result = d
    remaining = abs(days)
    direction = 1 if days >= 0 else -1

    while remaining > 0:
        result += timedelta(days=direction)
        if is_business_day(result):
            remaining -= 1

    return result


def subtract_business_days(d: date, days: int) -> date:
    """Subtrai N dias uteis de uma data."""
    return add_business_days(d, -days)


def anticipate_to_friday(d: date) -> date:
    """
    Antecipa data para sexta-feira se cair em fim de semana ou feriado.
    Usado para enviar notificacoes antes do vencimento quando este cai no final de semana.
    """
    result = d
    while not is_business_day(result):
        result -= timedelta(days=1)
    return result


def get_today_brasilia() -> date:
    """Retorna hoje no fuso horario de Brasilia (GMT-3)."""
    now = datetime.now(TZ_BRASILIA)
    return now.date()


def get_now_brasilia() -> datetime:
    """Retorna agora no fuso horario de Brasilia."""
    return datetime.now(TZ_BRASILIA)


def format_date(d: date) -> str:
    """Formata data no padrao YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")


def format_date_br(d: date) -> str:
    """Formata data no padrao DD/MM/YYYY."""
    return d.strftime("%d/%m/%Y")


def parse_date(date_str: str) -> date:
    """Parse de data no formato YYYY-MM-DD."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def is_business_hours(hour_start: int = 8, hour_end: int = 20) -> bool:
    """Verifica se estamos em horario comercial (Brasilia)."""
    now = get_now_brasilia()
    return hour_start <= now.hour < hour_end


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 6: apps/ia/app/tools/manutencao.py
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
Tools de Manutenção - Identificação de Equipamentos (Lázaro/Alugar Ar)

Este módulo implementa:
- identificar_equipamento: Detecta qual equipamento do cliente precisa de manutenção
- analisar_foto_equipamento: Usa Gemini Vision para identificar equipamento na foto

Contexto:
- 82% dos clientes têm apenas 1 equipamento (trivial)
- 9% têm múltiplos de marcas diferentes (pergunta marca)
- 9% têm múltiplos mesma marca (pergunta local ou foto)

Integração:
- Busca dados de contract_details no Supabase
- Usa Gemini Vision para análise de fotos
- Retorna informações estruturadas para a ANA responder
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import date, datetime

import google.generativeai as genai

from app.config import settings
from app.services.supabase import get_supabase_service
from app.services.manutencao_slots import (
    listar_slots_disponiveis,
    registrar_agendamento,
    verificar_slot,
)

logger = logging.getLogger(__name__)


# ============================================================================
# TOOL: identificar_equipamento
# ============================================================================

async def identificar_equipamento(
    telefone: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Identifica qual equipamento do cliente precisa de manutenção.

    Lógica de identificação:
    1. Busca contratos do cliente pelo telefone
    2. Se 1 equipamento → retorna direto (82% dos casos)
    3. Se múltiplos com marcas diferentes → retorna lista para perguntar
    4. Se múltiplos mesma marca → retorna lista para perguntar local/BTUs

    Args:
        telefone: Telefone do cliente (formato: 5565999999999)
        agent_id: ID do agente (default: Lázaro)

    Returns:
        dict:
            - cenario: "unico" | "multiplos_marcas" | "multiplos_mesmo"
            - equipamentos: Lista de equipamentos encontrados
            - pergunta_sugerida: Texto sugerido para a ANA perguntar (opcional)
            - total: Quantidade de equipamentos
            - sucesso: True/False
            - mensagem: Mensagem de status
    """
    try:
        logger.info(f"Identificando equipamento para telefone {telefone}")

        supabase = get_supabase_service()

        # Limpar telefone (apenas números)
        telefone_clean = telefone.replace("+", "").replace("-", "").replace(" ", "")

        # Buscar contratos do cliente via join com asaas_clientes
        response = supabase.client.from_('contract_details').select(
            """
            id,
            customer_id,
            equipamentos,
            endereco_instalacao,
            asaas_clientes!customer_id(mobile_phone)
            """
        ).eq('agent_id', agent_id).execute()

        if not response.data:
            logger.warning(f"Nenhum contrato encontrado para agent {agent_id}")
            return {
                "cenario": "sem_equipamento",
                "equipamentos": [],
                "total": 0,
                "sucesso": False,
                "mensagem": "Não encontrei equipamentos cadastrados para este telefone."
            }

        # Filtrar contratos por telefone
        contratos_cliente = []
        for contrato in response.data:
            # Verificar se o contrato tem cliente associado
            if contrato.get("asaas_clientes") and len(contrato["asaas_clientes"]) > 0:
                cliente_phone = contrato["asaas_clientes"][0].get("mobile_phone", "")
                cliente_phone_clean = cliente_phone.replace("+", "").replace("-", "").replace(" ", "")

                if cliente_phone_clean == telefone_clean:
                    contratos_cliente.append(contrato)

        if not contratos_cliente:
            logger.info(f"Nenhum contrato encontrado para telefone {telefone}")
            return {
                "cenario": "sem_equipamento",
                "equipamentos": [],
                "total": 0,
                "sucesso": False,
                "mensagem": "Não encontrei equipamentos cadastrados para este telefone."
            }

        # Consolidar equipamentos de todos os contratos
        todos_equipamentos = []
        for contrato in contratos_cliente:
            equipamentos = contrato.get("equipamentos", [])
            endereco = contrato.get("endereco_instalacao", "")

            if isinstance(equipamentos, list):
                for equip in equipamentos:
                    if isinstance(equip, dict):
                        equip_info = {
                            "marca": equip.get("marca", "Não informado"),
                            "btus": equip.get("btus", 0),
                            "tipo": equip.get("tipo", "Split"),
                            "local": equip.get("local", endereco),
                            "contract_id": contrato["id"]
                        }
                        todos_equipamentos.append(equip_info)

        total = len(todos_equipamentos)

        # ===================================================================
        # CENÁRIO 1: Apenas 1 equipamento (82% dos casos)
        # ===================================================================
        if total == 1:
            equip = todos_equipamentos[0]
            logger.info(f"Cenário ÚNICO: {equip['marca']} {equip['btus']} BTUs")

            return {
                "cenario": "unico",
                "equipamentos": todos_equipamentos,
                "total": 1,
                "sucesso": True,
                "mensagem": f"Encontrei 1 equipamento: {equip['marca']} {equip['btus']} BTUs ({equip['tipo']}). É esse?",
                "equipamento_confirmado": equip
            }

        # ===================================================================
        # CENÁRIO 2: Múltiplos equipamentos
        # ===================================================================
        if total > 1:
            # Agrupar por marca
            marcas = set(e["marca"] for e in todos_equipamentos)

            # Se marcas DIFERENTES → perguntar marca
            if len(marcas) > 1:
                marcas_lista = ", ".join(sorted(marcas))
                logger.info(f"Cenário MÚLTIPLOS MARCAS: {marcas_lista}")

                return {
                    "cenario": "multiplos_marcas",
                    "equipamentos": todos_equipamentos,
                    "total": total,
                    "sucesso": True,
                    "mensagem": f"Vi que você tem {total} equipamentos de marcas diferentes. Qual deles está com problema?",
                    "pergunta_sugerida": f"É o {marcas_lista}?"
                }

            # Se MESMA marca → perguntar local ou BTUs
            logger.info(f"Cenário MÚLTIPLOS MESMA MARCA: {total} equipamentos")

            # Construir lista de opções
            opcoes = []
            for i, equip in enumerate(todos_equipamentos, 1):
                local = equip.get("local", "")
                btus = equip.get("btus", 0)

                if local:
                    opcoes.append(f"{i}. {equip['marca']} {btus} BTUs ({local})")
                else:
                    opcoes.append(f"{i}. {equip['marca']} {btus} BTUs")

            lista_opcoes = "\n".join(opcoes)

            return {
                "cenario": "multiplos_mesmo",
                "equipamentos": todos_equipamentos,
                "total": total,
                "sucesso": True,
                "mensagem": f"Vi que você tem {total} equipamentos {todos_equipamentos[0]['marca']}. Qual deles?",
                "pergunta_sugerida": f"Opções:\n{lista_opcoes}\n\nPode me dizer qual?"
            }

        # ===================================================================
        # FALLBACK: Nenhum equipamento
        # ===================================================================
        logger.warning(f"Nenhum equipamento encontrado para {telefone}")
        return {
            "cenario": "sem_equipamento",
            "equipamentos": [],
            "total": 0,
            "sucesso": False,
            "mensagem": "Não encontrei equipamentos cadastrados. Pode me informar a marca e o modelo?"
        }

    except Exception as e:
        logger.error(f"Erro ao identificar equipamento: {e}", exc_info=True)
        return {
            "cenario": "erro",
            "equipamentos": [],
            "total": 0,
            "sucesso": False,
            "mensagem": f"Erro ao buscar equipamentos: {str(e)}"
        }


# ============================================================================
# TOOL: verificar_disponibilidade_manutencao
# ============================================================================

async def verificar_disponibilidade_manutencao(
    data: str,
    periodo: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Verifica se existe slot disponivel para manutencao em uma data e periodo.

    Args:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        periodo: 'manha' ou 'tarde'
        agent_id: ID do agente (default: Lazaro)

    Returns:
        dict:
            - disponivel: True se o slot esta livre, False se ocupado
            - data: Data consultada (YYYY-MM-DD)
            - periodo: Periodo consultado
            - label_periodo: Descricao amigavel do periodo
            - mensagem: Mensagem descritiva
            - alternativas: Quais outros slots estao disponiveis no mesmo dia
    """
    try:
        logger.info(f"Verificando disponibilidade: {data} {periodo}")

        # Validar periodo
        if periodo not in ("manha", "tarde"):
            return {
                "disponivel": False,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": "Periodo invalido. Use 'manha' (08h-12h) ou 'tarde' (14h-18h).",
                "alternativas": [],
            }

        # Converter string para date
        try:
            data_obj = date.fromisoformat(data)
        except ValueError:
            return {
                "disponivel": False,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "alternativas": [],
            }

        # Verificar slot solicitado
        disponivel = verificar_slot(data_obj, periodo, agent_id)

        # Verificar alternativas no mesmo dia
        todos_slots = listar_slots_disponiveis(data_obj, agent_id)
        alternativas = []
        for p in ("manha", "tarde"):
            if p != periodo and todos_slots.get(p):
                label = "Manhã (08h-12h)" if p == "manha" else "Tarde (14h-18h)"
                alternativas.append({"periodo": p, "label": label})

        labels = {"manha": "Manhã (08h-12h)", "tarde": "Tarde (14h-18h)"}
        label_periodo = labels.get(periodo, periodo)
        data_br = data_obj.strftime("%d/%m/%Y")

        if disponivel:
            mensagem = (
                f"Otimo! O periodo da {label_periodo} em {data_br} "
                f"esta disponivel para manutencao."
            )
        else:
            if alternativas:
                alts_str = " ou ".join(a["label"] for a in alternativas)
                mensagem = (
                    f"O periodo da {label_periodo} em {data_br} ja esta ocupado. "
                    f"Mas ainda temos disponibilidade: {alts_str}."
                )
            else:
                mensagem = (
                    f"O dia {data_br} esta totalmente ocupado. "
                    f"Por favor, escolha outra data."
                )

        return {
            "disponivel": disponivel,
            "data": data,
            "periodo": periodo,
            "label_periodo": label_periodo,
            "mensagem": mensagem,
            "alternativas": alternativas,
        }

    except Exception as e:
        logger.error(f"Erro ao verificar disponibilidade: {e}", exc_info=True)
        return {
            "disponivel": False,
            "data": data,
            "periodo": periodo,
            "label_periodo": periodo,
            "mensagem": f"Erro ao verificar disponibilidade: {str(e)}",
            "alternativas": [],
        }


# ============================================================================
# TOOL: confirmar_agendamento_manutencao
# ============================================================================

async def confirmar_agendamento_manutencao(
    data: str,
    periodo: str,
    contract_id: str,
    cliente_nome: str,
    telefone: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Confirma e registra o agendamento de manutencao no slot solicitado.

    Deve ser chamada APOS verificar_disponibilidade_manutencao retornar
    disponivel=True e o cliente confirmar o horario.

    Args:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        periodo: 'manha' ou 'tarde'
        contract_id: ID do contrato no Supabase
        cliente_nome: Nome do cliente
        telefone: Telefone do cliente (ex: 5565999999999)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        dict:
            - sucesso: True se agendado, False se falhou
            - agendamento_id: UUID do registro criado (se sucesso)
            - data: Data agendada (YYYY-MM-DD)
            - periodo: Periodo agendado
            - label_periodo: Descricao amigavel
            - mensagem: Mensagem de confirmacao ou erro
            - slot_ocupado: True se o slot ja estava ocupado no momento do registro
    """
    try:
        logger.info(
            f"Confirmando agendamento: {data} {periodo} | "
            f"cliente={cliente_nome} | contract={contract_id}"
        )

        # Validar periodo
        if periodo not in ("manha", "tarde"):
            return {
                "sucesso": False,
                "agendamento_id": None,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": "Periodo invalido. Use 'manha' ou 'tarde'.",
                "slot_ocupado": False,
            }

        # Converter string para date
        try:
            data_obj = date.fromisoformat(data)
        except ValueError:
            return {
                "sucesso": False,
                "agendamento_id": None,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "slot_ocupado": False,
            }

        # Registrar agendamento (inclui verificacao dupla interna)
        resultado = registrar_agendamento(
            data=data_obj,
            periodo=periodo,
            contract_id=contract_id,
            cliente_nome=cliente_nome,
            telefone=telefone,
            agent_id=agent_id,
        )

        # Atualizar contract_details com status 'scheduled' se agendamento foi bem-sucedido
        if resultado.get("sucesso") and contract_id:
            try:
                supabase = get_supabase_service()
                supabase.client.table("contract_details").update({
                    "maintenance_status": "scheduled",
                    "agendamento_confirmado_at": datetime.utcnow().isoformat(),
                }).eq("id", contract_id).execute()
                logger.info(f"[MANUT] Contract {contract_id} atualizado para 'scheduled'")
            except Exception as e:
                logger.error(f"[MANUT] Erro ao atualizar contract_details: {e}")

        labels = {"manha": "Manhã (08h-12h)", "tarde": "Tarde (14h-18h)"}
        label_periodo = labels.get(periodo, periodo)

        return {
            "sucesso": resultado["sucesso"],
            "agendamento_id": resultado.get("agendamento_id"),
            "data": data,
            "periodo": periodo,
            "label_periodo": label_periodo,
            "mensagem": resultado["mensagem"],
            "slot_ocupado": resultado.get("slot_ocupado", False),
        }

    except Exception as e:
        logger.error(f"Erro ao confirmar agendamento: {e}", exc_info=True)
        return {
            "sucesso": False,
            "agendamento_id": None,
            "data": data,
            "periodo": periodo,
            "label_periodo": periodo,
            "mensagem": f"Erro interno ao confirmar agendamento: {str(e)}",
            "slot_ocupado": False,
        }


MAINTENANCE_FUNCTION_DECLARATIONS = [
    {
        "name": "identificar_equipamento",
        "description": "Identifica qual equipamento de ar-condicionado do cliente precisa de manutenção. Use quando o cliente reportar problema ou solicitar agendamento de manutenção.",
        "parameters": {
            "type": "object",
            "properties": {
                "telefone": {
                    "type": "string",
                    "description": "Telefone do cliente (formato: 5565999999999)"
                }
            },
            "required": ["telefone"]
        }
    },
    {
        "name": "verificar_disponibilidade_manutencao",
        "description": (
            "Verifica se existe slot disponivel para agendamento de manutencao preventiva "
            "em uma data e periodo especificos. "
            "SEMPRE use esta tool antes de confirmar um agendamento. "
            "Se o slot estiver ocupado, informe o cliente e sugira as alternativas retornadas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Data desejada no formato YYYY-MM-DD (ex: 2026-02-20)"
                },
                "periodo": {
                    "type": "string",
                    "enum": ["manha", "tarde"],
                    "description": (
                        "Periodo desejado: 'manha' (08h-12h) ou 'tarde' (14h-18h). "
                        "Interprete 'de manha', 'antes do meio dia', 'cedo' como 'manha'. "
                        "Interprete 'de tarde', 'depois do almoco', 'a tarde' como 'tarde'."
                    )
                }
            },
            "required": ["data", "periodo"]
        }
    },
    {
        "name": "confirmar_agendamento_manutencao",
        "description": (
            "Confirma e registra o agendamento de manutencao preventiva. "
            "Use SOMENTE apos verificar_disponibilidade_manutencao retornar disponivel=True "
            "e o cliente confirmar o dia e periodo. "
            "Apos confirmar com sucesso, informe o cliente e transfira para o departamento."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Data do agendamento no formato YYYY-MM-DD (ex: 2026-02-20)"
                },
                "periodo": {
                    "type": "string",
                    "enum": ["manha", "tarde"],
                    "description": "Periodo: 'manha' (08h-12h) ou 'tarde' (14h-18h)"
                },
                "contract_id": {
                    "type": "string",
                    "description": "ID do contrato do cliente no Supabase (UUID)"
                },
                "cliente_nome": {
                    "type": "string",
                    "description": "Nome completo do cliente"
                },
                "telefone": {
                    "type": "string",
                    "description": "Telefone do cliente no formato WhatsApp (ex: 5565999999999)"
                }
            },
            "required": ["data", "periodo", "contract_id", "cliente_nome", "telefone"]
        }
    }
]


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  ARQUIVO 7: apps/ia/app/main.py - TRECHOS RELEVANTES
#
# ##############################################################################
# ##############################################################################
# ##############################################################################

"""
Trechos do main.py relacionados a manutenção preventiva.
"""

# =============================================================================
# IMPORTS (linha 46)
# =============================================================================

# from app.jobs.notificar_manutencoes import run_maintenance_notifier_job, is_maintenance_notifier_running, _force_run_maintenance_notifier


# =============================================================================
# SCHEDULER - Configuração do job (linhas 428-437)
# =============================================================================

# scheduler.add_job(
#     run_maintenance_notifier_job,
#     CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Cuiaba"),
#     id="maintenance_notifier",
#     name="Maintenance Notifier Job (ANA)",
#     replace_existing=True,
# )


# =============================================================================
# ENDPOINTS - APIs de manutenção (linhas 1595-1720)
# =============================================================================

# @app.post("/api/jobs/maintenance-notifier/run", tags=["jobs"])
# async def run_maintenance_notifier_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
#     """
#     Executa o job de notificacao de manutencao preventiva manualmente.
#     Respeita verificacoes de dia util e horario comercial.
#     """
#     if is_maintenance_notifier_running():
#         return {"status": "error", "message": "Job ja esta em execucao"}
#
#     background_tasks.add_task(run_maintenance_notifier_job)
#     return {"status": "started", "message": "Maintenance notifier job iniciado em background"}


# @app.post("/api/jobs/maintenance-notifier/run-force", tags=["jobs"])
# async def run_maintenance_notifier_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
#     """
#     Executa o job de notificacao de manutencao FORCANDO execucao.
#     Ignora verificacoes de horario/dia util. APENAS PARA DEBUG/TESTES.
#     """
#     if is_maintenance_notifier_running():
#         return {"status": "error", "message": "Job ja esta em execucao"}
#
#     background_tasks.add_task(_force_run_maintenance_notifier)
#     return {"status": "started", "message": "Maintenance notifier job FORCADO iniciado em background"}


# @app.get("/api/jobs/maintenance-notifier/status", tags=["jobs"])
# async def maintenance_notifier_status() -> Dict[str, Any]:
#     """Retorna o status do job de manutencao preventiva."""
#     return {
#         "running": is_maintenance_notifier_running(),
#         "scheduler_active": app_state.scheduler is not None,
#     }


# @app.get("/api/manutencao/slots", tags=["manutencao"])
# async def get_slots_manutencao(
#     data: str,
#     agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
# ) -> Dict[str, Any]:
#     """
#     Retorna a disponibilidade de slots de manutencao em uma data.
#     """
#     from datetime import date as date_type
#     from app.services.manutencao_slots import listar_slots_disponiveis
#
#     try:
#         data_obj = date_type.fromisoformat(data)
#     except ValueError:
#         return JSONResponse(
#             status_code=400,
#             content={"success": False, "error": f"Data invalida: '{data}'", "statusCode": 400}
#         )
#
#     slots = listar_slots_disponiveis(data_obj, agent_id)
#     return {"success": True, "data": slots}


# @app.get("/api/manutencao/slots/semana", tags=["manutencao"])
# async def get_slots_semana(
#     data_inicio: str,
#     agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
# ) -> Dict[str, Any]:
#     """
#     Retorna a disponibilidade de slots de manutencao para os proximos 7 dias.
#     """
#     ...


# ##############################################################################
# ##############################################################################
# ##############################################################################
#
#  FIM DO ARQUIVO CONSOLIDADO
#
# ##############################################################################
# ##############################################################################
# ##############################################################################
