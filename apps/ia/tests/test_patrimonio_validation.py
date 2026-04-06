"""
Testes para validação de patrimônios extraídos de contratos.

Cobre:
1. validar_patrimonios() - rejeita patrimônios inválidos (código de produto, não-numérico)
2. Normalização para 4 dígitos
3. Detecção de contrato sem equipamentos
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Mock das dependências pesadas antes do import
_settings_mock = MagicMock()
_settings_mock.google_api_key = "fake"
_settings_mock.supabase_url = "fake"
_settings_mock.supabase_key = "fake"

config_mod = ModuleType("app.config")
config_mod.settings = _settings_mock
sys.modules.setdefault("app.config", config_mod)
sys.modules.setdefault("app.services.gateway_pagamento", MagicMock())
sys.modules.setdefault("app.services.supabase", MagicMock())
sys.modules.setdefault("app.core.utils.retry", MagicMock())
sys.modules.setdefault("app.domain.billing.models.payment", MagicMock())

# Agora importar
from app.domain.billing.services.contract_extraction_service import validar_patrimonios


# ─── Fixtures: respostas simuladas do Gemini ────────────────────────────────

GEMINI_TIPO1_OK = {
    "equipamentos": [
        {"patrimonio": "0258", "marca": "VIX", "btus": 12000, "valor_comercial": 2700.0},
    ],
}

GEMINI_TIPO2B_CORRETO = {
    "equipamentos": [
        {"patrimonio": "0566", "marca": "BRAVOLT", "btus": 12000, "valor_comercial": 2700.0},
        {"patrimonio": "0518", "marca": "VG", "btus": 12000, "valor_comercial": 2700.0},
    ],
}

GEMINI_PATRIMONIO_INVALIDO_CODIGO_PRODUTO = {
    "equipamentos": [
        {"patrimonio": "PRD00628", "marca": "CONFEE", "btus": 12000, "valor_comercial": 2700.0},
    ],
}

GEMINI_PATRIMONIO_INVALIDO_CODIGO_LINHA = {
    "equipamentos": [
        {"patrimonio": "000196", "marca": "CONFEE", "btus": 12000, "valor_comercial": 2700.0},
    ],
}

GEMINI_PATRIMONIO_NAO_NUMERICO = {
    "equipamentos": [
        {"patrimonio": "PATRI26", "marca": "VIX", "btus": 12000, "valor_comercial": 2700.0},
    ],
}

GEMINI_SEM_EQUIPAMENTOS = {
    "equipamentos": [],
}

GEMINI_MISTURA_VALIDOS_INVALIDOS = {
    "equipamentos": [
        {"patrimonio": "0285", "marca": "AGRATTO", "btus": 18000, "valor_comercial": 3700.0},
        {"patrimonio": "PRD00675", "marca": "COMFEE", "btus": 12000, "valor_comercial": 2700.0},
        {"patrimonio": "0293", "marca": "AGRATTO", "btus": 12000, "valor_comercial": 2800.0},
    ],
}


# ─── Testes ─────────────────────────────────────────────────────────────────

class TestValidarPatrimonios:

    def test_patrimonio_valido_passa(self):
        result = validar_patrimonios(GEMINI_TIPO1_OK.copy())
        eqs = result["equipamentos"]
        assert len(eqs) == 1
        assert eqs[0]["patrimonio"] == "0258"

    def test_patrimonio_tipo2b_passa(self):
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_TIPO2B_CORRETO))
        eqs = result["equipamentos"]
        assert len(eqs) == 2
        pats = {e["patrimonio"] for e in eqs}
        assert pats == {"0566", "0518"}

    def test_rejeita_codigo_produto(self):
        """PRD00628 não é patrimônio, é código de produto."""
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_PATRIMONIO_INVALIDO_CODIGO_PRODUTO))
        eqs = result["equipamentos"]
        assert len(eqs) == 0

    def test_normaliza_codigo_linha_6_digitos(self):
        """000196 deve ser normalizado para 0196 (4 dígitos)."""
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_PATRIMONIO_INVALIDO_CODIGO_LINHA))
        eqs = result["equipamentos"]
        assert len(eqs) == 1
        assert eqs[0]["patrimonio"] == "0196"

    def test_rejeita_nao_numerico(self):
        """PATRI26 não é patrimônio válido."""
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_PATRIMONIO_NAO_NUMERICO))
        eqs = result["equipamentos"]
        assert len(eqs) == 0

    def test_sem_equipamentos_retorna_warning(self):
        """Contrato sem equipamentos deve retornar dados mas com flag."""
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_SEM_EQUIPAMENTOS))
        assert result.get("_warning_no_equipamentos") is True

    def test_filtra_invalidos_mantem_validos(self):
        """Mistura de válidos e inválidos: mantém só os válidos."""
        import copy
        result = validar_patrimonios(copy.deepcopy(GEMINI_MISTURA_VALIDOS_INVALIDOS))
        eqs = result["equipamentos"]
        pats = {e["patrimonio"] for e in eqs}
        assert "0285" in pats
        assert "0293" in pats
        assert "PRD00675" not in pats

    def test_patrimonio_1_digito_normalizado(self):
        """Patrimônio "5" deve virar "0005"."""
        data = {"equipamentos": [
            {"patrimonio": "5", "marca": "X", "btus": 9000, "valor_comercial": 2500.0},
        ]}
        result = validar_patrimonios(data)
        assert result["equipamentos"][0]["patrimonio"] == "0005"

    def test_patrimonio_3_digitos_normalizado(self):
        """Patrimônio "196" deve virar "0196"."""
        data = {"equipamentos": [
            {"patrimonio": "196", "marca": "X", "btus": 12000, "valor_comercial": 2700.0},
        ]}
        result = validar_patrimonios(data)
        assert result["equipamentos"][0]["patrimonio"] == "0196"
