"""
Servico de sincronizacao de clientes Asaas.

Responsavel por:
- Sincronizar clientes na tabela asaas_clientes
- Match de leads com clientes (conversao)
- Cache local de clientes com TTL
- Resolucao de nomes de clientes

Extraido de: app/webhooks/pagamentos.py (Fase 3.3)
Refatorado para usar AsaasCustomersRepository (Fase 9.12)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.gateway_pagamento import AsaasService
from app.domain.billing.models.payment import CUSTOMER_CACHE_TTL_MINUTES
from app.integrations.supabase.repositories import (
    asaas_customers_repository,
    asaas_contracts_repository,
    asaas_payments_repository,
)

logger = logging.getLogger(__name__)


def _is_invalid_customer_name(name) -> bool:
    """Verifica se o nome e invalido/fallback."""
    if not name or not str(name).strip():
        return True
    lower = str(name).lower().strip()
    if lower in ("desconhecido", "sem nome", "cliente", "?"):
        return True
    if lower.startswith("cliente #"):
        return True
    # Padrao "Cliente abc123" (6 caracteres hex)
    if re.match(r"^cliente [a-f0-9]{6}$", lower):
        return True
    return False


async def sincronizar_cliente(
    supabase: Any,
    customer: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Sincroniza cliente na tabela asaas_clientes.

    Busca dados completos do cliente via API Asaas e faz upsert.
    Campos: id, agent_id, name, cpf_cnpj, email, phone, mobile_phone,
            address, address_number, complement, province, city, state, postal_code,
            date_created, external_reference, observations
    """
    customer_id = customer.get("id")
    if not customer_id:
        logger.warning("[SINCRONIZAR CLIENTE] customer_id ausente")
        return

    try:
        # Busca API key do agente para consultar dados completos
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key, table_leads")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        customer_data = customer  # Usa dados do webhook como fallback

        if result.data and result.data.get("asaas_api_key"):
            try:
                asaas = AsaasService(api_key=result.data["asaas_api_key"])
                full_customer = await asaas.get_customer(customer_id)
                if full_customer:
                    customer_data = full_customer
                    logger.debug("[SINCRONIZAR CLIENTE] Dados completos obtidos via API")
            except Exception as e:
                logger.warning("[SINCRONIZAR CLIENTE] Erro ao buscar via API, usando dados do webhook: %s", e)

        # Usar repositorio para upsert
        await asaas_customers_repository.upsert(
            customer_id=customer_id,
            agent_id=agent_id,
            data=customer_data,
        )

        logger.info("[SINCRONIZAR CLIENTE] Cliente %s sincronizado: %s", customer_id, customer_data.get("name"))

        # ================================================================
        # MATCH LEAD → CLIENTE ASAAS (Rastreamento de conversao)
        # Tenta vincular o cliente recem-criado a um lead existente
        # ================================================================
        try:
            table_leads = result.data.get("table_leads") if result.data else None
            if table_leads:
                await match_lead_to_customer(
                    supabase=supabase,
                    agent_id=agent_id,
                    customer_id=customer_id,
                    cpf_cnpj=customer_data.get("cpfCnpj"),
                    mobile_phone=customer_data.get("mobilePhone"),
                    table_leads=table_leads,
                )
        except Exception as match_err:
            logger.warning("[SINCRONIZAR CLIENTE] Erro no match lead->cliente (best-effort): %s", match_err)

    except Exception as e:
        logger.error("[SINCRONIZAR CLIENTE] Erro ao sincronizar cliente %s: %s", customer_id, e)


