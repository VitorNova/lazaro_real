"""
Auth API - Endpoints de autenticacao usando Supabase Auth.

Endpoints:
- POST /register        - Registro (email, password, name)
- POST /login           - Login (email, password)
- POST /logout          - Logout
- GET  /me              - Dados do usuario logado
- POST /refresh         - Renovar token
- POST /forgot-password - Recuperar senha
- POST /reset-password  - Resetar senha
- PUT  /update-profile  - Atualizar perfil
- PUT  /change-password - Alterar senha

Migrado de agnes-agent (Node.js) auth.handler.ts + auth.service.ts.
Usa Supabase Auth (GoTrue) ao inves de JWT customizado.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, alias="refresh_token")
    refreshToken: Optional[str] = None

    @property
    def token(self) -> str:
        return self.refresh_token or self.refreshToken or ""


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    notes: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


# ============================================================================
# HELPERS
# ============================================================================

def _session_to_dict(session) -> Dict[str, Any]:
    """Converte Session do Supabase para dict serializavel."""
    if not session:
        return {}
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": session.expires_in,
        "expires_at": session.expires_at,
        "token_type": session.token_type or "bearer",
    }


def _auth_user_to_dict(user) -> Dict[str, Any]:
    """Converte User do Supabase Auth para dict serializavel."""
    if not user:
        return {}
    return {
        "id": str(user.id),
        "email": user.email,
        "email_confirmed_at": str(user.email_confirmed_at) if user.email_confirmed_at else None,
        "created_at": str(user.created_at) if user.created_at else None,
        "updated_at": str(user.updated_at) if user.updated_at else None,
        "user_metadata": user.user_metadata or {},
    }


def _extract_session_info(request: Request) -> Dict[str, str]:
    """Extrai informacoes de sessao do request (IP, User-Agent, Device)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.headers.get("x-real-ip") or request.client.host if request.client else "unknown"
    )
    user_agent = request.headers.get("user-agent", "unknown")

    # Deteccao simples de device
    ua_lower = user_agent.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        device = "Mobile"
    elif "tablet" in ua_lower or "ipad" in ua_lower:
        device = "Tablet"
    elif "mac" in ua_lower:
        device = "Mac"
    elif "windows" in ua_lower:
        device = "Windows PC"
    elif "linux" in ua_lower:
        device = "Linux"
    else:
        device = "Desktop"

    return {"ip": ip, "user_agent": user_agent, "device": device}


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    """
    Registra novo usuario via Supabase Auth.

    Cria usuario em auth.users (Supabase Auth) e em public.users (perfil).
    """
    try:
        svc = get_supabase_service()

        # 1. Criar usuario no Supabase Auth
        auth_response = svc.client.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {
                "data": {
                    "name": body.name,
                }
            }
        })

        if not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "REGISTRATION_FAILED", "message": "Falha ao criar usuario"},
            )

        auth_user = auth_response.user

        # 2. Criar perfil na tabela public.users
        try:
            now = datetime.now(timezone.utc).isoformat()
            svc.client.table("users").upsert({
                "id": str(auth_user.id),
                "email": body.email,
                "name": body.name,
                "role": "user",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "last_login": now,
                "email_verified": auth_user.email_confirmed_at is not None,
            }).execute()
        except Exception as profile_err:
            logger.warning(f"Erro ao criar perfil public.users: {profile_err}")

        logger.info(f"Usuario registrado: {body.email} (id={auth_user.id})")

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "success": True,
                "user": _auth_user_to_dict(auth_user),
                "session": _session_to_dict(auth_response.session),
            },
        )

    except HTTPException:
        raise
    except Exception as err:
        error_msg = str(err)
        logger.error(f"Erro no registro: {type(err).__name__}")

        # Tratar erros comuns do Supabase Auth
        if "already registered" in error_msg.lower() or "already been registered" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "EMAIL_EXISTS", "message": "Email ja cadastrado"},
            )

        if "invalid" in error_msg.lower() and "email" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INVALID_EMAIL", "message": "Endereco de email invalido"},
            )

        # Erros do Supabase Auth com status HTTP
        if hasattr(err, "status") and hasattr(err, "message"):
            status_code = getattr(err, "status", 500)
            if 400 <= status_code < 500:
                raise HTTPException(
                    status_code=status_code,
                    detail={"error": "AUTH_ERROR", "message": getattr(err, "message", error_msg)},
                )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro interno ao registrar"},
        )


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """
    Autentica usuario via Supabase Auth.

    Retorna access_token e refresh_token.
    """
    try:
        svc = get_supabase_service()

        # Autenticar via GoTrue REST API (thread-safe, nao muta singleton)
        async with httpx.AsyncClient() as http:
            auth_http_response = await http.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=password",
                json={"email": body.email, "password": body.password},
                headers={
                    "apikey": settings.supabase_service_key,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

        if auth_http_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "INVALID_CREDENTIALS", "message": "Email ou senha incorretos"},
            )

        auth_data = auth_http_response.json()

        # Extrair user e session do response HTTP
        auth_user_data = auth_data.get("user", {})
        session_data = {
            "access_token": auth_data.get("access_token"),
            "refresh_token": auth_data.get("refresh_token"),
            "expires_in": auth_data.get("expires_in"),
            "expires_at": auth_data.get("expires_at"),
            "token_type": auth_data.get("token_type", "bearer"),
        }

        if not auth_user_data.get("id") or not session_data.get("access_token"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "INVALID_CREDENTIALS", "message": "Email ou senha incorretos"},
            )

        user_id = auth_user_data["id"]
        user_email = auth_user_data.get("email", body.email)
        user_metadata = auth_user_data.get("user_metadata", {})
        session_info = _extract_session_info(request)

        # Atualizar last_login e resetar failed_login_attempts na public.users
        try:
            svc.client.table("users").update({
                "last_login": datetime.now(timezone.utc).isoformat(),
                "failed_login_attempts": 0,
                "locked_until": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user_id).execute()
        except Exception as update_err:
            logger.debug(f"Erro ao atualizar last_login: {update_err}")

        # Buscar perfil completo
        profile = {}
        try:
            result = (
                svc.client.table("users")
                .select("name, role, avatar_url, is_active")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                profile = result.data[0]
        except Exception:
            pass

        # Verificar se conta esta ativa
        if profile and not profile.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "ACCOUNT_DISABLED", "message": "Conta desativada. Contate o administrador."},
            )

        logger.info(f"Login: {body.email} (device={session_info['device']}, ip={session_info['ip']})")

        return {
            "success": True,
            "user": {
                "id": user_id,
                "email": user_email,
                "email_confirmed_at": auth_user_data.get("email_confirmed_at"),
                "created_at": auth_user_data.get("created_at"),
                "updated_at": auth_user_data.get("updated_at"),
                "user_metadata": user_metadata,
                "name": profile.get("name") or user_metadata.get("name", ""),
                "role": profile.get("role", "user"),
                "avatar_url": profile.get("avatar_url"),
            },
            # Top-level camelCase tokens (matches Node.js format expected by frontend)
            "accessToken": session_data["access_token"],
            "refreshToken": session_data["refresh_token"],
        }

    except HTTPException:
        raise
    except Exception as err:
        error_msg = str(err)
        logger.error(f"Erro no login: {type(err).__name__}")

        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "INVALID_CREDENTIALS", "message": "Email ou senha incorretos"},
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro interno ao autenticar"},
        )


