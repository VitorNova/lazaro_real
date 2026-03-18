# tests/test_dashboard_auth.py
"""
TDD — Remover fallback de autenticação no Dashboard [2026-03-18]

Contexto: _get_user_id_from_request aceita query param user_id como fallback.
Causa: Se JWT falha, atacante pode fornecer ?user_id=victim-uuid para acessar dados.
Correção: Remover fallback, usar apenas Depends(get_current_user).

Este teste valida que query param user_id NÃO é aceito como autenticação.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestDashboardAuth:
    """
    Testes de autenticação no Dashboard.

    Vulnerabilidade: GET /api/dashboard/stats?user_id=X bypassa autenticação.
    Correção esperada: 401 mesmo com user_id no query param.
    """

    @pytest.fixture
    def client_with_mocks(self):
        """Cliente com Supabase mockado (auth e DB)."""
        from app.main import app

        with patch("app.api.routes.dashboard.get_supabase_service") as mock_svc:
            svc = MagicMock()

            # Mock auth.get_user falha (sem JWT válido)
            svc.client.auth.get_user.side_effect = Exception("Invalid JWT")

            # Mock DB queries retorna dados válidos (mostra que bypass funciona)
            mock_response = MagicMock()
            mock_response.data = [
                {"id": "agent-1", "name": "Ana", "table_leads": "leads_ana", "timezone": "America/Sao_Paulo"}
            ]
            svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_response
            svc.client.table.return_value.select.return_value.execute.return_value = mock_response

            mock_svc.return_value = svc

            client = TestClient(app, raise_server_exceptions=False)
            yield client

    @pytest.fixture
    def client_with_auth(self):
        """Cliente de teste com auth mockado via dependency override."""
        from app.main import app
        from app.middleware.auth import get_current_user

        async def mock_get_current_user():
            return {"id": "user-123", "email": "test@test.com", "role": "user"}

        app.dependency_overrides[get_current_user] = mock_get_current_user

        # Mock do Supabase para queries
        with patch("app.api.routes.dashboard.get_supabase_service") as mock_svc:
            svc = MagicMock()
            # Mock auth.get_user retorna usuário válido
            user_mock = MagicMock()
            user_mock.user = MagicMock()
            user_mock.user.id = "user-123"
            svc.client.auth.get_user.return_value = user_mock

            # Mock DB queries
            mock_response = MagicMock()
            mock_response.data = []
            svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_response
            svc.client.table.return_value.select.return_value.execute.return_value = mock_response

            mock_svc.return_value = svc

            client = TestClient(app, raise_server_exceptions=False)
            yield client

        app.dependency_overrides.clear()

    def test_rejects_query_param_user_id_without_jwt(self, client_with_mocks):
        """
        GET /api/dashboard/stats?user_id=X deve rejeitar sem JWT válido.

        ANTES da correção: Retorna 200 (usa user_id do query param como fallback)
        DEPOIS da correção: Retorna 401 (ignora query param, exige JWT válido)
        """
        response = client_with_mocks.get(
            "/api/dashboard/stats",
            params={"user_id": "attacker-provided-uuid"},
        )

        assert response.status_code == 401, (
            f"Dashboard aceita user_id via query param!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:500]}\n"
            f"Vulnerabilidade: atacante pode acessar dados de qualquer usuário."
        )

    def test_rejects_leads_by_category_with_query_user_id(self, client_with_mocks):
        """
        GET /api/dashboard/leads-by-category?user_id=X deve rejeitar sem JWT.

        Outro endpoint vulnerável ao mesmo pattern.
        """
        response = client_with_mocks.get(
            "/api/dashboard/leads-by-category",
            params={"user_id": "attacker-uuid", "category": "total"},
        )

        assert response.status_code == 401, (
            f"Endpoint leads-by-category aceita user_id via query param!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:500]}"
        )

    def test_accepts_valid_jwt(self, client_with_auth):
        """
        GET /api/dashboard/stats com JWT válido deve retornar dados.

        Cenário: Usuário autenticado acessa dashboard.
        Esperado: 200 OK com dados do dashboard.
        """
        response = client_with_auth.get(
            "/api/dashboard/stats",
            headers={"Authorization": "Bearer valid-token"},
        )

        # Não deve ser 401
        assert response.status_code != 401, (
            f"Dashboard rejeita request com JWT válido!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:300]}"
        )
