# ╔══════════════════════════════════════════════════════════════╗
# ║  AGENTS CRUD — List, Get, Create, Update, Delete           ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Agent CRUD endpoints.
"""

import logging
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.security.prompt_sanitizer import validate_system_prompt
from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

crud_router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AgentCreate(BaseModel):
    name: str
    ai_provider: Optional[str] = "gemini"
    gemini_api_key: Optional[str] = None
    claude_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    claude_model: Optional[str] = None
    openai_model: Optional[str] = None
    system_prompt: str
    pipeline_stages: Optional[List[dict]] = None
    business_hours: Optional[dict] = None
    work_days: Optional[List[str]] = None
    timezone: Optional[str] = "America/Sao_Paulo"
    product_description: Optional[str] = None
    product_value: Optional[float] = None
    owner_phone: Optional[str] = None
    follow_up_enabled: Optional[bool] = False
    follow_up_config: Optional[dict] = None
    salvador_prompt: Optional[str] = None
    google_calendar_enabled: Optional[bool] = False
    asaas_enabled: Optional[bool] = False
    asaas_api_key: Optional[str] = None
    asaas_config: Optional[dict] = None
    response_size: Optional[str] = "medium"
    split_messages: Optional[bool] = True
    split_mode: Optional[str] = "paragraph"
    message_buffer_delay: Optional[int] = 9000
    qualification_enabled: Optional[bool] = True
    qualification_config: Optional[dict] = None
    agent_type: Optional[str] = "SDR"
    type: Optional[str] = "agnes"
    handoff_triggers: Optional[dict] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    ai_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    claude_api_key: Optional[str] = None
    claude_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    system_prompt: Optional[str] = None
    business_hours: Optional[dict] = None
    work_days: Optional[List[str]] = None
    timezone: Optional[str] = None
    product_description: Optional[str] = None
    product_value: Optional[float] = None
    follow_up_enabled: Optional[bool] = None
    follow_up_config: Optional[dict] = None
    salvador_prompt: Optional[str] = None
    google_calendar_enabled: Optional[bool] = None
    asaas_enabled: Optional[bool] = None
    asaas_api_key: Optional[str] = None
    asaas_config: Optional[dict] = None
    owner_phone: Optional[str] = None
    response_size: Optional[str] = None
    split_messages: Optional[bool] = None
    split_mode: Optional[str] = None
    message_buffer_delay: Optional[int] = None
    qualification_enabled: Optional[bool] = None
    qualification_config: Optional[dict] = None
    pipeline_stages: Optional[List[dict]] = None
    handoff_triggers: Optional[dict] = None


# ============================================================================
# API KEY VALIDATION
# ============================================================================

async def validate_gemini_key(api_key: str) -> Dict[str, Any]:
    """Validate Gemini API key with a test request."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                json={"contents": [{"parts": [{"text": "Hi"}]}]},
            )
            if resp.status_code == 200:
                return {"valid": True}
            if resp.status_code in (400, 403):
                return {"valid": False, "error": "API key invalida ou sem permissao"}
            return {"valid": True}
    except Exception:
        return {"valid": True}  # Network error, don't block


async def validate_claude_key(api_key: str) -> Dict[str, Any]:
    """Validate Claude/Anthropic API key with a test request."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                return {"valid": True}
            if resp.status_code in (401, 403):
                return {"valid": False, "error": "API key invalida"}
            return {"valid": True}
    except Exception:
        return {"valid": True}


async def validate_openai_key(api_key: str) -> Dict[str, Any]:
    """Validate OpenAI API key with a test request."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return {"valid": True}
            if resp.status_code in (401, 403):
                return {"valid": False, "error": "API key invalida"}
            return {"valid": True}
    except Exception:
        return {"valid": True}


# ============================================================================
# HELPERS
# ============================================================================

