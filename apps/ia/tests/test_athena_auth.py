# tests/test_athena_auth.py
"""
TDD — Autenticação obrigatória no endpoint Athena (lazaro-ia level) [2026-03-18]

Contexto: Endpoint POST /api/athena/ask faz proxy para agnes-agent sem validar auth.
         Atualmente a auth vem do agnes-agent, mas lazaro-ia deveria validar também.
Causa: Falta Depends(get_current_user) no router de lazaro-ia.
Correção: Adicionar autenticação obrigatória no proxy (defense-in-depth).

Este teste valida que o proxy NÃO é chamado quando a request não tem auth válida.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


class TestAthenaAuth:
    """
    Testes de autenticação no endpoint Athena (lazaro-ia level).

    Vulnerabilidade: POST /api/athena/ask faz proxy sem validar auth primeiro.
    Correção esperada: 401 Unauthorized ANTES de chamar proxy_to_agnes.
    """

    @pytest.fixture
    def client_with_proxy_mock(self):
        """Cliente de teste com proxy mockado para verificar que NÃO é chamado."""
        from app.main import app

        with patch("app.api.routes.athena.proxy_to_agnes", new_callable=AsyncMock) as mock_proxy:
            mock_proxy.return_value = MagicMock(
                status_code=200,
                body=b'{"response": "Athena response"}',
            )
            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_proxy

    @pytest.fixture
    def client_with_auth_and_proxy_mock(self):
        """Cliente de teste com auth mockado E proxy mockado."""
        from app.main import app
        from app.middleware.auth import get_current_user

        async def mock_get_current_user():
            return {"id": "user-123", "email": "test@test.com", "role": "user"}

        app.dependency_overrides[get_current_user] = mock_get_current_user

        with patch("app.api.routes.athena.proxy_to_agnes", new_callable=AsyncMock) as mock_proxy:
            # Mock retorna resposta válida
            from fastapi.responses import JSONResponse
            mock_proxy.return_value = JSONResponse(content={"response": "OK"})

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_proxy

        app.dependency_overrides.clear()

    def test_proxy_not_called_without_auth(self, client_with_proxy_mock):
        """
        POST /api/athena/ask deve rejeitar request SEM chamar o proxy.

        ANTES da correção: proxy_to_agnes é chamado (auth delegada ao agnes-agent)
        DEPOIS da correção: 401 retornado ANTES do proxy ser chamado
        """
        client, mock_proxy = client_with_proxy_mock

        response = client.post(
            "/api/athena/ask",
            json={"question": "Qual o status do sistema?"},
        )

        # O proxy NÃO deve ter sido chamado (auth deve bloquear antes)
        assert not mock_proxy.called, (
            "O proxy foi chamado mesmo sem autenticação!\n"
            "A autenticação deve ser feita no lazaro-ia, não delegada ao agnes-agent."
        )

        # Deve retornar 401
        assert response.status_code == 401, (
            f"Esperado 401, recebeu {response.status_code}\n"
            f"Response: {response.text[:300]}"
        )

    def test_proxy_called_with_valid_auth(self, client_with_auth_and_proxy_mock):
        """
        POST /api/athena/ask com auth válida deve chamar o proxy.

        Cenário: Usuário autenticado faz request.
        Esperado: Proxy é chamado e response é retornada.
        """
        client, mock_proxy = client_with_auth_and_proxy_mock

        response = client.post(
            "/api/athena/ask",
            json={"question": "Qual o status do sistema?"},
        )

        # O proxy DEVE ter sido chamado
        assert mock_proxy.called, (
            "O proxy NÃO foi chamado mesmo com autenticação válida!\n"
            "O proxy deve ser chamado após autenticação bem-sucedida."
        )

        # Não deve retornar 401
        assert response.status_code != 401, (
            f"Request autenticada foi rejeitada!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:300]}"
        )
