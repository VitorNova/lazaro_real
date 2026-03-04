"""Dry run do billing v2 - simula sem enviar mensagens."""
import asyncio
import logging
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List

# === IMPORTS EXATOS DO billing_job_v2.py ===
from app.jobs.cobrar_clientes import get_agents_with_asaas
from app.utils.business_days import get_today_brasilia

# === IMPORTS EXATOS DO agent_processor.py ===
from app.billing.collector import collect_payments
from app.billing.eligibility import run_eligibility_checks
from app.billing.models import EligiblePayment, CollectorResult, RejectedPayment
from app.billing.ruler import evaluate, DEFAULT_SCHEDULE
from app.utils.business_days import add_business_days, subtract_business_days

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def dry_run_agent(agent: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    Executa pipeline completo para um agente SEM enviar mensagens.
    Retorna estatisticas detalhadas.
    """
    config = (agent.get("asaas_config") or {}).get("autoCollection") or {}
    max_attempts = (config.get("afterDue") or {}).get("maxAttempts", 15)
    agent_id = agent["id"]

    stats = {
        "collected": 0,
        "source": "",
        "cache_age_hours": 0.0,
        "degraded": False,
        "eligible": 0,
        "rejected": 0,
        "rejection_reasons": defaultdict(int),
        "would_send": defaultdict(int),  # offset -> count
        "would_skip_offset": 0,  # nao esta no schedule
    }

    all_collector_results: List[CollectorResult] = []
    all_eligible: List[EligiblePayment] = []
    all_rejected: List[RejectedPayment] = []

    # ========================================================================
    # FASE 1: PENDING - Lembretes (D-2, D-1)
    # ========================================================================
    reminder_days = config.get("reminderDays") or [2, 1]

    for days_ahead in reminder_days:
        target_date = add_business_days(today, days_ahead)
        result = await collect_payments(agent, "PENDING", target_date, target_date)
        all_collector_results.append(result)

        if result.degraded:
            stats["degraded"] = True
            continue

        eligibility = await run_eligibility_checks(
            result.payments, agent_id, max_attempts
        )
        all_eligible.extend(eligibility.eligible)
        all_rejected.extend(eligibility.rejected)

    # ========================================================================
    # FASE 2: PENDING - Vencimento hoje (D0)
    # ========================================================================
    on_due_date = config.get("onDueDate", True)

    if on_due_date:
        result = await collect_payments(agent, "PENDING", today, today)
        all_collector_results.append(result)

        if result.degraded:
            stats["degraded"] = True
        else:
            eligibility = await run_eligibility_checks(
                result.payments, agent_id, max_attempts
            )
            all_eligible.extend(eligibility.eligible)
            all_rejected.extend(eligibility.rejected)

    # ========================================================================
    # FASE 3: OVERDUE - Atrasos (D+1 a D+30)
    # ========================================================================
    after_due_config = config.get("afterDue") or {}
    after_due_enabled = after_due_config.get("enabled", True)

    if after_due_enabled:
        thirty_ago = subtract_business_days(today, 30)
        yesterday = subtract_business_days(today, 1)

        result = await collect_payments(agent, "OVERDUE", thirty_ago, yesterday)
        all_collector_results.append(result)

        if result.degraded:
            stats["degraded"] = True
        else:
            eligibility = await run_eligibility_checks(
                result.payments, agent_id, max_attempts
            )
            all_eligible.extend(eligibility.eligible)
            all_rejected.extend(eligibility.rejected)

    # ========================================================================
    # CONSOLIDAR ESTATISTICAS
    # ========================================================================

    # Source e cache age (pegar do primeiro resultado com dados)
    for cr in all_collector_results:
        if cr.payments:
            stats["source"] = cr.source
            stats["cache_age_hours"] = cr.cache_age_hours
            break
    if not stats["source"] and all_collector_results:
        stats["source"] = all_collector_results[0].source
        stats["cache_age_hours"] = all_collector_results[0].cache_age_hours

    # Total coletado
    stats["collected"] = sum(len(cr.payments) for cr in all_collector_results)

    # Rejeitados
    stats["rejected"] = len(all_rejected)
    for r in all_rejected:
        stats["rejection_reasons"][r.reason] += 1

    # Elegiveis e decisao da regua
    stats["eligible"] = len(all_eligible)
    for eligible in all_eligible:
        decision = evaluate(today, eligible.payment.due_date)
        if decision.should_send:
            # Formatar offset para exibicao
            if decision.offset < 0:
                offset_label = f"D{decision.offset}"  # D-1, D-2
            elif decision.offset == 0:
                offset_label = "D0"
            else:
                offset_label = f"D+{decision.offset}"  # D+1, D+3...
            stats["would_send"][offset_label] += 1
        else:
            stats["would_skip_offset"] += 1

    return stats


def print_agent_summary(agent: Dict[str, Any], stats: Dict[str, Any]) -> None:
    """Imprime resumo formatado para um agente."""
    agent_name = agent.get("name", "Sem nome")
    agent_id = agent.get("id", "?")

    print(f"\n{'='*60}")
    print(f"=== AGENTE: {agent_name} ({agent_id[:8]}...) ===")
    print(f"{'='*60}")

    print(f"\nFaturas coletadas: {stats['collected']}")
    print(f"Source: {stats['source']} | cache age: {stats['cache_age_hours']:.1f}h")
    print(f"Degraded: {stats['degraded']}")

    print(f"\nElegiveis: {stats['eligible']}")
    print(f"Rejeitados: {stats['rejected']}")

    if stats["rejection_reasons"]:
        for reason, count in sorted(stats["rejection_reasons"].items()):
            print(f"  - {reason}: {count}")

    print(f"\nEnvios que faria hoje:")
    if stats["would_send"]:
        # Ordenar por offset numerico
        def sort_key(label):
            if label == "D0":
                return 0
            elif label.startswith("D-"):
                return int(label[1:])
            else:  # D+X
                return int(label[2:])

        for offset_label in sorted(stats["would_send"].keys(), key=sort_key):
            count = stats["would_send"][offset_label]
            # Adicionar descricao do template
            template_desc = _get_template_description(offset_label)
            print(f"  - {offset_label} ({template_desc}): {count}")
    else:
        print("  (nenhum)")

    print(f"\nPularia (offset nao na schedule): {stats['would_skip_offset']}")


def _get_template_description(offset_label: str) -> str:
    """Retorna descricao do template baseado no offset."""
    if offset_label.startswith("D-"):
        return "reminder"
    elif offset_label == "D0":
        return "dueToday"
    else:
        offset = int(offset_label[2:])
        if offset <= 5:
            return "overdueGentle"
        elif offset <= 10:
            return "overdueModerate"
        else:
            return "overdueFinal"


async def main():
    """Entry point do dry run."""
    print("\n" + "="*60)
    print("BILLING V2 - DRY RUN")
    print("Este script NAO envia mensagens. Somente leitura.")
    print("="*60)

    today = get_today_brasilia()
    print(f"\nData de referencia: {today}")
    print(f"Schedule padrao: {DEFAULT_SCHEDULE}")

    # Buscar agentes
    print("\nBuscando agentes com Asaas configurado...")
    agents = await get_agents_with_asaas()
    print(f"Encontrados: {len(agents)} agentes")

    if not agents:
        print("\nNenhum agente encontrado. Encerrando.")
        return

    # Processar cada agente
    total_stats = {
        "collected": 0,
        "eligible": 0,
        "rejected": 0,
        "would_send": 0,
        "would_skip": 0,
        "degraded": 0,
    }

    for agent in agents:
        try:
            stats = await dry_run_agent(agent, today)
            print_agent_summary(agent, stats)

            # Acumular totais
            total_stats["collected"] += stats["collected"]
            total_stats["eligible"] += stats["eligible"]
            total_stats["rejected"] += stats["rejected"]
            total_stats["would_send"] += sum(stats["would_send"].values())
            total_stats["would_skip"] += stats["would_skip_offset"]
            if stats["degraded"]:
                total_stats["degraded"] += 1

        except Exception as e:
            print(f"\n[ERRO] Agente {agent.get('id')}: {e}")
            logger.exception(f"Erro processando agente {agent.get('id')}")

    # Resumo final
    print("\n" + "="*60)
    print("=== RESUMO TOTAL ===")
    print("="*60)
    print(f"Agentes processados: {len(agents)}")
    print(f"Agentes degradados: {total_stats['degraded']}")
    print(f"Total faturas coletadas: {total_stats['collected']}")
    print(f"Total elegiveis: {total_stats['eligible']}")
    print(f"Total rejeitados: {total_stats['rejected']}")
    print(f"Total que ENVIARIA hoje: {total_stats['would_send']}")
    print(f"Total que PULARIA (offset): {total_stats['would_skip']}")
    print("\n" + "="*60)
    print("DRY RUN COMPLETO - NENHUMA MENSAGEM FOI ENVIADA")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
