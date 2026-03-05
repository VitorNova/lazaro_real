"""
Payment Fetcher Service - Busca de pagamentos da API Asaas e Supabase.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.2)

Funcionalidades:
- Busca pagamentos da API Asaas (fonte da verdade)
- Fallback para Supabase se API falhar
- Sincronizacao de cache em background
- Enriquecimento com dados de clientes (nome, telefone)
- Resolucao de nomes de clientes multi-nivel
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.gateway_pagamento import AsaasService, create_asaas_service
from app.services.supabase import get_supabase_service

from app.domain.billing.models.billing_config import INVALID_NAMES

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


# ============================================================================
# CUSTOMER NAME RESOLUTION
# ============================================================================


def _is_valid_customer_name(name: Optional[str]) -> bool:
    """Verifica se o nome do cliente e valido (nao vazio/placeholder)."""
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
    Resolve o nome do cliente para uma cobranca.

    Ordem de prioridade:
    1. Nome da API (se valido)
    2. Nome existente no banco (asaas_cobrancas)
    3. Nome na tabela de clientes (asaas_clientes)
    4. Busca na API do Asaas (/customers/{id})

    Retorna None se nao conseguir resolver (para nao sobrescrever valor existente).
    """
    # 1. Se API retornou nome valido, usar
    if _is_valid_customer_name(api_customer_name):
        return api_customer_name

    if not customer_id:
        return None

    # 2. Tentar do registro existente (mais rapido, preserva valor anterior)
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

    # 4. Ultimo recurso: API do Asaas
    if asaas_service:
        try:
            customer_from_api = await asaas_service.get_customer(customer_id)
            if customer_from_api and _is_valid_customer_name(customer_from_api.get("name")):
                return customer_from_api["name"]
        except Exception:
            pass

    # Nao conseguiu resolver - retorna None para NAO sobrescrever
    return None


# ============================================================================
# API ASAAS - FETCH FUNCTIONS
# ============================================================================


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

    IMPORTANTE: Preserva customer_name existente se API nao retornar nome valido.
    A API /payments nao retorna customerName, entao precisamos resolver de outras fontes.

    Args:
        agent_id: ID do agente
        payments: Lista de payments da API Asaas
        asaas_api_key: Chave API do Asaas para buscar cliente (opcional)
    """
    if not payments:
        return

    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()

    # Criar servico Asaas se temos a chave (para resolver nomes de clientes)
    asaas_service: Optional[AsaasService] = None
    if asaas_api_key:
        try:
            asaas_service = create_asaas_service(api_key=asaas_api_key)
        except Exception:
            pass  # Continua sem o servico, usara banco como fallback

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

            # Resolver nome do cliente (FIX: API /payments nao retorna customerName)
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

            # PROTECAO: So incluir customer_name se tiver nome valido
            # Se resolved_name e None, NAO sobrescrever o valor existente
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
    Mantem ambos os formatos para compatibilidade.
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

    # 2. Extrair customer IDs unicos
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
    from app.core.utils.dias_uteis import get_today_brasilia
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
