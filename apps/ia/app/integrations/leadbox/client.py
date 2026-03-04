# ==============================================================================
# LEADBOX CLIENT
# Cliente HTTP para API Leadbox
# Baseado em apps/ia/app/services/leadbox.py
# ==============================================================================

from __future__ import annotations

import asyncio
import structlog
from typing import Optional, Any

import httpx

from .types import (
    LeadboxConfig,
    LeadboxCredentials,
    TransferResult,
    QueueInfo,
    SendMessageResult,
    format_phone,
)

logger = structlog.get_logger(__name__)


class LeadboxClient:
    """
    Cliente para integracao com Leadbox (sistema de atendimento).

    Gerencia:
    - Transferencia de atendimentos para departamentos
    - Atribuicao de tickets para atendentes
    - Envio de mensagens via API PUSH
    - Consulta de filas

    Exemplo de uso:
        client = LeadboxClient(
            base_url="https://api.leadbox.com",
            api_uuid="abc-123",
            api_token="token-xyz"
        )
        result = await client.transfer_to_department(
            phone="5511999999999",
            queue_id=1,
            user_id=10
        )
    """

    def __init__(
        self,
        base_url: str,
        api_uuid: str,
        api_token: str,
        timeout: float = 30.0,
    ):
        """
        Inicializa o LeadboxClient.

        Args:
            base_url: URL base da API Leadbox
            api_uuid: UUID da API externa do Leadbox
            api_token: Token Bearer para autenticacao
            timeout: Timeout para requisicoes em segundos (default: 30)
        """
        self.base_url = base_url.rstrip("/")
        self.api_uuid = api_uuid
        self.api_token = api_token
        self.timeout = timeout

        if not self.base_url:
            raise ValueError("base_url e obrigatorio")
        if not self.api_uuid:
            raise ValueError("api_uuid e obrigatorio")
        if not self.api_token:
            raise ValueError("api_token e obrigatorio")

        self._headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.info(
            "leadbox_client_initialized",
            base_url=self.base_url,
            api_uuid=self.api_uuid[:8] + "...",
        )

    # ==========================================================================
    # HTTP METHODS
    # ==========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Executa uma requisicao HTTP para a API Leadbox."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        logger.debug(
            "leadbox_request",
            method=method,
            url=url,
            has_data=data is not None,
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    params=params,
                )

                logger.debug(
                    "leadbox_response",
                    status=response.status_code,
                )

                response.raise_for_status()

                try:
                    return response.json()
                except Exception:
                    return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                logger.error(
                    "leadbox_http_error",
                    status=e.response.status_code,
                    body=e.response.text[:200],
                )
                raise

            except httpx.RequestError as e:
                logger.error("leadbox_request_error", error=str(e))
                raise

    async def _post(
        self, endpoint: str, data: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Executa requisicao POST."""
        return await self._request("POST", endpoint, data=data)

    async def _put(
        self, endpoint: str, data: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Executa requisicao PUT."""
        return await self._request("PUT", endpoint, data=data)

    async def _get(
        self, endpoint: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Executa requisicao GET."""
        return await self._request("GET", endpoint, params=params)

    # ==========================================================================
    # TRANSFER METHODS
    # ==========================================================================

    async def transfer_to_department(
        self,
        phone: str,
        queue_id: int,
        user_id: Optional[int] = None,
        mensagem: Optional[str] = None,
        external_key: Optional[str] = None,
    ) -> TransferResult:
        """
        Transfere um atendimento para um departamento/fila.

        Usa a API PUSH do Leadbox que cria ou encontra o ticket pelo numero
        e transfere automaticamente para a fila/usuario especificado.

        Args:
            phone: Numero de telefone do cliente
            queue_id: ID da fila/departamento no Leadbox
            user_id: ID do usuario/atendente (opcional)
            mensagem: Mensagem para o cliente (None=default, ""=silencioso)
            external_key: Chave externa para rastreamento (opcional)

        Returns:
            TransferResult com status da operacao
        """
        try:
            formatted_phone = format_phone(phone)

            logger.info(
                "leadbox_transfer_start",
                phone=formatted_phone[:8] + "***",
                queue_id=queue_id,
                user_id=user_id,
            )

            endpoint = f"/v1/api/external/{self.api_uuid}"

            payload: dict[str, Any] = {
                "number": formatted_phone,
                "externalKey": external_key or f"transfer-{formatted_phone}-{queue_id}",
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Mensagem: None=default, ""=silencioso, string=customizada
            if mensagem is None:
                payload["body"] = "O departamento ideal vai falar com você."
            elif mensagem:
                payload["body"] = mensagem

            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            response = await self._post(endpoint, payload)

            # Extrair ticket_id da resposta
            ticket_id = None
            ticket_queue_id = queue_id
            ticket_user_id = user_id

            if isinstance(response, dict):
                ticket_id = (
                    response.get("message", {}).get("ticketId")
                    or response.get("ticket", {}).get("id")
                    or response.get("ticketId")
                    or response.get("id")
                )
                ticket_obj = response.get("ticket", {})
                if ticket_obj:
                    ticket_queue_id = ticket_obj.get("queueId") or queue_id
                    ticket_user_id = ticket_obj.get("userId") or user_id

            logger.info(
                "leadbox_transfer_success",
                ticket_id=ticket_id,
                queue_id=ticket_queue_id,
                user_id=ticket_user_id,
            )

            return TransferResult(
                sucesso=True,
                mensagem=f"Atendimento transferido para a fila {queue_id}"
                + (f" e atribuido ao usuario {user_id}" if user_id else ""),
                ticket_id=str(ticket_id) if ticket_id else None,
                queue_id=ticket_queue_id,
                user_id=ticket_user_id,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error("leadbox_transfer_http_error", error=error_msg)
            return TransferResult(
                sucesso=False,
                mensagem=f"Erro ao transferir: {error_msg}",
                ticket_id=None,
                queue_id=queue_id,
                user_id=user_id,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error("leadbox_transfer_error", error=error_msg)
            return TransferResult(
                sucesso=False,
                mensagem=f"Erro inesperado: {error_msg}",
                ticket_id=None,
                queue_id=queue_id,
                user_id=user_id,
            )

    async def assign_user_silent(
        self,
        phone: str,
        queue_id: int,
        user_id: int,
        ticket_id: Optional[int] = None,
    ) -> TransferResult:
        """
        Atribui userId a um ticket SEM enviar mensagem para o cliente.

        Usa PUT /tickets/{id} que apenas atualiza o ticket sem criar mensagem.

        Args:
            phone: Numero de telefone (usado se ticket_id nao informado)
            queue_id: ID da fila
            user_id: ID do usuario a atribuir
            ticket_id: ID do ticket (opcional)

        Returns:
            TransferResult com status da operacao
        """
        try:
            # Se nao tem ticket_id, buscar pelo telefone
            if not ticket_id:
                queue_info = await self.get_current_queue(phone)
                if queue_info and queue_info.get("ticket_id"):
                    ticket_id = queue_info["ticket_id"]
                else:
                    logger.warning(
                        "leadbox_assign_ticket_not_found",
                        phone=phone[:8] + "***",
                    )
                    return TransferResult(
                        sucesso=False,
                        mensagem="Ticket nao encontrado para este telefone",
                        ticket_id=None,
                        queue_id=queue_id,
                        user_id=user_id,
                    )

            logger.info(
                "leadbox_assign_silent_start",
                ticket_id=ticket_id,
                user_id=user_id,
            )

            # PUT com retry
            response = None
            last_error = None

            for retry in range(3):
                try:
                    response = await self._put(
                        f"/tickets/{ticket_id}",
                        {"queueId": queue_id, "userId": user_id},
                    )
                    last_error = None
                    break
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if retry < 2 and e.response.status_code >= 500:
                        logger.warning(
                            "leadbox_assign_retry",
                            retry=retry + 1,
                            status=e.response.status_code,
                        )
                        await asyncio.sleep(1.5 * (retry + 1))
                        continue
                    raise
                except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                    last_error = e
                    if retry < 2:
                        await asyncio.sleep(1.5 * (retry + 1))
                        continue
                    raise

            if last_error:
                raise last_error

            logger.info(
                "leadbox_assign_silent_success",
                ticket_id=ticket_id,
                user_id=user_id,
            )

            return TransferResult(
                sucesso=True,
                mensagem=f"Usuario {user_id} atribuido ao ticket {ticket_id} (silencioso)",
                ticket_id=str(ticket_id),
                queue_id=response.get("queueId") or queue_id if response else queue_id,
                user_id=response.get("userId") or user_id if response else user_id,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error("leadbox_assign_http_error", error=error_msg)
            return TransferResult(
                sucesso=False,
                mensagem=f"Erro ao atribuir usuario: {error_msg}",
                ticket_id=str(ticket_id) if ticket_id else None,
                queue_id=queue_id,
                user_id=user_id,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error("leadbox_assign_error", error=error_msg)
            return TransferResult(
                sucesso=False,
                mensagem=f"Erro inesperado: {error_msg}",
                ticket_id=str(ticket_id) if ticket_id else None,
                queue_id=queue_id,
                user_id=user_id,
            )

    # ==========================================================================
    # MESSAGE METHODS
    # ==========================================================================

    async def send_message(
        self,
        phone: str,
        message: str,
        queue_id: Optional[int] = None,
        external_key: Optional[str] = None,
    ) -> SendMessageResult:
        """
        Envia uma mensagem para um numero via API PUSH do Leadbox.

        Args:
            phone: Numero de telefone do destinatario
            message: Texto da mensagem
            queue_id: ID da fila (opcional)
            external_key: Chave externa (opcional)

        Returns:
            SendMessageResult com status
        """
        try:
            formatted_phone = format_phone(phone)

            logger.info(
                "leadbox_send_message",
                phone=formatted_phone[:8] + "***",
            )

            endpoint = f"/v1/api/external/{self.api_uuid}"

            payload: dict[str, Any] = {
                "number": formatted_phone,
                "body": message,
                "externalKey": external_key or f"msg-{formatted_phone}",
            }

            if queue_id:
                payload["queueId"] = queue_id

            response = await self._post(endpoint, payload)

            logger.info("leadbox_send_message_success")

            return SendMessageResult(
                success=True,
                response=response,
                error=None,
            )

        except Exception as e:
            logger.error("leadbox_send_message_error", error=str(e))
            return SendMessageResult(
                success=False,
                response=None,
                error=str(e),
            )

    # ==========================================================================
    # QUERY METHODS
    # ==========================================================================

    async def get_current_queue(
        self,
        phone: str,
        ticket_id: Optional[int] = None,
    ) -> Optional[QueueInfo]:
        """
        Consulta a fila atual de um lead no Leadbox.

        Args:
            phone: Numero de telefone
            ticket_id: ID do ticket (opcional)

        Returns:
            QueueInfo ou None
        """
        formatted_phone = format_phone(phone)

        try:
            # Se tem ticket_id, consulta direto
            if ticket_id:
                try:
                    response = await self._put(f"/tickets/{ticket_id}", {})
                    return QueueInfo(
                        queue_id=response.get("queueId"),
                        user_id=response.get("userId"),
                        ticket_id=ticket_id,
                        status=response.get("status"),
                        contact_found=True,
                    )
                except Exception:
                    pass

            # Buscar contato pelo telefone
            contact_resp = await self._get(
                "/contacts",
                {"searchParam": formatted_phone, "limit": 1},
            )

            contacts = contact_resp.get(
                "contacts", contact_resp if isinstance(contact_resp, list) else []
            )
            contact = contacts[0] if contacts else None

            if not contact or not contact.get("id"):
                return None

            contact_id = contact["id"]

            # Buscar tickets abertos do contato
            try:
                tickets_resp = await self._get(
                    "/tickets",
                    {"contactId": contact_id, "status": "open,pending", "limit": 10},
                )

                tickets = tickets_resp.get(
                    "tickets", tickets_resp if isinstance(tickets_resp, list) else []
                )

                for t in tickets:
                    if t.get("status") in ("open", "pending"):
                        return QueueInfo(
                            queue_id=t.get("queueId"),
                            user_id=t.get("userId"),
                            ticket_id=t.get("id"),
                            status=t.get("status"),
                            contact_found=True,
                        )

                return QueueInfo(contact_found=True)

            except Exception as e:
                # API de tickets pode falhar (bug conhecido do Leadbox)
                logger.warning("leadbox_tickets_api_error", error=str(e))
                return QueueInfo(contact_found=True)

        except Exception as e:
            logger.error("leadbox_get_queue_error", error=str(e))
            return None

    async def update_ticket(
        self,
        ticket_id: int,
        queue_id: Optional[int] = None,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Atualiza um ticket.

        Args:
            ticket_id: ID do ticket
            queue_id: Nova fila (opcional)
            user_id: Novo usuario (opcional)
            status: Novo status (opcional)

        Returns:
            Ticket atualizado ou None
        """
        try:
            data: dict[str, Any] = {}
            if queue_id is not None:
                data["queueId"] = queue_id
            if user_id is not None:
                data["userId"] = user_id
            if status is not None:
                data["status"] = status

            if not data:
                return None

            response = await self._put(f"/tickets/{ticket_id}", data)
            return response

        except Exception as e:
            logger.error(
                "leadbox_update_ticket_error",
                ticket_id=ticket_id,
                error=str(e),
            )
            return None

    # ==========================================================================
    # HEALTH CHECK
    # ==========================================================================

    async def health_check(self) -> bool:
        """
        Verifica se o servico Leadbox esta acessivel.

        Returns:
            True se acessivel, False caso contrario
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers={"Accept": "application/json"},
                )
                return response.status_code < 500
        except Exception as e:
            logger.error("leadbox_health_check_failed", error=str(e))
            return False


# ==============================================================================
# FACTORY FUNCTIONS
# ==============================================================================


def create_leadbox_client(config: LeadboxConfig) -> Optional[LeadboxClient]:
    """
    Cria uma instancia do LeadboxClient a partir de uma configuracao.

    Args:
        config: Configuracao do Leadbox (de um agente)

    Returns:
        LeadboxClient ou None se nao configurado
    """
    if not config.get("enabled"):
        logger.debug("leadbox_not_enabled")
        return None

    api_url = config.get("api_url")
    api_uuid = config.get("api_uuid")
    api_token = config.get("api_token")

    if not api_url or not api_uuid or not api_token:
        logger.warning(
            "leadbox_incomplete_config",
            has_url=bool(api_url),
            has_uuid=bool(api_uuid),
            has_token=bool(api_token),
        )
        return None

    return LeadboxClient(
        base_url=api_url,
        api_uuid=api_uuid,
        api_token=api_token,
    )


def create_leadbox_client_from_credentials(
    credentials: LeadboxCredentials,
) -> LeadboxClient:
    """
    Cria LeadboxClient a partir de credenciais.

    Args:
        credentials: Credenciais do Leadbox

    Returns:
        LeadboxClient
    """
    return LeadboxClient(
        base_url=credentials.base_url,
        api_uuid=credentials.api_uuid,
        api_token=credentials.api_token,
    )
