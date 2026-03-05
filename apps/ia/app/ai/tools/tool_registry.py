"""
Registry centralizado de tools para IA.

Factory que cria e registra todas as tools disponiveis
para function calling do Gemini.

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.14)
"""

from typing import Any, Callable, Dict

import structlog

from app.ai.tools.scheduling_tools import SchedulingTools
from app.ai.tools.transfer_tools import TransferTools
from app.ai.tools.maintenance_tools import MaintenanceTools
from app.ai.tools.billing_tools import BillingTools
from app.ai.tools.customer_tools import CustomerTools
from app.services.supabase import SupabaseService

logger = structlog.get_logger(__name__)

# Timezone padrao do sistema
DEFAULT_TIMEZONE = "America/Sao_Paulo"


class ToolRegistry:
    """
    Registry centralizado de tools para function calling.

    Agrega todas as tools dos diferentes dominios (scheduling,
    transfer, maintenance, billing, customer) em um unico
    dicionario de handlers.
    """

    def __init__(
        self,
        supabase: SupabaseService,
        context: Dict[str, Any],
    ):
        """
        Inicializa o registry com todas as tools.

        Args:
            supabase: Servico Supabase para persistencia
            context: Contexto de processamento (agent_id, remotejid, etc)
        """
        self.supabase = supabase
        self.context = context
        self.logger = logger.bind(component="ToolRegistry")

        # Inicializar todas as tool classes
        self._scheduling_tools = SchedulingTools(supabase, context)
        self._transfer_tools = TransferTools(supabase, context)
        self._maintenance_tools = MaintenanceTools(context)
        self._billing_tools = BillingTools(context)
        self._customer_tools = CustomerTools(context, supabase)

    def get_lead_timezone(self) -> str:
        """
        Busca o timezone salvo do lead ou retorna o padrao.

        Returns:
            Timezone string (ex: "America/Sao_Paulo")
        """
        try:
            remotejid = self.context.get("remotejid")
            table_leads = self.context.get("table_leads")
            lead = self.supabase.get_lead_by_remotejid(table_leads, remotejid)

            if lead and lead.get("timezone"):
                return lead["timezone"]

            return DEFAULT_TIMEZONE
        except Exception as e:
            self.logger.warning("timezone_fetch_error", error=str(e))
            return DEFAULT_TIMEZONE

    def get_all_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario com todos os handlers registrados.

        O dicionario mapeia nome_tool -> handler async.

        Tools ativas (v2):
        - consultar_cliente: Consulta unificada do cliente
        - salvar_dados_lead: Salva CPF/nome do lead
        - transferir_departamento: Transfere para departamento

        Tools de manutencao (habilitadas Fase 9.7):
        - identificar_equipamento: Identifica ACs do cliente (qtd, local)
        - analisar_foto_equipamento: Analisa foto via Gemini Vision
        - verificar_disponibilidade_manutencao: Verifica slots
        - confirmar_agendamento_manutencao: Confirma agendamento

        Tools legadas (desabilitadas):
        - consulta_agenda: Consulta horarios disponiveis
        - agendar: Cria agendamento
        - cancelar_agendamento: Cancela agendamento
        - reagendar: Reagenda
        - detectar_fuso_horario: Detecta timezone
        - buscar_cobrancas: Substituida por consultar_cliente

        Returns:
            Dict com nome -> handler callable
        """
        handlers = {}

        # Tools v2 (ativas)
        handlers.update(self._billing_tools.get_handlers())
        handlers.update(self._customer_tools.get_handlers())
        handlers.update(self._transfer_tools.get_handlers())

        # Tools legadas (mantidas para fallback)
        handlers.update(self._scheduling_tools.get_handlers())
        handlers.update(self._maintenance_tools.get_handlers())

        self.logger.debug(
            "handlers_registered",
            count=len(handlers),
            tools=list(handlers.keys()),
        )

        return handlers


def create_tool_registry(
    supabase: SupabaseService,
    context: Dict[str, Any],
) -> ToolRegistry:
    """
    Factory function para criar ToolRegistry.

    Args:
        supabase: Servico Supabase
        context: Contexto de processamento

    Returns:
        Instancia configurada de ToolRegistry
    """
    return ToolRegistry(supabase, context)


def get_function_handlers(
    supabase: SupabaseService,
    context: Dict[str, Any],
) -> Dict[str, Callable]:
    """
    Funcao de conveniencia para obter handlers diretamente.

    Substitui o metodo _create_function_handlers do WhatsAppWebhookHandler.

    Args:
        supabase: Servico Supabase
        context: Contexto de processamento

    Returns:
        Dict com nome -> handler callable
    """
    registry = create_tool_registry(supabase, context)
    return registry.get_all_handlers()