@router.post("/logout")
async def logout(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Encerra sessao do usuario.

    Usa admin.sign_out(jwt) para invalidar o token no Supabase Auth.
    """
    try:
        svc = get_supabase_service()

        # Invalidar token via admin API (sign_out recebe JWT, nao user_id)
        jwt_token = user.get("_token")
        if jwt_token:
            try:
                svc.client.auth.admin.sign_out(jwt_token, scope="global")
            except Exception:
                pass  # Stateless - nao e critico se falhar

        logger.info(f"Logout: {user.get('email')} (id={user.get('id')})")

        return {"success": True, "message": "Sessao encerrada"}

    except Exception as err:
        logger.error(f"Erro no logout: {err}")
        # Mesmo com erro, retorna sucesso (abordagem stateless)
        return {"success": True, "message": "Sessao encerrada"}


@router.get("/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Retorna dados do usuario logado.

    Combina dados do Supabase Auth com perfil em public.users.
    """
    try:
        svc = get_supabase_service()

        # Buscar perfil completo
        profile = {}
        try:
            result = (
                svc.client.table("users")
                .select("*")
                .eq("id", user["id"])
                .limit(1)
                .execute()
            )
            if result.data:
                profile = result.data[0]
                # Remover campos sensiveis
                for field in ("password_hash", "refresh_token", "verification_token", "reset_password_token"):
                    profile.pop(field, None)
        except Exception as err:
            logger.debug(f"Perfil nao encontrado: {err}")

        return {
            "success": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": profile.get("name") or user.get("name", ""),
                "role": profile.get("role") or user.get("role", "user"),
                "avatar_url": profile.get("avatar_url"),
                "is_active": profile.get("is_active", True),
                "email_verified": user.get("email_verified", False),
                "created_at": profile.get("created_at") or user.get("created_at"),
                "last_login": profile.get("last_login"),
                "notes": profile.get("notes"),
                "updated_at": profile.get("updated_at"),
            },
        }

    except Exception as err:
        logger.error(f"Erro ao buscar usuario: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao buscar dados do usuario"},
        )


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    """
    Renova access_token usando refresh_token.

    Usa HTTP direto ao GoTrue (thread-safe, nao muta o singleton client).
    """
    try:
        # Chamar GoTrue REST API diretamente (thread-safe)
        async with httpx.AsyncClient() as http:
            response = await http.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=refresh_token",
                json={"refresh_token": body.token},
                headers={
                    "apikey": settings.supabase_service_key,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

        if response.status_code != 200:
            error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_data.get("error_description") or error_data.get("msg") or "Token expirado ou invalido"

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "REFRESH_FAILED", "message": error_msg},
            )

        data = response.json()

        return {
            "success": True,
            "accessToken": data.get("access_token"),
            "refreshToken": data.get("refresh_token"),
        }

    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Erro ao renovar token: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao renovar token"},
        )


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """
    Envia email de recuperacao de senha via Supabase Auth.

    O Supabase envia um email com link para redefinicao.
    """
    try:
        svc = get_supabase_service()

        # Configurar redirect URL
        redirect_to = None
        if settings.frontend_url:
            redirect_to = f"{settings.frontend_url}/reset-password"

        options = {}
        if redirect_to:
            options["redirect_to"] = redirect_to

        svc.client.auth.reset_password_email(body.email, options=options)

        logger.info(f"Email de recuperacao enviado para: {body.email}")

        # Sempre retorna sucesso (nao revela se email existe)
        return {
            "success": True,
            "message": "Se o email estiver cadastrado, um link de recuperacao sera enviado.",
        }

    except Exception as err:
        logger.error(f"Erro ao enviar email de recuperacao: {err}")
        # Retorna sucesso mesmo com erro (nao revela se email existe)
        return {
            "success": True,
            "message": "Se o email estiver cadastrado, um link de recuperacao sera enviado.",
        }


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """
    Reseta senha usando access_token recebido no email de recuperacao.

    O frontend recebe o access_token via URL hash apos o usuario clicar no link.
    """
    try:
        svc = get_supabase_service()

        # 1. Validar o access_token para obter o user
        user_response = svc.client.auth.get_user(body.access_token)

        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "INVALID_TOKEN", "message": "Token invalido ou expirado"},
            )

        user_id = str(user_response.user.id)

        # 2. Atualizar senha via admin API
        svc.client.auth.admin.update_user_by_id(
            user_id,
            {"password": body.new_password}
        )

        # 3. Limpar tokens de reset na public.users
        try:
            svc.client.table("users").update({
                "reset_password_token": None,
                "reset_password_expires": None,
                "failed_login_attempts": 0,
                "locked_until": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user_id).execute()
        except Exception:
            pass

        logger.info(f"Senha resetada para user {user_id}")

        return {"success": True, "message": "Senha atualizada com sucesso"}

    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Erro ao resetar senha: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao resetar senha"},
        )


