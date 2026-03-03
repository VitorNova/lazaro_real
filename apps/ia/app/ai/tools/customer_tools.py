"""
Tools de cliente/lead para IA.

Handlers para function calling do Gemini relacionados a:
- Salvar dados do lead (CPF/nome coletados durante conversa)

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.13)
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class CustomerTools:
    """
    Colecao de tools de cliente/lead para function calling.

    Salva dados do lead coletados durante a conversa.
    """

    def __init__(self, context: Dict[str, Any], supabase_client):
        """
        Inicializa as tools de cliente.

        Args:
            context: Contexto de processamento (agent_id, remotejid, table_leads, etc)
            supabase_client: Cliente Supabase para persistencia
        """
        self.context = context
        self.supabase = supabase_client
        self.logger = logger.bind(component="CustomerTools")

    def _clean_cpf(self, cpf: str) -> Optional[str]:
        """
        Limpa CPF/CNPJ removendo caracteres nao numericos.

        Args:
            cpf: CPF ou CNPJ com ou sem formatacao

        Returns:
            CPF limpo ou None se vazio
        """
        if not cpf:
            return None
        return re.sub(r'\D', '', cpf)

    def _validate_document(self, cpf_limpo: str) -> tuple[bool, str, str]:
        """
        Valida formato do documento.

        Args:
            cpf_limpo: Documento apenas com numeros

        Returns:
            Tupla (valido, tipo_doc, mensagem_erro)
        """
        if not cpf_limpo:
            return False, "", "CPF nao informado"

        if len(cpf_limpo) == 11:
            return True, "CPF", ""
        elif len(cpf_limpo) == 14:
            return True, "CNPJ", ""
        else:
            return (
                False,
                "",
                f"Documento invalido. CPF deve ter 11 digitos, CNPJ 14. "
                f"Informado: {len(cpf_limpo)} digitos.",
            )

    async def salvar_dados_lead(
        self,
        cpf: str = None,
        nome: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Salva CPF e nome do lead na base quando ele fornece durante a conversa.

        Usado para rastreamento de conversao Lead -> Cliente Asaas.

        Args:
            cpf: CPF ou CNPJ do lead (sera limpo e validado)
            nome: Nome do lead (opcional)

        Returns:
            Dict com resultado da operacao
        """
        self.logger.info(
            "salvar_dados_lead_start",
            cpf=cpf,
            nome=nome,
        )

        # Limpar e validar CPF
        cpf_limpo = self._clean_cpf(cpf)
        valido, tipo_doc, erro = self._validate_document(cpf_limpo)

        if not valido:
            return {
                "sucesso": False,
                "mensagem": erro,
            }

        # Buscar dados do contexto
        table_leads = self.context.get("table_leads")
        remotejid = self.context.get("remotejid")

        if not table_leads or not remotejid:
            self.logger.error(
                "salvar_dados_lead_context_incomplete",
                table_leads=table_leads,
                remotejid=remotejid,
            )
            return {
                "sucesso": False,
                "mensagem": "Erro interno ao salvar dados",
            }

        # Montar dados para atualizacao
        update_data = {
            "cpf_cnpj": cpf_limpo,
            "updated_date": datetime.utcnow().isoformat(),
        }

        if nome:
            update_data["nome"] = nome

        # Salvar na tabela de leads
        try:
            self.supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                update_data,
            )

            self.logger.info(
                "salvar_dados_lead_success",
                remotejid=remotejid,
                cpf=cpf_limpo,
                tipo=tipo_doc,
            )

            return {
                "sucesso": True,
                "cpf": cpf_limpo,
                "tipo": tipo_doc,
                "mensagem": f"{tipo_doc} salvo com sucesso",
            }

        except Exception as e:
            self.logger.error(
                "salvar_dados_lead_error",
                error=str(e),
                exc_info=True,
            )
            return {
                "sucesso": False,
                "mensagem": f"Erro ao salvar {tipo_doc}: {str(e)}",
            }

    def get_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario de handlers para registro no tool registry.

        Returns:
            Dict com nome_tool -> handler
        """
        return {
            "salvar_dados_lead": self.salvar_dados_lead,
        }


# Factory function para criar tools de cliente
def create_customer_tools(
    context: Dict[str, Any],
    supabase_client,
) -> CustomerTools:
    """
    Cria instancia de CustomerTools.

    Args:
        context: Contexto de processamento
        supabase_client: Cliente Supabase

    Returns:
        Instancia configurada de CustomerTools
    """
    return CustomerTools(context, supabase_client)
