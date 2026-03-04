"""
Diana v2 - Servico de campanhas.

Gerencia:
- Criacao de campanhas a partir de CSV
- Disparo via UAZAPI
- Processamento de respostas
- Estatisticas
"""

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from supabase import create_client, Client

from app.config import settings
from .types import (
    DianaStatus,
    DianaProspect,
    DianaCampanha,
    DianaConversationHistory,
)
from .phone_formatter import (
    format_phone,
    format_to_remotejid,
    extract_phone_from_remotejid,
)
from .message_service import DianaMessageService

logger = logging.getLogger("diana.campaign")


class DianaCampaignService:
    """
    Servico principal para gerenciar campanhas Diana.

    Funcionalidades:
    - Criar campanha a partir de CSV
    - Disparar mensagens
    - Processar respostas (webhook)
    - Estatisticas
    """

    def __init__(self, supabase_client: Optional[Client] = None):
        """
        Inicializa o servico.

        Args:
            supabase_client: Cliente Supabase (usa default se nao fornecido)
        """
        self.supabase = supabase_client or create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
        logger.info("DianaCampaignService inicializado")

    # ========================================================================
    # Criacao de Campanha
    # ========================================================================

    async def create_campaign_from_csv(
        self,
        agent_id: str,
        csv_content: str,
        campaign_name: str,
        system_prompt: str,
        mensagem_template: str,
        uazapi_base_url: str,
        uazapi_token: str,
        delay_min: int = 30,
        delay_max: int = 60,
        auto_dispatch: bool = True,
    ) -> Dict[str, Any]:
        """
        Cria campanha a partir de CSV.

        Fluxo:
        1. Parsear CSV (aceita qualquer coluna, mapeia as conhecidas)
        2. Formatar telefones
        3. Criar campanha no banco
        4. Criar prospects no banco
        5. Se auto_dispatch, dispara via UAZAPI

        Args:
            agent_id: ID do agente
            csv_content: Conteudo do CSV
            campaign_name: Nome da campanha
            system_prompt: Prompt que guia a IA
            mensagem_template: Template da mensagem inicial
            uazapi_base_url: URL da UAZAPI
            uazapi_token: Token da UAZAPI
            delay_min: Delay minimo entre mensagens (segundos)
            delay_max: Delay maximo entre mensagens (segundos)
            auto_dispatch: Se True, dispara imediatamente

        Returns:
            {
                "campaign_id": str,
                "total": int,
                "queued": int,
                "errors": int,
                "invalid_phones": [{"row": int, "phone": str, "error": str}],
                "uazapi_folder_id": str,
            }
        """
        logger.info(f"Criando campanha: {campaign_name} para agente {agent_id}")

        invalid_phones: List[Dict[str, Any]] = []
        prospects: List[DianaProspect] = []

        # 1. Parsear CSV
        try:
            prospects, invalid_phones = self._parse_csv(csv_content, agent_id)
        except Exception as e:
            logger.error(f"Erro ao parsear CSV: {e}")
            return {
                "success": False,
                "error": f"Erro ao parsear CSV: {e}",
                "campaign_id": None,
                "total": 0,
                "queued": 0,
                "errors": 0,
                "invalid_phones": [],
            }

        if not prospects:
            return {
                "success": False,
                "error": "Nenhum prospect valido encontrado no CSV",
                "campaign_id": None,
                "total": 0,
                "queued": 0,
                "errors": len(invalid_phones),
                "invalid_phones": invalid_phones,
            }

        # 2. Criar campanha no banco
        campanha = DianaCampanha(
            agent_id=agent_id,
            nome=campaign_name,
            system_prompt=system_prompt,
            mensagem_template=mensagem_template,
            status="pending",
            total_prospects=len(prospects),
            delay_min=delay_min,
            delay_max=delay_max,
        )

        try:
            result = self.supabase.table("diana_campanhas").insert(
                campanha.to_dict()
            ).execute()
            campaign_id = result.data[0]["id"]
            campanha.id = campaign_id
            logger.info(f"Campanha criada: {campaign_id}")
        except Exception as e:
            logger.error(f"Erro ao criar campanha: {e}")
            return {
                "success": False,
                "error": f"Erro ao criar campanha no banco: {e}",
                "campaign_id": None,
                "total": len(prospects),
                "queued": 0,
                "errors": len(invalid_phones),
                "invalid_phones": invalid_phones,
            }

        # 3. Criar prospects no banco
        for prospect in prospects:
            prospect.campanha_id = campaign_id

        try:
            prospects_data = [p.to_dict() for p in prospects]
            self.supabase.table("diana_prospects").insert(prospects_data).execute()
            logger.info(f"Criados {len(prospects)} prospects")
        except Exception as e:
            logger.error(f"Erro ao criar prospects: {e}")
            # Continua mesmo com erro

        # 4. Disparar via UAZAPI (se auto_dispatch)
        uazapi_folder_id = None
        queued = 0

        if auto_dispatch:
            try:
                message_service = DianaMessageService(
                    uazapi_base_url=uazapi_base_url,
                    uazapi_token=uazapi_token,
                )

                # Prepara mensagens personalizadas
                messages = []
                for prospect in prospects:
                    template_vars = prospect.get_template_vars()
                    personalized_msg = self._substitute_variables(
                        mensagem_template, template_vars
                    )
                    messages.append({
                        "phone": prospect.telefone_formatado,
                        "text": personalized_msg,
                    })

                # Envia para UAZAPI
                result = await message_service.send_bulk(
                    messages=messages,
                    campaign_name=campaign_name,
                    delay_min=delay_min,
                    delay_max=delay_max,
                )

                if result["success"]:
                    uazapi_folder_id = result["folder_id"]
                    queued = result["count"]

                    # Atualiza campanha com folder_id
                    self.supabase.table("diana_campanhas").update({
                        "uazapi_campaign_id": uazapi_folder_id,
                        "status": "active",
                        "total_enviados": queued,
                    }).eq("id", campaign_id).execute()

                    # Atualiza status dos prospects para SENT
                    now = datetime.now(timezone.utc).isoformat()
                    self.supabase.table("diana_prospects").update({
                        "status": DianaStatus.SENT,
                        "enviado_at": now,
                    }).eq("campanha_id", campaign_id).execute()

                    # Salvar mensagem enviada no historico de cada prospect
                    for prospect in prospects:
                        template_vars = prospect.get_template_vars()
                        personalized_msg = self._substitute_variables(
                            mensagem_template, template_vars
                        )

                        # Historico inicial com mensagem enviada
                        initial_history = {
                            "messages": [{
                                "role": "assistant",
                                "content": personalized_msg,
                                "timestamp": now,
                            }]
                        }

                        # Atualiza prospect com mensagem enviada e historico
                        self.supabase.table("diana_prospects").update({
                            "mensagem_enviada": personalized_msg,
                            "conversation_history": initial_history,
                        }).eq("agent_id", agent_id).eq(
                            "telefone_formatado", prospect.telefone_formatado
                        ).execute()

                    logger.info(
                        f"Historico inicial salvo para {len(prospects)} prospects"
                    )

                    logger.info(f"Campanha disparada: {queued} mensagens na fila")
                else:
                    logger.error(f"Erro ao disparar: {result['error']}")

            except Exception as e:
                logger.error(f"Erro ao disparar campanha: {e}")

        return {
            "success": True,
            "campaign_id": campaign_id,
            "total": len(prospects),
            "queued": queued,
            "errors": len(invalid_phones),
            "invalid_phones": invalid_phones,
            "uazapi_folder_id": uazapi_folder_id,
        }

    def _parse_csv(
        self,
        csv_content: str,
        agent_id: str,
    ) -> tuple[List[DianaProspect], List[Dict[str, Any]]]:
        """
        Parseia CSV e retorna lista de prospects.

        Aceita qualquer coluna. Mapeia automaticamente colunas conhecidas:
        - nome, name, Nome, NAME
        - telefone, phone, celular, whatsapp, Telefone, TELEFONE
        - empresa, company, Empresa, EMPRESA
        - email, Email, EMAIL
        - cargo, position, job, Cargo

        Colunas extras vao para dados_extras.

        Args:
            csv_content: Conteudo do CSV
            agent_id: ID do agente

        Returns:
            Tupla (prospects, invalid_phones)
        """
        prospects = []
        invalid_phones = []
        seen_phones = set()  # Para deduplicacao de telefones

        # Detect delimiter
        sample = csv_content[:1000]
        delimiter = "," if sample.count(",") > sample.count(";") else ";"

        reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)

        # Mapeamento de colunas conhecidas (lowercase)
        column_mapping = {
            # Nome
            "nome": "nome",
            "name": "nome",
            "nome completo": "nome",
            "full name": "nome",
            # Telefone
            "telefone": "telefone",
            "phone": "telefone",
            "celular": "telefone",
            "whatsapp": "telefone",
            "fone": "telefone",
            "tel": "telefone",
            "mobile": "telefone",
            # Empresa
            "empresa": "empresa",
            "company": "empresa",
            "companhia": "empresa",
            "org": "empresa",
            "organization": "empresa",
            # Email
            "email": "email",
            "e-mail": "email",
            "mail": "email",
            # Cargo
            "cargo": "cargo",
            "position": "cargo",
            "job": "cargo",
            "funcao": "cargo",
            "titulo": "cargo",
            "title": "cargo",
        }

        for row_num, row in enumerate(reader, start=2):  # Comeca em 2 (header eh 1)
            prospect_data: Dict[str, Any] = {
                "nome": None,
                "telefone": None,
                "empresa": None,
                "email": None,
                "cargo": None,
            }
            dados_extras: Dict[str, Any] = {}

            for column, value in row.items():
                if not column or not value:
                    continue

                column_lower = column.lower().strip()
                value_clean = str(value).strip()

                # Verifica se eh coluna conhecida
                if column_lower in column_mapping:
                    mapped_key = column_mapping[column_lower]
                    prospect_data[mapped_key] = value_clean
                else:
                    # Coluna extra
                    dados_extras[column] = value_clean

            # Valida telefone
            telefone_raw = prospect_data.get("telefone")
            if not telefone_raw:
                invalid_phones.append({
                    "row": row_num,
                    "phone": "",
                    "error": "Telefone nao encontrado",
                })
                continue

            telefone_formatado = format_phone(telefone_raw)
            if not telefone_formatado:
                invalid_phones.append({
                    "row": row_num,
                    "phone": telefone_raw,
                    "error": "Formato de telefone invalido",
                })
                continue

            # Dedup: verifica se telefone ja foi visto
            if telefone_formatado in seen_phones:
                invalid_phones.append({
                    "row": row_num,
                    "phone": telefone_raw,
                    "error": "Telefone duplicado no CSV",
                })
                continue
            seen_phones.add(telefone_formatado)

            remotejid = format_to_remotejid(telefone_raw)

            # Cria prospect
            prospect = DianaProspect(
                agent_id=agent_id,
                nome=prospect_data.get("nome"),
                telefone=telefone_raw,
                telefone_formatado=telefone_formatado,
                remotejid=remotejid,
                empresa=prospect_data.get("empresa"),
                email=prospect_data.get("email"),
                cargo=prospect_data.get("cargo"),
                dados_extras=dados_extras if dados_extras else None,
                status=DianaStatus.PENDING,
            )

            prospects.append(prospect)

        logger.info(
            f"CSV parseado: {len(prospects)} validos, "
            f"{len(invalid_phones)} invalidos"
        )

        return prospects, invalid_phones

    def _substitute_variables(
        self,
        template: str,
        variables: Dict[str, str],
    ) -> str:
        """Substitui variaveis no template."""
        result = template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, value or "")
        return result

    # ========================================================================
    # Processamento de Respostas (Webhook)
    # ========================================================================

    async def process_response(
        self,
        agent_id: str,
        remotejid: str,
        message_text: str,
        uazapi_base_url: str,
        uazapi_token: str,
        message_payload: Optional[Dict] = None,
    ) -> Optional[str]:
        """
        Processa resposta de um prospect.

        Chamado pelo webhook quando uma mensagem chega.

        Fluxo:
        1. Busca prospect pelo remotejid
        2. Se nao encontrar, retorna None (nao eh prospect Diana)
        3. Atualiza status para "responded"
        4. Carrega system_prompt da campanha
        5. Carrega historico de mensagens
        6. Gera resposta com Gemini
        7. Salva mensagem no historico
        8. Retorna resposta para enviar

        Args:
            agent_id: ID do agente
            remotejid: ID do remetente
            message_text: Texto da mensagem
            uazapi_base_url: URL da UAZAPI
            uazapi_token: Token da UAZAPI
            message_payload: Payload completo (opcional)

        Returns:
            Texto da resposta ou None se nao for prospect Diana
        """
        logger.info(f"Processando resposta de {remotejid[:15]}...")

        # 1. Busca prospect
        prospect = self._get_prospect_by_remotejid(agent_id, remotejid)
        if not prospect:
            # Tenta buscar pelo telefone extraido
            phone = extract_phone_from_remotejid(remotejid)
            if phone:
                prospect = self._get_prospect_by_phone(agent_id, phone)

        if not prospect:
            logger.debug(f"Nao eh prospect Diana: {remotejid[:15]}")
            return None

        logger.info(f"Prospect Diana encontrado: {prospect.get('nome')} (ID: {prospect.get('id')})")

        # 2. Busca campanha
        campanha = self._get_campaign(prospect.get("campanha_id"))
        if not campanha:
            logger.warning(f"Campanha nao encontrada para prospect {prospect.get('id')}")
            return None

        system_prompt = campanha.get("system_prompt")
        if not system_prompt:
            logger.warning(f"Campanha sem system_prompt: {campanha.get('id')}")
            return None

        # 3. Atualiza status do prospect
        now = datetime.now(timezone.utc).isoformat()
        updates: Dict[str, Any] = {"updated_at": now}

        if prospect.get("status") == DianaStatus.SENT:
            updates["status"] = DianaStatus.RESPONDED
            updates["respondido_at"] = now

            # Atualiza contador da campanha (UPDATE direto, nao usa RPC)
            try:
                camp_result = self.supabase.table("diana_campanhas").select(
                    "total_respondidos"
                ).eq("id", prospect.get("campanha_id")).limit(1).execute()

                if camp_result.data:
                    current = camp_result.data[0].get("total_respondidos", 0) or 0
                    self.supabase.table("diana_campanhas").update({
                        "total_respondidos": current + 1,
                        "updated_at": now,
                    }).eq("id", prospect.get("campanha_id")).execute()
            except Exception as e:
                logger.warning(f"Erro ao incrementar respondidos: {e}")

        self.supabase.table("diana_prospects").update(updates).eq(
            "id", prospect.get("id")
        ).execute()

        # 4. Carrega historico de conversa
        history = self._get_conversation_history(prospect.get("id"))

        # 5. Gera resposta com Gemini
        try:
            message_service = DianaMessageService(
                uazapi_base_url=uazapi_base_url,
                uazapi_token=uazapi_token,
            )

            # Dados do prospect para substituir variaveis
            prospect_data = {
                "nome": prospect.get("nome") or "",
                "empresa": prospect.get("empresa") or "",
                "email": prospect.get("email") or "",
                "cargo": prospect.get("cargo") or "",
            }
            if prospect.get("dados_extras"):
                for k, v in prospect.get("dados_extras", {}).items():
                    prospect_data[k.lower().replace(" ", "_")] = str(v) if v else ""

            response_text = await message_service.generate_ai_response(
                system_prompt=system_prompt,
                user_message=message_text,
                history=history,
                prospect_data=prospect_data,
            )

            # 6. Salva mensagens no historico
            self._save_message(prospect.get("id"), "user", message_text, now)
            self._save_message(
                prospect.get("id"),
                "assistant",
                response_text,
                datetime.now(timezone.utc).isoformat(),
            )

            logger.info(f"Resposta gerada para prospect {prospect.get('id')}")
            return response_text

        except Exception as e:
            logger.error(f"Erro ao gerar resposta: {e}")
            return None

    def _get_prospect_by_remotejid(
        self,
        agent_id: str,
        remotejid: str,
    ) -> Optional[Dict[str, Any]]:
        """Busca prospect pelo remotejid."""
        try:
            result = self.supabase.table("diana_prospects").select("*").eq(
                "agent_id", agent_id
            ).eq("remotejid", remotejid).limit(1).execute()

            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar prospect: {e}")
            return None

    def _get_prospect_by_phone(
        self,
        agent_id: str,
        phone: str,
    ) -> Optional[Dict[str, Any]]:
        """Busca prospect pelo telefone formatado."""
        try:
            result = self.supabase.table("diana_prospects").select("*").eq(
                "agent_id", agent_id
            ).eq("telefone_formatado", phone).limit(1).execute()

            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar prospect por telefone: {e}")
            return None

    def _get_campaign(self, campaign_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Busca campanha pelo ID."""
        if not campaign_id:
            return None
        try:
            result = self.supabase.table("diana_campanhas").select("*").eq(
                "id", campaign_id
            ).limit(1).execute()

            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar campanha: {e}")
            return None

    def _get_conversation_history(
        self,
        prospect_id: int,
    ) -> List[Dict[str, str]]:
        """Carrega historico de conversa do prospect."""
        try:
            result = self.supabase.table("diana_prospects").select(
                "conversation_history"
            ).eq("id", prospect_id).limit(1).execute()

            if result.data and result.data[0].get("conversation_history"):
                history_data = result.data[0]["conversation_history"]
                history = DianaConversationHistory.from_dict(history_data)
                return history.to_gemini_format()

            return []
        except Exception as e:
            logger.error(f"Erro ao carregar historico: {e}")
            return []

    def _save_message(
        self,
        prospect_id: int,
        role: str,
        content: str,
        timestamp: str,
    ) -> None:
        """Salva mensagem no historico do prospect."""
        try:
            # Carrega historico atual
            result = self.supabase.table("diana_prospects").select(
                "conversation_history"
            ).eq("id", prospect_id).limit(1).execute()

            history_data = {"messages": []}
            if result.data and result.data[0].get("conversation_history"):
                history_data = result.data[0]["conversation_history"]

            # Adiciona nova mensagem
            history_data["messages"].append({
                "role": role,
                "content": content,
                "timestamp": timestamp,
            })

            # Atualiza no banco
            self.supabase.table("diana_prospects").update({
                "conversation_history": history_data,
            }).eq("id", prospect_id).execute()

        except Exception as e:
            logger.error(f"Erro ao salvar mensagem: {e}")

    # ========================================================================
    # Estatisticas e Listagem
    # ========================================================================

    def get_campaign_stats(
        self,
        agent_id: str,
        campaign_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retorna estatisticas de campanhas.

        Args:
            agent_id: ID do agente
            campaign_id: ID da campanha (opcional, se None retorna todas)

        Returns:
            Dict com estatisticas
        """
        try:
            query = self.supabase.table("diana_campanhas").select("*").eq(
                "agent_id", agent_id
            )

            if campaign_id:
                query = query.eq("id", campaign_id)

            result = query.execute()

            if not result.data:
                return {
                    "total_campanhas": 0,
                    "total_prospects": 0,
                    "total_enviados": 0,
                    "total_respondidos": 0,
                    "total_interessados": 0,
                }

            campanhas = result.data

            return {
                "total_campanhas": len(campanhas),
                "total_prospects": sum(c.get("total_prospects", 0) for c in campanhas),
                "total_enviados": sum(c.get("total_enviados", 0) for c in campanhas),
                "total_respondidos": sum(c.get("total_respondidos", 0) for c in campanhas),
                "total_interessados": sum(c.get("total_interessados", 0) for c in campanhas),
                "campanhas": campanhas if campaign_id else None,
            }

        except Exception as e:
            logger.error(f"Erro ao obter stats: {e}")
            return {}

    def list_campaigns(self, agent_id: str) -> List[Dict[str, Any]]:
        """Lista campanhas do agente."""
        try:
            result = self.supabase.table("diana_campanhas").select("*").eq(
                "agent_id", agent_id
            ).order("created_at", desc=True).execute()

            return result.data or []
        except Exception as e:
            logger.error(f"Erro ao listar campanhas: {e}")
            return []

    def list_prospects(
        self,
        agent_id: str,
        campaign_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Lista prospects de uma campanha."""
        try:
            query = self.supabase.table("diana_prospects").select("*").eq(
                "agent_id", agent_id
            ).eq("campanha_id", campaign_id)

            if status:
                query = query.eq("status", status)

            result = query.order("created_at", desc=True).range(
                offset, offset + limit - 1
            ).execute()

            return result.data or []
        except Exception as e:
            logger.error(f"Erro ao listar prospects: {e}")
            return []

    # ========================================================================
    # Controle de Campanha
    # ========================================================================

    async def pause_campaign(
        self,
        agent_id: str,
        campaign_id: str,
        uazapi_base_url: str,
        uazapi_token: str,
    ) -> Dict[str, Any]:
        """Pausa uma campanha."""
        try:
            campanha = self._get_campaign(campaign_id)
            if not campanha or campanha.get("agent_id") != agent_id:
                return {"success": False, "error": "Campanha nao encontrada"}

            folder_id = campanha.get("uazapi_campaign_id")
            if folder_id:
                message_service = DianaMessageService(
                    uazapi_base_url=uazapi_base_url,
                    uazapi_token=uazapi_token,
                )
                await message_service.control_campaign(folder_id, "stop")

            self.supabase.table("diana_campanhas").update({
                "status": "paused",
            }).eq("id", campaign_id).execute()

            return {"success": True}

        except Exception as e:
            logger.error(f"Erro ao pausar campanha: {e}")
            return {"success": False, "error": str(e)}

    async def resume_campaign(
        self,
        agent_id: str,
        campaign_id: str,
        uazapi_base_url: str,
        uazapi_token: str,
    ) -> Dict[str, Any]:
        """Retoma uma campanha pausada."""
        try:
            campanha = self._get_campaign(campaign_id)
            if not campanha or campanha.get("agent_id") != agent_id:
                return {"success": False, "error": "Campanha nao encontrada"}

            folder_id = campanha.get("uazapi_campaign_id")
            if folder_id:
                message_service = DianaMessageService(
                    uazapi_base_url=uazapi_base_url,
                    uazapi_token=uazapi_token,
                )
                await message_service.control_campaign(folder_id, "continue")

            self.supabase.table("diana_campanhas").update({
                "status": "active",
            }).eq("id", campaign_id).execute()

            return {"success": True}

        except Exception as e:
            logger.error(f"Erro ao retomar campanha: {e}")
            return {"success": False, "error": str(e)}


# ============================================================================
# Singleton
# ============================================================================

_diana_campaign_service: Optional[DianaCampaignService] = None


def get_diana_campaign_service() -> DianaCampaignService:
    """Retorna instancia singleton do DianaCampaignService."""
    global _diana_campaign_service
    if _diana_campaign_service is None:
        _diana_campaign_service = DianaCampaignService()
    return _diana_campaign_service
