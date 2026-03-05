"""
Billing Charge Job - Regua de cobranca automatizada via WhatsApp.

Envia lembretes antes do vencimento, no dia e apos vencimento.
Portado de agnes-agent/src/jobs/billing-charge.job.ts

Fluxo:
1. Busca agentes com asaas_api_key configurado
2. Para cada agente, busca cobrancas PENDING e OVERDUE no Supabase
3. Calcula dias ate/apos vencimento
4. Seleciona template adequado (D-2, D0, D+1..D+15)
5. Envia mensagem via WhatsApp (UAZAPI)
6. Registra envio no banco (billing_notifications)
"""

import logging
import re
import traceback
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.dispatch_logger import get_dispatch_logger
from app.services.gateway_pagamento import AsaasService, create_asaas_service
from app.services.leadbox import LeadboxService
from app.services.leadbox_push import QUEUE_BILLING, leadbox_push_silent
from app.services.redis import get_redis_service
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.core.utils.dias_uteis import (
    add_business_days,
    anticipate_to_friday,
    format_date,
    format_date_br,
    get_today_brasilia,
    is_business_day,
    is_business_hours,
    parse_date,
    subtract_business_days,
)

logger = logging.getLogger(__name__)

# Lock distribuído via Redis (TTL: 30 minutos)
BILLING_JOB_LOCK_KEY = "lock:billing_job:global"
BILLING_JOB_LOCK_TTL = 1800  # 30 minutos

# Status de pagamentos pagos (para pular)
PAID_STATUSES = {"RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"}

# Tipos de pagamento por cartao (skip PENDING, processar OVERDUE)
CARD_BILLING_TYPES = {"CREDIT_CARD", "DEBIT_CARD"}


# ============================================================================
# DEFAULT TEMPLATES
# ============================================================================

DEFAULT_MESSAGES = {
    # Lembrete antes do vencimento
    "reminder": (
        "Ola {nome}! Lembrete: sua fatura de {valor} vence em {vencimento}. "
        "Evite juros pagando em dia."
    ),
    # No dia do vencimento
    "dueDate": (
        "Ola {nome}! Hoje e o dia do vencimento da sua fatura de {valor}. "
        "Efetue o pagamento para evitar juros."
    ),
    # Generico vencido
    "overdue": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento} e esta "
        "ha {dias_atraso} dias em atraso. Regularize sua situacao."
    ),
    # D+1 a D+5 (gentil)
    "overdue1": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento}. "
        "Evite juros, regularize: {link}"
    ),
    # D+6 a D+10 (firme)
    "overdue2": (
        "Ola {nome}! Sua fatura de {valor} esta ha {dias_atraso} dias em atraso. "
        "Regularize agora: {link}"
    ),
    # D+11 a D+15 (urgente)
    "overdue3": (
        "Ola {nome}! URGENTE: Sua fatura de {valor} esta ha {dias_atraso} dias vencida. "
        "Ultimo aviso antes de medidas adicionais: {link}"
    ),
    # Consolidado - multiplas faturas
    "overdueConsolidated1": (
        "Ola {nome}! Voce tem {qtd} faturas em atraso, totalizando {total}. "
        "Evite juros, regularize sua situacao: {link}"
    ),
    "overdueConsolidated2": (
        "Ola {nome}! Voce tem {qtd} faturas vencidas, totalizando {total}. "
        "Regularize agora: {link}"
    ),
    "overdueConsolidated3": (
        "Ola {nome}! URGENTE: Voce tem {qtd} faturas vencidas, totalizando {total}. "
        "Ultimo aviso antes de medidas adicionais: {link}"
    ),
}


# ============================================================================
# API ASAAS - FETCH FUNCTIONS (NOVA ARQUITETURA)
# ============================================================================

# Configuracao de retry para chamadas a API Asaas
ASAAS_RETRY_CONFIG = {
    "max_retries": 2,
    "backoff_factor": 1.5,  # 1s, 1.5s
    "timeout": 30.0,
}


async def fetch_payments_from_asaas(
    asaas_service: AsaasService,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Busca pagamentos diretamente da API Asaas.
    Retorna (payments, source) onde source = 'api' ou 'error'.

    Args:
        asaas_service: Instancia do AsaasService
        status: "PENDING" ou "OVERDUE"
        due_date_start: Data inicio do filtro
        due_date_end: Data fim do filtro

    Returns:
        Tupla (lista de payments, source)
        - source = 'api' se sucesso
        - source = 'error' se falhou
    """
    try:
        # Filtros conforme documentacao Asaas
        params = {
            "status": status,
            "dueDate[ge]": due_date_start.strftime("%Y-%m-%d"),
            "dueDate[le]": due_date_end.strftime("%Y-%m-%d"),
            "offset": 0,
            "limit": 100,
        }

        all_payments = []
        page_count = 0
        max_pages = 10  # Safety: max 10 paginas (1000 payments)

        while True:
            _log(f"Buscando {status} da API Asaas (offset={params['offset']}, limit={params['limit']})")
            response = await asaas_service.list_payments(**params)

            data = response.get("data", [])
            all_payments.extend(data)

            has_more = response.get("hasMore", False)
            total_count = response.get("totalCount", 0)

            _log(f"API Asaas retornou {len(data)} pagamentos ({len(all_payments)}/{total_count} total)")

            if not has_more:
                break

            params["offset"] += params["limit"]
            page_count += 1

            if page_count >= max_pages:
                _log_warn(f"Limite de paginacao atingido ({max_pages} paginas) para {status}")
                break

        _log(f"Total de {len(all_payments)} pagamentos {status} buscados da API Asaas")
        return all_payments, "api"

    except Exception as e:
        _log_error(f"Erro ao buscar {status} da API Asaas: {e}")
        return [], "error"


async def fetch_payments_with_fallback(
    agent: Dict[str, Any],
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Tenta buscar da API Asaas. Se falhar, usa Supabase como fallback.
    Retorna (payments, source).

    Args:
        agent: Dicionario com dados do agente (id, asaas_api_key)
        status: "PENDING" ou "OVERDUE"
        due_date_start: Data inicio do filtro
        due_date_end: Data fim do filtro

    Returns:
        Tupla (lista de payments, source)
        - source = 'api' se veio da API Asaas
        - source = 'fallback' se veio do Supabase (API falhou)
    """
    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "unknown")

    # Tentar API Asaas primeiro
    asaas_api_key = agent.get("asaas_api_key")
    if not asaas_api_key:
        _log_warn(f"Agente {agent_name} sem asaas_api_key, usando fallback Supabase")
        payments = await _fetch_from_supabase_fallback(agent_id, status, due_date_start, due_date_end)
        return payments, "fallback"

    try:
        asaas_service = create_asaas_service(api_key=asaas_api_key)
        payments, source = await fetch_payments_from_asaas(
            asaas_service, status, due_date_start, due_date_end
        )

        if source == "api" and len(payments) >= 0:  # 0 ou mais e valido (pode nao ter cobrancas)
            _log(f"Buscou {len(payments)} {status} da API Asaas para {agent_name}")
            return payments, "api"
        else:
            raise Exception("API Asaas retornou erro ou resposta invalida")

    except Exception as e:
        _log_warn(f"API Asaas indisponivel para {agent_name}: {e}, usando fallback Supabase")

    # Fallback para Supabase
    payments = await _fetch_from_supabase_fallback(agent_id, status, due_date_start, due_date_end)
    return payments, "fallback"


