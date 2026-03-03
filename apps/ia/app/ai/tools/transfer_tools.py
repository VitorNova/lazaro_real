"""
Tools de transferencia e deteccao de fuso horario.

Handlers para function calling do Gemini relacionados a:
- Transferir atendimento para departamento (Leadbox)
- Detectar fuso horario do lead

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.10)
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import structlog

from app.services.leadbox import LeadboxService, resolve_department
from app.services.supabase import SupabaseService

logger = structlog.get_logger(__name__)

# Timezone padrao do sistema
DEFAULT_TIMEZONE = "America/Sao_Paulo"

# Mapeamento de estados brasileiros para timezones
TIMEZONE_MAP = {
    # GMT-3 (Brasilia) - Maioria dos estados
    "SP": "America/Sao_Paulo",
    "RJ": "America/Sao_Paulo",
    "MG": "America/Sao_Paulo",
    "PR": "America/Sao_Paulo",
    "SC": "America/Sao_Paulo",
    "RS": "America/Sao_Paulo",
    "ES": "America/Sao_Paulo",
    "BA": "America/Sao_Paulo",
    "SE": "America/Sao_Paulo",
    "AL": "America/Sao_Paulo",
    "PE": "America/Sao_Paulo",
    "PB": "America/Sao_Paulo",
    "RN": "America/Sao_Paulo",
    "CE": "America/Sao_Paulo",
    "PI": "America/Sao_Paulo",
    "MA": "America/Sao_Paulo",
    "PA": "America/Sao_Paulo",
    "AP": "America/Sao_Paulo",
    "TO": "America/Sao_Paulo",
    "GO": "America/Sao_Paulo",
    "DF": "America/Sao_Paulo",
    # GMT-4 (Manaus/Cuiaba)
    "MT": "America/Cuiaba",
    "MS": "America/Campo_Grande",
    "RO": "America/Porto_Velho",
    "AM": "America/Manaus",
    "RR": "America/Boa_Vista",
    # GMT-5 (Acre)
    "AC": "America/Rio_Branco",
}

# Descricoes amigaveis dos timezones
TIMEZONE_DESCRIPTIONS = {
    "America/Sao_Paulo": "GMT-3 (horario de Brasilia)",
    "America/Cuiaba": "GMT-4 (horario de Cuiaba)",
    "America/Campo_Grande": "GMT-4 (horario de Campo Grande)",
    "America/Manaus": "GMT-4 (horario de Manaus)",
    "America/Porto_Velho": "GMT-4 (horario de Porto Velho)",
    "America/Boa_Vista": "GMT-4 (horario de Boa Vista)",
    "America/Rio_Branco": "GMT-5 (horario do Acre)",
}

# Palavras que indicam defeito/manutencao corretiva
PALAVRAS_DEFEITO = [
    "defeito", "quebrado", "quebrou", "nao gela", "não gela",
    "pingando", "vazando", "barulho", "nao liga", "não liga",
    "nao funciona", "não funciona", "problema", "estragou",
    "parou", "queimou", "cheiro", "goteira", "gelo", "congelando",
    "manutencao", "manutenção", "reparo", "conserto", "tecnico", "técnico",
]

# Palavras bloqueadas para transferencia em contexto de cobranca
PALAVRAS_BLOQUEADAS_BILLING = [
    "pix", "link", "boleto", "codigo", "código", "qr",
    "pagamento", "fatura", "pagar",
]


class TransferTools:
    """
    Colecao de tools de transferencia para function calling.

    Usa Leadbox API para transferir atendimentos.
    """

    def __init__(
        self,
        supabase: SupabaseService,
        context: Dict[str, Any],
    ):
        """
        Inicializa as tools de transferencia.

        Args:
            supabase: Servico Supabase para persistencia
            context: Contexto de processamento (agent_id, remotejid, etc)
        """
        self.supabase = supabase
        self.context = context
        self.logger = logger.bind(component="TransferTools")

    def _extract_cpf_from_history(self, table_messages: str, remotejid: str) -> Optional[str]:
        """
        Extrai CPF/CNPJ do historico de conversa.

        Args:
            table_messages: Nome da tabela de mensagens
            remotejid: RemoteJid do lead

        Returns:
            CPF/CNPJ extraido ou None
        """
        try:
            history_record = self.supabase.get_conversation_history(table_messages, remotejid)
            if not history_record or not history_record.get("messages"):
                return None

            messages = history_record.get("messages", [])

            # Regex para CPF e CNPJ
            cpf_pattern = r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b'
            cnpj_pattern = r'\b\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2}\b'
            digits_11_pattern = r'\b\d{11}\b'
            digits_14_pattern = r'\b\d{14}\b'

            for msg in reversed(messages):  # Mais recente primeiro
                role = msg.get("role", "")
                if role != "user":
                    continue  # So mensagens do lead

                text = ""
                parts = msg.get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        text += part["text"] + " "
                    elif isinstance(part, str):
                        text += part + " "

                # Tentar CNPJ primeiro (mais longo)
                match = re.search(cnpj_pattern, text)
                if not match:
                    match = re.search(digits_14_pattern, text)
                if not match:
                    match = re.search(cpf_pattern, text)
                if not match:
                    match = re.search(digits_11_pattern, text)

                if match:
                    cpf_extraido = re.sub(r'\D', '', match.group())
                    if len(cpf_extraido) in [11, 14]:
                        self.logger.info(
                            "cpf_extracted_from_history",
                            cpf=cpf_extraido,
                        )
                        return cpf_extraido

            return None
        except Exception as e:
            self.logger.warning("cpf_extraction_error", error=str(e))
            return None

    def _determine_interest_type(self, motivo: str) -> str:
        """
        Determina tipo de interesse baseado no motivo.

        Args:
            motivo: Motivo da transferencia

        Returns:
            Tipo de interesse (ALUGUEL, MANUTENCAO, OUTRO)
        """
        motivo_lower = (motivo or "").lower()

        if any(p in motivo_lower for p in ["alugar", "aluguel", "locacao", "locação", "locar", "alugo"]):
            return "ALUGUEL"
        elif any(p in motivo_lower for p in ["manutencao", "manutenção", "defeito", "conserto", "reparo"]):
            return "MANUTENCAO"
        else:
            return "OUTRO"

    def _is_defeito(self, motivo: str) -> bool:
        """Verifica se motivo indica defeito/manutencao corretiva."""
        motivo_lower = (motivo or "").lower()
        return any(palavra in motivo_lower for palavra in PALAVRAS_DEFEITO)

    def _handle_manutencao_corretiva(
        self,
        phone: str,
        agent_id: str,
        motivo: str,
        dept_name: str,
    ) -> None:
        """
        Registra manutencao corretiva quando cliente relata defeito.
        Best-effort: nao impede transferencia se falhar.
        """
        try:
            # Normalizar telefone
            phone_sem_55 = phone[2:] if phone.startswith("55") else phone
            phone_com_55 = phone if phone.startswith("55") else f"55{phone}"

            cliente_result = self.supabase.client.table("asaas_clientes").select(
                "id"
            ).or_(f"mobile_phone.eq.{phone_com_55},mobile_phone.eq.{phone_sem_55}").limit(1).execute()

            if not cliente_result.data:
                self.logger.info("manut_corretiva_cliente_not_found", phone=phone)
                return

            customer_id = cliente_result.data[0]["id"]

            contrato_result = self.supabase.client.table("contract_details").select(
                "id, maintenance_status"
            ).eq("agent_id", agent_id).eq(
                "customer_id", customer_id
            ).order("created_at", desc=True).limit(1).execute()

            if not contrato_result.data:
                self.logger.info("manut_corretiva_no_contract", phone=phone)
                return

            contrato = contrato_result.data[0]
            self.supabase.client.table("contract_details").update({
                "maintenance_type": "corretiva",
                "maintenance_status": "scheduled",
                "problema_relatado": (motivo or "Problema relatado pelo cliente")[:500],
                "observacoes": f"Transferido pela IA. Departamento: {dept_name}",
                "created_by": "ia_transfer",
            }).eq("id", contrato["id"]).execute()

            self.logger.info(
                "manut_corretiva_registered",
                contrato_id=contrato["id"],
                motivo=motivo[:100] if motivo else None,
            )

        except Exception as e:
            self.logger.warning("manut_corretiva_error", error=str(e))

    def _handle_manutencao_preventiva_transfer(
        self,
        phone: str,
        agent_id: str,
        motivo: str,
        dept_name: str,
    ) -> None:
        """
        Marca manutencao preventiva como transferida.
        Best-effort: nao impede transferencia se falhar.
        """
        try:
            phone_sem_55 = phone[2:] if phone.startswith("55") else phone
            phone_com_55 = phone if phone.startswith("55") else f"55{phone}"

            cliente_result = self.supabase.client.table("asaas_clientes").select(
                "id"
            ).or_(f"mobile_phone.eq.{phone_com_55},mobile_phone.eq.{phone_sem_55}").limit(1).execute()

            if not cliente_result.data:
                return

            customer_id = cliente_result.data[0]["id"]

            contrato_result = self.supabase.client.table("contract_details").select(
                "id, maintenance_status"
            ).eq("agent_id", agent_id).eq(
                "customer_id", customer_id
            ).eq("maintenance_status", "notified").order("created_at", desc=True).limit(1).execute()

            if not contrato_result.data:
                return

            contrato = contrato_result.data[0]
            now = datetime.utcnow().isoformat()

            self.supabase.client.table("contract_details").update({
                "maintenance_status": "transferred",
                "transferido_at": now,
                "observacoes": f"Transferido pela IA. Departamento: {dept_name}. Motivo: {motivo or 'N/A'}",
            }).eq("id", contrato["id"]).execute()

            self.logger.info(
                "manut_preventiva_transferred",
                contrato_id=contrato["id"],
            )

        except Exception as e:
            self.logger.warning("manut_preventiva_transfer_error", error=str(e))

    async def transferir_departamento(
        self,
        departamento: str = None,
        motivo: str = None,
        observacoes: str = None,
        queue_id: int = None,
        user_id: int = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Transfere atendimento para departamento via Leadbox.

        Args:
            departamento: Nome do departamento (ex: "comercial", "suporte")
            motivo: Motivo da transferencia
            observacoes: Observacoes adicionais
            queue_id: ID da fila (alternativa ao departamento)
            user_id: ID do usuario especifico (opcional)

        Returns:
            Dict com sucesso e mensagem
        """
        self.logger.info(
            "transfer_start",
            departamento=departamento,
            queue_id=queue_id,
            user_id=user_id,
            motivo=motivo,
        )

        try:
            # Protecao: Nao transferir em contexto de cobranca para pedir pix/link
            conversation_context = self.context.get("conversation_context", "")
            if conversation_context in ["disparo_billing", "billing"]:
                motivo_lower = (motivo or "").lower()
                if any(palavra in motivo_lower for palavra in PALAVRAS_BLOQUEADAS_BILLING):
                    self.logger.warning(
                        "transfer_blocked_billing_context",
                        context=conversation_context,
                        motivo=motivo,
                    )
                    return {
                        "sucesso": False,
                        "mensagem": "Para enviar o link de pagamento, use a tool consultar_cliente. Nao e necessario transferir.",
                        "instrucao": "USE a tool consultar_cliente para buscar o link de pagamento do cliente. NAO transfira.",
                    }

            # Converter para int (Gemini pode enviar float como 454.0)
            if queue_id is not None:
                queue_id = int(queue_id)
            if user_id is not None:
                user_id = int(user_id)

            handoff_config = self.context.get("handoff_triggers")

            if not handoff_config:
                self.logger.warning("handoff_not_configured")
                return {
                    "sucesso": False,
                    "mensagem": "Transferencia nao configurada para este agente",
                }

            if not handoff_config.get("enabled", True):
                return {
                    "sucesso": False,
                    "mensagem": "Transferencia desabilitada para este agente",
                }

            api_url = handoff_config.get("api_url")
            api_uuid = handoff_config.get("api_uuid")
            api_token = handoff_config.get("api_token")
            departments = handoff_config.get("departments", {})

            if not api_url or not api_uuid or not api_token:
                self.logger.error("leadbox_incomplete_config")
                return {
                    "sucesso": False,
                    "mensagem": "Configuracao Leadbox incompleta",
                }

            # Resolver queue_id se passou departamento por nome
            resolved_queue = queue_id
            if departamento and not queue_id:
                dept_config = departments.get(departamento.lower())
                if dept_config:
                    resolved_queue = int(dept_config.get("id") or dept_config.get("queue_id") or 0) or None

            # Resolver departamento dinamicamente
            final_queue_id, final_user_id, dept_name = resolve_department(
                handoff_triggers=handoff_config,
                queue_id=resolved_queue,
                motivo=motivo,
            )

            self.logger.info(
                "transfer_resolved",
                final_queue_id=final_queue_id,
                final_user_id=final_user_id,
                dept_name=dept_name,
            )

            if not final_queue_id:
                return {
                    "sucesso": False,
                    "mensagem": "Departamento nao configurado",
                }

            # Criar LeadboxService
            leadbox = LeadboxService(
                base_url=api_url,
                api_uuid=api_uuid,
                api_key=api_token,
            )

            # Preparar motivo interno
            transfer_reason = motivo or "Transferindo atendimento"
            if observacoes:
                transfer_reason += f" | {observacoes}"

            # Executar transferencia
            phone = self.context.get("phone")
            result = await leadbox.transfer_to_department(
                phone=phone,
                queue_id=final_queue_id,
                user_id=final_user_id,
            )

            self.logger.info("transfer_api_result", result=result)

            if result["sucesso"]:
                # Marcar lead como pausado (atendimento humano)
                table_leads = self.context.get("table_leads")
                table_messages = self.context.get("table_messages")
                remotejid = self.context.get("remotejid")
                agent_id = self.context.get("agent_id")
                now = datetime.utcnow().isoformat()

                # Dados extras do lead
                extra_lead_data = {}
                extra_lead_data["interest_type"] = self._determine_interest_type(motivo)

                # Verificar se lead ja tem CPF salvo
                lead_atual = self.supabase.get_lead_by_remotejid(table_leads, remotejid)
                cpf_existente = lead_atual.get("cpf_cnpj") if lead_atual else None

                if not cpf_existente and table_messages:
                    cpf_extraido = self._extract_cpf_from_history(table_messages, remotejid)
                    if cpf_extraido:
                        extra_lead_data["cpf_cnpj"] = cpf_extraido

                # Update principal do lead
                update_data = {
                    "Atendimento_Finalizado": "true",
                    "current_state": "human",
                    "paused_at": now,
                    "handoff_at": now,
                    "transfer_reason": transfer_reason,
                    "ticket_id": result.get("ticket_id"),
                    "current_queue_id": result.get("queue_id"),
                    "current_user_id": result.get("user_id"),
                }
                update_data.update(extra_lead_data)

                self.supabase.update_lead_by_remotejid(
                    table_leads,
                    remotejid,
                    update_data,
                )

                # Detectar e registrar manutencao corretiva
                if self._is_defeito(motivo):
                    self._handle_manutencao_corretiva(phone, agent_id, motivo, dept_name)
                elif conversation_context == "manutencao_preventiva":
                    self._handle_manutencao_preventiva_transfer(phone, agent_id, motivo, dept_name)

                self.logger.info(
                    "transfer_success",
                    dept=dept_name,
                    ticket_id=result.get("ticket_id"),
                )

                return {
                    "sucesso": True,
                    "mensagem": "O departamento ideal vai falar com voce.",
                    "instrucao": "IMPORTANTE: Use EXATAMENTE a mensagem acima para o usuario. NAO mencione filas, IDs ou detalhes tecnicos.",
                }
            else:
                self.logger.info("transfer_api_error", error=result.get("mensagem"))
                return {
                    "sucesso": False,
                    "mensagem": "Desculpe, tive um problema ao tentar te transferir. Pode tentar novamente em alguns instantes?",
                    "erro_interno": result.get("mensagem"),
                }

        except Exception as e:
            self.logger.error("transfer_exception", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao transferir: {str(e)}",
            }

    async def detectar_fuso_horario(
        self,
        cidade: str = None,
        estado: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Detecta o fuso horario do lead baseado na localizacao.
        Salva no lead para uso futuro em agendamentos.

        Args:
            cidade: Nome da cidade (opcional)
            estado: Sigla do estado (ex: SP, MT, RJ)

        Returns:
            Dict com sucesso, timezone, offset e mensagem
        """
        self.logger.debug(
            "detectar_fuso_start",
            cidade=cidade,
            estado=estado,
        )

        try:
            if not estado:
                return {
                    "sucesso": False,
                    "mensagem": "Estado nao informado. Preciso saber o estado (ex: SP, MT, RJ) para detectar o fuso horario.",
                }

            estado_upper = estado.upper().strip()

            # Buscar timezone no mapeamento
            timezone = TIMEZONE_MAP.get(estado_upper, DEFAULT_TIMEZONE)

            # Determinar descricao amigavel
            offset_desc = TIMEZONE_DESCRIPTIONS.get(timezone, timezone)

            # Salvar no lead
            remotejid = self.context.get("remotejid")
            table_leads = self.context.get("table_leads")

            update_data = {
                "timezone": timezone,
                "estado": estado_upper,
            }
            if cidade:
                update_data["cidade"] = cidade.strip()

            self.supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                update_data,
            )

            self.logger.debug(
                "fuso_detected",
                timezone=timezone,
                offset=offset_desc,
            )

            return {
                "sucesso": True,
                "timezone": timezone,
                "offset": offset_desc,
                "cidade": cidade,
                "estado": estado_upper,
                "mensagem": f"Fuso horario detectado: {offset_desc}. Todos os horarios de agendamento serao no seu horario local.",
            }

        except Exception as e:
            self.logger.error("detectar_fuso_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao detectar fuso horario: {str(e)}",
            }

    def get_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario de handlers para registro no tool registry.

        Returns:
            Dict com nome_tool -> handler
        """
        return {
            "transferir_departamento": self.transferir_departamento,
            "detectar_fuso_horario": self.detectar_fuso_horario,
        }


# Factory function para criar tools de transferencia
def create_transfer_tools(
    supabase: SupabaseService,
    context: Dict[str, Any],
) -> TransferTools:
    """
    Cria instancia de TransferTools.

    Args:
        supabase: Servico Supabase
        context: Contexto de processamento

    Returns:
        Instancia configurada de TransferTools
    """
    return TransferTools(supabase, context)