async def match_lead_to_customer(
    supabase: Any,
    agent_id: str,
    customer_id: str,
    cpf_cnpj: Optional[str],
    mobile_phone: Optional[str],
    table_leads: Optional[str] = None,
) -> bool:
    """
    Tenta vincular um cliente Asaas recem-criado a um lead existente.

    Prioridade de match:
    1. CPF/CNPJ exato (mais confiavel)
    2. Telefone (ultimos 11 digitos do remotejid)

    Se encontrar, atualiza o lead com:
    - asaas_customer_id
    - converted_at
    - pipeline_step = 'cliente'

    Returns:
        True se encontrou e vinculou, False caso contrario
    """
    if not agent_id:
        return False

    # Buscar table_leads do agente se nao fornecido
    if not table_leads:
        agent_result = (
            supabase.client.table("agents")
            .select("table_leads")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not agent_result.data or not agent_result.data.get("table_leads"):
            logger.debug("[CONVERSAO] Agente %s nao tem table_leads configurado", agent_id[:8])
            return False

        table_leads = agent_result.data["table_leads"]

    now = datetime.utcnow().isoformat()

    # ================================================================
    # PRIORIDADE 1: Match por CPF/CNPJ
    # ================================================================
    if cpf_cnpj:
        cpf_limpo = re.sub(r'\D', '', cpf_cnpj)
        if len(cpf_limpo) in [11, 14]:
            try:
                lead_result = (
                    supabase.client.table(table_leads)
                    .select("id, nome, remotejid, asaas_customer_id")
                    .eq("cpf_cnpj", cpf_limpo)
                    .is_("asaas_customer_id", "null")  # So leads nao vinculados
                    .limit(1)
                    .execute()
                )

                if lead_result.data:
                    lead = lead_result.data[0]
                    supabase.client.table(table_leads).update({
                        "asaas_customer_id": customer_id,
                        "converted_at": now,
                        "pipeline_step": "cliente",
                        "journey_stage": "cliente",
                        "updated_date": now,
                    }).eq("id", lead["id"]).execute()

                    logger.info(
                        "[CONVERSAO] Lead %s convertido! CPF: %s -> Cliente Asaas: %s",
                        lead.get("remotejid", "")[-11:], cpf_limpo, customer_id
                    )
                    return True
            except Exception as e:
                logger.warning("[CONVERSAO] Erro no match por CPF: %s", e)

    # ================================================================
    # PRIORIDADE 2: Match por telefone (fallback)
    # ================================================================
    if mobile_phone:
        phone_limpo = re.sub(r'\D', '', mobile_phone)
        if len(phone_limpo) >= 10:
            # Extrair ultimos 11 digitos para comparar
            phone_suffix = phone_limpo[-11:] if len(phone_limpo) >= 11 else phone_limpo

            try:
                # Buscar lead pelo telefone no remotejid
                lead_result = (
                    supabase.client.table(table_leads)
                    .select("id, nome, remotejid, asaas_customer_id")
                    .ilike("remotejid", f"%{phone_suffix}%")
                    .is_("asaas_customer_id", "null")  # So leads nao vinculados
                    .limit(1)
                    .execute()
                )

                if lead_result.data:
                    lead = lead_result.data[0]
                    supabase.client.table(table_leads).update({
                        "asaas_customer_id": customer_id,
                        "converted_at": now,
                        "pipeline_step": "cliente",
                        "journey_stage": "cliente",
                        "updated_date": now,
                    }).eq("id", lead["id"]).execute()

                    logger.info(
                        "[CONVERSAO] Lead %s convertido via telefone! Tel: %s -> Cliente Asaas: %s",
                        lead.get("remotejid", "")[-11:], phone_suffix, customer_id
                    )
                    return True
            except Exception as e:
                logger.warning("[CONVERSAO] Erro no match por telefone: %s", e)

    logger.debug("[CONVERSAO] Nenhum lead encontrado para customer_id=%s", customer_id)
    return False


async def get_cached_customer(
    supabase: Any,
    customer_id: str,
    agent_id: str,
    ttl_minutes: int = CUSTOMER_CACHE_TTL_MINUTES,
) -> Optional[Dict[str, Any]]:
    """
    Busca cliente no cache local (asaas_clientes) se estiver fresco.

    Args:
        supabase: Cliente Supabase (mantido para compatibilidade, nao usado)
        customer_id: ID do cliente no Asaas
        agent_id: ID do agente
        ttl_minutes: Tempo maximo desde ultima atualizacao (minutos)

    Returns:
        Dict com dados do cliente se cacheado e fresco, None se nao encontrado ou stale
    """
    # Usar repositorio com cache TTL
    return await asaas_customers_repository.find_cached(
        customer_id=customer_id,
        agent_id=agent_id,
        ttl_minutes=ttl_minutes,
    )


async def resolve_customer_name(
    supabase: Any,
    customer_id,
    proposed_name,
    agent_id=None,
) -> str:
    """
    Resolve o nome do cliente usando hierarquia de fontes.

    Args:
        supabase: Cliente do Supabase (mantido para compatibilidade, parcialmente usado)
        customer_id: ID do cliente no Asaas
        proposed_name: Nome proposto (pode ser fallback)
        agent_id: ID do agente (opcional, para filtrar por agente)

    Returns:
        Nome resolvido ou fallback original
    """
    # 1. Se proposed_name e valido, usa ele
    if proposed_name and not _is_invalid_customer_name(proposed_name):
        return proposed_name

    if not customer_id:
        return proposed_name or "Desconhecido"

    # 2. Busca em asaas_clientes via repository
    try:
        name = await asaas_customers_repository.find_name(
            customer_id=customer_id,
            agent_id=agent_id,
        )
        if name:
            logger.debug("[RESOLVE_NAME] Nome obtido de asaas_clientes: %s", name)
            return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_clientes: %s", e)

    # 3. Busca em asaas_cobrancas via repository
    try:
        name = await asaas_payments_repository.find_name_by_customer_id(
            customer_id=customer_id,
            agent_id=agent_id,
        )
        if name:
            logger.debug("[RESOLVE_NAME] Nome obtido de asaas_cobrancas: %s", name)
            return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_cobrancas: %s", e)

    # 4. Busca em asaas_contratos via repository
    try:
        name = await asaas_contracts_repository.find_name_by_customer_id(
            customer_id=customer_id,
            agent_id=agent_id,
        )
        if name:
            logger.debug("[RESOLVE_NAME] Nome obtido de asaas_contratos: %s", name)
            return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_contratos: %s", e)

    # 5. Ultimo recurso: retorna proposed_name original
    return proposed_name or "Desconhecido"
