"""
Testes para consultar_cliente e get_billing_data_for_context

Cenários:
1. Cliente encontrado por CPF → fluxo original preservado
2. Cliente encontrado por mobile_phone com 55 → remove 55 e acha
3. Cliente encontrado por mobile_phone sem 55 → acha diretamente
4. Cliente encontrado via billing_notifications → fluxo original preservado
5. Cliente não encontrado por nenhum método → retorna pedindo CPF
6. CPF inválido → retorna erro de CPF inválido
7. Cliente encontrado por mobile_phone → asaas_customer_id salvo no lead
8. Cliente já tem asaas_customer_id no lead → não faz busca extra
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import date


# ============================================================================
# CENÁRIO 1: Cliente encontrado por CPF
# ============================================================================

class TestConsultarClientePorCPF:
    """Cenário 1: Cliente encontrado por CPF - fluxo original preservado."""

    @pytest.mark.asyncio
    async def test_encontra_cliente_por_cpf_valido(self, cliente_exemplo, cobranca_exemplo):
        """CPF válido retorna dados do cliente sem buscar por telefone."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            # Arrange
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            # Mock asaas_clientes - retorna cliente por CPF
            mock_clientes_table = MagicMock()
            mock_clientes_table.select.return_value = mock_clientes_table
            mock_clientes_table.eq.return_value = mock_clientes_table
            mock_clientes_table.is_.return_value = mock_clientes_table
            mock_clientes_table.execute.return_value = MagicMock(data=[cliente_exemplo])

            # Mock asaas_cobrancas - retorna cobrança
            mock_cobrancas_table = MagicMock()
            mock_cobrancas_table.select.return_value = mock_cobrancas_table
            mock_cobrancas_table.eq.return_value = mock_cobrancas_table
            mock_cobrancas_table.in_.return_value = mock_cobrancas_table
            mock_cobrancas_table.is_.return_value = mock_cobrancas_table
            mock_cobrancas_table.order.return_value = mock_cobrancas_table
            mock_cobrancas_table.limit.return_value = mock_cobrancas_table
            mock_cobrancas_table.execute.return_value = MagicMock(data=[cobranca_exemplo])

            # Mock contract_details - sem contratos
            mock_contratos_table = MagicMock()
            mock_contratos_table.select.return_value = mock_contratos_table
            mock_contratos_table.eq.return_value = mock_contratos_table
            mock_contratos_table.execute.return_value = MagicMock(data=[])

            # Mock billing_notifications - NÃO deve ser chamado
            mock_billing_table = MagicMock()

            def table_router(name):
                if name == "asaas_clientes":
                    return mock_clientes_table
                elif name == "asaas_cobrancas":
                    return mock_cobrancas_table
                elif name == "contract_details":
                    return mock_contratos_table
                elif name == "billing_notifications":
                    return mock_billing_table
                return MagicMock()

            mock_supabase.table = table_router

            # Act
            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="12345678901")

            # Assert
            assert result["sucesso"] is True
            assert result["encontrou"] is True
            assert result["cliente"]["nome"] == "João Silva"
            # billing_notifications NÃO deve ter sido consultado
            mock_billing_table.select.assert_not_called()

    @pytest.mark.asyncio
    async def test_cpf_encontra_cliente_deletado_no_asaas(self, cliente_exemplo):
        """CPF encontra cliente mesmo se deleted_at não é null (fallback)."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            # Primeiro execute retorna vazio (cliente ativo não encontrado)
            # Segundo execute retorna cliente (fallback para deletados)
            mock_table = MagicMock()
            mock_table.select.return_value = mock_table
            mock_table.eq.return_value = mock_table
            mock_table.is_.return_value = mock_table
            mock_table.in_.return_value = mock_table
            mock_table.order.return_value = mock_table
            mock_table.limit.return_value = mock_table

            execute_calls = [
                MagicMock(data=[]),  # Primeira busca (ativos)
                MagicMock(data=[cliente_exemplo]),  # Fallback (deletados)
                MagicMock(data=[]),  # Cobranças
                MagicMock(data=[]),  # Contratos
            ]
            mock_table.execute.side_effect = execute_calls

            mock_supabase.table.return_value = mock_table

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="12345678901")

            assert result["sucesso"] is True
            assert result["encontrou"] is True


# ============================================================================
# CENÁRIOS 2-3: Cliente encontrado por mobile_phone em asaas_clientes
# ============================================================================

class TestConsultarClientePorMobilePhone:
    """Cenários 2-3: Cliente encontrado por mobile_phone em asaas_clientes."""

    @pytest.mark.asyncio
    async def test_encontra_por_mobile_phone_com_55(self, cliente_exemplo):
        """
        Cenário 2: Telefone vem com 55 (ex: 5566999887766)
        Deve remover 55 e buscar por 66999887766 em asaas_clientes.mobile_phone
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            # Track das chamadas para verificar parâmetros
            mobile_phone_queries = []

            def track_eq(field, value):
                if field == "mobile_phone":
                    mobile_phone_queries.append(value)
                mock_table = MagicMock()
                mock_table.select.return_value = mock_table
                mock_table.eq.side_effect = track_eq
                mock_table.is_.return_value = mock_table
                mock_table.in_.return_value = mock_table
                mock_table.order.return_value = mock_table
                mock_table.limit.return_value = mock_table
                # Retorna cliente quando busca por mobile_phone
                if field == "mobile_phone" and value == "66999887766":
                    mock_table.execute.return_value = MagicMock(data=[cliente_exemplo])
                else:
                    mock_table.execute.return_value = MagicMock(data=[])
                return mock_table

            mock_table = MagicMock()
            mock_table.select.return_value = mock_table
            mock_table.eq.side_effect = track_eq
            mock_table.is_.return_value = mock_table
            mock_table.in_.return_value = mock_table
            mock_table.order.return_value = mock_table
            mock_table.limit.return_value = mock_table
            mock_table.execute.return_value = MagicMock(data=[])

            mock_supabase.table.return_value = mock_table

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(telefone="5566999887766")

            # Assert - deve ter buscado por 66999887766 (sem 55)
            assert result["sucesso"] is True
            assert result["encontrou"] is True
            assert "66999887766" in mobile_phone_queries

    @pytest.mark.asyncio
    async def test_encontra_por_mobile_phone_sem_55(self, cliente_exemplo):
        """
        Cenário 3: Telefone já vem sem 55 (ex: 66999887766)
        Deve buscar diretamente.

        Fluxo sem CPF:
        1. billing_notifications: vazio
        2. asaas_clientes (mobile_phone): retorna cliente
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            def table_router(name):
                if name == "asaas_clientes":
                    # Sem CPF, a primeira chamada já é mobile_phone
                    return create_chainable_mock([cliente_exemplo])
                elif name == "billing_notifications":
                    return create_chainable_mock([])
                elif name == "asaas_cobrancas":
                    return create_chainable_mock([])
                elif name == "contract_details":
                    return create_chainable_mock([])
                return create_chainable_mock([])

            mock_supabase.table.side_effect = table_router

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(telefone="66999887766")

            assert result["sucesso"] is True
            assert result["encontrou"] is True


# ============================================================================
# CENÁRIO 4: Cliente encontrado via billing_notifications
# ============================================================================

class TestConsultarClienteViaBillingNotifications:
    """Cenário 4: Cliente encontrado via billing_notifications - fluxo original."""

    @pytest.mark.asyncio
    async def test_encontra_via_billing_notifications(
        self, cliente_exemplo, billing_notification_exemplo
    ):
        """
        Cliente que recebeu disparo é encontrado via billing_notifications.
        NÃO deve buscar em asaas_clientes.mobile_phone.
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            mobile_phone_search_count = {"count": 0}

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            def table_router(name):
                if name == "billing_notifications":
                    # Retorna notificação (cliente encontrado por disparo)
                    return create_chainable_mock([billing_notification_exemplo])
                elif name == "asaas_clientes":
                    # Busca por customer_id (após encontrar via billing)
                    return create_chainable_mock([cliente_exemplo])
                elif name == "asaas_cobrancas":
                    return create_chainable_mock([])
                elif name == "contract_details":
                    return create_chainable_mock([])
                return create_chainable_mock([])

            mock_supabase.table.side_effect = table_router

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(telefone="5566999887766")

            assert result["sucesso"] is True
            assert result["encontrou"] is True
            assert result["cliente"]["nome"] == "João Silva"


