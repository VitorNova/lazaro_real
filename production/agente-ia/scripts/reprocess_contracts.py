#!/usr/bin/env python3
"""
Script para reprocessar contratos sem PDF processado.

Uso:
    cd /var/www/phant/agente-ia
    python -m scripts.reprocess_contracts

Este script:
1. Busca todos os contratos em asaas_contratos que NAO tem registro em contract_details
2. Para cada contrato, chama a mesma logica do webhook SUBSCRIPTION_CREATED
3. Processa em lote com delay entre cada um (evita rate limit)
4. Loga progresso e resultado final
"""

import asyncio
import sys
import os

# Adiciona o diretorio pai ao path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import List, Tuple

from app.config import settings
from app.services.supabase import get_supabase_service
from app.webhooks.asaas import _processar_subscription_created_background

# Agent ID do Lazaro
LAZARO_AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Delay entre processamentos (segundos)
DELAY_BETWEEN_CONTRACTS = 8


async def get_contracts_without_pdf() -> List[Tuple[str, str]]:
    """
    Busca contratos que nao tem registro em contract_details.
    Retorna lista de tuplas (subscription_id, customer_id).
    """
    supabase = get_supabase_service()

    # Query via RPC ou raw SQL - usando abordagem simples via tabelas
    # Primeiro busca todos os contratos do agente
    result = (
        supabase.client
        .table("asaas_contratos")
        .select("id, customer_id")
        .eq("agent_id", LAZARO_AGENT_ID)
        .execute()
    )

    all_contracts = result.data or []

    if not all_contracts:
        return []

    # Busca quais ja tem contract_details
    subscription_ids = [c["id"] for c in all_contracts]

    processed_result = (
        supabase.client
        .table("contract_details")
        .select("subscription_id")
        .eq("agent_id", LAZARO_AGENT_ID)
        .in_("subscription_id", subscription_ids)
        .execute()
    )

    processed_ids = {r["subscription_id"] for r in (processed_result.data or [])}

    # Filtra os que NAO foram processados
    pending = [
        (c["id"], c["customer_id"])
        for c in all_contracts
        if c["id"] not in processed_ids
    ]

    return pending


async def reprocess_all():
    """Reprocessa todos os contratos pendentes."""
    print("=" * 60)
    print(f"REPROCESSAMENTO DE CONTRATOS SEM PDF")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Agent ID: {LAZARO_AGENT_ID}")
    print("=" * 60)

    # Busca contratos pendentes
    print("\n[1/3] Buscando contratos sem contract_details...")
    pending = await get_contracts_without_pdf()

    if not pending:
        print("Nenhum contrato pendente encontrado!")
        return

    print(f"Encontrados {len(pending)} contratos para reprocessar.")

    # Lista os contratos
    print("\nContratos a processar:")
    for i, (sub_id, cus_id) in enumerate(pending, 1):
        print(f"  {i:2d}. {sub_id} (customer: {cus_id})")

    # Processa cada um
    print(f"\n[2/3] Iniciando processamento (delay de {DELAY_BETWEEN_CONTRACTS}s entre cada)...")

    success = 0
    failed = 0

    for i, (subscription_id, customer_id) in enumerate(pending, 1):
        print(f"\n--- Contrato {i}/{len(pending)} ---")
        print(f"Subscription: {subscription_id}")
        print(f"Customer: {customer_id}")

        try:
            await _processar_subscription_created_background(
                subscription_id=subscription_id,
                customer_id=customer_id,
                agent_id=LAZARO_AGENT_ID,
            )

            # Verifica se foi salvo
            supabase = get_supabase_service()
            check = (
                supabase.client
                .table("contract_details")
                .select("id, qtd_ars, valor_comercial_total")
                .eq("subscription_id", subscription_id)
                .eq("agent_id", LAZARO_AGENT_ID)
                .maybe_single()
                .execute()
            )

            if check.data:
                success += 1
                qtd = check.data.get("qtd_ars", 0)
                valor = check.data.get("valor_comercial_total", 0)
                print(f"[OK] Processado! {qtd} equipamentos, R$ {valor:.2f}")
            else:
                failed += 1
                print(f"[AVISO] Processamento concluiu mas nao salvou (sem PDF?)")

        except Exception as e:
            failed += 1
            print(f"[ERRO] {e}")

        # Delay entre processamentos (exceto ultimo)
        if i < len(pending):
            print(f"Aguardando {DELAY_BETWEEN_CONTRACTS}s...")
            await asyncio.sleep(DELAY_BETWEEN_CONTRACTS)

    # Resultado final
    print("\n" + "=" * 60)
    print("[3/3] RESULTADO FINAL")
    print("=" * 60)
    print(f"Total processados: {len(pending)}")
    print(f"Sucesso: {success}")
    print(f"Falha/Sem PDF: {failed}")
    print(f"Fim: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Verifica quantos ainda faltam
    remaining = await get_contracts_without_pdf()
    print(f"Contratos ainda pendentes: {len(remaining)}")


if __name__ == "__main__":
    asyncio.run(reprocess_all())
