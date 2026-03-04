"""
Google Calendar OAuth2 endpoints para agente-ia.

Endpoints:
- POST /start         - Gera URL de autorizacao Google
- GET  /callback      - Recebe callback do Google, troca code por tokens
- GET  /status/{id}   - Verifica status da conexao
- POST /disconnect/{id} - Desconecta Google Calendar
- GET  /calendars/{id}  - Lista calendarios disponiveis
- POST /calendars/{id}/select - Seleciona calendario

Traduzido do agnes-agent (Node.js) oauth.handler.ts.
"""

import base64
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests as http_requests

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

from app.config import settings
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Scopes necessarios
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


# ============================================================================
# REQUEST MODELS
# ============================================================================

class StartRequest(BaseModel):
    agent_id: str
    redirect_uri: Optional[str] = None


class SelectCalendarRequest(BaseModel):
    calendar_id: str


# ============================================================================
# HELPERS
# ============================================================================

def _get_oauth_config():
    """Retorna client_id e client_secret validados."""
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret

    if not client_id or not client_secret:
        raise ValueError("GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET devem estar configurados")

    return client_id, client_secret


def _build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Constroi URL de autorizacao Google OAuth2."""
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _exchange_code_for_tokens(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Troca authorization code por tokens."""
    client_id, client_secret = _get_oauth_config()

    response = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )

    if response.status_code != 200:
        logger.error(f"[GoogleOAuth] Token exchange failed: {response.text}")
        raise ValueError(f"Token exchange failed: {response.text}")

    return response.json()


def _get_calendar_service_from_refresh_token(refresh_token: str):
    """Cria Google Calendar service a partir de refresh_token."""
    client_id, client_secret = _get_oauth_config()

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=GOOGLE_SCOPES,
    )
    credentials.refresh(GoogleRequest())

    return build("calendar", "v3", credentials=credentials)


def _get_callback_url() -> str:
    """Retorna URL de callback para OAuth."""
    base = settings.api_base_url
    if not base:
        base = "https://ai.phant.com.br"
    return f"{base}/api/google/oauth/callback"


def _get_frontend_url() -> str:
    """Retorna URL do frontend."""
    return settings.frontend_url or "https://ia.phant.com.br"


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/start")
async def oauth_start(
    body: StartRequest,
    x_user_id: Optional[str] = Header(None),
):
    """
    Inicia fluxo OAuth2 - retorna URL de autorizacao Google.

    agent_id pode ser UUID valido ou "pending" para wizard.
    """
    try:
        client_id, _ = _get_oauth_config()

        if not body.agent_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "agent_id e obrigatorio (use 'pending' para wizard)"},
            )

        if not x_user_id:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Usuario nao autenticado (x-user-id header)"},
            )

        callback_url = _get_callback_url()

        # Criar state com informacoes para o callback
        state_data = {
            "agent_id": body.agent_id,
            "user_id": x_user_id,
            "redirect_uri": body.redirect_uri or _get_frontend_url(),
        }
        state = base64.b64encode(json.dumps(state_data).encode()).decode()

        auth_url = _build_auth_url(client_id, callback_url, state)

        logger.info(f"[GoogleOAuth] Start: agent_id={body.agent_id}, user_id={x_user_id}")

        return {"status": "success", "auth_url": auth_url}

    except ValueError as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"[GoogleOAuth] Start error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erro ao iniciar autenticacao"},
        )


