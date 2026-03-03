"""
Leads reanalysis endpoints for Observer batch processing.

This module provides:
- POST /api/reanalyze-leads/{agent_id}: Batch reanalyze leads with Observer
- GET /api/reanalyze-leads/status: Get reanalysis job status
"""

from datetime import datetime
from typing import Any, Dict

import structlog
from fastapi import APIRouter, BackgroundTasks

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["observer"])

# Global state for reanalysis job
_reanalyze_running: bool = False
_reanalyze_progress: Dict[str, Any] = {}


async def _run_reanalyze_leads(agent_id: str, batch_size: int = 50) -> Dict[str, Any]:
    """
    Processa todos os leads de um agente com o Observer Service.

    Extrai insights de todas as conversas:
    - origin (facebook_ads, instagram, google_ads, etc)
    - speakers (quem falou na conversa)
    - sentiment (positivo, neutro, negativo)
    - summary (resumo da conversa)

    Args:
        agent_id: ID do agente
        batch_size: Numero de leads por batch

    Returns:
        Estatisticas do processamento
    """
    global _reanalyze_running, _reanalyze_progress

    from app.services.supabase import get_supabase_service
    from app.services.observer.observer import get_observer_service

    _reanalyze_running = True
    _reanalyze_progress = {
        "agent_id": agent_id,
        "status": "running",
        "total": 0,
        "processed": 0,
        "success": 0,
        "errors": 0,
        "skipped": 0,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
    }

    try:
        supabase = get_supabase_service()
        observer = get_observer_service()

        # Buscar agente
        agent = supabase.get_agent_by_id(agent_id)
        if not agent:
            _reanalyze_progress["status"] = "error"
            _reanalyze_progress["error"] = f"Agente {agent_id} nao encontrado"
            return _reanalyze_progress

        table_leads = agent.get("table_leads")
        table_messages = agent.get("table_messages")

        if not table_leads or not table_messages:
            _reanalyze_progress["status"] = "error"
            _reanalyze_progress["error"] = "Agente sem table_leads ou table_messages configurado"
            return _reanalyze_progress

        # Contar total de leads
        total_leads = supabase.count_leads(table_leads)
        _reanalyze_progress["total"] = total_leads

        logger.info(
            f"[REANALYZE] Iniciando processamento de {total_leads} leads para agente {agent.get('name', agent_id)}"
        )

        offset = 0
        while offset < total_leads:
            # Buscar batch de leads
            leads = supabase.get_all_leads(table_leads, limit=batch_size, offset=offset)

            for lead in leads:
                lead_id = lead.get("id")
                remotejid = lead.get("remotejid")
                lead_name = lead.get("nome", "Desconhecido")

                _reanalyze_progress["processed"] += 1
                _reanalyze_progress["current_lead"] = lead_name

                if not remotejid:
                    logger.debug(f"[REANALYZE] Lead {lead_id} sem remotejid, pulando")
                    _reanalyze_progress["skipped"] += 1
                    continue

                try:
                    # Verificar se tem historico
                    history = supabase.get_conversation_history(table_messages, remotejid)
                    if not history or not history.get("messages") or len(history.get("messages", [])) < 2:
                        logger.debug(f"[REANALYZE] Lead {lead_id} sem historico suficiente, pulando")
                        _reanalyze_progress["skipped"] += 1
                        continue

                    # Executar Observer
                    insights = await observer.analyze(
                        table_leads=table_leads,
                        table_messages=table_messages,
                        lead_id=lead_id,
                        remotejid=remotejid,
                        tools_used=None,
                        force=True,  # Ignora throttle
                        agent_id=agent_id,
                    )

                    if insights:
                        _reanalyze_progress["success"] += 1
                        origin = insights.get("origin", "unknown")
                        logger.debug(f"[REANALYZE] Lead {lead_id} ({lead_name}): origin={origin}")
                    else:
                        _reanalyze_progress["skipped"] += 1

                except Exception as e:
                    logger.error(f"[REANALYZE] Erro ao processar lead {lead_id}: {e}")
                    _reanalyze_progress["errors"] += 1

            offset += batch_size

            # Log de progresso a cada batch
            logger.info(
                f"[REANALYZE] Progresso: {_reanalyze_progress['processed']}/{total_leads} "
                f"(success={_reanalyze_progress['success']}, errors={_reanalyze_progress['errors']}, skipped={_reanalyze_progress['skipped']})"
            )

        _reanalyze_progress["status"] = "completed"
        _reanalyze_progress["finished_at"] = datetime.utcnow().isoformat()
        _reanalyze_progress.pop("current_lead", None)

        logger.info(
            f"[REANALYZE] Concluido! Total={total_leads}, Success={_reanalyze_progress['success']}, "
            f"Errors={_reanalyze_progress['errors']}, Skipped={_reanalyze_progress['skipped']}"
        )

        return _reanalyze_progress

    except Exception as e:
        logger.error(f"[REANALYZE] Erro fatal: {e}", exc_info=True)
        _reanalyze_progress["status"] = "error"
        _reanalyze_progress["error"] = str(e)
        _reanalyze_progress["finished_at"] = datetime.utcnow().isoformat()
        return _reanalyze_progress

    finally:
        _reanalyze_running = False


@router.post("/reanalyze-leads/{agent_id}")
async def reanalyze_leads(
    agent_id: str,
    background_tasks: BackgroundTasks,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """
    Executa o Observer Service em batch para reler todas as conversas de um agente.

    Extrai e atualiza insights de origem (facebook_ads, instagram, google_ads, etc),
    speakers, sentiment e summary para todos os leads.

    Args:
        agent_id: ID do agente (tenant)
        batch_size: Numero de leads por batch (default: 50)

    Returns:
        Status do job iniciado
    """
    global _reanalyze_running

    if _reanalyze_running:
        return {
            "status": "error",
            "message": "Job de reanalise ja esta em execucao",
            "progress": _reanalyze_progress,
        }

    background_tasks.add_task(_run_reanalyze_leads, agent_id, batch_size)

    return {
        "status": "started",
        "message": f"Reanalise de leads iniciada para agente {agent_id}",
        "batch_size": batch_size,
    }


@router.get("/reanalyze-leads/status")
async def reanalyze_leads_status() -> Dict[str, Any]:
    """
    Retorna o status atual do job de reanalise de leads.

    Returns:
        Progresso do job (total, processed, success, errors, skipped)
    """
    return {
        "running": _reanalyze_running,
        "progress": _reanalyze_progress,
    }
