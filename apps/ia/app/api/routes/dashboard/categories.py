# ╔══════════════════════════════════════════════════════════════╗
# ║  DASHBOARD — Leads by category + Health                    ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Endpoints:
  - GET /api/dashboard/leads-by-category
  - GET /api/dashboard/health
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

from app.services.supabase import get_supabase_service

from app.api.routes.dashboard import (
    _get_user_id_from_request,
    get_period_dates,
    is_outside_business_hours,
)

logger = logging.getLogger(__name__)

categories_router = APIRouter()


@categories_router.get("/leads-by-category")
async def get_leads_by_category(
    request: Request,
    category: str = Query(..., description="Categoria: total, qualified, hot, schedules, outside_hours"),
    period: str = Query(default="week", description="Período: day, week, month, total"),
    user_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Retorna leads filtrados por categoria (clique nos big numbers)."""
    uid = _get_user_id_from_request(request, user_id)
    supabase = get_supabase_service()

    agents_resp = (
        supabase.client.table("agents")
        .select("id, name, table_leads, timezone")
        .eq("user_id", uid)
        .execute()
    )
    agents = agents_resp.data or []

    if not agents:
        return {"status": "success", "data": {"leads": [], "category": category, "period": period}}

    period_start, _, _ = get_period_dates(period)
    period_iso = period_start.isoformat()

    category_titles = {
        "total": "Leads do Período",
        "qualified": "Leads Qualificados",
        "hot": "Leads Quentes",
        "schedules": "Agendamentos",
        "outside_hours": "Leads Fora do Horário",
    }

    # Schedules (tabela separada)
    if category == "schedules":
        agent_ids = [a.get("id") for a in agents]
        agent_map = {a["id"]: a["name"] for a in agents}

        try:
            query = (
                supabase.client.table("schedules")
                .select("id, agent_id, lead_id, customer_name, company_name, remote_jid, scheduled_at, status, created_at")
                .in_("agent_id", agent_ids)
                .order("scheduled_at", desc=True)
            )
            if period != "total":
                query = query.gte("scheduled_at", period_iso)

            sch_resp = query.execute()
            schedules = sch_resp.data or []

            formatted = []
            for s in schedules:
                phone = (s.get("remote_jid") or "").replace("@s.whatsapp.net", "").replace("unknown_", "")
                formatted.append({
                    "id": s.get("id"),
                    "nome": s.get("customer_name") or "Sem nome",
                    "telefone": phone or None,
                    "empresa": s.get("company_name"),
                    "agendamento": s.get("scheduled_at"),
                    "status": s.get("status"),
                    "agente": agent_map.get(s.get("agent_id", ""), "Desconhecido"),
                    "created_at": s.get("created_at"),
                })

            return {
                "status": "success",
                "data": {
                    "leads": formatted,
                    "category": category,
                    "period": period,
                    "title": category_titles.get(category, ""),
                },
            }
        except Exception as e:
            logger.error(f"[Dashboard] Error fetching schedules by category: {e}")
            return {"status": "success", "data": {"leads": [], "category": category, "period": period}}

    # Leads (outras categorias)
    all_leads: List[Dict] = []
    processed_tables = set()

    for agent in agents:
        table_leads = agent.get("table_leads")
        if not table_leads or table_leads in processed_tables:
            continue
        processed_tables.add(table_leads)

        timezone = agent.get("timezone", "America/Cuiaba")
        tz_offset = -4 if "Cuiaba" in (timezone or "") else -3

        try:
            query = (
                supabase.client.table(table_leads)
                .select("id, nome, telefone, remotejid, pipeline_step, lead_temperature, created_date, updated_date, status")
                .order("created_date", desc=True)
                .limit(200)
            )

            if category == "total":
                if period != "total":
                    query = query.gte("created_date", period_iso)

            elif category == "qualified":
                query = query.or_(
                    "pipeline_step.ilike.%qualificado%,"
                    "pipeline_step.ilike.%agendado%,"
                    "pipeline_step.ilike.%interessado%,"
                    "pipeline_step.ilike.%transferido%"
                )

            elif category == "hot":
                query = query.or_("lead_temperature.eq.hot,lead_temperature.eq.quente")

            elif category == "outside_hours":
                if period != "total":
                    query = query.gte("created_date", period_iso)

            resp = query.execute()
            leads = resp.data or []

            if category == "outside_hours":
                leads = [
                    l for l in leads
                    if is_outside_business_hours(l.get("created_date", ""), tz_offset)
                ]

            for l in leads:
                l["agente"] = agent.get("name", "")

            all_leads.extend(leads)

        except Exception as e:
            logger.warning(f"[Dashboard] Error fetching leads from {table_leads}: {e}")

    return {
        "status": "success",
        "data": {
            "leads": all_leads,
            "category": category,
            "period": period,
            "title": category_titles.get(category, ""),
        },
    }


@categories_router.get("/health")
async def dashboard_health() -> Dict[str, Any]:
    """Health check do módulo de dashboard."""
    return {
        "status": "ok",
        "module": "dashboard",
        "timestamp": datetime.utcnow().isoformat(),
    }
