# ╔══════════════════════════════════════════════════════════════╗
# ║  AGENTS CONNECTION — WhatsApp QR code, status, disconnect  ║
# ╚══════════════════════════════════════════════════════════════╝
"""
WhatsApp connection endpoints for agents.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

from app.api.routes.agents.crud import _get_agent_or_404

logger = logging.getLogger(__name__)

connection_router = APIRouter()


# ============================================================================
# HELPERS
# ============================================================================

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


# ============================================================================
# ENDPOINTS
# ============================================================================

# ---------------------------------------------------------------------------
# 6. GET /api/agents/{agent_id}/qrcode
# ---------------------------------------------------------------------------

@connection_router.get("/{agent_id}/qrcode")
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

@connection_router.get("/{agent_id}/connection-status")
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

@connection_router.post("/{agent_id}/disconnect")
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
