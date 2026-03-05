"""
Tools de cobranca/billing para IA.

Handlers para function calling do Gemini relacionados a:
- Buscar cobrancas pendentes do cliente
- Consultar cliente (dados unificados)

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.12)
"""

import re
from typing import Any, Callable, Dict, List, Optional

import structlog
from supabase import create_client

from app.config import settings
from app.ai.tools.cliente import consultar_cliente

logger = structlog.get_logger(__name__)


class BillingTools:
    """
    Colecao de tools de cobranca para function calling.

    Busca cobrancas pendentes e dados financeiros do cliente.
    """

    def __init__(self, context: Dict[str, Any]):
        """
        Inicializa as tools de cobranca.

        Args:
            context: Contexto de processamento (agent_id, remotejid, etc)
        """
        self.context = context
        self.logger = logger.bind(component="BillingTools")
        self._supabase_client = None

    @property
    def supabase_client(self):
        """Lazy initialization do cliente Supabase."""
        if self._supabase_client is None:
            self._supabase_client = create_client(
                settings.supabase_url,
                settings.supabase_service_key,
            )
        return self._supabase_client

    def _extract_phone_from_remotejid(self, remotejid: str) -> str:
        """Extrai telefone limpo do remotejid."""
        return (
            remotejid
            .replace("@s.whatsapp.net", "")
            .replace("@lid", "")
            .replace("@c.us", "")
        )

    def _clean_cpf(self, cpf: str) -> Optional[str]:
        """
        Limpa e valida CPF/CNPJ.

        Args:
            cpf: CPF ou CNPJ com ou sem formatacao

        Returns:
            CPF limpo ou None se invalido
        """
        if not cpf:
            return None

        cpf_limpo = re.sub(r'\D', '', cpf)

        if len(cpf_limpo) not in [11, 14]:
            return None

        return cpf_limpo

    def _get_phone_variations(self, telefone: str) -> List[str]:
        """Retorna variacoes do telefone (com e sem 55)."""
        telefones = [telefone]
        if not telefone.startswith("55"):
            telefones.append(f"55{telefone}")
        if telefone.startswith("55"):
            telefones.append(telefone[2:])
        return telefones

    async def _search_by_cpf(
        self,
        cpf_limpo: str,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Busca cliente por CPF em asaas_clientes."""
        self.logger.debug("search_by_cpf", cpf=cpf_limpo, agent_id=agent_id)

        query = self.supabase_client.table("asaas_clientes").select(
            "id, name, mobile_phone, agent_id"
        ).eq("cpf_cnpj", cpf_limpo).is_("deleted_at", "null")

        if agent_id:
            query = query.eq("agent_id", agent_id)

        result = query.execute()

        if result.data and len(result.data) > 0:
            cliente = result.data[0]
            self.logger.info(
                "customer_found_by_cpf",
                customer_id=cliente["id"],
                name=cliente["name"],
            )
            return cliente

        return None

    async def _search_by_phone_notifications(
        self,
        telefone: str,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Busca cobrancas enviadas por telefone em billing_notifications."""
        telefones = self._get_phone_variations(telefone)

        self.logger.debug("search_by_phone", phones=telefones)

        for tel in telefones:
            query = self.supabase_client.table("billing_notifications").select(
                "customer_id, customer_name, payment_id, valor, due_date, status, payment_link"
            ).eq("phone", tel).in_(
                "status", ["sent", "pending"]
            )

            if agent_id:
                query = query.eq("agent_id", agent_id)

            result = query.order("sent_at", desc=True).limit(5).execute()

            if result.data:
                cobrancas = result.data
                self.logger.info(
                    "notifications_found",
                    phone=tel,
                    count=len(cobrancas),
                )

                # Formatar resposta
                lista_cobrancas = []
                for cob in cobrancas:
                    valor = cob.get('valor')
                    lista_cobrancas.append({
                        "valor": f"R$ {float(valor):.2f}" if valor else "N/A",
                        "vencimento": cob.get("due_date", "N/A"),
                        "status": cob.get("status", "pendente"),
                        "link": cob.get("payment_link", ""),
                    })

                primeira = cobrancas[0]
                link = primeira.get("payment_link", "")
                valor = primeira.get("valor")
                valor_fmt = f"R$ {float(valor):.2f}" if valor else ""

                return {
                    "sucesso": True,
                    "encontrou": True,
                    "cliente": primeira.get("customer_name", "Cliente"),
                    "cobrancas": lista_cobrancas,
                    "quantidade": len(cobrancas),
                    "link_pagamento": link,
                    "tipo_link": "fatura",
                    "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s) de {valor_fmt}. Link: {link}",
                }

        return None

    async def _search_customer_charges(
        self,
        customer_id: str,
        customer_name: str,
        agent_id: str,
    ) -> Dict[str, Any]:
        """Busca cobrancas do cliente em asaas_cobrancas."""
        self.logger.debug("search_customer_charges", customer_id=customer_id)

        query = self.supabase_client.table("asaas_cobrancas").select(
            "id, value, due_date, status, invoice_url, bank_slip_url"
        ).eq("customer_id", customer_id).in_(
            "status", ["PENDING", "OVERDUE"]
        ).is_("deleted_at", "null")

        if agent_id:
            query = query.eq("agent_id", agent_id)

        result = query.order("due_date", desc=False).limit(10).execute()

        if result.data:
            cobrancas = result.data
            self.logger.info(
                "charges_found",
                customer_id=customer_id,
                count=len(cobrancas),
            )

            # Formatar resposta
            lista_cobrancas = []
            for cob in cobrancas:
                lista_cobrancas.append({
                    "id": cob["id"],
                    "valor": f"R$ {cob['value']:.2f}" if cob.get('value') else "N/A",
                    "vencimento": cob.get("due_date", "N/A"),
                    "status": "Vencida" if cob.get("status") == "OVERDUE" else "Pendente",
                    "link_fatura": cob.get("invoice_url", ""),
                    "link_boleto": cob.get("bank_slip_url", ""),
                })

            primeira = cobrancas[0]
            link = primeira.get("invoice_url", primeira.get("bank_slip_url", ""))

            total = sum(c.get("value", 0) for c in cobrancas)
            valor_primeira = primeira.get("value", 0)

            return {
                "sucesso": True,
                "encontrou": True,
                "cliente": customer_name or "Cliente",
                "cobrancas": lista_cobrancas,
                "quantidade": len(cobrancas),
                "total": f"R$ {total:.2f}",
                "valor_primeira": f"R$ {valor_primeira:.2f}",
                "link_pagamento": link,
                "instrucao": "Envie o link ao cliente. Explique que ao abrir o link, ele pode escolher pagar por PIX ou boleto.",
                "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s). Valor: R$ {valor_primeira:.2f}. Link: {link}",
            }
        else:
            return {
                "sucesso": True,
                "encontrou": False,
                "cliente": customer_name,
                "mensagem": f"Boa noticia! Nao encontrei nenhuma fatura pendente para {customer_name}.",
            }

    async def buscar_cobrancas(
        self,
        cpf: str = None,
        tipo_link: str = "fatura",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Busca cobrancas pendentes do cliente.

        Cenario 1 (recebeu cobranca): Usa telefone do contexto
        Cenario 2 (pediu do nada): Usa CPF informado

        Args:
            cpf: CPF/CNPJ do cliente (opcional)
            tipo_link: Tipo de link preferido (fatura ou boleto)

        Returns:
            Dict com cobrancas encontradas e link de pagamento
        """
        self.logger.info(
            "buscar_cobrancas_start",
            cpf=cpf,
            tipo_link=tipo_link,
        )

        try:
            remotejid = self.context.get("remotejid", "")
            agent_id = self.context.get("agent_id")
            telefone_lead = self._extract_phone_from_remotejid(remotejid)

            # Limpar e validar CPF
            cpf_limpo = self._clean_cpf(cpf)
            if cpf and not cpf_limpo:
                return {
                    "sucesso": False,
                    "mensagem": "CPF invalido. Informe apenas os numeros (11 digitos).",
                }

            customer_id = None
            customer_name = None

            # 1. Se tem CPF, buscar cliente por CPF
            if cpf_limpo:
                cliente = await self._search_by_cpf(cpf_limpo, agent_id)
                if cliente:
                    customer_id = cliente["id"]
                    customer_name = cliente["name"]

            # 2. Se nao tem CPF/customer_id, buscar por telefone em billing_notifications
            if not customer_id and telefone_lead:
                result = await self._search_by_phone_notifications(telefone_lead, agent_id)
                if result:
                    return result

            # 3. Se encontrou customer_id por CPF, buscar cobrancas em asaas_cobrancas
            if customer_id:
                return await self._search_customer_charges(customer_id, customer_name, agent_id)

            # Nao encontrou cliente
            if cpf_limpo:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Nao encontrei cadastro com esse CPF. Verifique se digitou corretamente ou entre em contato com o financeiro.",
                }
            else:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Para localizar suas faturas, preciso que informe seu CPF.",
                }

        except Exception as e:
            self.logger.error("buscar_cobrancas_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao buscar cobrancas: {str(e)}",
            }

    async def consultar_cliente_unificado(
        self,
        cpf: str = None,
        verificar_pagamento: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Consulta unificada do cliente: dados, financeiro, contratos, equipamentos.

        Substitui: buscar_cobrancas + identificar_equipamento

        Args:
            cpf: CPF/CNPJ do cliente
            verificar_pagamento: Se True, busca faturas pagas recentemente

        Returns:
            Dict com dados completos do cliente
        """
        self.logger.info(
            "consultar_cliente_start",
            cpf=cpf,
            verificar_pagamento=verificar_pagamento,
        )

        remotejid = self.context.get("remotejid", "")
        telefone = self._extract_phone_from_remotejid(remotejid)
        agent_id = self.context.get("agent_id")

        return await consultar_cliente(
            cpf=cpf,
            telefone=telefone,
            agent_id=agent_id,
            verificar_pagamento=verificar_pagamento,
        )

    def get_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario de handlers para registro no tool registry.

        Returns:
            Dict com nome_tool -> handler
        """
        return {
            "buscar_cobrancas": self.buscar_cobrancas,
            "consultar_cliente": self.consultar_cliente_unificado,
        }


# Factory function para criar tools de billing
def create_billing_tools(context: Dict[str, Any]) -> BillingTools:
    """
    Cria instancia de BillingTools.

    Args:
        context: Contexto de processamento

    Returns:
        Instancia configurada de BillingTools
    """
    return BillingTools(context)