# ============================================================================
# CENÁRIO 5: Cliente não encontrado por nenhum método
# ============================================================================

class TestConsultarClienteNaoEncontrado:
    """Cenário 5: Cliente não encontrado por nenhum método."""

    @pytest.mark.asyncio
    async def test_sem_cpf_sem_billing_sem_mobile_retorna_pedir_cpf(self):
        """
        Quando não encontra por nenhum método, retorna mensagem pedindo CPF.
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            # Todas as tabelas retornam vazio
            mock_supabase.table.return_value = create_chainable_mock([])

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(telefone="5566111222333")

            assert result["sucesso"] is False
            assert result["encontrou"] is False
            assert "cpf" in result["mensagem"].lower() or "cnpj" in result["mensagem"].lower()

    @pytest.mark.asyncio
    async def test_cpf_nao_encontrado_retorna_cpf_nao_cadastrado(self):
        """CPF informado mas não existe no sistema."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            mock_supabase.table.return_value = create_chainable_mock([])

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="99999999999")

            assert result["sucesso"] is False
            assert result["encontrou"] is False
            assert "n" in result["mensagem"].lower() and "encontr" in result["mensagem"].lower()


# ============================================================================
# CENÁRIO 6: CPF inválido
# ============================================================================

class TestConsultarClienteCPFInvalido:
    """Cenário 6: CPF inválido."""

    @pytest.mark.asyncio
    async def test_cpf_curto_retorna_erro(self):
        """CPF com menos de 11 dígitos retorna erro."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="123456")

            assert result["sucesso"] is False
            assert "invalido" in result["mensagem"].lower()

    @pytest.mark.asyncio
    async def test_cpf_longo_demais_retorna_erro(self):
        """CPF com mais de 14 dígitos retorna erro."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="123456789012345")

            assert result["sucesso"] is False
            assert "invalido" in result["mensagem"].lower()

    @pytest.mark.asyncio
    async def test_cpf_com_caracteres_especiais_e_extraido(self):
        """CPF com pontos e traços é limpo antes de validar."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            mock_supabase.table.return_value = create_chainable_mock([])

            from app.ai.tools.cliente import consultar_cliente
            # CPF com formatação: 123.456.789-01 -> 12345678901 (11 dígitos, válido)
            result = await consultar_cliente(cpf="123.456.789-01")

            # Não deve retornar erro de CPF inválido (validação passa)
            # Pode retornar "não encontrado" porque mock retorna vazio
            assert "invalido" not in result.get("mensagem", "").lower()


# ============================================================================
# CENÁRIO 7: Cliente encontrado por mobile_phone - salva asaas_customer_id
# ============================================================================

class TestVinculoAsaasCustomerIdNoLead:
    """Cenários 7-8: Salvar/usar asaas_customer_id no lead."""

    @pytest.mark.asyncio
    async def test_salva_customer_id_no_lead_apos_encontrar_por_mobile(
        self, cliente_exemplo, lead_exemplo
    ):
        """
        Cenário 7: Quando encontra cliente por mobile_phone,
        deve salvar asaas_customer_id na tabela de leads.

        Fluxo sem CPF:
        1. billing_notifications: vazio
        2. asaas_clientes (mobile_phone): retorna cliente
        3. table_leads: busca lead, faz update com asaas_customer_id
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            update_calls = []

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])

                # Track update calls
                def track_update(data):
                    update_calls.append(data)
                    return mock
                mock.update.side_effect = track_update

                return mock

            def table_router(name):
                if name == "asaas_clientes":
                    # Sem CPF, a primeira chamada já é mobile_phone
                    return create_chainable_mock([cliente_exemplo])
                elif name == "billing_notifications":
                    return create_chainable_mock([])
                elif name == "asaas_cobrancas":
                    return create_chainable_mock([])
                elif name == "contract_details":
                    return create_chainable_mock([])
                elif name == "LeadboxCRM_Ana_14e6e5ce":
                    # Lead sem asaas_customer_id (para permitir update)
                    return create_chainable_mock([lead_exemplo])
                return create_chainable_mock([])

            mock_supabase.table.side_effect = table_router

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(
                telefone="5566999887766",
                agent_id="14e6e5ce-4627-4e38-aac8-f0191669ff53",
                table_leads="LeadboxCRM_Ana_14e6e5ce",
                remotejid="5566999887766@s.whatsapp.net"
            )

            assert result["sucesso"] is True
            assert result["encontrou"] is True
            # Verificar que foi chamado update com asaas_customer_id
            assert len(update_calls) > 0
            assert update_calls[0].get("asaas_customer_id") == "cus_abc123"


