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

    def _buscar_cliente_por_cpf(self, cpf_limpo: str) -> Optional[Dict[str, Any]]:
        """
        Busca cliente em asaas_clientes por CPF.

        Args:
            cpf_limpo: CPF apenas numeros

        Returns:
            Dict com dados do cliente ou None
        """
        try:
            agent_id = self.context.get("agent_id")

            query = self.supabase.client.table("asaas_clientes").select(
                "id, name, cpf_cnpj, mobile_phone, email"
            ).eq("cpf_cnpj", cpf_limpo)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            result = query.limit(1).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            self.logger.warning("buscar_cliente_error", error=str(e))
            return None

    def _buscar_contrato_por_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca contrato em contract_details por customer_id.

        Args:
            customer_id: ID do cliente no Asaas

        Returns:
            Dict com dados do contrato ou None
        """
        try:
            agent_id = self.context.get("agent_id")

            query = self.supabase.client.table("contract_details").select(
                "id, numero_contrato, maintenance_status, proxima_manutencao, "
                "endereco_instalacao, equipamentos, valor_mensal"
            ).eq("customer_id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            result = query.limit(1).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            self.logger.warning("buscar_contrato_error", error=str(e))
            return None

    def _montar_retorno_enriquecido(
        self,
        cpf_limpo: str,
        tipo_doc: str,
        cliente_data: Optional[Dict[str, Any]],
        contrato_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Monta retorno enriquecido com dados de cliente e contrato.

        Args:
            cpf_limpo: CPF salvo
            tipo_doc: Tipo do documento (CPF/CNPJ)
            cliente_data: Dados do cliente ou None
            contrato_data: Dados do contrato ou None

        Returns:
            Dict com retorno enriquecido
        """
        result = {
            "sucesso": True,
            "cpf": cpf_limpo,
            "tipo": tipo_doc,
        }

        # Adicionar dados do cliente
        if cliente_data:
            result["cliente"] = {
                "nome": cliente_data.get("name"),
                "cpf": cliente_data.get("cpf_cnpj"),
                "telefone": cliente_data.get("mobile_phone"),
                "email": cliente_data.get("email"),
            }
        else:
            result["cliente"] = None

        # Adicionar dados do contrato
        if contrato_data:
            result["contrato"] = {
                "id": contrato_data.get("id"),
                "numero": contrato_data.get("numero_contrato"),
                "maintenance_status": contrato_data.get("maintenance_status"),
                "proxima_manutencao": contrato_data.get("proxima_manutencao"),
                "endereco": contrato_data.get("endereco_instalacao"),
                "equipamentos": contrato_data.get("equipamentos"),
                "valor_mensal": contrato_data.get("valor_mensal"),
            }
        else:
            result["contrato"] = None

        # Montar mensagem e instrucao contextuais
        result["mensagem"], result["instrucao"] = self._montar_mensagem_contextual(
            cliente_data, contrato_data
        )

        return result

    def _montar_mensagem_contextual(
        self,
        cliente_data: Optional[Dict[str, Any]],
        contrato_data: Optional[Dict[str, Any]],
    ) -> tuple[str, str]:
        """
        Monta mensagem e instrucao contextuais baseadas nos dados encontrados.

        Returns:
            Tupla (mensagem, instrucao)
        """
        # Cenario 1: Cliente encontrado com contrato e manutencao notificada
        if cliente_data and contrato_data:
            nome = cliente_data.get("name", "Cliente")
            status = contrato_data.get("maintenance_status", "pending")
            proxima = contrato_data.get("proxima_manutencao")
            endereco = contrato_data.get("endereco_instalacao")

            if status == "notified" and proxima:
                mensagem = (
                    f"Cliente {nome} encontrado. "
                    f"Manutencao preventiva notificada para {proxima}."
                )
                instrucao = (
                    "Pergunte qual o melhor dia e horario para a visita tecnica, "
                    "e confirme o endereco de instalacao."
                )
            elif status == "scheduled":
                mensagem = f"Cliente {nome} encontrado. Manutencao ja agendada."
                instrucao = "Pergunte se deseja remarcar ou se tem alguma duvida sobre a visita."
            else:
                mensagem = f"Cliente {nome} encontrado."
                if endereco:
                    mensagem += f" Endereco: {endereco}."
                instrucao = "Pergunte como pode ajudar o cliente."

            return mensagem, instrucao

        # Cenario 2: Cliente encontrado sem contrato
        if cliente_data and not contrato_data:
            nome = cliente_data.get("name", "Cliente")
            mensagem = f"Cliente {nome} encontrado, mas sem contrato ativo."
            instrucao = "Pergunte como pode ajudar. Se for sobre aluguel, colete os dados necessarios."
            return mensagem, instrucao

        # Cenario 3: Cliente nao encontrado
        mensagem = "CPF registrado, mas nao encontrei cadastro no sistema."
        instrucao = (
            "Verifique se o CPF esta correto. "
            "Se o cliente for novo, colete os dados para cadastro."
        )
        return mensagem, instrucao

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

            # Enriquecer retorno buscando cliente e contrato
            cliente_data = self._buscar_cliente_por_cpf(cpf_limpo)
            contrato_data = None

            if cliente_data:
                customer_id = cliente_data.get("id")
                if customer_id:
                    contrato_data = self._buscar_contrato_por_customer(customer_id)

            self.logger.info(
                "salvar_dados_lead_enriched",
                cliente_encontrado=cliente_data is not None,
                contrato_encontrado=contrato_data is not None,
            )

            return self._montar_retorno_enriquecido(
                cpf_limpo, tipo_doc, cliente_data, contrato_data
            )

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
