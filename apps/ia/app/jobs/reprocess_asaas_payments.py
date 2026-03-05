"""
Reprocess Asaas Payments - Sincronizacao completa Asaas -> Supabase.

Este script foi criado para recuperar todos os pagamentos perdidos porque o
webhook do Asaas nunca teve token de autenticacao configurado (hasAuthToken: false).

Objetivo:
- Sincronizar TODOS os payments do Asaas com asaas_cobrancas
- Sincronizar customers associados em asaas_clientes
- Criar paridade TOTAL entre Asaas e banco local
- Funcionar como dry-run primeiro, depois aplicar mudancas

Uso:
    # Dry-run (mostra o que faria sem alterar nada)
    python -m app.jobs.reprocess_asaas_payments --dry-run

    # Executar de verdade
    python -m app.jobs.reprocess_asaas_payments

    # Com data inicial customizada
    python -m app.jobs.reprocess_asaas_payments --since 2026-01-01

Autor: Claude Code
Data: 2026-03-02
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Rate limiting - max 5 req/s para API Asaas
REQUEST_DELAY = 0.25  # 250ms entre requests


# ============================================================================
# CLASSES DE ESTATISTICAS
# ============================================================================

class ReprocessStats:
    """Estatisticas do reprocessamento."""

    def __init__(self):
        self.total_found = 0
        self.created = 0
        self.updated = 0
        self.already_synced = 0
        self.errors = 0
        self.customers_synced = 0
        self.details: List[str] = []

    def add_detail(self, msg: str):
        self.details.append(msg)
        logger.info(msg)

    def print_summary(self):
        logger.info("\n" + "=" * 60)
        logger.info("RESUMO DO REPROCESSAMENTO")
        logger.info("=" * 60)
        logger.info(f"Total de pagamentos encontrados no Asaas: {self.total_found}")
        logger.info(f"Criados (nao existiam localmente):        {self.created}")
        logger.info(f"Atualizados (status divergente):          {self.updated}")
        logger.info(f"Ja sincronizados (sem alteracao):         {self.already_synced}")
        logger.info(f"Clientes sincronizados:                   {self.customers_synced}")
        logger.info(f"Erros:                                    {self.errors}")
        logger.info("=" * 60)


# ============================================================================
# FUNCOES AUXILIARES
# ============================================================================




async def fetch_all_payments_paginated(
    asaas_service,
    start_date: str,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Busca TODOS os pagamentos da API Asaas desde uma data, com paginacao.

    Args:
        asaas_service: Instancia do AsaasService
        start_date: Data inicial no formato YYYY-MM-DD
        status: Status opcional para filtrar

    Returns:
        Lista de todos os pagamentos
    """
    all_payments = []
    offset = 0
    limit = 100
    max_iterations = 100  # Max 10000 payments

    while True:
        try:
            params = {
                "dateCreated[ge]": start_date,
                "offset": offset,
                "limit": limit,
            }
            if status:
                params["status"] = status

            response = await asaas_service.list_payments(**params)
            data = response.get("data", [])
            all_payments.extend(data)

            has_more = response.get("hasMore", False)
            total_count = response.get("totalCount", 0)

            logger.info(f"[REPROCESS ASAAS PAYMENTS] Pagina {offset // limit + 1}: {len(data)} payments (total: {len(all_payments)}/{total_count})")

            if not has_more or len(data) == 0:
                break

            offset += limit
            max_iterations -= 1

            if max_iterations <= 0:
                logger.warning(f"[REPROCESS ASAAS PAYMENTS] Limite de paginacao atingido ({100 * limit} payments)")
                break

            # Rate limiting
            await asyncio.sleep(REQUEST_DELAY)

        except Exception as e:
            logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao buscar pagamentos (offset={offset}): {e}")
            break

    return all_payments