def _sanitize_table_name(name: str) -> str:
    """Sanitize agent name for PostgreSQL table names (PascalCase)."""
    normalized = unicodedata.normalize("NFD", name)
    clean = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean)
    words = clean.strip().split()
    pascal = "".join(w.capitalize() for w in words) if words else "Agent"
    if not pascal or not pascal[0].isalpha():
        pascal = "Agent" + pascal
    return pascal


def _execute_sql(sql: str) -> None:
    """Execute raw SQL via Supabase exec_sql RPC function."""
    svc = get_supabase_service()
    result = svc.client.rpc("exec_sql", {"query": sql}).execute()
    if hasattr(result, "error") and result.error:
        raise Exception(f"SQL error: {result.error}")


def _get_create_leads_sql(table_name: str) -> str:
    """Generate SQL to create the leads table."""
    safe = table_name.replace('"', '')
    idx = safe.lower().replace("-", "_")
    return f'''
CREATE TABLE IF NOT EXISTS "{safe}" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remotejid VARCHAR(50) NOT NULL,
    pushname VARCHAR(255),
    nome VARCHAR(255),
    empresa VARCHAR(255),
    email VARCHAR(255),
    telefone VARCHAR(50),
    pipeline_step VARCHAR(100) DEFAULT 'novo-lead',
    resumo TEXT,
    crm TEXT,
    "Msg_model" TIMESTAMP,
    "Msg_user" TIMESTAMP,
    "BANT" INTEGER DEFAULT 0,
    "FIT" INTEGER DEFAULT 0,
    bant_details JSONB,
    fit_details JSONB,
    follow_up_count INTEGER DEFAULT 0,
    follow_up_type VARCHAR(50),
    last_follow_up_at TIMESTAMP,
    next_follow_up_at TIMESTAMP,
    follow_up_opted_out BOOLEAN DEFAULT false,
    "Atendimento_Finalizado" VARCHAR(10) DEFAULT 'false',
    pausar_ia BOOLEAN DEFAULT false,
    paused_at TIMESTAMP,
    handoff_reason TEXT,
    handoff_at TIMESTAMP,
    current_queue_id INTEGER,
    current_user_id INTEGER,
    ticket_id INTEGER,
    dianaContext TEXT,
    timezone VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_{idx}_remotejid" ON "{safe}" (remotejid);
'''


def _get_create_messages_sql(table_name: str) -> str:
    """Generate SQL to create the messages table."""
    safe = table_name.replace('"', '')
    idx = safe.lower().replace("-", "_")
    return f'''
CREATE TABLE IF NOT EXISTS "{safe}" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remotejid VARCHAR(50) NOT NULL,
    conversation_history JSONB DEFAULT '{{"messages": []}}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_{idx}_remotejid" ON "{safe}" (remotejid);
'''


def _get_create_msg_temp_sql(table_name: str) -> str:
    """Generate SQL to create the message buffer table."""
    safe = table_name.replace('"', '')
    idx = safe.lower().replace("-", "_")
    return f'''
CREATE TABLE IF NOT EXISTS "{safe}" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remotejid VARCHAR(50) NOT NULL,
    messages JSONB DEFAULT '[]'::jsonb,
    processing BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS "idx_{idx}_remotejid" ON "{safe}" (remotejid);
'''


