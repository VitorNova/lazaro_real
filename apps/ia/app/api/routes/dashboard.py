"""
Dashboard API Routes - Migrated from Node.js (agnes-agent)

Endpoints para estatísticas do dashboard Leadbox IA.
Compatível com o frontend em /var/www/phant/crm/index.html
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request, HTTPException

from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_period_dates(period: str) -> Tuple[datetime, datetime, datetime]:
    """
    Calcula datas de início do período atual e anterior.
    Retorna: (period_start, prev_period_start, prev_period_end)
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "day":
        period_start = today_start
        prev_start = today_start - timedelta(days=1)
        prev_end = today_start

    elif period == "month":
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_end = period_start - timedelta(days=1)
        prev_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_end = period_start

    elif period == "total":
        period_start = datetime(2020, 1, 1)
        prev_start = datetime(2019, 1, 1)
        prev_end = datetime(2020, 1, 1)

    else:  # week (default)
        days_since_sunday = now.isoweekday() % 7
        week_start = today_start - timedelta(days=days_since_sunday)
        period_start = week_start
        prev_start = week_start - timedelta(weeks=1)
        prev_end = week_start

    return period_start, prev_start, prev_end


def is_outside_business_hours(
    created_date_str: str,
    timezone_offset_hours: int = -4,
    start_hour: int = 8,
    end_hour: int = 17,
) -> bool:
    """
    Verifica se um lead foi criado fora do horário comercial.
    Default: America/Cuiaba (UTC-4), 8h-17h, seg-sex.
    """
    try:
        if not created_date_str:
            return False
        dt_str = created_date_str.replace("Z", "+00:00")
        if "+" not in dt_str and "-" not in dt_str[10:]:
            dt_str += "+00:00"
        dt = datetime.fromisoformat(dt_str)
        local_dt = dt + timedelta(hours=timezone_offset_hours)
        hour = local_dt.hour
        weekday = local_dt.weekday()
        return hour < start_hour or hour >= end_hour or weekday >= 5
    except Exception:
        return False


def calculate_change(current: int, previous: int) -> str:
    """Calcula variação percentual entre períodos."""
    if previous == 0:
        return "+100%" if current > 0 else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def format_time_ago(date_str: Optional[str]) -> str:
    """Formata tempo relativo."""
    if not date_str:
        return "Nunca"
    try:
        then = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(then.tzinfo) if then.tzinfo else datetime.utcnow()
        diff = now - then
        minutes = int(diff.total_seconds() / 60)
        hours = int(diff.total_seconds() / 3600)
        days = diff.days

        if minutes < 1:
            return "Agora"
        if minutes < 60:
            return f"Ha {minutes} minutos"
        if hours < 24:
            return f"Ha {hours} horas"
        return f"Ha {days} dias"
    except Exception:
        return "Nunca"


def get_agent_color(agent_type: str) -> str:
    """Retorna cor do agente baseado no tipo."""
    t = (agent_type or "").lower()
    if t in ("agnes", "sdr"):
        return "violet"
    if t in ("salvador", "followup"):
        return "amber"
    if t == "diana":
        return "blue"
    return "gray"


MONTH_ORDER = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MONTH_MAP = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

SOURCE_COLORS = {
    "Facebook": "#1877F2", "facebook": "#1877F2", "facebook_ads": "#1877F2",
    "WhatsApp": "#25D366", "whatsapp": "#25D366",
    "Direto": "#6B7280", "direto": "#6B7280",
    "Google": "#4285F4", "google": "#4285F4",
    "Prospeccao": "#3B82F6", "prospeccao": "#3B82F6",
    "diana": "#8B5CF6", "diana_handoff": "#8B5CF6",
    "Indicacao": "#10B981", "indicacao": "#10B981",
    "organic": "#059669", "manual": "#64748B",
}


def _get_user_id_from_request(request: Request, query_user_id: Optional[str] = None) -> str:
    """
    Extrai user_id do JWT.

    SECURITY FIX: Removido fallback para query_user_id (CVE bypass auth).
    O parâmetro query_user_id é mantido por compatibilidade de assinatura,
    mas NUNCA é usado como fonte de autenticação.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        try:
            svc = get_supabase_service()
            user_resp = svc.client.auth.get_user(token)
            if user_resp and user_resp.user:
                return user_resp.user.id
        except Exception as e:
            logger.warning(f"[Dashboard] JWT auth failed: {e}")

    # SECURITY: Fallback para query_user_id REMOVIDO
    # Anteriormente: if query_user_id: return query_user_id

    raise HTTPException(status_code=401, detail="Authentication required")


# ============================================================================
# GET /api/dashboard/stats
# ============================================================================

@router.get("/stats")
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


# ============================================================================
# GET /api/dashboard/leads-by-category
# ============================================================================

@router.get("/leads-by-category")
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


# ============================================================================
# GET /api/dashboard/health
# ============================================================================

@router.get("/health")
async def dashboard_health() -> Dict[str, Any]:
    """Health check do módulo de dashboard."""
    return {
        "status": "ok",
        "module": "dashboard",
        "timestamp": datetime.utcnow().isoformat(),
    }
