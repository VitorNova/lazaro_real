"""
Tools de manutencao para IA.

Handlers para function calling do Gemini relacionados a:
- Identificar equipamento do cliente
- Analisar foto de equipamento (Gemini Vision)
- Verificar disponibilidade de slots de manutencao
- Confirmar agendamento de manutencao

Nota: Este modulo e um wrapper que delega para app.tools.manutencao,
onde a logica real de manutencao esta implementada.

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.11)
"""

from typing import Any, Callable, Dict, List, Optional

import structlog

from app.tools.manutencao import (
    analisar_foto_equipamento,
    confirmar_agendamento_manutencao,
    identificar_equipamento,
    verificar_disponibilidade_manutencao,
)

logger = structlog.get_logger(__name__)


class MaintenanceTools:
    """
    Colecao de tools de manutencao para function calling.

    Usado pelo agente Lazaro (Alugar Ar) para:
    - Identificar equipamentos do cliente
    - Analisar fotos de equipamentos
    - Verificar/confirmar slots de manutencao
    """

    def __init__(self, context: Dict[str, Any]):
        """
        Inicializa as tools de manutencao.

        Args:
            context: Contexto de processamento (agent_id, remotejid, phone, etc)
        """
        self.context = context
        self.logger = logger.bind(component="MaintenanceTools")

    def _extract_phone_from_remotejid(self, remotejid: str) -> str:
        """
        Extrai telefone limpo do remotejid.

        Args:
            remotejid: RemoteJid do WhatsApp

        Returns:
            Telefone sem sufixos
        """
        return (
            remotejid
            .replace("@s.whatsapp.net", "")
            .replace("@lid", "")
            .replace("@c.us", "")
        )

    async def identificar_equipamento(
        self,
        telefone: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Identifica equipamento do cliente para manutencao.

        Busca os equipamentos cadastrados para o cliente baseado
        no telefone ou contrato.

        Args:
            telefone: Telefone do cliente (opcional, usa do contexto)

        Returns:
            Dict com equipamentos encontrados
        """
        self.logger.debug("identificar_equipamento_start", telefone=telefone)

        # Se nao informou telefone, usar do contexto
        if not telefone:
            telefone = self.context.get("phone")

        agent_id = self.context.get("agent_id")

        return await identificar_equipamento(
            telefone=telefone,
            agent_id=agent_id,
        )

    async def analisar_foto_equipamento(
        self,
        foto_url: str,
        equipamentos_cliente: List[Dict] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Analisa foto do equipamento usando Gemini Vision.

        Identifica modelo, marca e possveis problemas visiveis
        no equipamento fotografado.

        Args:
            foto_url: URL da foto do equipamento
            equipamentos_cliente: Lista de equipamentos do cliente (para matching)

        Returns:
            Dict com analise da foto
        """
        self.logger.debug(
            "analisar_foto_start",
            foto_url=foto_url[:50] if foto_url else None,
        )

        if not equipamentos_cliente:
            equipamentos_cliente = []

        return await analisar_foto_equipamento(
            foto_url,
            equipamentos_cliente,
        )

    async def verificar_disponibilidade(
        self,
        data: str,
        periodo: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Verifica se slot de manutencao esta disponivel.

        Args:
            data: Data desejada (YYYY-MM-DD)
            periodo: Periodo do dia (manha, tarde)

        Returns:
            Dict com disponibilidade do slot
        """
        self.logger.debug(
            "verificar_disponibilidade_start",
            data=data,
            periodo=periodo,
        )

        agent_id = self.context.get("agent_id")

        return await verificar_disponibilidade_manutencao(
            data=data,
            periodo=periodo,
            agent_id=agent_id,
        )

    async def confirmar_agendamento(
        self,
        data: str,
        periodo: str,
        contract_id: str,
        cliente_nome: str,
        telefone: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Confirma e registra agendamento de manutencao no slot.

        Args:
            data: Data do agendamento (YYYY-MM-DD)
            periodo: Periodo do dia (manha, tarde)
            contract_id: ID do contrato
            cliente_nome: Nome do cliente
            telefone: Telefone do cliente (opcional)

        Returns:
            Dict com confirmacao do agendamento
        """
        self.logger.debug(
            "confirmar_agendamento_start",
            data=data,
            periodo=periodo,
            contract_id=contract_id,
        )

        agent_id = self.context.get("agent_id")

        # Se nao informou telefone, extrair do remotejid
        if not telefone:
            remotejid = self.context.get("remotejid", "")
            telefone = self._extract_phone_from_remotejid(remotejid)

        return await confirmar_agendamento_manutencao(
            data=data,
            periodo=periodo,
            contract_id=contract_id,
            cliente_nome=cliente_nome,
            telefone=telefone,
            agent_id=agent_id,
        )

    def get_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario de handlers para registro no tool registry.

        Returns:
            Dict com nome_tool -> handler
        """
        return {
            "identificar_equipamento": self.identificar_equipamento,
            "analisar_foto_equipamento": self.analisar_foto_equipamento,
            "verificar_disponibilidade_manutencao": self.verificar_disponibilidade,
            "confirmar_agendamento_manutencao": self.confirmar_agendamento,
        }


# Factory function para criar tools de manutencao
def create_maintenance_tools(context: Dict[str, Any]) -> MaintenanceTools:
    """
    Cria instancia de MaintenanceTools.

    Args:
        context: Contexto de processamento

    Returns:
        Instancia configurada de MaintenanceTools
    """
    return MaintenanceTools(context)
