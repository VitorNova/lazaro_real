"""
Leadbox Dispatch - Roteia ticket para fila correta de forma inteligente.

Lógica híbrida:
- Se ticket JÁ EXISTE: PUT /tickets/{id} move pra fila certa (caller envia via UAZAPI)
- Se ticket NÃO EXISTE: POST PUSH com body (cria ticket + envia mensagem numa tacada só)

Isso evita mensagem vazia e mensagem duplicada nos dois cenários.
"""

import asyncio
import time
import logging
from typing import Any, Dict, Optional

import httpx

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


# IDs das filas no Leadbox (Lazaro)
QUEUE_BILLING = 544      # Fila de cobrança
QUEUE_MAINTENANCE = 545  # Fila de manutenção
QUEUE_GENERIC = 537      # Fila genérica (onde tickets caem por padrão)


async def leadbox_push_silent(
    phone: str,
    queue_id: int,
    agent_id: str,
    message: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Dispatch inteligente pro Leadbox.

    Args:
        phone: Telefone do cliente
        queue_id: ID da fila no Leadbox (544=billing, 545=manutenção)
        agent_id: ID do agente no Supabase
        message: Mensagem a enviar (usada se precisar criar ticket via PUSH)
        user_id: ID do usuário para atribuir (opcional)

    Returns:
        Dict com:
            success: bool
            ticket_existed: bool - True se ticket já existia
            ticket_id: int|None - ID do ticket
            message_sent_via_push: bool - True se PUSH já enviou a mensagem
            ticket_check_failed: bool - True se não conseguiu verificar ticket existente
                                        (caller deve usar UAZAPI direto nesse caso)
            queue_confirmation_failed: bool - True se PUT de confirmação de fila falhou
                                              (ticket pode estar na fila errada)
    """
    result = {
        "success": False,
        "ticket_existed": False,
        "ticket_id": None,
        "message_sent_via_push": False,
        "ticket_check_failed": False,  # True se não conseguiu verificar ticket existente
        "queue_confirmation_failed": False,  # True se PUT de confirmação falhou
    }

    supabase = get_supabase_service()
    clean_phone = _format_phone(phone)

    try:
        # Buscar config do Leadbox no agente
        agent_result = supabase.client.table("agents").select(
            "handoff_triggers"
        ).eq("id", agent_id).limit(1).execute()

        if not agent_result.data:
            logger.warning(f"[LEADBOX PUSH] Agente {agent_id} não encontrado")
            return result

        handoff = agent_result.data[0].get("handoff_triggers") or {}
        api_url = handoff.get("api_url")
        api_uuid = handoff.get("api_uuid")
        api_token = handoff.get("api_token")

        if not api_url or not api_uuid or not api_token:
            logger.warning("[LEADBOX PUSH] Config incompleta (api_url/api_uuid/api_token)")
            return result

        if not handoff.get("enabled"):
            logger.debug("[LEADBOX PUSH] Leadbox desabilitado no agente")
            return result

        # Buscar userId da fila nos dispatch_departments (se não informado)
        if user_id is None:
            dispatch_depts = handoff.get("dispatch_departments") or {}
            for dept_key, dept in dispatch_depts.items():
                if dept.get("queueId") == queue_id:
                    user_id = dept.get("userId")
                    break

        base_url = api_url.rstrip('/')
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # ================================================================
        # PASSO 1: Buscar ticket existente do contato
        # ================================================================
        ticket_id = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Buscar contato pelo telefone
                contact_resp = await client.get(
                    f"{base_url}/contacts",
                    params={"searchParam": clean_phone, "limit": 1},
                    headers=headers,
                )
                contact_resp.raise_for_status()
                contact_data = contact_resp.json()

                contacts = contact_data.get("contacts", contact_data if isinstance(contact_data, list) else [])
                contact = contacts[0] if contacts else None

                if contact and contact.get("id"):
                    contact_id = contact["id"]
                    # Buscar tickets abertos do contato
                    tickets_resp = await client.get(
                        f"{base_url}/tickets",
                        params={"contactId": contact_id, "status": "open,pending", "limit": 10},
                        headers=headers,
                    )
                    tickets_resp.raise_for_status()
                    tickets_data = tickets_resp.json()

                    tickets = tickets_data.get("tickets", tickets_data if isinstance(tickets_data, list) else [])
                    if isinstance(tickets, list):
                        # Procurar qualquer ticket aberto (não precisa ser da fila específica)
                        for t in tickets:
                            if t.get("status") in ("open", "pending"):
                                ticket_id = t.get("id")
                                break

                    if ticket_id:
                        logger.debug(f"[LEADBOX PUSH] Ticket existente encontrado: {ticket_id}")

        except Exception as e:
            logger.warning(f"[LEADBOX PUSH] Erro ao buscar ticket existente: {e}")
            # NÃO continua - retorna erro para evitar mensagem duplicada
            # Se não sabemos se ticket existe, PUSH pode enviar mensagem duplicada
            result["ticket_check_failed"] = True
            return result

        # ================================================================
        # PASSO 2: Decidir estratégia
        # ================================================================
        if ticket_id:
            # CENÁRIO 1: Ticket existe → PUT para mover de fila
            # Caller envia mensagem via UAZAPI (sem duplicar)
            result["ticket_existed"] = True
            result["message_sent_via_push"] = False

            put_url = f"{base_url}/tickets/{ticket_id}"
            put_payload: Dict[str, Any] = {"queueId": queue_id}
            if user_id:
                put_payload["userId"] = user_id

            async with httpx.AsyncClient(timeout=10) as client:
                put_resp = await client.put(put_url, json=put_payload, headers=headers)
                put_resp.raise_for_status()

            result["ticket_id"] = ticket_id
            result["success"] = True
            logger.info(
                f"[LEADBOX PUSH] PUT ok (ticket existia): ticketId={ticket_id} -> "
                f"queueId={queue_id}, userId={user_id}"
            )

        else:
            # CENÁRIO 2: Sem ticket → POST PUSH com body (cria + envia)
            # Caller NÃO envia via UAZAPI (PUSH já envia)
            result["ticket_existed"] = False
            result["message_sent_via_push"] = True

            external_key = f"push-{int(time.time())}"
            payload: Dict[str, Any] = {
                "number": clean_phone,
                "externalKey": external_key,
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Incluir body pra não enviar mensagem vazia
            if message:
                payload["body"] = message

            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            push_url = f"{base_url}/v1/api/external/{api_uuid}/?token={api_token}"
            logger.debug(f"[LEADBOX PUSH] POST PUSH {push_url[:60]}... payload keys={list(payload.keys())}")

            async with httpx.AsyncClient(timeout=15) as client:
                push_resp = await client.post(push_url, json=payload, headers=headers)
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
                f"[LEADBOX PUSH] PUSH ok (ticket novo): phone={clean_phone[:8]}***, "
                f"queueId={queue_id}, ticketId={ticket_id}"
            )

            # PUT pra garantir fila (PUSH pode ignorar forceTicketToDepartment)
            if ticket_id:
                await asyncio.sleep(2)
                try:
                    put_url = f"{base_url}/tickets/{ticket_id}"
                    put_payload = {"queueId": queue_id}
                    if user_id:
                        put_payload["userId"] = user_id

                    async with httpx.AsyncClient(timeout=10) as client:
                        put_resp = await client.put(put_url, json=put_payload, headers=headers)
                        put_resp.raise_for_status()

                    logger.info(f"[LEADBOX PUSH] PUT confirmação: ticketId={ticket_id} -> queueId={queue_id}")
                except Exception as e:
                    logger.warning(f"[LEADBOX PUSH] PUT confirmação falhou: {e}")
                    result["queue_confirmation_failed"] = True

        return result

    except httpx.HTTPStatusError as e:
        logger.warning(f"[LEADBOX PUSH] HTTP {e.response.status_code}: {e.response.text[:100]}")
        return result
    except Exception as e:
        logger.warning(f"[LEADBOX PUSH] Erro: {e}")
        return result


def _format_phone(phone: str) -> str:
    """Formata telefone para o padrão Leadbox (apenas dígitos, com 55)."""
    clean = phone.replace("@s.whatsapp.net", "").replace("@c.us", "").replace("@lid", "")
    clean = "".join(filter(str.isdigit, clean))
    if len(clean) == 10 or len(clean) == 11:
        clean = f"55{clean}"
    return clean