async def _fetch_from_supabase_fallback(
    agent_id: str,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> List[Dict[str, Any]]:
    """
    Busca pagamentos do Supabase (cache).
    Funcao interna para fallback quando API Asaas falha.
    """
    try:
        if status == "PENDING":
            # Para PENDING, buscar apenas a data especifica (nao range)
            return await get_pending_payments_by_due_date(agent_id, due_date_start)
        else:  # OVERDUE
            return await get_overdue_payments(agent_id, due_date_start, due_date_end)
    except Exception as e:
        _log_error(f"Erro ao buscar {status} do Supabase (fallback): {e}")
        return []


async def sync_payments_to_cache(
    agent_id: str,
    payments: List[Dict[str, Any]],
    asaas_api_key: Optional[str] = None,
) -> None:
    """
    Sincroniza pagamentos da API Asaas para o cache Supabase.
    Roda em background (nao bloqueia envio de mensagens).

    IMPORTANTE: Preserva customer_name existente se API não retornar nome válido.
    A API /payments não retorna customerName, então precisamos resolver de outras fontes.

    Args:
        agent_id: ID do agente
        payments: Lista de payments da API Asaas
        asaas_api_key: Chave API do Asaas para buscar cliente (opcional)
    """
    if not payments:
        return

    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()

    # Criar serviço Asaas se temos a chave (para resolver nomes de clientes)
    asaas_service: Optional[AsaasService] = None
    if asaas_api_key:
        try:
            asaas_service = create_asaas_service(api_key=asaas_api_key)
        except Exception:
            pass  # Continua sem o serviço, usará banco como fallback

    synced_count = 0
    error_count = 0
    names_preserved = 0

    for payment in payments:
        try:
            payment_id = payment.get("id")
            if not payment_id:
                continue

            customer_id = payment.get("customer", "")
            api_customer_name = payment.get("customerName", "")

            # Resolver nome do cliente (FIX: API /payments não retorna customerName)
            resolved_name = await _resolve_customer_name_for_payment(
                supabase,
                asaas_service,
                payment_id,
                customer_id,
                api_customer_name,
            )

            # Montar dados para upsert
            data = {
                "id": payment_id,
                "agent_id": agent_id,
                "customer_id": customer_id,
                "value": payment.get("value", 0.0),
                "status": payment.get("status", ""),
                "billing_type": payment.get("billingType", ""),
                "due_date": payment.get("dueDate"),
                "invoice_url": payment.get("invoiceUrl"),
                "bank_slip_url": payment.get("bankSlipUrl"),
                "subscription_id": payment.get("subscription"),
                "last_synced_at": now,
                "sync_source": "api_sync",
                "updated_at": now,
            }

            # PROTEÇÃO: Só incluir customer_name se tiver nome válido
            # Se resolved_name é None, NÃO sobrescrever o valor existente
            if resolved_name is not None:
                data["customer_name"] = resolved_name
            else:
                names_preserved += 1

            supabase.client.table("asaas_cobrancas").upsert(data, on_conflict="id").execute()
            synced_count += 1

        except Exception as e:
            _log_error(f"Erro ao sincronizar payment {payment.get('id', 'unknown')} para cache: {e}")
            error_count += 1

    _log(f"Cache atualizado: {synced_count} payments sincronizados, {error_count} erros, {names_preserved} nomes preservados")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def mask_phone(phone: str) -> str:
    """Mascara telefone para logs (LGPD/GDPR compliance)."""
    if not phone or len(phone) < 8:
        return "****"
    # Mostra primeiros 4 e ultimos 4 digitos: 5566****4084
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


def mask_customer_name(name: str) -> str:
    """Mascara nome de cliente para logs (LGPD/GDPR compliance)."""
    if not name or len(name) < 3:
        return "***"
    # Mostra apenas primeira letra + asteriscos
    return name[0] + "*" * (len(name) - 1)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


# ============================================================================
# CUSTOMER NAME RESOLUTION (FIX: API /payments não retorna customerName)
# ============================================================================

INVALID_NAMES = {"", "Sem nome", "Desconhecido", "Cliente", "Cliente Asaas"}


def _is_valid_customer_name(name: Optional[str]) -> bool:
    """Verifica se o nome do cliente é válido (não vazio/placeholder)."""
    if not name:
        return False
    return name.strip() not in INVALID_NAMES


async def _resolve_customer_name_for_payment(
    supabase,
    asaas_service: Optional[AsaasService],
    payment_id: str,
    customer_id: str,
    api_customer_name: str = "",
) -> Optional[str]:
    """
    Resolve o nome do cliente para uma cobrança.

    Ordem de prioridade:
    1. Nome da API (se válido)
    2. Nome existente no banco (asaas_cobrancas)
    3. Nome na tabela de clientes (asaas_clientes)
    4. Busca na API do Asaas (/customers/{id})

    Retorna None se não conseguir resolver (para não sobrescrever valor existente).
    """
    # 1. Se API retornou nome válido, usar
    if _is_valid_customer_name(api_customer_name):
        return api_customer_name

    if not customer_id:
        return None

    # 2. Tentar do registro existente (mais rápido, preserva valor anterior)
    try:
        existing = (
            supabase.client.table("asaas_cobrancas")
            .select("customer_name")
            .eq("id", payment_id)
            .maybe_single()
            .execute()
        )
        if existing.data and _is_valid_customer_name(existing.data.get("customer_name")):
            return existing.data["customer_name"]
    except Exception:
        pass

    # 3. Tentar da tabela de clientes
    try:
        cliente = (
            supabase.client.table("asaas_clientes")
            .select("name")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        if cliente.data and _is_valid_customer_name(cliente.data.get("name")):
            return cliente.data["name"]
    except Exception:
        pass

    # 4. Último recurso: API do Asaas
    if asaas_service:
        try:
            customer_from_api = await asaas_service.get_customer(customer_id)
            if customer_from_api and _is_valid_customer_name(customer_from_api.get("name")):
                return customer_from_api["name"]
        except Exception:
            pass

    # Não conseguiu resolver - retorna None para NÃO sobrescrever
    return None


def format_brl(value: float) -> str:
    """Formata valor em Real brasileiro (R$ 1.234,56)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_message(
    template: str,
    customer_name: str,
    value: float,
    due_date_str: str,
    *,
    days_overdue: Optional[int] = None,
    days_until_due: Optional[int] = None,
    payment_link: Optional[str] = None,
) -> str:
    """Formata mensagem substituindo variaveis. Suporta {var} e {{var}}."""
    formatted_value = format_brl(value)
    formatted_date = format_date_br(parse_date(due_date_str))

    message = template
    # Suporta {variavel} e {{variavel}}
    message = re.sub(r"\{\{?nome\}\}?", customer_name, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?valor\}\}?", formatted_value, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?vencimento\}\}?", formatted_date, message, flags=re.IGNORECASE)

    if days_overdue is not None:
        message = re.sub(r"\{\{?dias_atraso\}\}?", str(days_overdue), message, flags=re.IGNORECASE)

    if days_until_due is not None:
        message = re.sub(r"\{\{?dias\}\}?", str(days_until_due), message, flags=re.IGNORECASE)

    if payment_link:
        message = re.sub(r"\{\{?link\}\}?", payment_link, message, flags=re.IGNORECASE)
    else:
        message = re.sub(r"\s*\{\{?link\}\}?", "", message, flags=re.IGNORECASE)

    return message


def format_consolidated_message(
    template: str,
    customer_name: str,
    total_value: float,
    payment_count: int,
    max_days_overdue: int,
    payment_link: Optional[str] = None,
) -> str:
    """Formata mensagem consolidada (multiplas faturas)."""
    formatted_total = format_brl(total_value)

    message = template
    message = re.sub(r"\{\{?nome\}\}?", customer_name, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?total\}\}?", formatted_total, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?qtd\}\}?", str(payment_count), message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?dias_atraso\}\}?", str(max_days_overdue), message, flags=re.IGNORECASE)

    if payment_link:
        message = re.sub(r"\{\{?link\}\}?", payment_link, message, flags=re.IGNORECASE)
    else:
        message = re.sub(r"\s*\{\{?link\}\}?", "", message, flags=re.IGNORECASE)

    return message


def get_overdue_template(days_overdue: int, messages: Dict[str, Any]) -> str:
    """
    Seleciona template de cobranca baseado nos dias de atraso.
    Prioriza templates especificos por dia (overdueDia1, overdueDia2...),
    senao usa templates por faixa (overdueTemplate1, overdueTemplate2, overdueTemplate3).
    """
    # Tenta template especifico do dia (ex: overdueDia1, overdueDia2...)
    specific_key = f"overdueDia{days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    # Fallback para templates por faixa
    if days_overdue <= 5:
        return messages.get("overdueTemplate1") or DEFAULT_MESSAGES["overdue1"]
    elif days_overdue <= 10:
        return messages.get("overdueTemplate2") or DEFAULT_MESSAGES["overdue2"]
    else:
        return messages.get("overdueTemplate3") or DEFAULT_MESSAGES["overdue3"]


def get_consolidated_overdue_template(max_days_overdue: int, messages: Dict[str, Any]) -> str:
    """
    Seleciona template consolidado baseado nos dias de atraso.
    Prioriza templates especificos por dia (overdueConsolidatedDia1...),
    senao usa templates por faixa.
    """
    # Tenta template consolidado especifico do dia
    specific_key = f"overdueConsolidatedDia{max_days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    # Fallback para templates por faixa
    if max_days_overdue <= 5:
        return messages.get("overdueConsolidatedTemplate1") or DEFAULT_MESSAGES["overdueConsolidated1"]
    elif max_days_overdue <= 10:
        return messages.get("overdueConsolidatedTemplate2") or DEFAULT_MESSAGES["overdueConsolidated2"]
    else:
        return messages.get("overdueConsolidatedTemplate3") or DEFAULT_MESSAGES["overdueConsolidated3"]


def should_skip_payment(
    payment: Dict[str, Any],
    is_overdue: bool = False,
) -> bool:
    """
    Verifica se o pagamento deve ser ignorado.
    - Cartao PENDING: pular (cobrado automaticamente)
    - Cartao OVERDUE: processar (falhou)
    - Assinaturas: processar normalmente (boleto/pix)
    """
    # Cartao de credito/debito: PENDING -> pular, OVERDUE -> processar
    billing_type = payment.get("billing_type", "")
    if billing_type in CARD_BILLING_TYPES and not is_overdue:
        return True

    return False


def get_customer_phone(payment: Dict[str, Any]) -> Optional[str]:
    """
    Obtem telefone do pagamento normalizado (ja vem do JOIN com asaas_clientes).
    Prioriza mobile_phone sobre phone.
    """
    phone = payment.get("mobile_phone") or payment.get("phone")
    if not phone:
        return None

    # Remove caracteres nao numericos
    cleaned = re.sub(r"\D", "", str(phone))

    # Adiciona codigo do pais se nao tiver
    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    # Valida formato basico
    if len(cleaned) < 12 or len(cleaned) > 13:
        return None

    return cleaned


def phone_to_remotejid(phone: str) -> str:
    """Converte telefone para formato remoteJid do WhatsApp."""
    cleaned = re.sub(r"\D", "", phone)
    return f"{cleaned}@s.whatsapp.net"


# ============================================================================
# SUPABASE QUERY FUNCTIONS
# ============================================================================

def _enrich_payments_with_customers(
    payments: List[Dict[str, Any]],
    customers_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Enriquece lista de cobrancas com dados de clientes (merge em Python).
    Nao depende de FK no banco - faz lookup pelo customer_id.
    """
    result = []
    for row in payments:
        customer_id = row.get("customer_id", "")
        cliente = customers_by_id.get(customer_id) or {}

        # Prioriza nome do cliente; fallback para customer_name da cobranca
        nome = cliente.get("name") or row.get("customer_name") or "Cliente"
        mobile_phone = cliente.get("mobile_phone")
        phone = cliente.get("phone")

        result.append({
            **row,
            # Dados do cliente (normalizados)
            "customer_name": nome,
            "mobile_phone": mobile_phone,
            "phone": phone,
            # Aliases para compatibilidade com codigo de envio
            "customer": customer_id,
            "subscription": row.get("subscription_id"),
            "dueDate": str(row.get("due_date")) if row.get("due_date") else None,
            "billingType": row.get("billing_type"),
            "invoiceUrl": row.get("invoice_url"),
            "bankSlipUrl": row.get("bank_slip_url"),
        })
    return result


async def _fetch_customers_by_ids(
    agent_id: str,
    customer_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Busca clientes pelo lista de IDs e retorna dicionario {customer_id: cliente}.
    Executa query separada pois nao existe FK entre asaas_cobrancas e asaas_clientes.
    """
    if not customer_ids:
        return {}

    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("asaas_clientes")
            .select("id, name, mobile_phone, phone")
            .in_("id", customer_ids)
            .execute()
        )
        return {c["id"]: c for c in (response.data or [])}
    except Exception as e:
        _log_warn(f"Erro ao buscar clientes: {e}")
        return {}


def _normalize_api_payment(payment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza payment da API Asaas (camelCase) para formato interno (snake_case).
    Mantém ambos os formatos para compatibilidade.
    """
    return {
        **payment,
        # Normaliza camelCase -> snake_case
        "customer_id": payment.get("customer") or payment.get("customer_id", ""),
        "customer_name": payment.get("customerName") or payment.get("customer_name", ""),
        "due_date": payment.get("dueDate") or payment.get("due_date"),
        "billing_type": payment.get("billingType") or payment.get("billing_type", ""),
        "invoice_url": payment.get("invoiceUrl") or payment.get("invoice_url"),
        "bank_slip_url": payment.get("bankSlipUrl") or payment.get("bank_slip_url"),
        "subscription_id": payment.get("subscription") or payment.get("subscription_id"),
    }


async def enrich_payments_from_api(
    agent_id: str,
    payments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Normaliza e enriquece payments da API Asaas com dados de clientes.

    1. Normaliza camelCase -> snake_case
    2. Busca dados de clientes (nome, telefone) do asaas_clientes
    3. Retorna payments prontos para processamento

    Resolve o bug de customer_name e phone sendo NULL quando vem da API.
    """
    if not payments:
        return []

    # 1. Normalizar todos os payments
    normalized = [_normalize_api_payment(p) for p in payments]

    # 2. Extrair customer IDs únicos
    customer_ids = list({p["customer_id"] for p in normalized if p.get("customer_id")})

    # 3. Buscar dados dos clientes
    customers_by_id = await _fetch_customers_by_ids(agent_id, customer_ids)

    # 4. Enriquecer com dados dos clientes
    return _enrich_payments_with_customers(normalized, customers_by_id)


async def get_pending_payments_by_due_date(
    agent_id: str,
    due_date: date,
) -> List[Dict[str, Any]]:
    """
    Busca cobrancas PENDING com vencimento na data especificada.
    Faz duas queries separadas (cobrancas + clientes) e merge em Python,
    pois nao existe FK declarada entre as tabelas.
    """
    supabase = get_supabase_service()
    due_date_str = due_date.strftime("%Y-%m-%d")

    try:
        response = (
            supabase.client.table("asaas_cobrancas")
            .select(
                "id, customer_id, customer_name, subscription_id, value, "
                "billing_type, due_date, invoice_url, bank_slip_url, status"
            )
            .eq("agent_id", agent_id)
            .eq("status", "PENDING")
            .eq("due_date", due_date_str)
            .eq("deleted_from_asaas", False)
            .execute()
        )
        payments = response.data or []
        if not payments:
            return []

        customer_ids = list({p["customer_id"] for p in payments if p.get("customer_id")})
        customers = await _fetch_customers_by_ids(agent_id, customer_ids)
        return _enrich_payments_with_customers(payments, customers)

    except Exception as e:
        _log_error(f"Erro ao buscar pagamentos PENDING para {due_date_str}: {e}")
        return []


async def get_pending_payments_today(
    agent_id: str,
) -> List[Dict[str, Any]]:
    """Busca cobrancas PENDING com vencimento hoje."""
    today = get_today_brasilia()
    return await get_pending_payments_by_due_date(agent_id, today)


async def get_overdue_payments(
    agent_id: str,
    min_date: date,
    max_date: date,
) -> List[Dict[str, Any]]:
    """
    Busca cobrancas OVERDUE (vencidas) no periodo especificado.
    Faz duas queries separadas (cobrancas + clientes) e merge em Python,
    pois nao existe FK declarada entre as tabelas.
    """
    supabase = get_supabase_service()

    try:
        response = (
            supabase.client.table("asaas_cobrancas")
            .select(
                "id, customer_id, customer_name, subscription_id, value, "
                "billing_type, due_date, invoice_url, bank_slip_url, status"
            )
            .eq("agent_id", agent_id)
            .eq("status", "OVERDUE")
            .gte("due_date", min_date.strftime("%Y-%m-%d"))
            .lte("due_date", max_date.strftime("%Y-%m-%d"))
            .eq("deleted_from_asaas", False)
            .execute()
        )
        payments = response.data or []
        if not payments:
            return []

        customer_ids = list({p["customer_id"] for p in payments if p.get("customer_id")})
        customers = await _fetch_customers_by_ids(agent_id, customer_ids)
        return _enrich_payments_with_customers(payments, customers)

    except Exception as e:
        _log_error(f"Erro ao buscar pagamentos OVERDUE: {e}")
        return []


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

async def get_agents_with_asaas() -> List[Dict[str, Any]]:
    """
    Busca agentes com Asaas configurado.
    Cobranca automatica e HABILITADA POR PADRAO para todos com asaas_api_key.
    So e desabilitada se explicitamente: asaas_config.autoCollection.enabled = false
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("agents")
            .select(
                "id, name, asaas_api_key, asaas_config, "
                "uazapi_base_url, uazapi_token, uazapi_instance_id, "
                "table_leads, table_messages, handoff_triggers"
            )
            .eq("status", "active")
            .not_.is_("asaas_api_key", "null")
            .neq("asaas_api_key", "")
            .execute()
        )

        agents = response.data or []

        # Filtrar: so pula se explicitamente enabled === false
        result = []
        for agent in agents:
            asaas_config = agent.get("asaas_config") or {}
            auto_collection = asaas_config.get("autoCollection") or {}
            enabled = auto_collection.get("enabled")
            # Se nao definido ou True, processa. So pula se explicitamente False
            if enabled is not False:
                result.append(agent)

        return result

    except Exception as e:
        _log_error(f"Erro ao buscar agentes com Asaas: {e}")
        return []


async def claim_notification(
    agent_id: str,
    payment_id: str,
    notification_type: str,
    scheduled_date: str,
    customer_id: Optional[str] = None,
    phone: Optional[str] = None,
    days_from_due: Optional[int] = None,
) -> bool:
    """
    Tenta registrar notificacao atomicamente usando stored procedure.
    Previne race condition - retorna True se conseguiu clamar, False se ja existia.
    """
    supabase = get_supabase_service()
    try:
        response = supabase.client.rpc(
            "claim_billing_notification",
            {
                "p_agent_id": agent_id,
                "p_payment_id": payment_id,
                "p_notification_type": notification_type,
                "p_scheduled_date": scheduled_date,
                "p_customer_id": customer_id,
                "p_phone": phone,
                "p_days_from_due": days_from_due,
            },
        ).execute()

        if response.data and len(response.data) > 0:
            return response.data[0].get("claimed", False)
        return False
    except Exception as e:
        _log_error(f"Erro ao clamar notificacao: {e}")
        return False


async def save_cobranca_enviada(
    agent_id: str,
    payment: Dict[str, Any],
    customer_name: str,
    phone: str,
    message_text: str,
    notification_type: str,
    days_from_due: int,
    payment_link: Optional[str] = None,
) -> None:
    """Salva registro completo da cobranca enviada em billing_notifications (tabela unificada)."""
    supabase = get_supabase_service()
    try:
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        due_date = payment.get("due_date") or payment.get("dueDate")
        if not due_date:
            _log_warn(f"due_date ausente para payment {payment.get('id')} - usando scheduled_date como fallback")
            due_date = today_str  # Fallback: usar data de hoje
        record = {
            "agent_id": agent_id,
            "payment_id": payment["id"],
            "customer_id": payment.get("customer_id") or payment.get("customer"),
            "phone": phone,  # billing_notifications usa 'phone', não 'customer_phone'
            "customer_name": customer_name,
            "valor": payment.get("value"),
            "due_date": due_date,
            "billing_type": payment.get("billing_type") or payment.get("billingType"),
            "subscription_id": payment.get("subscription_id") or payment.get("subscription"),
            "message_text": message_text,
            "notification_type": notification_type,
            "days_from_due": days_from_due,
            "scheduled_date": today_str,
            "status": "sent",  # billing_notifications usa 'sent', não 'enviado'
            "sent_at": datetime.utcnow().isoformat(),
        }
        # UPSERT: claim_notification já cria registro básico, aqui atualizamos com dados completos
        supabase.client.table("billing_notifications").upsert(
            record,
            on_conflict="agent_id,payment_id,notification_type,scheduled_date"
        ).execute()
        _log(f"Cobranca salva em billing_notifications: {payment['id']} -> {mask_customer_name(customer_name)}")
    except Exception as e:
        _log_error(f"Erro ao salvar em billing_notifications: {e}")


async def update_notification_status(
    agent_id: str,
    payment_id: str,
    notification_type: str,
    scheduled_date: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Atualiza status da notificacao."""
    supabase = get_supabase_service()
    try:
        update_data: Dict[str, Any] = {
            "status": status,
            "sent_at": datetime.utcnow().isoformat() if status == "sent" else None,
        }
        if error_message:
            update_data["error_message"] = error_message

        (
            supabase.client.table("billing_notifications")
            .update(update_data)
            .eq("agent_id", agent_id)
            .eq("payment_id", payment_id)
            .eq("notification_type", notification_type)
            .eq("scheduled_date", scheduled_date)
            .execute()
        )
    except Exception as e:
        _log_error(f"Erro ao atualizar notificacao: {e}")


async def save_to_dead_letter_queue(
    agent_id: str,
    payment: Dict[str, Any],
    phone: str,
    message: str,
    notification_type: str,
    scheduled_date: str,
    days_from_due: int,
    error_message: str,
    dispatch_method: str = "uazapi",
) -> None:
    """
    Salva notificacao falhada no Dead Letter Queue para reprocessamento posterior.
    Classifica o tipo de erro para facilitar analise e retry estrategico.
    """
    supabase = get_supabase_service()

    # Classificar tipo de erro
    failure_reason = "unknown"
    if "timeout" in error_message.lower() or "timed out" in error_message.lower():
        failure_reason = "timeout"
    elif "429" in error_message or "rate limit" in error_message.lower():
        failure_reason = "rate_limit"
    elif "404" in error_message or "not found" in error_message.lower():
        failure_reason = "not_found"
    elif "401" in error_message or "403" in error_message or "unauthorized" in error_message.lower():
        failure_reason = "auth_error"
    elif "network" in error_message.lower() or "connection" in error_message.lower():
        failure_reason = "network_error"
    elif "invalid" in error_message.lower():
        failure_reason = "invalid_data"
    else:
        failure_reason = "api_error"

    try:
        record = {
            "agent_id": agent_id,
            "payment_id": payment["id"],
            "customer_id": payment.get("customer_id"),
            "customer_name": payment.get("customer_name"),
            "phone": phone,
            "message_text": message,
            "notification_type": notification_type,
            "dispatch_method": dispatch_method,
            "error_message": error_message[:1000],  # Limitar tamanho
            "failure_reason": failure_reason,
            "scheduled_date": scheduled_date,
            "days_from_due": days_from_due,
            "payment_value": payment.get("value"),
            "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
            "status": "pending",
            "attempts_count": 1,
        }
        supabase.client.table("billing_failed_notifications").insert(record).execute()
        _log(f"Falha salva no DLQ: {payment['id']} (motivo: {failure_reason})")
    except Exception as e:
        _log_error(f"Erro ao salvar no DLQ: {e}")


async def get_sent_count(agent_id: str, payment_id: str) -> int:
    """Conta quantas notificacoes overdue ja foram enviadas."""
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("billing_notifications")
            .select("id", count="exact")
            .eq("agent_id", agent_id)
            .eq("payment_id", payment_id)
            .eq("notification_type", "overdue")
            .eq("status", "sent")
            .execute()
        )
        return response.count or 0
    except Exception as e:
        _log_error(f"Erro ao contar notificacoes: {e}")
        return 0


# ============================================================================
# CONVERSATION HISTORY
# ============================================================================

async def ensure_lead_exists(
    agent: Dict[str, Any],
    phone: str,
    payment: Dict[str, Any],
) -> Optional[int]:
    """
    Garante que o lead existe na tabela. Se nao existir, cria.
    Retorna o ID do lead ou None se falhar.
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
            # Atualizar lead_origin e billing_context para contexto de cobrança
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
    """
    table_messages = agent.get("table_messages")
    if not table_messages:
        _log_warn(f"Agente {agent.get('name')} nao tem table_messages configurado")
        return None

    remotejid = phone_to_remotejid(phone)
    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()

    try:
        # Buscar registro existente
        response = (
            supabase.client.table(table_messages)
            .select("id")
            .eq("remotejid", remotejid)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]["id"]

        # Registro nao existe, criar novo
        # Estrutura da tabela: id (uuid), creat, remotejid, conversation_history, Msg_model, Msg_user
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

        # Buscar mensagem mais recente pelo remotejid
        response = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .eq("remotejid", remotejid)
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


# ============================================================================
# MAIN PROCESSING
# ============================================================================

async def process_agent_billing(agent: Dict[str, Any]) -> Dict[str, int]:
    """
    Processa notificacoes de cobranca para um agente especifico.
    Retorna contadores de mensagens enviadas/puladas.

    NOVA ARQUITETURA (2026-02-19):
    - Busca dados da API Asaas primeiro (fonte da verdade)
    - Fallback para Supabase se API falhar
    - Atualiza cache em background apos buscar da API
    """
    stats = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "api_success": 0,
        "api_failures": 0,
        "fallback_used": 0,
    }

    asaas_config = agent.get("asaas_config") or {}
    auto_collection = asaas_config.get("autoCollection") or {}

    if auto_collection.get("enabled") is False:
        _log(f"Cobranca automatica desabilitada para: {agent.get('name')}")
        return stats

    # Configuracoes da regua (D-2 e D-1 por padrao)
    reminder_days = auto_collection.get("reminderDays") or [2, 1]
    on_due_date = auto_collection.get("onDueDate", True)
    after_due = auto_collection.get("afterDue") or {
        "enabled": True,
        "overdueDays": list(range(1, 16)),
        "maxAttempts": 15,
    }
    messages = auto_collection.get("messages") or {}

    _log(f"Processando cobranca para agente: {agent.get('name')} ({agent['id'][:8]}...)")

    today = get_today_brasilia()
    today_str = format_date(today)

    async def send_notification(
        phone: str,
        message: str,
        payment: Dict[str, Any],
        notification_type: str,
        days_from_due: int,
    ) -> bool:
        """Envia notificacao via WhatsApp e registra."""
        # Tenta clamar a notificacao atomicamente (previne duplicatas)
        claimed = await claim_notification(
            agent_id=agent["id"],
            payment_id=payment["id"],
            notification_type=notification_type,
            scheduled_date=today_str,
            customer_id=payment.get("customer_id"),
            phone=phone,
            days_from_due=days_from_due,
        )

        if not claimed:
            _log(f"Notificacao ja enviada para {payment['id']} ({notification_type})")
            stats["skipped"] += 1
            return False

        try:
            # Verifica configuracao do WhatsApp
            if not agent.get("uazapi_base_url") or not agent.get("uazapi_token"):
                raise ValueError("Configuracao UAZAPI incompleta")

            signed = sign_message(message, agent.get("name", "Ana"))

            # ================================================================
            # DISPATCH INTELIGENTE: PUSH decide se cria ticket ou move
            # Se ticket NÃO existe: PUSH cria + envia mensagem (não usa UAZAPI)
            # Se ticket JÁ existe: PUT move fila, UAZAPI envia mensagem
            # ================================================================
            push_result = await leadbox_push_silent(
                phone, QUEUE_BILLING, agent["id"], message=signed
            )

            if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
                # Ticket check falhou ou ticket já existia — enviar via UAZAPI
                uazapi_client = UazapiService(
                    base_url=agent["uazapi_base_url"],
                    api_key=agent["uazapi_token"],
                )
                result = await uazapi_client.send_text_message(phone, signed)
                if not result.get("success"):
                    raise ValueError(result.get("error", "Erro desconhecido ao enviar"))

            # Salvar mensagem no conversation_history (cria lead se nao existir)
            await save_message_to_conversation_history(agent, phone, message, notification_type, payment)

            # Log dispatch in unified dispatch_log table
            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_dispatch(
                job_type="billing",
                agent_id=agent["id"],
                reference_id=payment["id"],
                phone=phone,
                notification_type=notification_type,
                message_text=message,
                status="sent",
                reference_table="asaas_cobrancas",
                customer_id=payment.get("customer_id") or payment.get("customer"),
                customer_name=payment.get("customer_name", "Desconhecido"),
                days_from_due=days_from_due,
                metadata={
                    "valor": payment.get("value"),
                    "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
                    "billing_type": payment.get("billing_type") or payment.get("billingType"),
                    "subscription_id": payment.get("subscription_id") or payment.get("subscription"),
                    "payment_link": payment.get("invoice_url") or payment.get("bank_slip_url"),
                },
            )

            # Marcar ia_cobrou e atualizar progresso da régua na cobrança
            supabase = get_supabase_service()
            try:
                # Buscar contagem atual de notificações para este payment
                count_result = supabase.client.table("billing_notifications") \
                    .select("id", count="exact") \
                    .eq("payment_id", payment["id"]) \
                    .eq("status", "sent") \
                    .execute()

                total_notifs = count_result.count if count_result.count else 1

                supabase.client.table("asaas_cobrancas").update({
                    "ia_cobrou": True,
                    "ia_cobrou_at": datetime.utcnow().isoformat(),
                    # Progresso da régua
                    "ia_total_notificacoes": total_notifs,
                    "ia_ultimo_step": notification_type,
                    "ia_ultimo_days_from_due": days_from_due,
                    "ia_ultima_notificacao_at": datetime.utcnow().isoformat(),
                }).eq("id", payment["id"]).eq("agent_id", agent["id"]).execute()
            except Exception as e:
                _log_warn(f"Erro ao marcar ia_cobrou em asaas_cobrancas: {e}")

            await update_notification_status(
                agent["id"], payment["id"], notification_type, today_str, "sent"
            )
            _log(f"Notificacao enviada: {payment['id']} ({notification_type}) -> {mask_phone(phone)}")
            stats["sent"] += 1
            return True

        except Exception as e:
            error_msg = str(e)
            await update_notification_status(
                agent["id"], payment["id"], notification_type, today_str, "failed", error_msg
            )
            _log_error(f"Erro ao enviar notificacao {payment['id']}: {error_msg}")

            # Log failure in unified dispatch_log table
            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_failure(
                job_type="billing",
                agent_id=agent["id"],
                reference_id=payment["id"],
                phone=phone,
                notification_type=notification_type,
                error_message=error_msg,
                message_text=message,
                reference_table="asaas_cobrancas",
                customer_id=payment.get("customer_id") or payment.get("customer"),
                customer_name=payment.get("customer_name"),
                days_from_due=days_from_due,
                metadata={
                    "valor": payment.get("value"),
                    "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
                    "billing_type": payment.get("billing_type") or payment.get("billingType"),
                },
            )

            stats["errors"] += 1
            return False

    # ========================================================================
    # 1. LEMBRETES ANTES DO VENCIMENTO
    # ========================================================================
    for days_ahead in reminder_days:
        target_due_date = add_business_days(today, days_ahead)
        anticipated_date = anticipate_to_friday(target_due_date)

        if format_date(anticipated_date) != today_str and format_date(target_due_date) != today_str:
            continue

        _log(f"Buscando pagamentos com vencimento em {format_date(target_due_date)} ({days_ahead} dias uteis)")

        # NOVA ARQUITETURA: Buscar da API Asaas com fallback para Supabase
        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="PENDING",
            due_date_start=target_due_date,
            due_date_end=target_due_date,
        )

        # Atualizar metricas e enriquecer dados
        if source == "api":
            stats["api_success"] += 1
            # Atualizar cache em background (nao bloqueia)
            import asyncio
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            # Enriquecer payments da API com dados de clientes (nome, telefone)
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        for payment in payments:
            if should_skip_payment(payment, is_overdue=False):
                continue

            phone = get_customer_phone(payment)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(payment.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            template = messages.get("reminderTemplate") or DEFAULT_MESSAGES["reminder"]
            due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
            msg = format_message(
                template,
                payment["customer_name"],
                float(payment["value"]),
                due_date_str,
                days_until_due=days_ahead,
                payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
            )
            await send_notification(phone, msg, payment, "reminder", days_ahead)

    # ========================================================================
    # 2. NOTIFICACAO NO DIA DO VENCIMENTO
    # ========================================================================
    if on_due_date:
        _log(f"Buscando pagamentos com vencimento hoje ({today_str})")

        # NOVA ARQUITETURA: Buscar da API Asaas com fallback para Supabase
        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="PENDING",
            due_date_start=today,
            due_date_end=today,
        )

        # Atualizar metricas e enriquecer dados
        if source == "api":
            stats["api_success"] += 1
            # Atualizar cache em background
            import asyncio
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            # Enriquecer payments da API com dados de clientes (nome, telefone)
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        for payment in payments:
            if should_skip_payment(payment, is_overdue=False):
                continue

            phone = get_customer_phone(payment)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(payment.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            template = messages.get("dueDateTemplate") or DEFAULT_MESSAGES["dueDate"]
            due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
            msg = format_message(
                template,
                payment["customer_name"],
                float(payment["value"]),
                due_date_str,
                payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
            )
            await send_notification(phone, msg, payment, "due_date", 0)

    # ========================================================================
    # 3. COBRANCAS APOS VENCIMENTO (D+1 a D+15 - agrupadas por cliente)
    # ========================================================================
    if after_due.get("enabled", True):
        max_attempts = after_due.get("maxAttempts", 15)
        overdue_days_list = after_due.get("overdueDays") or list(range(1, 16))

        _log(f"Buscando pagamentos vencidos (max: {max_attempts} tentativas, agrupado por cliente)")

        thirty_days_ago = subtract_business_days(today, 30)
        yesterday = subtract_business_days(today, 1)

        # NOVA ARQUITETURA: Buscar da API Asaas com fallback para Supabase
        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="OVERDUE",
            due_date_start=thirty_days_ago,
            due_date_end=yesterday,
        )

        # Atualizar metricas e enriquecer dados
        if source == "api":
            stats["api_success"] += 1
            # Atualizar cache em background
            import asyncio
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            # Enriquecer payments da API com dados de clientes (nome, telefone)
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        # Fase 3a: Filtrar pagamentos elegiveis
        eligible: List[Tuple[Dict[str, Any], int]] = []  # (payment, days_overdue)

        for payment in payments:
            if should_skip_payment(payment, is_overdue=True):
                continue

            due_date_val = payment.get("due_date")
            if isinstance(due_date_val, str):
                due_date_parsed = parse_date(due_date_val)
            elif isinstance(due_date_val, date):
                due_date_parsed = due_date_val
            else:
                _log_warn(f"Pagamento {payment['id']} sem due_date valido, pulando")
                continue

            days_overdue = (today - due_date_parsed).days

            # Verifica se esta na janela de cobranca
            if days_overdue not in overdue_days_list:
                continue

            # Status ja e OVERDUE no Supabase - nao precisa verificar na API Asaas
            # O webhook de cobranca atualiza o status automaticamente

            # Verifica maxAttempts
            sent_count = await get_sent_count(agent["id"], payment["id"])
            if sent_count >= max_attempts:
                _log(f"Pagamento {payment['id']} atingiu maximo de tentativas ({max_attempts})")
                continue

            eligible.append((payment, days_overdue))

        _log(f"{len(eligible)} pagamentos elegiveis para cobranca")

        # Fase 3b: Agrupar por cliente
        grouped: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
        for payment, days_ov in eligible:
            customer_id = payment.get("customer_id", payment.get("customer", ""))
            if customer_id not in grouped:
                grouped[customer_id] = []
            grouped[customer_id].append((payment, days_ov))

        _log(f"{len(grouped)} clientes para cobrar ({len(eligible)} faturas)")

        # Fase 3c: Enviar 1 mensagem por cliente
        for customer_id, customer_payments in grouped.items():
            # Pegar telefone do primeiro pagamento (todos do mesmo cliente)
            first_payment_data = customer_payments[0][0]
            phone = get_customer_phone(first_payment_data)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(first_payment_data.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            customer_name = first_payment_data.get("customer_name", "Cliente")
            max_days = max(dov for _, dov in customer_payments)

            if len(customer_payments) == 1:
                # Fatura unica
                payment, days_ov = customer_payments[0]
                template = get_overdue_template(days_ov, messages)
                due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
                msg = format_message(
                    template,
                    customer_name,
                    float(payment["value"]),
                    due_date_str,
                    days_overdue=days_ov,
                    payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
                )
                await send_notification(phone, msg, payment, "overdue", -days_ov)
            else:
                # Multiplas faturas - mensagem consolidada
                total_value = sum(float(p["value"]) for p, _ in customer_payments)
                first_payment, _ = customer_payments[0]

                template = get_consolidated_overdue_template(max_days, messages)
                msg = format_consolidated_message(
                    template,
                    customer_name,
                    total_value,
                    len(customer_payments),
                    max_days,
                    first_payment.get("invoice_url") or first_payment.get("bank_slip_url"),
                )

                _log(
                    f"Enviando cobranca consolidada: {mask_customer_name(customer_name)} - "
                    f"{len(customer_payments)} faturas, total {format_brl(total_value)}"
                )

                # Envia 1 mensagem apenas (usa primeiro payment)
                sent = await send_notification(
                    phone, msg, first_payment, "overdue", -max_days
                )

                # Registra para os demais payment_ids (evita reenvio)
                if sent:
                    for i in range(1, len(customer_payments)):
                        pmt, dov = customer_payments[i]
                        # Tenta clamar atomicamente (se ja existir, ignora)
                        claimed = await claim_notification(
                            agent_id=agent["id"],
                            payment_id=pmt["id"],
                            notification_type="overdue",
                            scheduled_date=today_str,
                            customer_id=pmt.get("customer_id"),
                            phone=phone,
                            days_from_due=-dov,
                        )
                        if claimed:
                            # Marca como sent imediatamente (consolidado)
                            await update_notification_status(
                                agent["id"], pmt["id"], "overdue", today_str, "sent"
                            )
                            _log(f"Registro salvo para {pmt['id']} (consolidado com {first_payment['id']})")

    _log(f"Processamento concluido para agente: {agent.get('name')}")
    return stats


# ============================================================================
# JOB ENTRY POINTS
# ============================================================================

async def process_billing_charges() -> Dict[str, Any]:
    """
    Processa todos os agentes com Asaas configurado.
    Retorna resumo da execucao.
    """
    redis = await get_redis_service()

    # Tenta adquirir lock distribuído via Redis
    lock_acquired = await redis.client.set(
        BILLING_JOB_LOCK_KEY, "1", nx=True, ex=BILLING_JOB_LOCK_TTL
    )
    if not lock_acquired:
        _log_warn("Job ja esta em execucao em outra instancia, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    today = get_today_brasilia()

    # So executa em dias uteis
    if not is_business_day(today):
        await redis.client.delete(BILLING_JOB_LOCK_KEY)
        _log("Hoje nao e dia util, pulando execucao")
        return {"status": "skipped", "reason": "not_business_day"}

    # Verifica horario comercial (8h-20h)
    if not is_business_hours(8, 20):
        await redis.client.delete(BILLING_JOB_LOCK_KEY)
        _log("Fora do horario comercial, pulando execucao")
        return {"status": "skipped", "reason": "outside_business_hours"}

    _log("Iniciando processamento de cobrancas...")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        agents = await get_agents_with_asaas()
        _log(f"Encontrados {len(agents)} agentes com Asaas configurado")

        for agent in agents:
            try:
                agent_stats = await process_agent_billing(agent)
                total_stats["sent"] += agent_stats["sent"]
                total_stats["skipped"] += agent_stats["skipped"]
                total_stats["errors"] += agent_stats["errors"]
                total_stats["agents_processed"] += 1
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent.get('name')}: {e}")

        _log(
            f"Job finalizado: {total_stats['sent']} mensagens enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento de cobrancas: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        # Libera lock distribuído
        await redis.client.delete(BILLING_JOB_LOCK_KEY)


async def run_billing_charge_job() -> Dict[str, Any]:
    """Entry point para o scheduler / execucao manual."""
    _log("Executando billing charge job...")
    return await process_billing_charges()


async def is_billing_charge_running() -> bool:
    """Verifica se o job esta rodando (via lock Redis)."""
    redis = await get_redis_service()
    return await redis.client.exists(BILLING_JOB_LOCK_KEY) > 0


async def _force_run_billing_charge() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    redis = await get_redis_service()

    # Tenta adquirir lock distribuído
    lock_acquired = await redis.client.set(
        BILLING_JOB_LOCK_KEY, "1", nx=True, ex=BILLING_JOB_LOCK_TTL
    )
    if not lock_acquired:
        _log_warn("Job ja esta em execucao em outra instancia, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _log("=== EXECUCAO FORCADA (ignorando horario/dia util) ===")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        agents = await get_agents_with_asaas()
        _log(f"Encontrados {len(agents)} agentes com Asaas configurado")

        if not agents:
            _log("Nenhum agente com Asaas configurado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            _log(f"Processando agente: {agent.get('name')} ({agent.get('id')})")
            try:
                agent_stats = await process_agent_billing(agent)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent.get('name')}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent.get('name')}: {e}")
                _log_error(traceback.format_exc())

        _log(
            f"=== Job finalizado: {total_stats['sent']} enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        # Libera lock distribuído
        await redis.client.delete(BILLING_JOB_LOCK_KEY)