@router.get("/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """
    Callback do OAuth2 - recebe code do Google, troca por tokens.

    Dois modos:
    1. agent_id valido: salva tokens no agente
    2. agent_id = "pending": retorna tokens encodados para o frontend
    """
    frontend_url = _get_frontend_url()

    try:
        # Verificar erro do Google
        if error:
            logger.error(f"[GoogleOAuth] Authorization error: {error}")
            return RedirectResponse(f"{frontend_url}?google_error={error}")

        if not code or not state:
            return RedirectResponse(f"{frontend_url}?google_error=missing_code_or_state")

        # Decodificar state
        try:
            state_data = json.loads(base64.b64decode(state).decode())
        except Exception:
            return RedirectResponse(f"{frontend_url}?google_error=invalid_state")

        agent_id = state_data.get("agent_id")
        user_id = state_data.get("user_id")
        redirect_uri = state_data.get("redirect_uri", frontend_url)

        # Trocar code por tokens
        callback_url = _get_callback_url()
        tokens = _exchange_code_for_tokens(code, callback_url)

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            logger.error("[GoogleOAuth] No refresh_token received")
            return RedirectResponse(f"{redirect_uri}?google_error=no_refresh_token")

        # Buscar info do calendario primario
        service = _get_calendar_service_from_refresh_token(refresh_token)
        calendar_info = service.calendarList().get(calendarId="primary").execute()
        calendar_id = calendar_info.get("id", "primary")
        calendar_email = calendar_info.get("summary", "")

        # Montar credenciais para salvar
        google_credentials = {
            "refresh_token": refresh_token,
            "access_token": tokens.get("access_token"),
            "expiry_date": tokens.get("expires_in"),
            "token_type": tokens.get("token_type"),
            "scope": tokens.get("scope"),
            "calendar_email": calendar_email,
        }

        # Modo 1: agent_id valido -> salvar no banco
        if agent_id and agent_id != "pending":
            supabase = get_supabase_service()

            result = (
                supabase.client.table("agents")
                .update({
                    "google_calendar_enabled": True,
                    "google_credentials": google_credentials,
                    "google_calendar_id": calendar_id,
                    "updated_at": datetime.utcnow().isoformat(),
                })
                .eq("id", agent_id)
                .eq("user_id", user_id)
                .execute()
            )

            if not result.data:
                logger.error(f"[GoogleOAuth] Failed to save credentials for agent {agent_id}")
                return RedirectResponse(f"{redirect_uri}?google_error=save_failed")

            logger.info(
                f"[GoogleOAuth] Connected: agent={agent_id}, "
                f"calendar={calendar_id}, email={calendar_email}"
            )

            from urllib.parse import quote
            return RedirectResponse(
                f"{redirect_uri}?google_connected=true&calendar_email={quote(calendar_email)}"
            )

        # Modo 2: pending -> retornar tokens encodados para o frontend
        encoded_data = base64.b64encode(json.dumps({
            "credentials": google_credentials,
            "calendar_id": calendar_id,
            "calendar_email": calendar_email,
        }).encode()).decode()

        logger.info(f"[GoogleOAuth] Returning tokens for pending agent, email={calendar_email}")

        from urllib.parse import quote
        return RedirectResponse(
            f"{redirect_uri}?google_pending=true&calendar_email={quote(calendar_email)}#google_data={encoded_data}"
        )

    except Exception as e:
        logger.error(f"[GoogleOAuth] Callback error: {e}", exc_info=True)
        from urllib.parse import quote
        return RedirectResponse(
            f"{frontend_url}?google_error={quote(str(e))}"
        )


@router.get("/status/{agent_id}")
async def oauth_status(
    agent_id: str,
    x_user_id: Optional[str] = Header(None),
):
    """Verifica status da conexao Google Calendar."""
    try:
        if not x_user_id:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Usuario nao autenticado"},
            )

        supabase = get_supabase_service()

        result = (
            supabase.client.table("agents")
            .select("google_calendar_enabled, google_credentials, google_calendar_id")
            .eq("id", agent_id)
            .eq("user_id", x_user_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Agente nao encontrado"},
            )

        agent = result.data[0]
        credentials = agent.get("google_credentials") or {}

        return {
            "status": "success",
            "connected": agent.get("google_calendar_enabled", False),
            "calendar_id": agent.get("google_calendar_id"),
            "calendar_email": credentials.get("calendar_email"),
        }

    except Exception as e:
        logger.error(f"[GoogleOAuth] Status error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erro ao verificar status"},
        )


@router.post("/disconnect/{agent_id}")
async def oauth_disconnect(
    agent_id: str,
    x_user_id: Optional[str] = Header(None),
):
    """Desconecta Google Calendar do agente."""
    try:
        if not x_user_id:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Usuario nao autenticado"},
            )

        supabase = get_supabase_service()

        # Buscar credenciais para revogar
        agent_result = (
            supabase.client.table("agents")
            .select("google_credentials")
            .eq("id", agent_id)
            .eq("user_id", x_user_id)
            .limit(1)
            .execute()
        )

        if agent_result.data:
            credentials = agent_result.data[0].get("google_credentials")
            if credentials and credentials.get("refresh_token"):
                try:
                    http_requests.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": credentials["refresh_token"]},
                        timeout=10,
                    )
                    logger.info(f"[GoogleOAuth] Token revoked for agent {agent_id}")
                except Exception as revoke_err:
                    logger.warning(f"[GoogleOAuth] Failed to revoke token: {revoke_err}")

        # Limpar credenciais no banco
        result = (
            supabase.client.table("agents")
            .update({
                "google_calendar_enabled": False,
                "google_credentials": None,
                "google_calendar_id": "primary",
                "updated_at": datetime.utcnow().isoformat(),
            })
            .eq("id", agent_id)
            .eq("user_id", x_user_id)
            .execute()
        )

        if not result.data:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Falha ao desconectar Google Calendar"},
            )

        logger.info(f"[GoogleOAuth] Disconnected agent {agent_id}")

        return {
            "status": "success",
            "message": "Google Calendar desconectado com sucesso",
        }

    except Exception as e:
        logger.error(f"[GoogleOAuth] Disconnect error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erro ao desconectar"},
        )


@router.get("/calendars/{agent_id}")
async def list_calendars(
    agent_id: str,
    x_user_id: Optional[str] = Header(None),
):
    """Lista calendarios disponiveis do usuario conectado."""
    try:
        if not x_user_id:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Usuario nao autenticado"},
            )

        supabase = get_supabase_service()

        result = (
            supabase.client.table("agents")
            .select("google_credentials")
            .eq("id", agent_id)
            .eq("user_id", x_user_id)
            .limit(1)
            .execute()
        )

        if not result.data or not result.data[0].get("google_credentials"):
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Google Calendar nao conectado"},
            )

        credentials = result.data[0]["google_credentials"]
        refresh_token = credentials.get("refresh_token")

        if not refresh_token:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "refresh_token ausente"},
            )

        # Listar calendarios
        service = _get_calendar_service_from_refresh_token(refresh_token)
        cal_list = service.calendarList().list().execute()

        calendars = [
            {
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "description": cal.get("description"),
                "primary": cal.get("primary", False),
                "accessRole": cal.get("accessRole"),
            }
            for cal in (cal_list.get("items") or [])
        ]

        return {"status": "success", "calendars": calendars}

    except Exception as e:
        logger.error(f"[GoogleOAuth] List calendars error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erro ao listar calendarios"},
        )


@router.post("/calendars/{agent_id}/select")
async def select_calendar(
    agent_id: str,
    body: SelectCalendarRequest,
    x_user_id: Optional[str] = Header(None),
):
    """Seleciona o calendario a ser usado pelo agente."""
    try:
        if not x_user_id:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Usuario nao autenticado"},
            )

        if not body.calendar_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "calendar_id e obrigatorio"},
            )

        supabase = get_supabase_service()

        result = (
            supabase.client.table("agents")
            .update({
                "google_calendar_id": body.calendar_id,
                "updated_at": datetime.utcnow().isoformat(),
            })
            .eq("id", agent_id)
            .eq("user_id", x_user_id)
            .execute()
        )

        if not result.data:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Falha ao selecionar calendario"},
            )

        logger.info(f"[GoogleOAuth] Calendar selected: {body.calendar_id} for agent {agent_id}")

        return {
            "status": "success",
            "message": "Calendario selecionado com sucesso",
            "calendar_id": body.calendar_id,
        }

    except Exception as e:
        logger.error(f"[GoogleOAuth] Select calendar error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erro ao selecionar calendario"},
        )