# ============================================================================
# CENÁRIO 8: Cliente já tem asaas_customer_id no lead
# ============================================================================

class TestClienteComCustomerIdExistente:
    """Cenário 8: Cliente já tem asaas_customer_id no lead."""

    @pytest.mark.asyncio
    async def test_usa_customer_id_do_lead_sem_busca_extra(
        self, cliente_exemplo, lead_com_customer_id
    ):
        """
        Se lead já tem asaas_customer_id, usa direto sem fazer buscas extras.
        Este teste é para get_billing_data_for_context.
        """
        with patch("app.domain.messaging.context.billing_context.get_redis_service") as mock_redis:
            # Mock Redis - sem cache
            mock_redis_service = AsyncMock()
            mock_redis_service.client.get.return_value = None
            mock_redis_service.client.setex.return_value = None
            mock_redis.return_value = mock_redis_service

            # Mock SupabaseService
            mock_supabase = MagicMock()

            billing_notifications_called = {"called": False}

            def create_chainable_mock(return_data=None, is_single=False):
                """Cria mock encadeável. is_single=True para maybe_single (retorna dict)."""
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.update.return_value = mock
                mock.maybe_single.return_value = mock
                # maybe_single retorna dict único, não lista
                if is_single:
                    mock.execute.return_value = MagicMock(data=return_data)
                else:
                    mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            def table_router(name):
                if name == "LeadboxCRM_Ana_14e6e5ce":
                    # Lead já tem asaas_customer_id - retorna lista (não é maybe_single)
                    return create_chainable_mock([lead_com_customer_id])
                elif name == "billing_notifications":
                    billing_notifications_called["called"] = True
                    return create_chainable_mock([])
                elif name == "asaas_clientes":
                    # asaas_clientes usa maybe_single, retorna dict único
                    return create_chainable_mock(cliente_exemplo, is_single=True)
                elif name == "asaas_cobrancas":
                    return create_chainable_mock([])
                elif name == "contract_details":
                    return create_chainable_mock([])
                return create_chainable_mock([])

            mock_supabase.client.table.side_effect = table_router

            from app.domain.messaging.context.billing_context import get_billing_data_for_context
            result = await get_billing_data_for_context(
                supabase=mock_supabase,
                phone="5566999887766",
                table_leads="LeadboxCRM_Ana_14e6e5ce",
                remotejid="5566999887766@s.whatsapp.net"
            )

            # Deve ter encontrado o cliente
            assert result is not None
            assert result["customer_id"] == cliente_exemplo["id"]

            # billing_notifications NÃO deve ter sido consultado
            # porque já tinha customer_id no lead
            assert billing_notifications_called["called"] is False


