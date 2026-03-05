"""
Function declarations and handlers for Gemini AI tools.

This module provides:
- FUNCTION_DECLARATIONS: List of tool definitions in Gemini format (ONLY ACTIVE TOOLS)
- FunctionHandlers: Class with async methods to execute each tool

REFATORACAO 2026-02-28:
- Reduzido de 11 tools para 2 tools ativas
- consultar_cliente: substitui buscar_cobrancas + identificar_equipamento
- transferir_departamento: mantida
- Tools antigas mantidas no codigo (nao deletadas) mas nao exportadas

REFATORACAO 2026-03-05 (Fase 9.7):
- Habilitadas 4 tools de manutencao:
  - identificar_equipamento: identifica ACs do cliente (qtd, local, marca)
  - analisar_foto_equipamento: analisa foto do AC via Gemini Vision
  - verificar_disponibilidade_manutencao: verifica slots disponiveis
  - confirmar_agendamento_manutencao: confirma e registra agendamento
- Agora IA pode coletar dados antes de transferir
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import re

from supabase import create_client
from app.config import settings
from app.ai.tools.cliente import CONSULTAR_CLIENTE_DECLARATION
from app.domain.maintenance.services.equipment_tools import MAINTENANCE_FUNCTION_DECLARATIONS

logger = logging.getLogger(__name__)


# ============================================================================
# TOOLS DESABILITADAS (mantidas no codigo, nao exportadas)
# ============================================================================

DISABLED_TOOLS = [
    "detectar_fuso_horario",
    "consulta_agenda",
    "agendar",
    "cancelar_agendamento",
    "reagendar",
    "buscar_cobrancas",        # substituida por consultar_cliente
    # Maintenance tools HABILITADAS na Fase 9.7:
    # - identificar_equipamento: identifica ACs do cliente
    # - analisar_foto_equipamento: analisa foto do AC
    # - verificar_disponibilidade_manutencao: verifica slots
    # - confirmar_agendamento_manutencao: confirma agendamento
]

# Tools de calendário (para compatibilidade, todas desabilitadas)
CALENDAR_TOOL_NAMES = ["consulta_agenda", "agendar", "cancelar_agendamento", "reagendar"]


# ============================================================================
# FUNCTION DECLARATIONS ATIVAS - Gemini Format
# ============================================================================

# Declaration do salvar_dados_lead - salva CPF/nome do lead
SALVAR_DADOS_LEAD_DECLARATION = {
    "name": "salvar_dados_lead",
    "description": (
        "Salva o CPF e nome do lead na base quando ele fornece durante a conversa. "
        "Usar SEMPRE que o lead informar o CPF, seja formatado (123.456.789-00) ou "
        "apenas numeros (12345678900). Tambem aceita CNPJ (14 digitos). "
        "Se o lead informar o nome, inclua tambem."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cpf": {
                "type": "string",
                "description": "CPF ou CNPJ do lead (11 digitos para CPF, 14 para CNPJ). Pode conter pontos, tracos ou barras - sera limpo automaticamente."
            },
            "nome": {
                "type": "string",
                "description": "Nome completo do lead (opcional, use se ele informar)"
            }
        },
        "required": ["cpf"]
    }
}

# Declaration do transferir_departamento (mantida igual)
TRANSFERIR_DEPARTAMENTO_DECLARATION = {
    "name": "transferir_departamento",
    "description": "Transfere o atendimento para outro departamento ou atendente humano. Use quando o assunto foge do seu escopo ou quando o cliente solicita falar com humano.",
    "parameters": {
        "type": "object",
        "properties": {
            "departamento": {
                "type": "string",
                "description": "Nome do departamento de destino (ex: financeiro, vendas, suporte). Opcional se queue_id for informado."
            },
            "queue_id": {
                "type": "integer",
                "description": "ID da fila/departamento no sistema. Use quando souber o ID direto."
            },
            "user_id": {
                "type": "integer",
                "description": "ID do usuario/atendente especifico. Opcional."
            },
            "motivo": {
                "type": "string",
                "description": "Motivo da transferencia"
            },
            "observacoes": {
                "type": "string",
                "description": "Observacoes adicionais para o atendente de destino"
            }
        },
        "required": ["motivo"]
    }
}

# FUNCTION_DECLARATIONS exportado - 7 TOOLS ATIVAS (3 base + 4 manutencao)
FUNCTION_DECLARATIONS = [
    CONSULTAR_CLIENTE_DECLARATION,
    SALVAR_DADOS_LEAD_DECLARATION,
    TRANSFERIR_DEPARTAMENTO_DECLARATION,
] + MAINTENANCE_FUNCTION_DECLARATIONS


# ============================================================================
# FUNCTION DECLARATIONS LEGADAS (mantidas para fallback, NAO exportadas)
# ============================================================================

_LEGACY_DECLARATIONS = [
    {
        "name": "consulta_agenda",
        "description": "Consulta horarios disponiveis na agenda. Se nao informar data, busca os proximos dias automaticamente.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Data especifica no formato YYYY-MM-DD (ex: 2024-01-15). Opcional - se omitido, busca proximos dias."
                },
                "duration": {
                    "type": "integer",
                    "description": "Duracao desejada em minutos (padrao: 30)"
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Quantos dias a frente buscar quando date nao informado (padrao: 5)"
                }
            },
            "required": []
        }
    },
    {
        "name": "agendar",
        "description": "Cria um novo agendamento na agenda. Gera automaticamente um link do Google Meet. Os dados do cliente sao obtidos automaticamente do contexto.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Data do agendamento no formato YYYY-MM-DD (ex: 2024-01-15)"
                },
                "time": {
                    "type": "string",
                    "description": "Horario do agendamento no formato HH:MM (ex: 14:00)"
                },
                "duration": {
                    "type": "integer",
                    "description": "Duracao em minutos (padrao: 30)"
                },
                "title": {
                    "type": "string",
                    "description": "Titulo do evento (opcional - usa nome do cliente se nao informado)"
                },
                "description": {
                    "type": "string",
                    "description": "Descricao ou observacoes do agendamento"
                }
            },
            "required": ["date", "time"]
        }
    },
    {
        "name": "cancelar_agendamento",
        "description": "Cancela um agendamento existente na agenda.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID do evento/agendamento a ser cancelado"
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo do cancelamento"
                }
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "reagendar",
        "description": "Reagenda um agendamento existente para uma nova data/hora.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID do evento/agendamento a ser reagendado"
                },
                "nova_data": {
                    "type": "string",
                    "description": "Nova data no formato YYYY-MM-DD (ex: 2024-01-16)"
                },
                "novo_horario": {
                    "type": "string",
                    "description": "Novo horario no formato HH:MM (ex: 15:00)"
                },
                "duration": {
                    "type": "integer",
                    "description": "Duracao em minutos (padrao: 30)"
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo do reagendamento"
                }
            },
            "required": ["event_id", "nova_data", "novo_horario"]
        }
    },
    {
        "name": "buscar_cobrancas",
        "description": "DESABILITADA - Substituida por consultar_cliente. Busca cobrancas/faturas pendentes do cliente.",
        "parameters": {
            "type": "object",
            "properties": {
                "cpf": {
                    "type": "string",
                    "description": "CPF do cliente (apenas numeros). Obrigatorio se o cliente nao recebeu cobranca recente."
                },
                "tipo_link": {
                    "type": "string",
                    "enum": ["pix", "boleto", "fatura"],
                    "description": "Tipo de link que o cliente quer: 'pix' para Pix copia-e-cola, 'boleto' para boleto PDF, 'fatura' para pagina de pagamento. Padrao: fatura"
                }
            },
            "required": []
        }
    },
    {
        "name": "detectar_fuso_horario",
        "description": "Detecta o fuso horário do lead baseado na cidade/estado. Use quando o lead informar de onde ele é para garantir agendamentos no horário correto dele.",
        "parameters": {
            "type": "object",
            "properties": {
                "cidade": {
                    "type": "string",
                    "description": "Nome da cidade do lead"
                },
                "estado": {
                    "type": "string",
                    "description": "Sigla do estado (ex: SP, MT, RJ, AM)"
                }
            },
            "required": ["estado"]
        }
    }
]


# ============================================================================
# FUNCAO AUXILIAR (mantida para compatibilidade, mas sempre retorna as 2 tools)
# ============================================================================

def get_function_declarations(has_calendar: bool = False) -> List[Dict[str, Any]]:
    """
    Retorna FUNCTION_DECLARATIONS.

    Args:
        has_calendar: Ignorado (mantido para compatibilidade)

    Returns:
        Lista de function declarations (7 tools ativas: 3 base + 4 manutencao)
    """
    logger.debug(f"Retornando {len(FUNCTION_DECLARATIONS)} tools ativas")
    return FUNCTION_DECLARATIONS


# ============================================================================
# FUNCTION HANDLERS
# ============================================================================

class FunctionHandlers:
    """
    Handles execution of AI tool function calls.

    Note: Calendar tools (consulta_agenda, agendar, cancelar_agendamento, reagendar,
    detectar_fuso_horario) are created dynamically per-request in whatsapp.py
    with per-agent OAuth credentials. This class only handles generic tools.
    """

    def __init__(
        self,
        leadbox_service: Any = None,
        supabase_service: Any = None
    ):
        self.leadbox = leadbox_service
        self.supabase = supabase_service

    async def transferir_departamento(
        self,
        motivo: str,
        departamento: Optional[str] = None,
        queue_id: Optional[int] = None,
        user_id: Optional[int] = None,
        observacoes: Optional[str] = None,
        **kwargs  # Aceita parâmetros extras do Gemini
    ) -> Dict[str, Any]:
        """
        Transfer the conversation to another department.

        Args:
            motivo: Reason for transfer
            departamento: Target department name (optional if queue_id provided)
            queue_id: Direct queue/department ID (optional if departamento provided)
            user_id: Direct user/agent ID (optional)
            observacoes: Additional notes for the receiving department

        Returns:
            Dict with sucesso, mensagem
        """
        try:
            logger.info(f"Transferindo: dept={departamento}, queue_id={queue_id}, user_id={user_id}, motivo={motivo}")

            # Se nao tem leadbox service configurado, retorna erro
            if not self.leadbox:
                return {
                    "sucesso": False,
                    "mensagem": "Servico de transferencia nao configurado. Use o handler do contexto."
                }

            # Execute transfer via leadbox service
            transfer_result = await self.leadbox.transfer_to_department(
                department=departamento.lower() if departamento else None,
                queue_id=queue_id,
                user_id=user_id,
                reason=motivo,
                notes=observacoes
            )

            dept_display = departamento or f"fila {queue_id}"

            return {
                "sucesso": True,
                "mensagem": f"Atendimento transferido para {dept_display}. Motivo: {motivo}"
            }

        except Exception as e:
            logger.error(f"Erro ao transferir: {e}")
            return {
                "sucesso": False,
                "mensagem": f"Erro ao transferir atendimento: {str(e)}"
            }

    async def buscar_cobrancas(
        self,
        cpf: Optional[str] = None,
        tipo_link: Optional[str] = "fatura",
        **kwargs  # Contexto extra (telefone, agent_id, etc)
    ) -> Dict[str, Any]:
        """
        LEGADO - Mantido para fallback. Substituido por consultar_cliente.

        Busca cobrancas pendentes do cliente.

        Cenario 1 (recebeu cobranca): Usa telefone do contexto
        Cenario 2 (pediu do nada): Usa CPF informado

        Args:
            cpf: CPF do cliente (apenas numeros)
            tipo_link: Tipo de link desejado (pix, boleto, fatura)
            **kwargs: Contexto (telefone_lead, agent_id)

        Returns:
            Dict com cobrancas encontradas ou mensagem de erro
        """
        try:
            # Extrair contexto
            telefone_lead = kwargs.get("telefone_lead") or kwargs.get("phone")
            agent_id = kwargs.get("agent_id")

            logger.info(f"[LEGADO] Buscando cobrancas: cpf={cpf}, telefone={telefone_lead}, agent_id={agent_id}")

            # Conectar ao Supabase
            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

            # Limpar CPF se fornecido
            cpf_limpo = None
            if cpf:
                cpf_limpo = re.sub(r'\D', '', cpf)
                if len(cpf_limpo) not in [11, 14]:
                    return {
                        "sucesso": False,
                        "mensagem": "CPF invalido. Informe apenas os numeros (11 digitos)."
                    }

            customer_id = None
            customer_name = None

            # ================================================================
            # ESTRATEGIA DE BUSCA
            # ================================================================

            # 1. Se tem CPF, buscar em asaas_clientes
            if cpf_limpo:
                logger.debug(f"Buscando cliente por CPF: {cpf_limpo}")
                result = supabase.table("asaas_clientes").select(
                    "id, name, mobile_phone"
                ).eq("cpf_cnpj", cpf_limpo).execute()

                if result.data:
                    # Filtrar por agent_id se disponivel
                    clientes = result.data
                    if agent_id:
                        clientes = [c for c in result.data if True]  # TODO: filtrar por agent

                    if clientes:
                        customer_id = clientes[0]["id"]
                        customer_name = clientes[0]["name"]
                        logger.info(f"Cliente encontrado por CPF: {customer_id} - {customer_name}")

            # 2. Se nao tem CPF, buscar em billing_notifications pelo telefone
            if not customer_id and telefone_lead:
                # Limpar telefone
                telefone_limpo = re.sub(r'\D', '', telefone_lead)
                # Tentar com e sem 55
                telefones_busca = [telefone_limpo]
                if not telefone_limpo.startswith("55"):
                    telefones_busca.append(f"55{telefone_limpo}")
                if telefone_limpo.startswith("55"):
                    telefones_busca.append(telefone_limpo[2:])

                logger.debug(f"Buscando cobranca enviada por telefone: {telefones_busca}")

                for tel in telefones_busca:
                    result = supabase.table("billing_notifications").select(
                        "customer_id, customer_name, payment_id, valor, due_date, status"
                    ).eq("phone", tel).in_(
                        "status", ["sent", "pending"]
                    # Ordenar por due_date ASC para priorizar cobranças vencidas (mais antigas primeiro)
                    # Fix: antes ordenava por sent_at DESC, retornando a cobrança mais recente em vez da vencida
                    ).order("due_date", desc=False).limit(5).execute()

                    if result.data:
                        # Encontrou cobrancas enviadas recentemente
                        cobrancas = result.data
                        logger.info(f"Encontradas {len(cobrancas)} cobrancas enviadas para {tel}")

                        # Formatar resposta
                        lista_cobrancas = []
                        for cob in cobrancas:
                            lista_cobrancas.append({
                                "valor": f"R$ {cob['valor']:.2f}" if cob.get('valor') else "N/A",
                                "vencimento": cob.get("due_date", "N/A"),
                                "status": cob.get("status", "pendente"),
                                "link": cob.get("payment_link", "")
                            })

                        # Retornar primeira cobranca com link
                        primeira = cobrancas[0]
                        link = primeira.get("payment_link", "")

                        return {
                            "sucesso": True,
                            "encontrou": True,
                            "cliente": primeira.get("customer_name", "Cliente"),
                            "cobrancas": lista_cobrancas,
                            "quantidade": len(cobrancas),
                            "link_pagamento": link,
                            "tipo_link": "fatura",
                            "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s). Segue o link para pagamento: {link}"
                        }
                        break

            # 3. Se encontrou customer_id, buscar em asaas_cobrancas
            if customer_id:
                logger.debug(f"Buscando cobrancas do cliente: {customer_id}")

                # s pendentes/vencidas
                result = supabase.table("asaas_cobrancas").select(
                    "id, value, due_date, status, invoice_url, bank_slip_url"
                ).eq("customer_id", customer_id).in_(
                    "status", ["PENDING", "OVERDUE"]
                ).order("due_date", desc=False).limit(10).execute()

                if result.data:
                    cobrancas = result.data
                    logger.info(f"Encontradas {len(cobrancas)} cobrancas para {customer_id}")

                    # Formatar resposta
                    lista_cobrancas = []
                    for cob in cobrancas:
                        lista_cobrancas.append({
                            "id": cob["id"],
                            "valor": f"R$ {cob['value']:.2f}" if cob.get('value') else "N/A",
                            "vencimento": cob.get("due_date", "N/A"),
                            "status": "Vencida" if cob.get("status") == "OVERDUE" else "Pendente",
                            "link_fatura": cob.get("invoice_url", ""),
                            "link_boleto": cob.get("bank_slip_url", "")
                        })

                    # Selecionar link baseado no tipo solicitado
                    primeira = cobrancas[0]
                    if tipo_link == "boleto":
                        link = primeira.get("bank_slip_url", primeira.get("invoice_url", ""))
                    else:
                        link = primeira.get("invoice_url", primeira.get("bank_slip_url", ""))

                    # Calcular total
                    total = sum(c.get("value", 0) for c in cobrancas)

                    return {
                        "sucesso": True,
                        "encontrou": True,
                        "cliente": customer_name or "Cliente",
                        "cobrancas": lista_cobrancas,
                        "quantidade": len(cobrancas),
                        "total": f"R$ {total:.2f}",
                        "link_pagamento": link,
                        "tipo_link": tipo_link,
                        "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s) totalizando R$ {total:.2f}. Segue o link para pagamento: {link}"
                    }
                else:
                    return {
                        "sucesso": True,
                        "encontrou": False,
                        "cliente": customer_name,
                        "mensagem": f"Boa noticia! Nao encontrei nenhuma fatura pendente para {customer_name}."
                    }

            # Nao encontrou cliente
            if cpf_limpo:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Nao encontrei cadastro com esse CPF. Verifique se digitou corretamente ou entre em contato com o financeiro."
                }
            else:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Para localizar suas faturas, preciso que informe seu CPF."
                }

        except Exception as e:
            logger.error(f"Erro ao buscar cobrancas: {e}")
            return {
                "sucesso": False,
                "mensagem": f"Erro ao buscar cobrancas: {str(e)}"
            }

    async def execute(
        self,
        function_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a function by name with given arguments.

        This is a dispatcher method that routes function calls
        to the appropriate handler method.

        Args:
            function_name: Name of the function to execute
            arguments: Dictionary of arguments to pass

        Returns:
            Result dictionary from the function handler
        """
        # Note: Calendar tools (consulta_agenda, agendar, cancelar_agendamento,
        # reagendar, detectar_fuso_horario) are handled per-request in whatsapp.py
        # with per-agent OAuth credentials. Only generic tools are dispatched here.
        handlers = {
            "transferir_departamento": self.transferir_departamento,
            "buscar_cobrancas": self.buscar_cobrancas,
        }

        handler = handlers.get(function_name)
        if not handler:
            logger.error(f"Funcao desconhecida: {function_name}")
            return {
                "sucesso": False,
                "mensagem": f"Funcao '{function_name}' nao encontrada. Funcoes disponiveis: {', '.join(handlers.keys())}"
            }

        try:
            return await handler(**arguments)
        except TypeError as e:
            logger.error(f"Erro de argumentos em {function_name}: {e}")
            return {
                "sucesso": False,
                "mensagem": f"Argumentos invalidos para '{function_name}': {str(e)}"
            }
