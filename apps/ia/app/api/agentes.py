"""
Agents CRUD API.

Provides endpoints for managing AI agents:
- List, Get, Create, Update, Delete agents
- QR code for WhatsApp connection
- Connection status check
- Disconnect from WhatsApp
"""

import logging
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

agents_router = APIRouter(prefix="/agents", tags=["agents"])


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


async def _create_uazapi_instance(instance_name: str, webhook_url: str) -> Dict[str, str]:
    """
    Create a UAZAPI instance via the admin API.

    Uses settings.uazapi_api_key as the admin token.
    Returns {"instance_id": ..., "token": ...}.
    """
    base_url = settings.uazapi_base_url.rstrip("/")
    admin_token = settings.uazapi_api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create instance
        resp = await client.post(
            f"{base_url}/instance/create",
            json={"instanceName": instance_name},
            headers={
                "admintoken": admin_token,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        instance_id = data.get("instance", {}).get("id", "")
        token = data.get("token", "")

        # Configure webhook on the new instance
        if token:
            try:
                await client.post(
                    f"{base_url}/webhook/set",
                    json={
                        "url": webhook_url,
                        "events": ["messages", "connection"],
                    },
                    headers={
                        "token": token,
                        "Content-Type": "application/json",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to set webhook on new instance: {e}")

        return {"instance_id": instance_id, "token": token}


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

@agents_router.get("/list")
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

@agents_router.get("/{agent_id}")
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

@agents_router.post("/create", status_code=201)
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

@agents_router.put("/{agent_id}")
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

@agents_router.delete("/{agent_id}")
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
            logger.info(f"[DeleteAgent] Dynamic tables dropped")
        except Exception as e:
            logger.warning(f"[DeleteAgent] Error dropping tables: {e}")

    # 3. Delete agent record
    try:
        svc.client.table("agents").delete().eq("id", agent_id).execute()
        logger.info(f"[DeleteAgent] Agent record deleted")
    except Exception as e:
        logger.error(f"[DeleteAgent] Error deleting agent record: {e}")
        raise HTTPException(status_code=500, detail="Falha ao deletar agente")

    return {"status": "success", "message": "Agente e dados deletados com sucesso"}


# ---------------------------------------------------------------------------
# 6. GET /api/agents/{agent_id}/qrcode
# ---------------------------------------------------------------------------

@agents_router.get("/{agent_id}/qrcode")
async def get_qrcode(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get QR code for WhatsApp connection.

    If no UAZAPI instance exists, creates one first.
    """
    svc = get_supabase_service()
    agent = _get_agent_or_404(agent_id, user["id"])

    instance_id = agent.get("uazapi_instance_id")
    base_url = agent.get("uazapi_base_url") or settings.uazapi_base_url
    token = agent.get("uazapi_token")

    # Handle stale creation locks
    if instance_id and str(instance_id).startswith("CREATING:"):
        parts = str(instance_id).replace("CREATING:", "").split(":")
        try:
            lock_ts = int(parts[0])
        except (ValueError, IndexError):
            lock_ts = 0
        if (int(datetime.utcnow().timestamp() * 1000) - lock_ts) < 45000:
            return {
                "status": "pending",
                "error": "Criacao de instancia em andamento. Aguarde.",
                "retry_after": 3,
            }
        # Lock expired, clear it
        instance_id = None
        token = None

    # --- If already connected, return status ---
    if agent.get("uazapi_connected") and base_url and token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/instance/status",
                    headers={"token": token, "Content-Type": "application/json"},
                )
                data = resp.json()
                if data.get("connected") or data.get("status") == "open":
                    return {
                        "status": "connected",
                        "phone_number": data.get("phoneNumber", ""),
                    }
        except Exception:
            pass
        # Not really connected, update DB
        svc.client.table("agents").update({"uazapi_connected": False}).eq("id", agent_id).execute()

    # --- Create instance if needed ---
    if not instance_id or not token:
        logger.info(f"[QRCode] Creating UAZAPI instance for agent {agent_id}")

        # Set lock
        lock_value = f"CREATING:{int(datetime.utcnow().timestamp() * 1000)}:{uuid.uuid4().hex[:8]}"
        svc.client.table("agents").update({"uazapi_instance_id": lock_value}).eq("id", agent_id).execute()

        try:
            short_id = agent_id.split("-")[0] if "-" in agent_id else agent_id[:8]
            instance_name = f"Agent_{short_id}"
            webhook_url = f"{settings.api_base_url or 'https://lazaro.fazinzz.com'}/webhooks/dynamic"

            result = await _create_uazapi_instance(instance_name, webhook_url)

            new_instance_id = result["instance_id"]
            new_token = result["token"]

            # Save real instance data (replaces lock)
            svc.client.table("agents").update({
                "whatsapp_provider": "uazapi",
                "uazapi_instance_id": new_instance_id,
                "uazapi_base_url": base_url,
                "uazapi_token": new_token,
                "uazapi_connected": False,
            }).eq("id", agent_id).execute()

            instance_id = new_instance_id
            token = new_token
            logger.info(f"[QRCode] Instance created: {new_instance_id}")

        except Exception as e:
            # Release lock
            svc.client.table("agents").update({
                "uazapi_instance_id": None,
            }).eq("id", agent_id).like("uazapi_instance_id", "CREATING:%").execute()

            error_msg = str(e)
            logger.error(f"[QRCode] Failed to create instance: {error_msg}")

            if "Maximum" in error_msg or "429" in error_msg:
                raise HTTPException(
                    status_code=503,
                    detail="Limite de instancias UAZAPI atingido. Delete agentes antigos.",
                )
            raise HTTPException(status_code=500, detail=f"Falha ao criar instancia: {error_msg}")

    # --- Get QR code from instance ---
    if not instance_id or not base_url:
        raise HTTPException(status_code=400, detail="Instancia WhatsApp nao configurada")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/instance/qrcode",
                headers={"token": token or "", "Content-Type": "application/json"},
            )
            data = resp.json()

            qr_code = data.get("qrcode") or data.get("base64")
            if qr_code:
                return {
                    "status": "pending",
                    "qr_code": qr_code,
                    "qr_code_url": f"/api/agents/{agent_id}/qrcode",
                }

            # Check if connected
            if data.get("connected") or data.get("status") == "open":
                svc.client.table("agents").update({"uazapi_connected": True}).eq("id", agent_id).execute()
                return {
                    "status": "connected",
                    "phone_number": data.get("phoneNumber", ""),
                }

            return {"status": "initializing", "retry_after": 5}

    except Exception as e:
        logger.error(f"[QRCode] Error getting QR: {e}")
        return {"status": "initializing", "retry_after": 5}


# ---------------------------------------------------------------------------
# 7. GET /api/agents/{agent_id}/connection-status
# ---------------------------------------------------------------------------

@agents_router.get("/{agent_id}/connection-status")
async def connection_status(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Check WhatsApp connection status for an agent."""
    svc = get_supabase_service()
    agent = _get_agent_or_404(agent_id, user["id"])

    instance_id = agent.get("uazapi_instance_id")
    base_url = agent.get("uazapi_base_url")
    token = agent.get("uazapi_token")

    if not instance_id or not base_url:
        return {"connected": False, "instance_status": "not_configured"}

    # Handle creation locks
    if str(instance_id).startswith("CREATING:"):
        return {"connected": False, "instance_status": "creating"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/instance/status",
                headers={"token": token or "", "Content-Type": "application/json"},
            )
            data = resp.json()

            connected = bool(
                data.get("loggedIn")
                or (data.get("connected") and data.get("status") == "open")
            )
            phone_number = data.get("phoneNumber") or data.get("phone") or ""
            instance_status = data.get("status", "unknown")

            # Update DB if changed
            if connected != agent.get("uazapi_connected"):
                svc.client.table("agents").update({"uazapi_connected": connected}).eq("id", agent_id).execute()

            return {
                "connected": connected,
                "phone_number": phone_number,
                "instance_status": instance_status,
            }

    except Exception as e:
        logger.error(f"[ConnectionStatus] Error: {e}")
        # Fallback to DB status
        return {
            "connected": agent.get("uazapi_connected", False),
            "phone_number": "",
            "instance_status": "error",
        }


# ---------------------------------------------------------------------------
# 8. POST /api/agents/{agent_id}/disconnect
# ---------------------------------------------------------------------------

@agents_router.post("/{agent_id}/disconnect")
async def disconnect_agent(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Disconnect agent from WhatsApp (does NOT delete instance)."""
    svc = get_supabase_service()
    agent = _get_agent_or_404(agent_id, user["id"])

    base_url = agent.get("uazapi_base_url")
    token = agent.get("uazapi_token")
    instance_id = agent.get("uazapi_instance_id")

    if not instance_id or not base_url:
        raise HTTPException(status_code=400, detail="Instancia WhatsApp nao configurada")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{base_url.rstrip('/')}/instance/logout",
                headers={"token": token or "", "Content-Type": "application/json"},
            )
    except Exception as e:
        logger.warning(f"[Disconnect] Error disconnecting: {e}")

    # Always mark as disconnected
    svc.client.table("agents").update({"uazapi_connected": False}).eq("id", agent_id).execute()

    return {"status": "success", "message": "Desconectado com sucesso"}