# ============================================================================
# TESTES ADICIONAIS: Cobertura de edge cases
# ============================================================================

class TestEdgeCases:
    """Testes de casos extremos."""

    @pytest.mark.asyncio
    async def test_telefone_com_arroba_whatsapp(self, cliente_exemplo):
        """
        Telefone no formato WhatsApp (5566999887766@s.whatsapp.net).
        Deve extrair apenas os números e encontrar o cliente.
        """
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.in_.return_value = mock
                mock.order.return_value = mock
                mock.limit.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            def table_router(name):
                if name == "asaas_clientes":
                    # Sem CPF, a primeira chamada já é mobile_phone
                    return create_chainable_mock([cliente_exemplo])
                elif name == "billing_notifications":
                    return create_chainable_mock([])
                elif name == "asaas_cobrancas":
                    return create_chainable_mock([])
                elif name == "contract_details":
                    return create_chainable_mock([])
                return create_chainable_mock([])

            mock_supabase.table.side_effect = table_router

            from app.ai.tools.cliente import consultar_cliente
            # Telefone com sufixo WhatsApp - deve extrair apenas os números
            result = await consultar_cliente(telefone="5566999887766@s.whatsapp.net")

            assert result["sucesso"] is True
            assert result["encontrou"] is True

    @pytest.mark.asyncio
    async def test_cnpj_valido_14_digitos(self):
        """CNPJ com 14 dígitos é aceito."""
        with patch("app.ai.tools.cliente.create_client") as mock_create:
            mock_supabase = MagicMock()
            mock_create.return_value = mock_supabase

            def create_chainable_mock(return_data=None):
                mock = MagicMock()
                mock.select.return_value = mock
                mock.eq.return_value = mock
                mock.is_.return_value = mock
                mock.execute.return_value = MagicMock(data=return_data or [])
                return mock

            mock_supabase.table.return_value = create_chainable_mock([])

            from app.ai.tools.cliente import consultar_cliente
            result = await consultar_cliente(cpf="12345678000190")  # CNPJ

            # Não deve dar erro de CPF inválido
            assert "invalido" not in result.get("mensagem", "").lower()
