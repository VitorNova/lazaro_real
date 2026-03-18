# tests/test_cors_security.py
"""
TDD — Validação de CORS Security [2026-03-18]

Contexto: CORS configurado com origin: true permite qualquer origem.
Causa: Atacante pode fazer requisições cross-origin de qualquer site.
Correção: Restringir origins para domínios permitidos.

Este teste valida a configuração do CORS no TypeScript (agnes-agent).
Como o TypeScript roda em processo separado, este teste faz requisições HTTP reais.
"""

import pytest
import httpx

# URLs de teste
AGNES_AGENT_URL = "http://127.0.0.1:3002"
ALLOWED_ORIGINS = [
    "https://lazaro.fazinzz.com",
    "https://www.lazaro.fazinzz.com",
]
BLOCKED_ORIGINS = [
    "https://evil.com",
    "https://attacker.example.com",
    "http://localhost:9999",
    "null",
]


class TestCORSSecurity:
    """
    Testes de segurança CORS para agnes-agent (TypeScript).

    Vulnerabilidade: origin: true aceita qualquer origem.
    Correção esperada: Whitelist de domínios permitidos.
    """

    @pytest.mark.asyncio
    async def test_cors_blocks_unknown_origin(self):
        """
        Requisição de origem desconhecida NÃO deve ter Access-Control-Allow-Origin.

        ANTES da correção: Retorna ACAO header com a origem (qualquer uma)
        DEPOIS da correção: NÃO retorna ACAO header para origens bloqueadas
        """
        async with httpx.AsyncClient() as client:
            for evil_origin in BLOCKED_ORIGINS:
                response = await client.options(
                    f"{AGNES_AGENT_URL}/health",
                    headers={
                        "Origin": evil_origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )

                acao_header = response.headers.get("access-control-allow-origin")

                # Após correção: origem bloqueada NÃO deve aparecer no header
                assert acao_header != evil_origin, (
                    f"CORS permite origem maliciosa: {evil_origin}\n"
                    f"Header retornado: {acao_header}\n"
                    "Vulnerabilidade: Atacante pode fazer requisições cross-origin"
                )

    @pytest.mark.asyncio
    async def test_cors_allows_legitimate_origins(self):
        """
        Requisição de origem permitida DEVE ter Access-Control-Allow-Origin.

        Após a correção, origens legítimas continuam funcionando.
        """
        async with httpx.AsyncClient() as client:
            for allowed_origin in ALLOWED_ORIGINS:
                response = await client.options(
                    f"{AGNES_AGENT_URL}/health",
                    headers={
                        "Origin": allowed_origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )

                acao_header = response.headers.get("access-control-allow-origin")

                # Origem permitida deve ser refletida ou ser wildcard
                assert acao_header in [allowed_origin, "*"], (
                    f"CORS bloqueia origem legítima: {allowed_origin}\n"
                    f"Header retornado: {acao_header}"
                )

    @pytest.mark.asyncio
    async def test_cors_no_wildcard_with_credentials(self):
        """
        Se credentials: true, não pode usar wildcard (*).

        Browsers rejeitam Access-Control-Allow-Origin: * quando
        Access-Control-Allow-Credentials: true está presente.
        """
        async with httpx.AsyncClient() as client:
            response = await client.options(
                f"{AGNES_AGENT_URL}/health",
                headers={
                    "Origin": "https://lazaro.fazinzz.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

            acao_header = response.headers.get("access-control-allow-origin")
            credentials_header = response.headers.get("access-control-allow-credentials")

            if credentials_header and credentials_header.lower() == "true":
                assert acao_header != "*", (
                    "CORS usa wildcard (*) com credentials: true\n"
                    "Isso é rejeitado pelos browsers e indica má configuração"
                )
