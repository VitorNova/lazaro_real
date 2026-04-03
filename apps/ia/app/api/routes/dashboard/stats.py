# ╔══════════════════════════════════════════════════════════════╗
# ║  DASHBOARD — GET /api/dashboard/stats                      ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Endpoint de estatísticas completas do dashboard.
Compatível com o frontend em /var/www/phant/crm/index.html
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

from app.services.supabase import get_supabase_service

from app.api.routes.dashboard import (
    MONTH_MAP,
    MONTH_ORDER,
    SOURCE_COLORS,
    _get_user_id_from_request,
    calculate_change,
    format_time_ago,
    get_agent_color,
    get_period_dates,
    is_outside_business_hours,
)

logger = logging.getLogger(__name__)

stats_router = APIRouter()


@stats_router.get("/stats")
async def get_dashboard_stats(
    request: Request,
    period: str = Query(default="total", description="Período: day, week, month, total"),
    user_id: Optional[str] = Query(default=None, description="Filtrar por user_id (legado)"),
) -> Dict[str, Any]:
    """
    Retorna estatísticas completas do dashboard.
    Formato compatível com o frontend (camelCase).
    """
    uid = _get_user_id_from_request(request, user_id)
    supabase = get_supabase_service()

    agents_resp = (
        supabase.client
        .table("agents")
        .select("*")
        .eq("user_id", uid)
        .execute()
    )
    agents = agents_resp.data or []

    if not agents:
        return {
            "status": "success",
            "data": {
                "totalLeads": 0, "totalLeadsChange": "0%",
                "leadsQualified": 0, "leadsQualifiedChange": "0%",
                "conversionRate": 0, "conversionRateChange": "0%",
                "schedulesTotal": 0, "schedulesTotalChange": "0%",
                "leadsOutsideHours": 0, "leadsOutsideHoursChange": "0%",
                "leadsByTemperature": {"hot": 0, "warm": 0, "cold": 0},
                "leadsOverTime": [],
                "leadSources": [],
                "agentsPerformance": [],
                "period": period,
            },
        }

    period_start, prev_start, prev_end = get_period_dates(period)
    period_iso = period_start.isoformat()
    prev_start_iso = prev_start.isoformat()
    prev_end_iso = prev_end.isoformat()

    # Contadores globais
    total_leads = 0
    total_leads_prev = 0
    leads_qualified = 0
    leads_qualified_prev = 0
    leads_converted = 0
    leads_outside_hours = 0
    leads_outside_hours_prev = 0
    temperature = {"hot": 0, "warm": 0, "cold": 0}
    timeline_map: Dict[str, int] = {}
    sources_map: Dict[str, int] = {}
    agents_performance: List[Dict[str, Any]] = []

    processed_leads_tables = set()
    processed_messages_tables = set()

    for agent in agents:
        table_leads = agent.get("table_leads")
        table_messages = agent.get("table_messages")
        agent_id = agent.get("id", "")
        agent_name = agent.get("name", "Unknown")
        agent_type = agent.get("agent_type", "SDR")
        timezone = agent.get("timezone", "America/Cuiaba")
        tz_offset = -4 if "Cuiaba" in (timezone or "") else -3

        agent_leads_count = 0
        pipeline_counts: Dict[str, int] = {}

        if table_leads and table_leads not in processed_leads_tables:
            processed_leads_tables.add(table_leads)

            try:
                # Count leads do período
                count_resp = (
                    supabase.client.table(table_leads)
                    .select("id", count="exact")
                    .gte("created_date", period_iso)
                    .execute()
                )
                period_count = count_resp.count or 0
                total_leads += period_count
                agent_leads_count = period_count

                # Count leads período anterior
                prev_resp = (
                    supabase.client.table(table_leads)
                    .select("id", count="exact")
                    .gte("created_date", prev_start_iso)
                    .lt("created_date", prev_end_iso)
                    .execute()
                )
                total_leads_prev += prev_resp.count or 0

                # Leads qualificados
                qual_resp = (
                    supabase.client.table(table_leads)
                    .select("id", count="exact")
                    .or_(
                        "pipeline_step.ilike.%qualificado%,"
                        "pipeline_step.ilike.%agendado%,"
                        "pipeline_step.ilike.%interessado%,"
                        "pipeline_step.ilike.%transferido%"
                    )
                    .execute()
                )
                leads_qualified += qual_resp.count or 0

                # Leads convertidos
                conv_resp = (
                    supabase.client.table(table_leads)
                    .select("id", count="exact")
                    .or_(
                        "status.ilike.%ganho%,"
                        "status.ilike.%fechado%,"
                        "status.ilike.%convertido%"
                    )
                    .execute()
                )
                leads_converted += conv_resp.count or 0

                # Leads com data (timeline, sources, temperature, outside hours)
                leads_data_resp = (
                    supabase.client.table(table_leads)
                    .select("created_date, lead_origin, lead_temperature, pipeline_step")
                    .order("created_date", desc=True)
                    .limit(1000)
                    .execute()
                )
                leads_data = leads_data_resp.data or []

                # Leads do período (outside hours)
                leads_period_resp = (
                    supabase.client.table(table_leads)
                    .select("created_date")
                    .gte("created_date", period_iso)
                    .execute()
                )
                leads_period = leads_period_resp.data or []

                # Leads do período anterior (outside hours prev)
                leads_prev_resp = (
                    supabase.client.table(table_leads)
                    .select("created_date")
                    .gte("created_date", prev_start_iso)
                    .lt("created_date", prev_end_iso)
                    .execute()
                )
                leads_prev = leads_prev_resp.data or []

                # Calcular fora do horário
                for lead in leads_period:
                    if is_outside_business_hours(lead.get("created_date", ""), tz_offset):
                        leads_outside_hours += 1

                for lead in leads_prev:
                    if is_outside_business_hours(lead.get("created_date", ""), tz_offset):
                        leads_outside_hours_prev += 1

                # Processar dados para gráficos
                for lead in leads_data:
                    temp = (lead.get("lead_temperature") or "cold").lower()
                    if temp in ("hot", "quente"):
                        temperature["hot"] += 1
                    elif temp in ("warm", "morno"):
                        temperature["warm"] += 1
                    else:
                        temperature["cold"] += 1

                    cd = lead.get("created_date")
                    if cd:
                        try:
                            dt = datetime.fromisoformat(cd.replace("Z", "+00:00"))
                            month_key = MONTH_MAP.get(dt.month, "?")
                            timeline_map[month_key] = timeline_map.get(month_key, 0) + 1
                        except Exception:
                            pass

                    origin = lead.get("lead_origin") or "Direto"
                    sources_map[origin] = sources_map.get(origin, 0) + 1

                    step = lead.get("pipeline_step") or "Novo"
                    pipeline_counts[step] = pipeline_counts.get(step, 0) + 1

            except Exception as e:
                logger.error(f"[Dashboard] Error processing leads table {table_leads}: {e}")

        # Agent metrics (mensagens, última atividade)
        last_activity = None
        mensagens_count = 0

        if table_messages and table_messages not in processed_messages_tables:
            processed_messages_tables.add(table_messages)

            try:
                last_msg_resp = (
                    supabase.client.table(table_messages)
                    .select("creat")
                    .order("creat", desc=True)
                    .limit(1)
                    .execute()
                )
                if last_msg_resp.data:
                    last_activity = last_msg_resp.data[0].get("creat")

                msg_count_resp = (
                    supabase.client.table(table_messages)
                    .select("id", count="exact")
                    .execute()
                )
                mensagens_count = msg_count_resp.count or 0

            except Exception as e:
                logger.warning(f"[Dashboard] Error fetching messages for {agent_name}: {e}")

        # SDR-specific metrics
        agendamentos_ia = 0
        qualificados_count = 0

        if agent_type == "SDR":
            try:
                sch_resp = (
                    supabase.client.table("schedules")
                    .select("id", count="exact")
                    .eq("agent_id", agent_id)
                    .execute()
                )
                agendamentos_ia = sch_resp.count or 0
            except Exception:
                pass

            if table_leads:
                try:
                    q_resp = (
                        supabase.client.table(table_leads)
                        .select("id", count="exact")
                        .eq("pipeline_step", "qualificado")
                        .execute()
                    )
                    qualificados_count = q_resp.count or 0
                except Exception:
                    pass

        # Montar agent performance
        buffer_delay_ms = agent.get("message_buffer_delay") or 14000
        tempo_resposta = f"{round(buffer_delay_ms / 1000)}s"

        agent_metrics = {
            "tempoResposta": tempo_resposta,
            "leadsAtendidos": agent_leads_count,
            "mensagensEnviadas": mensagens_count,
            "agendamentosIA": agendamentos_ia,
            "leadsQualificados": qualificados_count,
        }

        pipeline_cards = [
            {"etapa": etapa, "quantidade": qtd}
            for etapa, qtd in pipeline_counts.items()
        ]

        agents_performance.append({
            "id": agent_id,
            "name": agent_name,
            "type": agent_type or "SDR",
            "color": get_agent_color(agent_type),
            "status": "online" if agent.get("active") else "offline",
            "metrics": agent_metrics,
            "pipelineCards": pipeline_cards,
            "lastActivity": format_time_ago(last_activity),
        })

    # Agendamentos globais
    schedules_total = 0
    schedules_prev = 0
    agent_ids = [a.get("id") for a in agents if a.get("id")]

    if agent_ids:
        try:
            sch_period_resp = (
                supabase.client.table("schedules")
                .select("id", count="exact")
                .in_("agent_id", agent_ids)
                .gte("scheduled_at", period_iso)
                .execute()
            )
            schedules_total = sch_period_resp.count or 0

            sch_prev_resp = (
                supabase.client.table("schedules")
                .select("id", count="exact")
                .in_("agent_id", agent_ids)
                .gte("scheduled_at", prev_start_iso)
                .lt("scheduled_at", prev_end_iso)
                .execute()
            )
            schedules_prev = sch_prev_resp.count or 0
        except Exception as e:
            logger.warning(f"[Dashboard] Error fetching schedules: {e}")

    # Métricas derivadas
    conversion_rate = round((leads_converted / total_leads) * 100, 1) if total_leads > 0 else 0
    prev_conversion = round((leads_converted / total_leads_prev) * 100, 1) if total_leads_prev > 0 else 0

    leads_over_time = [
        {"name": month, "leads": timeline_map[month]}
        for month in MONTH_ORDER
        if month in timeline_map
    ]

    total_source_leads = sum(sources_map.values())
    lead_sources = sorted(sources_map.items(), key=lambda x: x[1], reverse=True)[:5]
    lead_sources_formatted = [
        {
            "name": name,
            "value": round((count / total_source_leads) * 100) if total_source_leads > 0 else 0,
            "color": SOURCE_COLORS.get(name, "#6B7280"),
        }
        for name, count in lead_sources
    ]

    stats = {
        "totalLeads": total_leads,
        "totalLeadsChange": calculate_change(total_leads, total_leads_prev),
        "leadsQualified": leads_qualified,
        "leadsQualifiedChange": calculate_change(leads_qualified, leads_qualified_prev),
        "conversionRate": conversion_rate,
        "conversionRateChange": calculate_change(int(conversion_rate * 10), int(prev_conversion * 10)),
        "schedulesTotal": schedules_total,
        "schedulesTotalChange": calculate_change(schedules_total, schedules_prev),
        "leadsOutsideHours": leads_outside_hours,
        "leadsOutsideHoursChange": calculate_change(leads_outside_hours, leads_outside_hours_prev),
        "leadsByTemperature": temperature,
        "leadsOverTime": leads_over_time,
        "leadSources": lead_sources_formatted,
        "agentsPerformance": agents_performance,
        "period": period,
    }

    logger.info(
        f"[Dashboard] Stats: {total_leads} leads, {leads_qualified} qualified, "
        f"{schedules_total} schedules, {leads_outside_hours} outside hours"
    )

    return {"status": "success", "data": stats}
