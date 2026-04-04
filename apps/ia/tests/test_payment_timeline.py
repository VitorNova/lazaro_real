# tests/test_payment_timeline.py
"""Testes para endpoint GET /api/dashboard/asaas/payment-timeline."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ─── Dados de teste ─────────────────────────────────────────────────────────

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

COBRANCAS_MOCK = [
    # Cliente A — pagou no dia, pagou atrasado, pendente
    {
        "customer_id": "cus_aaa",
        "customer_name": "Alice Silva",
        "value": 150.0,
        "status": "CONFIRMED",
        "due_date": "2026-01-10",
        "payment_date": "2026-01-10",
        "billing_type": "PIX",
    },
    {
        "customer_id": "cus_aaa",
        "customer_name": "Alice Silva",
        "value": 150.0,
        "status": "CONFIRMED",
        "due_date": "2026-02-10",
        "payment_date": "2026-02-13",
        "billing_type": "PIX",
    },
    {
        "customer_id": "cus_aaa",
        "customer_name": "Alice Silva",
        "value": 150.0,
        "status": "OVERDUE",
        "due_date": "2026-03-10",
        "payment_date": None,
        "billing_type": "BOLETO",
    },
    # Cliente B — sempre em dia
    {
        "customer_id": "cus_bbb",
        "customer_name": "Bruno Costa",
        "value": 200.0,
        "status": "RECEIVED",
        "due_date": "2026-01-15",
        "payment_date": "2026-01-14",
        "billing_type": "PIX",
    },
    {
        "customer_id": "cus_bbb",
        "customer_name": "Bruno Costa",
        "value": 200.0,
        "status": "CONFIRMED",
        "due_date": "2026-02-15",
        "payment_date": "2026-02-15",
        "billing_type": "PIX",
    },
    # Cliente C — sem payment_date (PENDING)
    {
        "customer_id": "cus_ccc",
        "customer_name": "Carla Dias",
        "value": 100.0,
        "status": "PENDING",
        "due_date": "2026-04-10",
        "payment_date": None,
        "billing_type": "BOLETO",
    },
]


def _make_supabase_mock():
    """Cria mock do supabase que retorna COBRANCAS_MOCK."""
    svc = MagicMock()
    sb = MagicMock()
    svc.client = sb

    # Chain: sb.table("asaas_cobrancas").select(...).eq(...).is_(...).execute()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=COBRANCAS_MOCK)
    sb.table.return_value.select.return_value.eq.return_value.is_.return_value = chain

    return svc


@pytest.fixture
def client():
    from app.main import app
    from app.middleware.auth import get_current_user

    async def mock_get_current_user():
        return {"id": "test", "role": "admin"}

    app.dependency_overrides[get_current_user] = mock_get_current_user

    svc = _make_supabase_mock()
    with patch("app.api.routes.asaas_dashboard.get_supabase_service", return_value=svc):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


class TestPaymentTimeline:
    """Testes do endpoint payment-timeline."""

    def test_returns_customers_grouped(self, client):
        """Deve retornar cobranças agrupadas por customer_id."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        customers = data["data"]["customers"]
        customer_ids = [c["customer_id"] for c in customers]
        assert "cus_aaa" in customer_ids
        assert "cus_bbb" in customer_ids
        assert "cus_ccc" in customer_ids

    def test_delta_days_calculated_correctly(self, client):
        """D+0 quando paga no dia, D+3 quando 3 dias atrasado, D-1 quando antecipou."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()
        customers = {c["customer_id"]: c for c in data["data"]["customers"]}

        alice = customers["cus_aaa"]
        # Jan: pagou no dia = D+0
        assert alice["payments"][0]["delta_days"] == 0
        assert alice["payments"][0]["delta"] == "D+0"
        # Fev: pagou 3 dias depois = D+3
        assert alice["payments"][1]["delta_days"] == 3
        assert alice["payments"][1]["delta"] == "D+3"
        # Mar: não pagou = None
        assert alice["payments"][2]["delta_days"] is None

        bruno = customers["cus_bbb"]
        # Jan: pagou 1 dia antes = D-1
        assert bruno["payments"][0]["delta_days"] == -1
        assert bruno["payments"][0]["delta"] == "D-1"

    def test_stats_avg_delta(self, client):
        """Stats deve calcular média dos delta_days (só pagos)."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()
        customers = {c["customer_id"]: c for c in data["data"]["customers"]}

        # Alice: D+0 e D+3 = avg 1.5
        assert customers["cus_aaa"]["stats"]["avg_delta_days"] == 1.5
        assert customers["cus_aaa"]["stats"]["total_payments"] == 2
        assert customers["cus_aaa"]["stats"]["total_pending"] == 1

        # Bruno: D-1 e D+0 = avg -0.5
        assert customers["cus_bbb"]["stats"]["avg_delta_days"] == -0.5

    def test_stats_trend(self, client):
        """Trend: compara média 1ª metade vs 2ª metade dos deltas."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()
        customers = {c["customer_id"]: c for c in data["data"]["customers"]}

        # Alice: deltas pagos = [0, 3]. 1ª metade avg=0, 2ª metade avg=3 → worsening
        assert customers["cus_aaa"]["stats"]["trend"] == "worsening"
        # Bruno: deltas pagos = [-1, 0]. 1ª metade avg=-1, 2ª metade avg=0 → diff=1 > 0.5 → worsening
        assert customers["cus_bbb"]["stats"]["trend"] == "worsening"

    def test_payments_sorted_chronologically(self, client):
        """Pagamentos devem vir em ordem cronológica (due_date asc)."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()

        for customer in data["data"]["customers"]:
            dates = [p["due_date"] for p in customer["payments"]]
            assert dates == sorted(dates), f"{customer['customer_name']} não está ordenado"

    def test_pending_has_null_delta(self, client):
        """Cobranças PENDING/OVERDUE sem payment_date devem ter delta null."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()
        customers = {c["customer_id"]: c for c in data["data"]["customers"]}

        carla = customers["cus_ccc"]
        assert carla["payments"][0]["delta_days"] is None
        assert carla["payments"][0]["delta"] is None

    def test_customer_with_only_pending_has_no_avg(self, client):
        """Cliente só com pendentes: avg_delta_days = None, trend = null."""
        resp = client.get("/api/dashboard/asaas/payment-timeline")
        data = resp.json()
        customers = {c["customer_id"]: c for c in data["data"]["customers"]}

        carla = customers["cus_ccc"]
        assert carla["stats"]["avg_delta_days"] is None
        assert carla["stats"]["trend"] is None