def _get_agent_or_404(agent_id: str, user_id: str) -> Dict[str, Any]:
    """Fetch agent ensuring it belongs to the user. Raises 404 if not found."""
    svc = get_supabase_service()
    result = (
        svc.client.table("agents")
        .select("*")
        .eq("id", agent_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Agente nao encontrado")
    return result.data[0]


async def _delete_uazapi_instance(base_url: str, token: str) -> None:
    """Delete a UAZAPI instance (disconnect + delete)."""
    base = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Logout first
            try:
                await client.post(
                    f"{base}/instance/logout",
                    headers={"token": token, "Content-Type": "application/json"},
                )
            except Exception:
                pass
            # Delete
            await client.delete(
                f"{base}/instance/delete",
                headers={"token": token, "Content-Type": "application/json"},
            )
    except Exception as e:
        logger.warning(f"Error deleting UAZAPI instance: {e}")


# ============================================================================
# ENDPOINTS
# ============================================================================

# ---------------------------------------------------------------------------
# 1. GET /api/agents/list
# ---------------------------------------------------------------------------

@crud_router.get("/list")
async def list_agents(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """List all agents for the authenticated user."""
    svc = get_supabase_service()
    user_id = user["id"]

    result = (
        svc.client.table("agents")
        .select("id,name,type,agent_type,status,avatar_url,uazapi_connected,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return {"status": "success", "agents": result.data or [], "total": len(result.data or [])}


# ---------------------------------------------------------------------------
# 2. GET /api/agents/{agent_id}
# ---------------------------------------------------------------------------

@crud_router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get full agent details (verifies ownership)."""
    agent = _get_agent_or_404(agent_id, user["id"])
    return {"status": "success", "agent": agent}


# ---------------------------------------------------------------------------
# 3. POST /api/agents/create
# ---------------------------------------------------------------------------

@crud_router.post("/create", status_code=201)
async def create_agent(
    body: AgentCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new AI agent with dynamic tables."""
    svc = get_supabase_service()
    user_id = user["id"]
    agent_id = str(uuid.uuid4())
    short_id = agent_id[:8]

    logger.info(f"[CreateAgent] user={user_id} name={body.name}")

    # --- Validate required fields ---
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Campo obrigatorio: name")
    if not body.system_prompt or not body.system_prompt.strip():
        raise HTTPException(status_code=400, detail="Campo obrigatorio: system_prompt")

    # --- Validate AI API key ---
    ai_provider = body.ai_provider or "gemini"
    try:
        if ai_provider == "gemini" and body.gemini_api_key:
            v = await validate_gemini_key(body.gemini_api_key)
            if not v.get("valid"):
                raise HTTPException(status_code=400, detail=f"API key do Gemini invalida: {v.get('error', '')}")
        if ai_provider == "claude":
            if not body.claude_api_key:
                raise HTTPException(status_code=400, detail="Campo obrigatorio: claude_api_key")
            v = await validate_claude_key(body.claude_api_key)
            if not v.get("valid"):
                raise HTTPException(status_code=400, detail=f"API key do Claude invalida: {v.get('error', '')}")
        if ai_provider == "openai":
            if not body.openai_api_key:
                raise HTTPException(status_code=400, detail="Campo obrigatorio: openai_api_key")
            v = await validate_openai_key(body.openai_api_key)
            if not v.get("valid"):
                raise HTTPException(status_code=400, detail=f"API key do OpenAI invalida: {v.get('error', '')}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"API key validation skipped: {e}")

    # --- Check agent limit per type (max 2) ---
    agent_type_value = body.type or "agnes"
    existing = (
        svc.client.table("agents")
        .select("id,name")
        .eq("user_id", user_id)
        .eq("type", agent_type_value)
        .execute()
    )
    if len(existing.data or []) >= 2:
        raise HTTPException(
            status_code=400,
            detail=f"Limite atingido: voce ja possui 2 agentes do tipo {agent_type_value}.",
        )

    # --- Generate table names ---
    sanitized_name = _sanitize_table_name(body.name)
    table_leads = f"LeadboxCRM_{sanitized_name}_{short_id}"
    table_messages = f"leadbox_messages_{sanitized_name}_{short_id}"
    table_msg_temp = f"msg_temp_{sanitized_name}_{short_id}"

    logger.info(f"[CreateAgent] tables: {table_leads}, {table_messages}, {table_msg_temp}")

    # --- Create dynamic tables ---
    try:
        sql = (
            _get_create_leads_sql(table_leads)
            + _get_create_messages_sql(table_messages)
            + _get_create_msg_temp_sql(table_msg_temp)
        )
        _execute_sql(sql)
        logger.info("[CreateAgent] Dynamic tables created")
    except Exception as e:
        logger.error(f"[CreateAgent] Failed to create tables: {e}")
        raise HTTPException(status_code=500, detail="Falha ao criar tabelas dinamicas")

    # --- Build agent data ---
    pipeline_stages = body.pipeline_stages or [
        {"id": "novo-lead", "name": "Novo Lead", "order": 0},
        {"id": "qualificado", "name": "Qualificado", "order": 1},
        {"id": "agendado", "name": "Agendado", "order": 2},
        {"id": "convertido", "name": "Convertido", "order": 3},
        {"id": "perdido", "name": "Perdido", "order": 4},
    ]

    agent_data: Dict[str, Any] = {
        "id": agent_id,
        "user_id": user_id,
        "name": body.name.strip(),
        "status": "active",
        "active": True,
        "type": agent_type_value,
        "agent_type": body.agent_type or "SDR",
        # WhatsApp - instance created later via /qrcode
        "whatsapp_provider": "uazapi",
        "uazapi_instance_id": None,
        "uazapi_token": None,
        "uazapi_base_url": settings.uazapi_base_url,
        "uazapi_connected": False,
        # Dynamic tables
        "table_leads": table_leads,
        "table_messages": table_messages,
        "table_msg_temp": table_msg_temp,
        # AI config
        "ai_provider": ai_provider,
        "gemini_api_key": body.gemini_api_key,
        "gemini_model": body.gemini_model or "gemini-2.5-flash",
        "claude_api_key": body.claude_api_key,
        "claude_model": body.claude_model or "claude-sonnet-4-20250514",
        "openai_api_key": body.openai_api_key,
        "openai_model": body.openai_model or "gpt-4o-mini",
        "owner_phone": body.owner_phone,
        "system_prompt": body.system_prompt,
        # Calendar / Payments
        "google_calendar_enabled": body.google_calendar_enabled or False,
        "asaas_enabled": body.asaas_enabled or False,
        "asaas_api_key": body.asaas_api_key,
        "asaas_config": body.asaas_config,
        # Product
        "product_description": body.product_description,
        "product_value": body.product_value,
        # Business
        "business_hours": body.business_hours or {"start": "08:00", "end": "17:00"},
        "work_days": body.work_days or ["seg", "ter", "qua", "qui", "sex"],
        "timezone": body.timezone or "America/Sao_Paulo",
        "pipeline_stages": pipeline_stages,
        # Response
        "response_size": body.response_size or "medium",
        "split_messages": body.split_messages if body.split_messages is not None else True,
        "split_mode": body.split_mode or "paragraph",
        "message_buffer_delay": body.message_buffer_delay or 9000,
        # Follow-up (Salvador)
        "follow_up_enabled": body.follow_up_enabled or False,
        "salvador_prompt": body.salvador_prompt,
        "follow_up_config": body.follow_up_config or {
            "steps": [
                {"delayMinutes": 10},
                {"delayMinutes": 60},
                {"delayMinutes": 1440},
            ],
        },
        # Qualification
        "qualification_enabled": body.qualification_enabled if body.qualification_enabled is not None else True,
        "qualification_config": body.qualification_config,
        # Handoff
        "handoff_triggers": body.handoff_triggers,
        "handoff_enabled": bool(body.handoff_triggers and body.handoff_triggers.get("enabled")),
    }

    # --- Insert agent ---
    try:
        insert_result = (
            svc.client.table("agents")
            .insert(agent_data)
            .execute()
        )
        logger.info(f"[CreateAgent] Agent {agent_id} saved")
    except Exception as e:
        logger.error(f"[CreateAgent] Failed to insert agent: {e}")
        # Rollback: drop tables
        try:
            _execute_sql(
                f'DROP TABLE IF EXISTS "{table_leads}" CASCADE;'
                f'DROP TABLE IF EXISTS "{table_messages}" CASCADE;'
                f'DROP TABLE IF EXISTS "{table_msg_temp}" CASCADE;'
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Falha ao salvar agente")

    webhook_url = f"{settings.api_base_url or 'https://lazaro.fazinzz.com'}/webhooks/dynamic"

    return {
        "status": "success",
        "agent_id": agent_id,
        "qr_code_url": f"/api/agents/{agent_id}/qrcode",
        "webhook_url": webhook_url,
        "message": "Agente criado com sucesso",
    }


# ---------------------------------------------------------------------------
# 4. PUT /api/agents/{agent_id}
# ---------------------------------------------------------------------------

@crud_router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update agent configuration."""
    svc = get_supabase_service()
    # Verify ownership
    _get_agent_or_404(agent_id, user["id"])

    # Build update dict from non-None fields
    update_data: Dict[str, Any] = {}
    for field_name, value in body.model_dump(exclude_unset=True).items():
        # Validar system_prompt contra prompt injection
        if field_name == "system_prompt" and value:
            is_valid, reason = validate_system_prompt(value)
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"System prompt contem padroes nao permitidos: {reason}"
                )
        update_data[field_name] = value

    if not update_data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    update_data["updated_at"] = datetime.utcnow().isoformat()

    try:
        svc.client.table("agents").update(update_data).eq("id", agent_id).execute()
    except Exception as e:
        logger.error(f"[UpdateAgent] Error: {e}")
        raise HTTPException(status_code=500, detail="Falha ao atualizar agente")

    return {"status": "success", "message": "Agente atualizado"}


# ---------------------------------------------------------------------------
# 5. DELETE /api/agents/{agent_id}
# ---------------------------------------------------------------------------

@crud_router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete agent and all related data (tables, UAZAPI instance)."""
    svc = get_supabase_service()
    agent = _get_agent_or_404(agent_id, user["id"])

    logger.info(f"[DeleteAgent] Deleting agent {agent_id} ({agent.get('name')})")

    # 1. Delete UAZAPI instance if exists
    uazapi_token = agent.get("uazapi_token")
    uazapi_base_url = agent.get("uazapi_base_url")
    uazapi_instance_id = agent.get("uazapi_instance_id")

    if uazapi_instance_id and uazapi_token and uazapi_base_url:
        if not str(uazapi_instance_id).startswith("CREATING:"):
            await _delete_uazapi_instance(uazapi_base_url, uazapi_token)
            logger.info(f"[DeleteAgent] UAZAPI instance deleted: {uazapi_instance_id}")

    # 2. Drop dynamic tables
    table_leads = agent.get("table_leads")
    table_messages = agent.get("table_messages")
    table_msg_temp = agent.get("table_msg_temp")

    drop_parts = []
    if table_leads:
        safe = table_leads.replace('"', '')
        drop_parts.append(f'DROP TABLE IF EXISTS "{safe}" CASCADE;')
    if table_messages:
        safe = table_messages.replace('"', '')
        drop_parts.append(f'DROP TABLE IF EXISTS "{safe}" CASCADE;')
    if table_msg_temp:
        safe = table_msg_temp.replace('"', '')
        drop_parts.append(f'DROP TABLE IF EXISTS "{safe}" CASCADE;')

    if drop_parts:
        try:
            _execute_sql("\n".join(drop_parts))
            logger.info("[DeleteAgent] Dynamic tables dropped")
        except Exception as e:
            logger.warning(f"[DeleteAgent] Error dropping tables: {e}")

    # 3. Delete agent record
    try:
        svc.client.table("agents").delete().eq("id", agent_id).execute()
        logger.info("[DeleteAgent] Agent record deleted")
    except Exception as e:
        logger.error(f"[DeleteAgent] Error deleting agent record: {e}")
        raise HTTPException(status_code=500, detail="Falha ao deletar agente")

    return {"status": "success", "message": "Agente e dados deletados com sucesso"}
