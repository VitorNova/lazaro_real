"""
Servico de sincronizacao de clientes Asaas.

Responsavel por:
- Sincronizar clientes na tabela asaas_clientes
- Match de leads com clientes (conversao)
- Cache local de clientes com TTL
- Resolucao de nomes de clientes

Extraido de: app/webhooks/pagamentos.py (Fase 3.3)
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.gateway_pagamento import AsaasService
from app.domain.billing.models.payment import CUSTOMER_CACHE_TTL_MINUTES

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
            .select("asaas_api_key")
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

        now = datetime.utcnow().isoformat()

        record = {
            "id": customer_id,
            "agent_id": agent_id,
            "name": customer_data.get("name"),
            "cpf_cnpj": customer_data.get("cpfCnpj"),
            "email": customer_data.get("email"),
            "phone": customer_data.get("phone"),
            "mobile_phone": customer_data.get("mobilePhone"),
            "address": customer_data.get("address"),
            "address_number": customer_data.get("addressNumber"),
            "complement": customer_data.get("complement"),
            "province": customer_data.get("province"),
            "city": customer_data.get("city"),
            "state": customer_data.get("state"),
            "postal_code": customer_data.get("postalCode"),
            "date_created": customer_data.get("dateCreated"),
            "external_reference": customer_data.get("externalReference"),
            "observations": customer_data.get("observations"),
            "updated_at": now,
            "deleted_at": None,
            "deleted_from_asaas": False,
        }

        supabase.client.table("asaas_clientes").upsert(
            record,
            on_conflict="id,agent_id"
        ).execute()

        logger.info("[SINCRONIZAR CLIENTE] Cliente %s sincronizado: %s", customer_id, customer_data.get("name"))

        # ================================================================
        # MATCH LEAD → CLIENTE ASAAS (Rastreamento de conversao)
        # Tenta vincular o cliente recem-criado a um lead existente
        # ================================================================
        try:
            await match_lead_to_customer(
                supabase=supabase,
                agent_id=agent_id,
                customer_id=customer_id,
                cpf_cnpj=customer_data.get("cpfCnpj"),
                mobile_phone=customer_data.get("mobilePhone"),
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

    # Buscar table_leads do agente
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
        supabase: Cliente Supabase
        customer_id: ID do cliente no Asaas
        agent_id: ID do agente
        ttl_minutes: Tempo maximo desde ultima atualizacao (minutos)

    Returns:
        Dict com dados do cliente se cacheado e fresco, None se nao encontrado ou stale
    """
    if not customer_id:
        return None

    try:
        result = (
            supabase.client
            .table("asaas_clientes")
            .select("name, updated_at")
            .eq("id", customer_id)
            .eq("agent_id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            return None

        # Verificar se esta dentro do TTL
        updated_at = result.data.get("updated_at")
        if updated_at:
            try:
                # Parse ISO format datetime
                if isinstance(updated_at, str):
                    last_update = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                else:
                    last_update = updated_at

                # Verificar se esta dentro do TTL
                now = datetime.now(timezone.utc)
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=timezone.utc)

                age_minutes = (now - last_update).total_seconds() / 60

                if age_minutes <= ttl_minutes:
                    name = result.data.get("name")
                    if name and not _is_invalid_customer_name(name):
                        logger.debug(
                            "[CACHE] Cliente %s encontrado no cache (%.1f min)",
                            customer_id, age_minutes
                        )
                        return result.data
                else:
                    logger.debug(
                        "[CACHE] Cliente %s stale (%.1f min > %d min TTL)",
                        customer_id, age_minutes, ttl_minutes
                    )
            except Exception as e:
                logger.debug("[CACHE] Erro ao parsear updated_at: %s", e)

        return None

    except Exception as e:
        logger.debug("[CACHE] Erro ao buscar cliente %s no cache: %s", customer_id, e)
        return None


async def resolve_customer_name(
    supabase: Any,
    customer_id,
    proposed_name,
    agent_id=None,
) -> str:
    """
    Resolve o nome do cliente usando hierarquia de fontes.

    Args:
        supabase: Cliente do Supabase
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

    # 2. Busca em asaas_clientes
    try:
        query = supabase.client.table("asaas_clientes").select("name").eq("id", customer_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("name"):
            name = result.data["name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_clientes: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_clientes: %s", e)

    # 3. Busca em asaas_cobrancas (nome existente valido)
    try:
        query = (
            supabase.client
            .table("asaas_cobrancas")
            .select("customer_name")
            .eq("customer_id", customer_id)
            .neq("customer_name", "Desconhecido")
            .neq("customer_name", "Sem nome")
            .neq("customer_name", "")
            .limit(1)
        )
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("customer_name"):
            name = result.data["customer_name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_cobrancas: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_cobrancas: %s", e)

    # 4. Busca em asaas_contratos (nome existente valido)
    try:
        query = (
            supabase.client
            .table("asaas_contratos")
            .select("customer_name")
            .eq("customer_id", customer_id)
            .neq("customer_name", "Desconhecido")
            .neq("customer_name", "Sem nome")
            .neq("customer_name", "")
            .limit(1)
        )
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("customer_name"):
            name = result.data["customer_name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_contratos: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_contratos: %s", e)

    # 5. Ultimo recurso: retorna proposed_name original
    return proposed_name or "Desconhecido"
