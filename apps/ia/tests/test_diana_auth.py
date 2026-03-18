# tests/test_diana_auth.py
"""
TDD — Validação de Autenticação nos Endpoints Diana [2026-03-18]

Contexto: Endpoints Diana não exigem autenticação.
Causa: Qualquer pessoa pode criar campanhas, listar prospects, etc.
Correção: Adicionar Depends(get_current_user) a todos os endpoints.

Este teste valida que endpoints Diana retornam 401 sem token.
Usa mocks para evitar criar dados reais no banco.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


class TestDianaAuth:
    """
    Testes de autenticação para endpoints Diana.

    Vulnerabilidade: Endpoints públicos sem autenticação.
    Correção esperada: 401 Unauthorized sem token válido.
    """

    @pytest.fixture
    def client(self):
        """Cliente de teste sem token de autenticação."""
        from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def mock_diana_service(self):
        """Mock do DianaCampaignService para evitar operações reais."""
        with patch("app.api.routes.diana.get_diana_campaign_service") as mock:
            service = MagicMock()
            service.create_campaign_from_csv = AsyncMock(return_value={
                "success": True,
                "campaign_id": "test-id",
                "total": 0,
                "queued": 0,
                "errors": 0,
                "invalid_phones": [],
            })
            service.list_campaigns = MagicMock(return_value=[])
            service.get_campaign_stats = MagicMock(return_value={
                "total_campanhas": 0,
                "total_prospects": 0,
                "total_enviados": 0,
                "total_respondidos": 0,
                "total_interessados": 0,
            })
            service.list_prospects = MagicMock(return_value=[])
            service.pause_campaign = AsyncMock(return_value={"success": True})
            service.resume_campaign = AsyncMock(return_value={"success": True})
            mock.return_value = service
            yield mock

    def test_create_campaign_requires_auth(self, client, mock_diana_service):
        """
        POST /api/diana/campaigns deve exigir autenticação.

        ANTES da correção: Retorna 200 (aceita request)
        DEPOIS da correção: Retorna 401 (unauthorized)
        """
        response = client.post(
            "/api/diana/campaigns",
            data={
                "agent_id": "fake-agent-id",
                "campaign_name": "Test Campaign",
                "system_prompt": "You are a sales agent",
                "mensagem_template": "Oi {nome}!",
                "uazapi_base_url": "https://fake.uazapi.com",
                "uazapi_token": "fake-token",
            },
            files={"file": ("test.csv", b"nome,telefone\nJoao,5511999999999", "text/csv")},
        )

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_list_campaigns_requires_auth(self, client, mock_diana_service):
        """
        GET /api/diana/campaigns/{agent_id} deve exigir autenticação.

        ANTES da correção: Retorna 200 ou dados
        DEPOIS da correção: Retorna 401 (unauthorized)
        """
        response = client.get("/api/diana/campaigns/fake-agent-id")

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_get_campaign_stats_requires_auth(self, client, mock_diana_service):
        """
        GET /api/diana/campaigns/{agent_id}/{campaign_id}/stats deve exigir autenticação.
        """
        response = client.get("/api/diana/campaigns/fake-agent-id/fake-campaign-id/stats")

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_list_prospects_requires_auth(self, client, mock_diana_service):
        """
        GET /api/diana/campaigns/{agent_id}/{campaign_id}/prospects deve exigir autenticação.
        """
        response = client.get("/api/diana/campaigns/fake-agent-id/fake-campaign-id/prospects")

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_pause_campaign_requires_auth(self, client, mock_diana_service):
        """
        POST /api/diana/campaigns/{agent_id}/{campaign_id}/pause deve exigir autenticação.
        """
        response = client.post(
            "/api/diana/campaigns/fake-agent-id/fake-campaign-id/pause",
            data={
                "uazapi_base_url": "https://fake.uazapi.com",
                "uazapi_token": "fake-token",
            },
        )

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_resume_campaign_requires_auth(self, client, mock_diana_service):
        """
        POST /api/diana/campaigns/{agent_id}/{campaign_id}/resume deve exigir autenticação.
        """
        response = client.post(
            "/api/diana/campaigns/fake-agent-id/fake-campaign-id/resume",
            data={
                "uazapi_base_url": "https://fake.uazapi.com",
                "uazapi_token": "fake-token",
            },
        )

        assert response.status_code == 401, (
            f"Endpoint permite acesso sem autenticação!\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text[:200]}"
        )

    def test_health_endpoint_remains_public(self, client):
        """
        GET /api/diana/health deve permanecer público (health check).
        """
        response = client.get("/api/diana/health")

        # Health check deve continuar funcionando sem auth
        assert response.status_code == 200, (
            f"Health check não deveria exigir autenticação!\n"
            f"Status: {response.status_code}"
        )
