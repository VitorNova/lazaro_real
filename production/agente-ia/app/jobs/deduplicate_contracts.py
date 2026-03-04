"""
Deduplicate Contracts Job - Remove duplicatas em contract_details.

Problema:
- Multiplas subscriptions do Asaas podem ter o mesmo numero_contrato
- Contratos reprocessados/renovados geram registros duplicados
- Metricas ficam infladas (conta o mesmo contrato multiplas vezes)

Solucao:
- Agrupa registros por numero_contrato
- Mantem o mais recente (parsed_at DESC)
- Deleta permanentemente os demais (hard delete)

Uso:
  python -m app.jobs.deduplicate_contracts --agent-id UUID [--dry-run]

Parametros:
  --agent-id: UUID do agente (obrigatorio)
  --dry-run: Simula sem deletar (default: False)

IMPORTANTE: Esta tabela nao tem soft delete (deleted_at). Os registros sao removidos permanentemente.

Exemplo:
  python -m app.jobs.deduplicate_contracts --agent-id 14e6e5ce-4627-4e38-aac8-f0191669ff53 --dry-run
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List

from app.services.supabase import get_supabase_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


async def find_duplicates(agent_id: str) -> List[Dict[str, Any]]:
    """
    Encontra contratos duplicados (mesmo numero_contrato).

    Args:
        agent_id: UUID do agente

    Returns:
        Lista de grupos de duplicatas, cada grupo contém:
        {
            "numero_contrato": "123-1",
            "ids": [uuid1, uuid2, ...],
            "count": 2
        }
    """
    svc = get_supabase_service()

    # Buscar todos os contract_details do agente
    logger.info(f"Buscando contratos do agente {agent_id}...")

    result = (
        svc.client
        .table("contract_details")
        .select("id, numero_contrato, parsed_at, subscription_id, locatario_nome")
        .eq("agent_id", agent_id)
        .order("numero_contrato", desc=False)
        .order("parsed_at", desc=True)
        .execute()
    )

    records = result.data or []
    logger.info(f"Encontrados {len(records)} contratos ativos")

    # Agrupar por numero_contrato
    groups: Dict[str, List[Dict[str, Any]]] = {}
    sem_numero = []

    for record in records:
        numero = record.get("numero_contrato")

        if not numero:
            sem_numero.append(record)
            continue

        if numero not in groups:
            groups[numero] = []
        groups[numero].append(record)

    # Filtrar apenas grupos com duplicatas
    duplicates = []
    for numero, items in groups.items():
        if len(items) > 1:
            duplicates.append({
                "numero_contrato": numero,
                "records": items,
                "count": len(items)
            })

    logger.info(f"Duplicatas encontradas: {len(duplicates)} grupos")
    logger.info(f"Contratos sem número: {len(sem_numero)}")

    return duplicates


async def deduplicate_contracts(
    agent_id: str,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Remove duplicatas de contratos.

    Logica:
    1. Agrupa por numero_contrato
    2. Mantem o mais recente (primeiro na ordem parsed_at DESC)
    3. Deleta permanentemente os demais (tabela nao tem soft delete)

    Args:
        agent_id: UUID do agente
        dry_run: Se True, apenas simula (nao deleta)

    Returns:
        Resumo da operacao:
        {
            "success": True,
            "duplicates_found": 7,
            "records_to_delete": 14,
            "records_deleted": 14,  # 0 se dry_run
            "deleted_ids": [...],
            "dry_run": True/False
        }
    """
    svc = get_supabase_service()

    logger.info("="*60)
    logger.info("INICIANDO DEDUPLICACAO DE CONTRATOS")
    logger.info("="*60)
    logger.info(f"Agente: {agent_id}")
    logger.info(f"Modo: {'DRY RUN (simulacao)' if dry_run else 'PRODUCAO (HARD DELETE)'}")
    logger.info("="*60)

    # 1. Encontrar duplicatas
    duplicates = await find_duplicates(agent_id)

    if not duplicates:
        logger.info("✅ Nenhuma duplicata encontrada!")
        return {
            "success": True,
            "duplicates_found": 0,
            "records_to_delete": 0,
            "records_deleted": 0,
            "deleted_ids": [],
            "dry_run": dry_run
        }

    # 2. Preparar lista de IDs para deletar
    ids_to_delete = []

    for group in duplicates:
        numero = group["numero_contrato"]
        records = group["records"]

        # Registros já vêm ordenados por parsed_at DESC
        # Primeiro = mais recente (MANTER)
        # Resto = duplicatas (DELETAR)
        keep = records[0]
        to_delete = records[1:]

        logger.info("")
        logger.info(f"📋 Contrato: {numero} ({len(records)} registros)")
        logger.info(f"   ✅ MANTER: ID {keep['id'][:8]}... | Parsed: {keep.get('parsed_at', 'N/A')} | Cliente: {keep.get('locatario_nome', 'N/A')}")

        for dup in to_delete:
            ids_to_delete.append(dup['id'])
            logger.warning(
                f"   ❌ DELETAR: ID {dup['id'][:8]}... | Parsed: {dup.get('parsed_at', 'N/A')} | "
                f"Cliente: {dup.get('locatario_nome', 'N/A')}"
            )

    logger.info("")
    logger.info("="*60)
    logger.info(f"RESUMO:")
    logger.info(f"  Grupos duplicados: {len(duplicates)}")
    logger.info(f"  Registros a deletar: {len(ids_to_delete)}")
    logger.info("="*60)

    # 3. Deletar (se não for dry-run)
    deleted_count = 0

    if not dry_run:
        if not ids_to_delete:
            logger.info("✅ Nada para deletar")
        else:
            logger.info(f"Deletando {len(ids_to_delete)} registros...")

            try:
                # Hard delete: remove permanentemente (tabela nao tem soft delete)
                result = (
                    svc.client
                    .table("contract_details")
                    .delete()
                    .in_("id", ids_to_delete)
                    .execute()
                )
                deleted_count = len(result.data) if result.data else 0
                logger.info(f"✅ {deleted_count} registros removidos permanentemente")

            except Exception as e:
                logger.error(f"❌ Erro ao deletar: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "duplicates_found": len(duplicates),
                    "records_to_delete": len(ids_to_delete),
                    "records_deleted": deleted_count,
                    "deleted_ids": [],
                    "dry_run": dry_run
                }
    else:
        logger.warning("⚠️  DRY RUN: Nenhum registro foi deletado (use sem --dry-run para executar)")

    logger.info("="*60)
    logger.info("✅ DEDUPLICACAO CONCLUIDA")
    logger.info("="*60)

    return {
        "success": True,
        "duplicates_found": len(duplicates),
        "records_to_delete": len(ids_to_delete),
        "records_deleted": deleted_count,
        "deleted_ids": ids_to_delete if not dry_run else [],
        "dry_run": dry_run
    }


async def main():
    """Entry point do script."""
    parser = argparse.ArgumentParser(
        description="Remove duplicatas de contratos em contract_details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Simular deduplicacao (DRY RUN)
  python -m app.jobs.deduplicate_contracts --agent-id 14e6e5ce-4627-4e38-aac8-f0191669ff53 --dry-run

  # Executar deduplicacao (PRODUCAO - CUIDADO: hard delete permanente!)
  python -m app.jobs.deduplicate_contracts --agent-id 14e6e5ce-4627-4e38-aac8-f0191669ff53
        """
    )

    parser.add_argument(
        "--agent-id",
        required=True,
        help="UUID do agente (obrigatorio)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula sem deletar (default: False)"
    )

    args = parser.parse_args()

    # Validar UUID simples
    if len(args.agent_id) != 36:
        logger.error("❌ agent-id deve ser um UUID valido (36 caracteres)")
        sys.exit(1)

    result = await deduplicate_contracts(
        agent_id=args.agent_id,
        dry_run=args.dry_run
    )

    if result["success"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
