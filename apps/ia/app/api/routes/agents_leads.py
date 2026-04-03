# ╔══════════════════════════════════════════════════════════════╗
# ║  AGENTS-LEADS — Implementação nativa Python                ║
# ╚══════════════════════════════════════════════════════════════╝
# apps/ia/app/api/routes/proxy_agnes.py
"""
Lista agentes com seus leads e métricas — consulta direta ao Supabase.

Endpoints:
- GET /api/agents-leads         -> lista agentes com leads_attended_by_ai
- GET /api/agents/{id}/metrics  -> métricas do agente
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import structlog

from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["agents-leads"])


@router.get("/agents-leads")
async def get_agents_leads(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """GET /api/agents-leads — Lista agentes com leads_attended_by_ai."""
    try:
        supabase = get_supabase_service()
        sb = supabase.client

        # Buscar agentes do usuário
        agents_resp = sb.table("agents").select(
            "id, name, agent_type, table_leads, table_messages, "
            "pipeline_stages, active"
        ).eq("user_id", user["id"]).execute()
        agents = agents_resp.data or []

        result_agents = []
        for agent in agents:
            agent_id = agent.get("id", "")
            table_leads = agent.get("table_leads")
            table_messages = agent.get("table_messages")

            # Contar leads atendidos por IA (Msg_model preenchido na tabela de mensagens)
            leads_attended = 0
            if table_messages:
                try:
                    att_resp = sb.table(table_messages).select(
                        "remotejid", count="exact"
                    ).not_.is_("Msg_model", "null").execute()
                    # Contar leads únicos que tiveram resposta de IA
                    leads_attended = att_resp.count or 0
                except Exception as e:
                    logger.warning("leads_attended_count_error",
                                   agent=agent_id, error=str(e))

            # Buscar leads para pipeline
            leads = []
            if table_leads:
                try:
                    leads_resp = sb.table(table_leads).select(
                        "id, nome, telefone, pipeline_step, lead_temperature, "
                        "Atendimento_Finalizado, created_date, status"
                    ).order("created_date", desc=True).limit(500).execute()
                    leads = leads_resp.data or []
                except Exception as e:
                    logger.warning("leads_fetch_error",
                                   agent=agent_id, table=table_leads, error=str(e))

            result_agents.append({
                "id": agent_id,
                "name": agent.get("name", ""),
                "type": agent.get("agent_type", "SDR"),
                "leads_attended_by_ai": leads_attended,
                "leads": leads,
                "pipeline_stages": agent.get("pipeline_stages") or [],
                "table_leads": table_leads,
                "active": agent.get("active", False),
            })

        return JSONResponse(content={
            "status": "success",
            "data": {"agents": result_agents},
        })

    except Exception as e:
        logger.exception("agents_leads_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )


@router.get("/agents/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """GET /api/agents/{id}/metrics — Métricas do agente."""
    try:
        supabase = get_supabase_service()
        sb = supabase.client

        agent_resp = sb.table("agents").select(
            "id, name, table_leads, table_messages, active"
        ).eq("id", agent_id).eq("user_id", user["id"]).limit(1).execute()

        if not agent_resp.data:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "error": "Agent not found"},
            )

        agent = agent_resp.data[0]
        table_messages = agent.get("table_messages")
        table_leads = agent.get("table_leads")

        total_messages = 0
        last_activity = None
        if table_messages:
            try:
                msg_resp = sb.table(table_messages).select(
                    "id", count="exact"
                ).execute()
                total_messages = msg_resp.count or 0

                last_resp = sb.table(table_messages).select(
                    "creat"
                ).order("creat", desc=True).limit(1).execute()
                if last_resp.data:
                    last_activity = last_resp.data[0].get("creat")
            except Exception:
                pass

        total_leads = 0
        if table_leads:
            try:
                leads_resp = sb.table(table_leads).select(
                    "id", count="exact"
                ).execute()
                total_leads = leads_resp.count or 0
            except Exception:
                pass

        return JSONResponse(content={
            "status": "success",
            "data": {
                "agent_id": agent_id,
                "total_messages": total_messages,
                "total_leads": total_leads,
                "last_activity": last_activity,
                "active": agent.get("active", False),
            },
        })

    except Exception as e:
        logger.exception("agent_metrics_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )
