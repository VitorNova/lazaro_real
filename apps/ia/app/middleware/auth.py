"""
Auth Middleware - Validacao de tokens JWT e Supabase Auth.

Suporta dois tipos de autenticacao:
1. JWT do agnes-agent (TypeScript) - usado pelo CRM
2. Supabase Auth - usado por outros clientes

Fornece dependencias FastAPI para proteger rotas:
- get_current_user: Obriga autenticacao (401 se sem token)
- get_optional_user: Autenticacao opcional (None se sem token)
- require_admin: Exige role super_admin
"""

import logging
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


async def _extract_token(request: Request) -> Optional[str]:
    """Extrai Bearer token do header Authorization."""
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


async def _validate_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Valida JWT gerado pelo agnes-agent (TypeScript).
    Usado pelo CRM frontend.
    """
    if not settings.jwt_secret:
        return None

    try:
        # Decodificar JWT com o mesmo secret do TypeScript
        decoded = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": True}
        )

        user_id = decoded.get("userId") or decoded.get("user_id") or decoded.get("sub")
        if not user_id:
            return None

        # Buscar perfil do usuario no banco
        svc = get_supabase_service()
        try:
            result = (
                svc.client.table("users")
                .select("*")
                .eq("id", str(user_id))
                .limit(1)
                .execute()
            )
            profile = result.data[0] if result.data else {}
        except Exception:
            profile = {}

        user_data: Dict[str, Any] = {
            "id": str(user_id),
            "email": decoded.get("email") or profile.get("email", ""),
            "role": profile.get("role", "user"),
            "is_active": profile.get("is_active", True),
            "name": profile.get("name", ""),
            "avatar_url": profile.get("avatar_url"),
            "email_verified": True,
            "created_at": profile.get("created_at"),
            "last_login": profile.get("last_login"),
            "_token": token,
        }

        logger.debug(f"JWT validado para user {user_id}")
        return user_data

    except jwt.ExpiredSignatureError:
        logger.debug("JWT expirado")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"JWT invalido: {e}")
        return None
    except Exception as e:
        logger.debug(f"Erro ao validar JWT: {e}")
        return None


async def _validate_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Valida token via Supabase Auth.
    Fallback para clientes que usam Supabase Auth direto.
    """
    try:
        svc = get_supabase_service()
        user_response = svc.client.auth.get_user(token)

        if not user_response or not user_response.user:
            return None

        auth_user = user_response.user

        # Buscar perfil na tabela public.users
        profile = None
        try:
            result = (
                svc.client.table("users")
                .select("*")
                .eq("id", str(auth_user.id))
                .limit(1)
                .execute()
            )
            if result.data:
                profile = result.data[0]
        except Exception as profile_err:
            logger.debug(f"Perfil nao encontrado para {auth_user.id}: {profile_err}")

        user_data: Dict[str, Any] = {
            "id": str(auth_user.id),
            "email": auth_user.email,
            "role": (profile or {}).get("role", "user"),
            "is_active": (profile or {}).get("is_active", True),
            "name": (profile or {}).get("name") or (auth_user.user_metadata or {}).get("name", ""),
            "avatar_url": (profile or {}).get("avatar_url"),
            "email_verified": auth_user.email_confirmed_at is not None,
            "created_at": str(auth_user.created_at) if auth_user.created_at else None,
            "last_login": (profile or {}).get("last_login"),
            "notes": (profile or {}).get("notes"),
            "_token": token,
        }

        return user_data

    except Exception as err:
        error_msg = str(err).lower()
        if "expired" in error_msg or "invalid" in error_msg:
            logger.debug(f"Supabase token invalido ou expirado: {err}")
        else:
            logger.debug(f"Erro ao validar Supabase token: {err}")
        return None


async def _validate_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Valida token tentando primeiro JWT (agnes-agent) e depois Supabase Auth.

    Ordem de tentativa:
    1. JWT do agnes-agent (usado pelo CRM)
    2. Supabase Auth (fallback)
    """
    # Tentar JWT primeiro (mais comum - CRM usa isso)
    user = await _validate_jwt_token(token)
    if user:
        return user

    # Fallback para Supabase Auth
    user = await _validate_supabase_token(token)
    if user:
        return user

    return None


async def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Dependencia FastAPI que exige autenticacao.

    Uso:
        @router.get("/me")
        async def me(user: Dict = Depends(get_current_user)):
            return user

    Raises:
        HTTPException 401: Se token ausente, invalido ou expirado.
        HTTPException 403: Se conta desativada.
    """
    token = await _extract_token(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_TOKEN", "message": "Token de autenticacao nao fornecido"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await _validate_token(token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_TOKEN", "message": "Token invalido ou expirado"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verificar se conta esta ativa
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ACCOUNT_DISABLED", "message": "Conta desativada"},
        )

    return user


async def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Dependencia FastAPI com autenticacao opcional.

    Retorna None se sem token, dados do usuario se autenticado.
    Nao levanta excecao se token ausente.
    """
    token = await _extract_token(request)
    if not token:
        return None

    return await _validate_token(token)


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Dependencia FastAPI que exige role super_admin.

    Uso:
        @router.get("/admin/users")
        async def list_users(admin: Dict = Depends(require_admin)):
            return users

    Raises:
        HTTPException 403: Se usuario nao e admin.
    """
    if user.get("role") != "super_admin":
        logger.warning(f"Acesso admin negado para user {user.get('id')} (role={user.get('role')})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Acesso restrito a administradores"},
        )

    return user