@router.put("/update-profile")
async def update_profile(
    body: UpdateProfileRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Atualiza perfil do usuario na tabela public.users.
    """
    try:
        svc = get_supabase_service()

        # Montar campos a atualizar (somente campos enviados)
        update_data: Dict[str, Any] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if body.name is not None:
            update_data["name"] = body.name
        if body.avatar_url is not None:
            update_data["avatar_url"] = body.avatar_url
        if body.notes is not None:
            update_data["notes"] = body.notes

        # Atualizar public.users
        result = (
            svc.client.table("users")
            .update(update_data)
            .eq("id", user["id"])
            .execute()
        )

        # Atualizar user_metadata no Supabase Auth tambem
        if body.name is not None:
            try:
                svc.client.auth.admin.update_user_by_id(
                    user["id"],
                    {"user_metadata": {"name": body.name}}
                )
            except Exception:
                pass

        updated = result.data[0] if result.data else {}

        # Remover campos sensiveis
        for field in ("password_hash", "refresh_token", "verification_token", "reset_password_token"):
            updated.pop(field, None)

        logger.info(f"Perfil atualizado: {user.get('email')} (id={user['id']})")

        return {
            "success": True,
            "user": updated,
        }

    except Exception as err:
        logger.error(f"Erro ao atualizar perfil: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao atualizar perfil"},
        )


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Altera senha do usuario.

    Verifica senha atual via sign_in_with_password antes de atualizar.
    """
    try:
        svc = get_supabase_service()

        # 1. Validar nova senha diferente da atual (antes da verificacao)
        if body.current_password == body.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "SAME_PASSWORD", "message": "Nova senha deve ser diferente da atual"},
            )

        # 2. Verificar senha atual via GoTrue REST API (thread-safe, nao muta singleton)
        async with httpx.AsyncClient() as http:
            verify_response = await http.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=password",
                json={"email": user["email"], "password": body.current_password},
                headers={
                    "apikey": settings.supabase_service_key,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )

        if verify_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "WRONG_PASSWORD", "message": "Senha atual incorreta"},
            )

        # 3. Atualizar senha via admin API
        svc.client.auth.admin.update_user_by_id(
            user["id"],
            {"password": body.new_password}
        )

        # 4. Atualizar updated_at
        try:
            svc.client.table("users").update({
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user["id"]).execute()
        except Exception:
            pass

        logger.info(f"Senha alterada: user_id={user['id']}")

        return {"success": True, "message": "Senha alterada com sucesso"}

    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Erro ao alterar senha: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao alterar senha"},
        )
