# ==============================================================================
# LEADBOX DISPATCH
# Dispatch inteligente para o Leadbox (criar/mover ticket)
# ==============================================================================

"""
Leadbox Dispatch - Roteia ticket para fila correta de forma inteligente.

Logica hibrida:
- Se ticket JA EXISTE: PUT /tickets/{id} move pra fila certa (caller envia via UAZAPI)
- Se ticket NAO EXISTE: POST PUSH com body (cria ticket + envia mensagem numa tacada so)

Isso evita mensagem vazia e mensagem duplicada nos dois cenarios.
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Any, Optional

import httpx

from .types import (
    DispatchResult,
    LeadboxCredentials,
    HandoffTriggers,
    format_phone,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# DISPATCH SERVICE
# ==============================================================================

class LeadboxDispatcher:
    """
    Dispatcher inteligente para Leadbox.

    Decide se deve criar novo ticket (PUSH) ou mover existente (PUT).
    """

    def __init__(self, credentials: LeadboxCredentials):
        """
        Inicializa dispatcher.

        Args:
            credentials: Credenciais do Leadbox
        """
        self.credentials = credentials
        self.base_url = credentials.base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {credentials.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def dispatch(
        self,
        phone: str,
        queue_id: int,
        message: str = "",
        user_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        Dispatch inteligente pro Leadbox.

        Args:
            phone: Telefone do cliente
            queue_id: ID da fila no Leadbox
            message: Mensagem a enviar (usada se precisar criar ticket via PUSH)
            user_id: ID do usuario para atribuir (opcional)

        Returns:
            DispatchResult com:
                success: bool
                ticket_existed: bool - True se ticket ja existia
                ticket_id: int|None - ID do ticket
                message_sent_via_push: bool - True se PUSH ja enviou a mensagem
                ticket_check_failed: bool - True se nao conseguiu verificar ticket existente
        """
        result: DispatchResult = {
            "success": False,
            "ticket_existed": False,
            "ticket_id": None,
            "message_sent_via_push": False,
            "ticket_check_failed": False,
        }

        clean_phone = format_phone(phone)

        try:
            # PASSO 1: Buscar ticket existente do contato
            ticket_id = await self._find_existing_ticket(clean_phone)

            if ticket_id is None and result.get("ticket_check_failed"):
                # Erro ao verificar - retorna para evitar duplicacao
                return result

            # PASSO 2: Decidir estrategia
            if ticket_id:
                # CENARIO 1: Ticket existe -> PUT para mover de fila
                return await self._move_existing_ticket(
                    ticket_id=ticket_id,
                    queue_id=queue_id,
                    user_id=user_id,
                )
            else:
                # CENARIO 2: Sem ticket -> POST PUSH com body
                return await self._create_ticket_via_push(
                    phone=clean_phone,
                    queue_id=queue_id,
                    message=message,
                    user_id=user_id,
                )

        except Exception as e:
            logger.warning(f"[LEADBOX DISPATCH] Erro: {e}")
            return result

    async def _find_existing_ticket(self, phone: str) -> Optional[int]:
        """
        Busca ticket aberto existente para o telefone.

        Args:
            phone: Telefone formatado

        Returns:
            ID do ticket ou None
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Buscar contato pelo telefone
                contact_resp = await client.get(
                    f"{self.base_url}/contacts",
                    params={"searchParam": phone, "limit": 1},
                    headers=self.headers,
                )
                contact_resp.raise_for_status()
                contact_data = contact_resp.json()

                contacts = contact_data.get("contacts", contact_data if isinstance(contact_data, list) else [])
                contact = contacts[0] if contacts else None

                if not contact or not contact.get("id"):
                    return None

                contact_id = contact["id"]

                # Buscar tickets abertos do contato
                tickets_resp = await client.get(
                    f"{self.base_url}/tickets",
                    params={"contactId": contact_id, "status": "open,pending", "limit": 10},
                    headers=self.headers,
                )
                tickets_resp.raise_for_status()
                tickets_data = tickets_resp.json()

                tickets = tickets_data.get("tickets", tickets_data if isinstance(tickets_data, list) else [])
                if isinstance(tickets, list):
                    for t in tickets:
                        if t.get("status") in ("open", "pending"):
                            ticket_id = t.get("id")
                            logger.debug(f"[LEADBOX DISPATCH] Ticket existente encontrado: {ticket_id}")
                            return ticket_id

                return None

        except Exception as e:
            logger.warning(f"[LEADBOX DISPATCH] Erro ao buscar ticket existente: {e}")
            # Sinaliza que falhou (para evitar duplicacao via PUSH)
            raise

    async def _move_existing_ticket(
        self,
        ticket_id: int,
        queue_id: int,
        user_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        Move ticket existente para nova fila.

        Caller envia mensagem via UAZAPI (sem duplicar).
        """
        result: DispatchResult = {
            "success": False,
            "ticket_existed": True,
            "ticket_id": ticket_id,
            "message_sent_via_push": False,
            "ticket_check_failed": False,
        }

        try:
            put_url = f"{self.base_url}/tickets/{ticket_id}"
            put_payload: dict[str, Any] = {"queueId": queue_id}
            if user_id:
                put_payload["userId"] = user_id

            async with httpx.AsyncClient(timeout=10) as client:
                put_resp = await client.put(put_url, json=put_payload, headers=self.headers)
                put_resp.raise_for_status()

            result["success"] = True
            logger.info(
                f"[LEADBOX DISPATCH] PUT ok (ticket existia): ticketId={ticket_id} -> "
                f"queueId={queue_id}, userId={user_id}"
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.warning(f"[LEADBOX DISPATCH] PUT HTTP {e.response.status_code}: {e.response.text[:100]}")
            return result
        except Exception as e:
            logger.warning(f"[LEADBOX DISPATCH] PUT erro: {e}")
            return result

    async def _create_ticket_via_push(
        self,
        phone: str,
        queue_id: int,
        message: str = "",
        user_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        Cria ticket novo via endpoint PUSH externo.

        PUSH ja envia a mensagem, caller NAO deve enviar via UAZAPI.
        """
        result: DispatchResult = {
            "success": False,
            "ticket_existed": False,
            "ticket_id": None,
            "message_sent_via_push": True,
            "ticket_check_failed": False,
        }

        try:
            external_key = f"push-{int(time.time())}"
            payload: dict[str, Any] = {
                "number": phone,
                "externalKey": external_key,
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Incluir body pra nao enviar mensagem vazia
            if message:
                payload["body"] = message

            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            # Endpoint PUSH externo (diferente da API interna)
            push_url = (
                f"{self.base_url}/v1/api/external/"
                f"{self.credentials.api_uuid}/?token={self.credentials.api_token}"
            )

            logger.debug(f"[LEADBOX DISPATCH] POST PUSH {push_url[:60]}...")

            async with httpx.AsyncClient(timeout=15) as client:
                push_resp = await client.post(push_url, json=payload, headers=self.headers)
                push_resp.raise_for_status()
                push_data = push_resp.json()

            ticket_id = (
                push_data.get("ticketId")
                or push_data.get("ticket", {}).get("id")
                or push_data.get("message", {}).get("ticketId")
            )

            result["ticket_id"] = ticket_id
            result["success"] = True

            logger.info(
                f"[LEADBOX DISPATCH] PUSH ok (ticket novo): phone={phone[:8]}***, "
                f"queueId={queue_id}, ticketId={ticket_id}"
            )

            # PUT pra garantir fila (PUSH pode ignorar forceTicketToDepartment)
            if ticket_id:
                await self._confirm_queue(ticket_id, queue_id, user_id)

            return result

        except httpx.HTTPStatusError as e:
            logger.warning(f"[LEADBOX DISPATCH] PUSH HTTP {e.response.status_code}: {e.response.text[:100]}")
            return result
        except Exception as e:
            logger.warning(f"[LEADBOX DISPATCH] PUSH erro: {e}")
            return result

    async def _confirm_queue(
        self,
        ticket_id: int,
        queue_id: int,
        user_id: Optional[int] = None,
    ) -> None:
        """
        PUT de confirmacao para garantir que ticket esta na fila certa.

        PUSH pode ignorar forceTicketToDepartment em alguns casos.
        """
        await asyncio.sleep(2)  # Aguarda PUSH processar

        try:
            put_url = f"{self.base_url}/tickets/{ticket_id}"
            put_payload: dict[str, Any] = {"queueId": queue_id}
            if user_id:
                put_payload["userId"] = user_id

            async with httpx.AsyncClient(timeout=10) as client:
                await client.put(put_url, json=put_payload, headers=self.headers)

            logger.info(f"[LEADBOX DISPATCH] PUT confirmacao: ticketId={ticket_id} -> queueId={queue_id}")

        except Exception as e:
            logger.warning(f"[LEADBOX DISPATCH] PUT confirmacao falhou (nao-critico): {e}")


# ==============================================================================
# FACTORY FUNCTIONS
# ==============================================================================

def create_dispatcher(credentials: LeadboxCredentials) -> LeadboxDispatcher:
    """
    Cria dispatcher a partir de credenciais.

    Args:
        credentials: Credenciais do Leadbox

    Returns:
        LeadboxDispatcher configurado
    """
    return LeadboxDispatcher(credentials)


def create_dispatcher_from_config(config: HandoffTriggers) -> Optional[LeadboxDispatcher]:
    """
    Cria dispatcher a partir de config de handoff.

    Args:
        config: Configuracao de handoff triggers

    Returns:
        LeadboxDispatcher ou None se config invalida
    """
    credentials = LeadboxCredentials.from_config(config)
    if not credentials:
        return None
    return LeadboxDispatcher(credentials)


# ==============================================================================
# CONVENIENCE FUNCTION
# ==============================================================================

async def leadbox_push_silent(
    phone: str,
    queue_id: int,
    agent_id: str,
    message: str = "",
    user_id: Optional[int] = None,
    supabase_client: Optional[Any] = None,
) -> DispatchResult:
    """
    Dispatch inteligente pro Leadbox (funcao de conveniencia).

    Busca config do agente no Supabase e executa dispatch.

    Args:
        phone: Telefone do cliente
        queue_id: ID da fila no Leadbox (544=billing, 545=manutencao)
        agent_id: ID do agente no Supabase
        message: Mensagem a enviar (usada se precisar criar ticket via PUSH)
        user_id: ID do usuario para atribuir (opcional)
        supabase_client: Cliente Supabase (opcional, usa default se nao informado)

    Returns:
        DispatchResult
    """
    result: DispatchResult = {
        "success": False,
        "ticket_existed": False,
        "ticket_id": None,
        "message_sent_via_push": False,
        "ticket_check_failed": False,
    }

    try:
        # Importar Supabase aqui para evitar import circular
        if supabase_client is None:
            from ..supabase import table
            agent_table = table("agents")
        else:
            agent_table = supabase_client.table("agents")

        # Buscar config do Leadbox no agente
        agent_result = agent_table.select(
            "handoff_triggers"
        ).eq("id", agent_id).limit(1).execute()

        if not agent_result.data:
            logger.warning(f"[LEADBOX DISPATCH] Agente {agent_id} nao encontrado")
            return result

        handoff: HandoffTriggers = agent_result.data[0].get("handoff_triggers") or {}

        if not handoff.get("enabled"):
            logger.debug("[LEADBOX DISPATCH] Leadbox desabilitado no agente")
            return result

        # Buscar userId da fila nos dispatch_departments (se nao informado)
        if user_id is None:
            dispatch_depts = handoff.get("dispatch_departments") or {}
            for dept_key, dept in dispatch_depts.items():
                if dept.get("queueId") == queue_id:
                    user_id = dept.get("userId")
                    break

        # Criar dispatcher e executar
        dispatcher = create_dispatcher_from_config(handoff)
        if not dispatcher:
            logger.warning("[LEADBOX DISPATCH] Config incompleta (api_url/api_uuid/api_token)")
            return result

        return await dispatcher.dispatch(
            phone=phone,
            queue_id=queue_id,
            message=message,
            user_id=user_id,
        )

    except Exception as e:
        logger.warning(f"[LEADBOX DISPATCH] Erro: {e}")
        return result
