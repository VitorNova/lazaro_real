#!/usr/bin/env python3
"""
Script para reprocessar contratos pendentes no Asaas.

Uso:
    python scripts/reprocess_pending_contracts.py

Este script chama o endpoint /webhooks/asaas/reprocess-contract para cada
contrato que precisa ser reprocessado.
"""

import asyncio
import httpx

# Contratos identificados como pendentes
CONTRACTS = [
    {"subscription_id": "sub_t3h74lwceohayg3f", "name": "ARIANNE", "type": "PDF"},
    {"subscription_id": "sub_6rapps1qkrlsvt0m", "name": "HORECIO", "type": "PDF"},
    {"subscription_id": "sub_kxpge4aansncktt7", "name": "MARCELA", "type": "PDF"},
    {"subscription_id": "sub_6bv4klprw2f767fj", "name": "RAYCCA", "type": "PDF"},
    {"subscription_id": "sub_m66zib0pjo46mlb6", "name": "VIVIANE", "type": "PDF"},
    {"subscription_id": "sub_n57yhbv9w2idllhw", "name": "FERNANDO", "type": "JPEG"},
]

# Agent ID do Lazaro
AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# URL do endpoint de reprocessamento (usar 127.0.0.1 para evitar problemas com IPv6)
API_URL = "http://127.0.0.1:3005/webhooks/asaas/reprocess-contract"


async def reprocess_contract(client: httpx.AsyncClient, contract: dict) -> dict:
    """Reprocessa um contrato individual."""
    try:
        response = await client.post(
            API_URL,
            json={
                "subscription_id": contract["subscription_id"],
                "agent_id": AGENT_ID,
            },
            timeout=30.0,
        )
        return {
            "name": contract["name"],
            "subscription_id": contract["subscription_id"],
            "type": contract["type"],
            "status_code": response.status_code,
            "response": response.json() if response.status_code < 500 else response.text,
        }
    except Exception as e:
        return {
            "name": contract["name"],
            "subscription_id": contract["subscription_id"],
            "type": contract["type"],
            "status_code": 0,
            "error": str(e),
        }


async def main():
    print("=" * 60)
    print("REPROCESSAMENTO DE CONTRATOS PENDENTES")
    print("=" * 60)
    print(f"\nAgent ID: {AGENT_ID}")
    print(f"Endpoint: {API_URL}")
    print(f"Contratos a processar: {len(CONTRACTS)}")
    print()

    results = []

    async with httpx.AsyncClient() as client:
        for i, contract in enumerate(CONTRACTS, 1):
            print(f"[{i}/{len(CONTRACTS)}] Processando {contract['name']} ({contract['type']})...")
            print(f"    Subscription: {contract['subscription_id']}")

            result = await reprocess_contract(client, contract)
            results.append(result)

            if result.get("status_code") == 202:
                print(f"    Status: OK - Agendado para processamento")
            elif result.get("status_code") == 404:
                print(f"    Status: NAO ENCONTRADO - Subscription nao existe")
            elif result.get("error"):
                print(f"    Status: ERRO - {result['error']}")
            else:
                print(f"    Status: {result.get('status_code')} - {result.get('response')}")

            print()

            # Delay entre chamadas para evitar sobrecarga
            if i < len(CONTRACTS):
                await asyncio.sleep(2)

    # Resumo
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)

    success = [r for r in results if r.get("status_code") == 202]
    failed = [r for r in results if r.get("status_code") != 202]

    print(f"\nAgendados com sucesso: {len(success)}")
    for r in success:
        print(f"  - {r['name']} ({r['type']})")

    if failed:
        print(f"\nFalharam: {len(failed)}")
        for r in failed:
            print(f"  - {r['name']}: {r.get('error') or r.get('response')}")

    print()
    print("IMPORTANTE: O processamento ocorre em background.")
    print("Aguarde alguns minutos e verifique a tabela contract_details.")
    print()
    print("Para verificar, execute:")
    print("  SELECT subscription_id, locatario_nome, qtd_ars, parsed_at")
    print("  FROM contract_details")
    print(f"  WHERE agent_id = '{AGENT_ID}'")
    print("  ORDER BY parsed_at DESC;")
    print()


if __name__ == "__main__":
    asyncio.run(main())
