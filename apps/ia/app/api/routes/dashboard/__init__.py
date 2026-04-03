# ╔══════════════════════════════════════════════════════════════╗
# ║  API DASHBOARD — Metricas e graficos (package)             ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Dashboard API Routes - Split into sub-modules.

Sub-routers:
  - stats.py: GET /api/dashboard/stats
  - categories.py: GET /api/dashboard/leads-by-category, GET /api/dashboard/health
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ============================================================================
# SHARED HELPER FUNCTIONS
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


# Import and include sub-routers
from app.api.routes.dashboard.stats import stats_router  # noqa: E402
from app.api.routes.dashboard.categories import categories_router  # noqa: E402

router.include_router(stats_router)
router.include_router(categories_router)