async def get_local_payment(supabase, payment_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """Busca pagamento local por ID."""
    try:
        result = (
            supabase.client
            .table("asaas_cobrancas")
            .select("*")
            .eq("id", payment_id)
            .eq("agent_id", agent_id)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception as e:
        logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao buscar payment local {payment_id}: {e}")
        return None


async def get_local_customer(supabase, customer_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """Busca cliente local por ID."""
    try:
        result = (
            supabase.client
            .table("asaas_clientes")
            .select("*")
            .eq("id", customer_id)
            .eq("agent_id", agent_id)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception as e:
        return None


async def sync_customer(
    supabase,
    asaas_service,
    customer_id: str,
    agent_id: str,
    dry_run: bool,
    stats: ReprocessStats,
) -> Optional[str]:
    """
    Sincroniza cliente do Asaas para o banco local.

    Returns:
        Nome do cliente ou None
    """
    if not customer_id:
        return None

    try:
        # Verificar se ja existe localmente
        local = await get_local_customer(supabase, customer_id, agent_id)
        if local:
            return local.get("name", "Desconhecido")

        # Buscar da API
        customer_data = await asaas_service.get_customer(customer_id)
        if not customer_data:
            return None

        await asyncio.sleep(REQUEST_DELAY)

        if dry_run:
            stats.add_detail(f"[REPROCESS] [DRY-RUN] Criaria cliente: {customer_id} ({customer_data.get('name')})")
            stats.customers_synced += 1
            return customer_data.get("name", "Desconhecido")

        # Inserir no banco
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

        stats.customers_synced += 1
        stats.add_detail(f"[REPROCESS] Criado cliente: {customer_id} ({customer_data.get('name')})")

        return customer_data.get("name", "Desconhecido")

    except Exception as e:
        logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao sincronizar cliente {customer_id}: {e}")
        return None


async def sync_payment(
    supabase,
    asaas_service,
    payment: Dict[str, Any],
    agent_id: str,
    dry_run: bool,
    stats: ReprocessStats,
) -> None:
    """
    Sincroniza um pagamento do Asaas para o banco local.
    """
    payment_id = payment.get("id", "")
    customer_id = payment.get("customer", "")
    status = payment.get("status", "")
    value = payment.get("value", 0)
    due_date = payment.get("dueDate", "")

    try:
        # 1. Sincronizar cliente primeiro
        customer_name = await sync_customer(
            supabase, asaas_service, customer_id, agent_id, dry_run, stats
        )
        if not customer_name:
            customer_name = "Desconhecido"

        # 2. Verificar se payment ja existe
        local = await get_local_payment(supabase, payment_id, agent_id)

        if local:
            # Comparar status
            local_status = local.get("status", "")
            if local_status == status:
                stats.already_synced += 1
                return
            else:
                # Status divergente - atualizar
                if dry_run:
                    stats.add_detail(
                        f"[REPROCESS] [DRY-RUN] Atualizaria: {payment_id} - "
                        f"status local: {local_status} -> {status}"
                    )
                else:
                    now = datetime.utcnow().isoformat()

                    update_data = {
                        "status": status,
                        "payment_date": payment.get("paymentDate"),
                        "updated_at": now,
                    }

                    # Campos extras para status especificos
                    if status == "REFUNDED":
                        update_data["refund_date"] = payment.get("refundDate") or now
                    elif status in ("RECEIVED", "CONFIRMED"):
                        update_data["payment_date"] = payment.get("paymentDate")

                    supabase.client.table("asaas_cobrancas").update(
                        update_data
                    ).eq("id", payment_id).eq("agent_id", agent_id).execute()

                    stats.add_detail(
                        f"[REPROCESS] Atualizado: {payment_id} - "
                        f"status: {local_status} -> {status}"
                    )

                stats.updated += 1
                return

        # 3. Payment nao existe - criar
        if dry_run:
            stats.add_detail(
                f"[REPROCESS] [DRY-RUN] Criaria: {payment_id} (R$ {value:.2f}) - "
                f"status: {status} | venc: {due_date} | cliente: {customer_name}"
            )
        else:
            now = datetime.utcnow().isoformat()

            # Calcular dias de atraso
            dias_atraso = 0
            if status == "OVERDUE" and due_date:
                try:
                    from datetime import date
                    hoje = date.today()
                    venc = datetime.strptime(due_date, "%Y-%m-%d").date()
                    diff = (hoje - venc).days
                    dias_atraso = diff if diff > 0 else 0
                except Exception:
                    pass

            record = {
                "id": payment_id,
                "agent_id": agent_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "subscription_id": payment.get("subscription"),
                "value": value,
                "net_value": payment.get("netValue"),
                "status": status,
                "billing_type": payment.get("billingType"),
                "due_date": due_date,
                "payment_date": payment.get("paymentDate"),
                "date_created": payment.get("dateCreated"),
                "description": payment.get("description"),
                "invoice_url": payment.get("invoiceUrl"),
                "bank_slip_url": payment.get("bankSlipUrl"),
                "dias_atraso": dias_atraso,
                "updated_at": now,
                "deleted_at": None,
                "deleted_from_asaas": False,
            }

            supabase.client.table("asaas_cobrancas").upsert(
                record,
                on_conflict="id"
            ).execute()

            stats.add_detail(
                f"[REPROCESS] Criado: {payment_id} (R$ {value:.2f}) - "
                f"status: {status} | venc: {due_date} | cliente: {customer_name}"
            )

        stats.created += 1

    except Exception as e:
        stats.errors += 1
        logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao sincronizar payment {payment_id}: {e}")


async def process_agent(
    supabase,
    agent: Dict[str, Any],
    start_date: str,
    dry_run: bool,
    stats: ReprocessStats,
) -> None:
    """
    Processa todos os pagamentos de um agente.
    """
    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Desconhecido")
    asaas_api_key = agent.get("asaas_api_key", "")

    if not asaas_api_key:
        logger.warning(f"[REPROCESS ASAAS PAYMENTS] Agente {agent_name} ({agent_id}) sem asaas_api_key - pulando")
        return

    logger.info(f"[REPROCESS ASAAS PAYMENTS] Processando agente: {agent_name} ({agent_id})")

    try:
        # Importar servico Asaas
        from app.services.gateway_pagamento import AsaasService
        asaas_service = AsaasService(api_key=asaas_api_key)

        # Buscar todos os payments desde a data inicial
        logger.info(f"[REPROCESS ASAAS PAYMENTS] Buscando pagamentos desde {start_date}...")
        payments = await fetch_all_payments_paginated(asaas_service, start_date)

        logger.info(f"[REPROCESS ASAAS PAYMENTS] Encontrados {len(payments)} pagamentos para {agent_name}")
        stats.total_found += len(payments)

        # Processar cada payment
        for i, payment in enumerate(payments):
            await sync_payment(supabase, asaas_service, payment, agent_id, dry_run, stats)

            # Rate limiting a cada 10 payments
            if (i + 1) % 10 == 0:
                await asyncio.sleep(REQUEST_DELAY)

    except Exception as e:
        logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao processar agente {agent_name}: {e}")
        stats.errors += 1


async def get_agents_with_asaas(supabase) -> List[Dict[str, Any]]:
    """Busca todos os agentes com asaas_api_key configurada."""
    try:
        result = (
            supabase.client
            .table("agents")
            .select("id, name, asaas_api_key")
            .not_.is_("asaas_api_key", "null")
            .neq("asaas_api_key", "")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"[REPROCESS ASAAS PAYMENTS] Erro ao buscar agentes: {e}")
        return []


async def run_reprocess(start_date: str, dry_run: bool = True) -> ReprocessStats:
    """
    Executa o reprocessamento de todos os pagamentos.

    Args:
        start_date: Data inicial no formato YYYY-MM-DD
        dry_run: Se True, apenas simula sem alterar dados

    Returns:
        Estatisticas do reprocessamento
    """
    # Importar servicos
    from app.services.supabase import get_supabase_service

    stats = ReprocessStats()

    mode = "[DRY-RUN]" if dry_run else "[EXECUTANDO]"
    logger.info(f"[REPROCESS ASAAS PAYMENTS] {mode} Iniciando reprocessamento desde {start_date}")

    # Obter supabase
    supabase = get_supabase_service()

    # Buscar agentes com Asaas configurado
    agents = await get_agents_with_asaas(supabase)
    logger.info(f"[REPROCESS ASAAS PAYMENTS] Encontrados {len(agents)} agentes com Asaas configurado")

    if not agents:
        logger.warning("[REPROCESS ASAAS PAYMENTS] Nenhum agente com asaas_api_key encontrado!")
        return stats

    # Processar cada agente
    for agent in agents:
        await process_agent(supabase, agent, start_date, dry_run, stats)

    return stats


def main():
    """Ponto de entrada do script."""
    parser = argparse.ArgumentParser(
        description="Reprocessa pagamentos do Asaas para sincronizar com banco local"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas simula sem alterar dados (default: True)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Executa de verdade (sem dry-run)"
    )
    parser.add_argument(
        "--since",
        type=str,
        default="2026-01-01",
        help="Data inicial no formato YYYY-MM-DD (default: 2026-01-01)"
    )

    args = parser.parse_args()

    # Determinar modo
    dry_run = not args.execute

    if dry_run:
        logger.info("\n" + "=" * 60)
        logger.info("MODO DRY-RUN: Nenhuma alteracao sera feita no banco")
        logger.info("Use --execute para aplicar as mudancas")
        logger.info("=" * 60 + "\n")
    else:
        logger.info("\n" + "=" * 60)
        logger.info("MODO EXECUCAO: As alteracoes SERAO aplicadas no banco")
        logger.info("=" * 60)

        # Confirmacao
        confirm = input("\nTem certeza que deseja continuar? (digite 'sim' para confirmar): ")
        if confirm.lower() != "sim":
            logger.info("Operacao cancelada.")
            sys.exit(0)
        logger.info("")

    # Executar
    start_time = time.time()
    stats = asyncio.run(run_reprocess(args.since, dry_run))
    elapsed = time.time() - start_time

    # Imprimir resumo
    stats.print_summary()
    logger.info(f"\nTempo total: {elapsed:.2f} segundos")

    if dry_run and (stats.created > 0 or stats.updated > 0):
        logger.info("\n>>> Para aplicar estas mudancas, execute novamente com --execute")


if __name__ == "__main__":
    main()
