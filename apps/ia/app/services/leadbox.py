"""
LeadboxService - Servico de integracao com Leadbox para transferencia de atendimento.

Este servico gerencia:
- Transferencia de atendimento para departamentos/filas
- Atribuicao de tickets para usuarios especificos

Usa a API PUSH do Leadbox.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, TypedDict

import httpx

from app.config import settings

# Configurar logging
logger = logging.getLogger(__name__)


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class TransferResult(TypedDict):
    """Resultado de uma transferencia."""
    sucesso: bool
    mensagem: str
    ticket_id: Optional[str]
    queue_id: Optional[int]
    user_id: Optional[int]


class LeadboxConfig(TypedDict, total=False):
    """Configuracao do Leadbox para um agente."""
    enabled: bool
    api_url: str
    api_uuid: str
    api_token: str
    ia_queue_id: Optional[int]
    ia_user_id: Optional[int]


# ============================================================================
# LEADBOX SERVICE
# ============================================================================

class LeadboxService:
    """
    Servico para integracao com Leadbox (sistema de atendimento).

    Gerencia:
    - Transferencia de atendimentos para departamentos
    - Atribuicao de tickets para atendentes

    Exemplo de uso:
        service = LeadboxService(
            base_url="https://api.leadbox.com",
            api_uuid="abc-123",
            api_key="token-xyz"
        )
        result = await service.transfer_to_department(
            phone="5511999999999",
            queue_id=1,
            user_id=10
        )
    """

    def __init__(
        self,
        base_url: str,
        api_uuid: str,
        api_key: str,
        timeout: float = 30.0
    ):
        """
        Inicializa o LeadboxService.

        Args:
            base_url: URL base da API Leadbox
            api_uuid: UUID da API externa do Leadbox
            api_key: Token Bearer para autenticacao
            timeout: Timeout para requisicoes em segundos (default: 30)
        """
        self.base_url = base_url.rstrip("/")
        self.api_uuid = api_uuid
        self.api_key = api_key
        self.timeout = timeout

        if not self.base_url:
            raise ValueError(
                "LEADBOX_BASE_URL e obrigatorio. "
                "Passe como parametro ou configure no ambiente."
            )

        if not self.api_uuid:
            raise ValueError(
                "LEADBOX_API_UUID e obrigatorio. "
                "Passe como parametro ou configure no ambiente."
            )

        if not self.api_key:
            raise ValueError(
                "LEADBOX_API_KEY e obrigatorio. "
                "Passe como parametro ou configure no ambiente."
            )

        # Headers padrao
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.info(
            f"LeadboxService inicializado. base_url={self.base_url}, "
            f"api_uuid={self.api_uuid[:8]}..."
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa uma requisicao HTTP para a API Leadbox.

        Args:
            method: Metodo HTTP (GET, POST, PUT, DELETE)
            endpoint: Endpoint da API (sem a base_url)
            data: Dados para enviar no body (JSON)
            params: Parametros de query string

        Returns:
            Resposta da API como dicionario

        Raises:
            httpx.HTTPStatusError: Se a resposta for um erro HTTP
            httpx.RequestError: Se houver erro de conexao
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        logger.debug(f"Leadbox Request: {method} {url}")
        if data:
            logger.debug(f"Leadbox Payload: {data}")

        # Logs detalhados antes da chamada
        logger.debug(f"[LEADBOX API] URL: {url}")
        logger.debug(f"[LEADBOX API] Headers: {self._headers}")
        logger.debug(f"[LEADBOX API] Payload: {data}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    params=params
                )

                # Logs detalhados depois da chamada
                logger.debug(f"[LEADBOX API] Status: {response.status_code}")
                logger.debug(f"[LEADBOX API] Response: {response.text}")

                logger.debug(f"Leadbox Response: {response.status_code}")

                response.raise_for_status()

                try:
                    return response.json()
                except Exception:
                    return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Leadbox HTTP Error: {e.response.status_code} - {e.response.text}"
                )
                raise

            except httpx.RequestError as e:
                logger.error(f"Leadbox Request Error: {e}")
                raise

    async def _post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao POST."""
        return await self._request("POST", endpoint, data=data)

    def _format_phone(self, phone: str) -> str:
        """
        Formata o numero de telefone para o padrao Leadbox.

        Remove sufixos do WhatsApp e caracteres especiais.

        Args:
            phone: Numero de telefone (pode conter @s.whatsapp.net, @lid, etc)

        Returns:
            Numero formatado (apenas digitos)
        """
        # Remover sufixos do WhatsApp
        clean = phone.replace("@s.whatsapp.net", "")
        clean = clean.replace("@c.us", "")
        clean = clean.replace("@lid", "")

        # Remover caracteres nao-numericos
        clean = "".join(filter(str.isdigit, clean))

        # Adicionar codigo do Brasil se necessario
        if len(clean) == 10 or len(clean) == 11:
            clean = f"55{clean}"

        return clean

    async def transfer_to_department(
        self,
        phone: str,
        queue_id: int,
        user_id: Optional[int] = None,
        notes: Optional[str] = None,
        external_key: Optional[str] = None,
        mensagem: Optional[str] = None
    ) -> TransferResult:
        """
        Transfere um atendimento para um departamento/fila.

        Usa a API PUSH do Leadbox que cria ou encontra o ticket pelo numero
        e transfere automaticamente para a fila/usuario especificado.

        Args:
            phone: Numero de telefone do cliente (remoteJid ou apenas numero)
            queue_id: ID da fila/departamento no Leadbox
            user_id: ID do usuario/atendente (opcional)
            notes: Mensagem/observacoes para o atendente (opcional)
            external_key: Chave externa para rastreamento (opcional)

        Returns:
            TransferResult com status da operacao

        Example:
            result = await service.transfer_to_department(
                phone="5511999999999",
                queue_id=1,
                user_id=10,
                notes="Cliente interessado em plano premium"
            )
        """
        try:
            formatted_phone = self._format_phone(phone)

            logger.info(
                f"Transferindo atendimento. phone={formatted_phone[:8]}***, "
                f"queue_id={queue_id}, user_id={user_id or 'N/A'}"
            )

            # Endpoint da API PUSH
            endpoint = f"/v1/api/external/{self.api_uuid}"

            # Construir payload
            # IMPORTANTE: "body" da API PUSH vira mensagem visivel pro cliente.
            # Nao expor motivo interno. O motivo fica no campo transfer_reason do Supabase.
            # Se mensagem for None, usa default. Se for string vazia "", não envia mensagem.
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "externalKey": external_key or f"transfer-{formatted_phone}-{queue_id}",
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Só incluir body se mensagem não for string vazia
            # mensagem=None -> usa default, mensagem="" -> silencioso (sem body)
            if mensagem is None:
                payload["body"] = "O departamento ideal vai falar com você."
            elif mensagem:  # String não-vazia
                payload["body"] = mensagem
            # Se mensagem == "", não incluímos body no payload (modo silencioso)

            # Se tiver userId, atribuir ao usuario especifico
            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            logger.debug(f"Payload de transferencia: {payload}")

            response = await self._post(endpoint, payload)

            logger.info(
                f"Transferencia realizada com sucesso. response={response}"
            )

            # Extrair ticket_id da resposta do Leadbox
            # Resposta: {"message": {"ticketId": 123, ...}, "ticket": {"id": 123, "queueId": ..., "userId": ...}}
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

            logger.debug(f"[LEADBOX] ticket_id extraido: {ticket_id}, queue_id: {ticket_queue_id}, user_id: {ticket_user_id}")

            return {
                "sucesso": True,
                "mensagem": f"Atendimento transferido para a fila {queue_id}" + (
                    f" e atribuido ao usuario {user_id}" if user_id else ""
                ),
                "ticket_id": str(ticket_id) if ticket_id else None,
                "queue_id": ticket_queue_id,
                "user_id": ticket_user_id,
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Erro ao transferir: {error_msg}")
            return {
                "sucesso": False,
                "mensagem": f"Erro ao transferir atendimento: {error_msg}",
                "ticket_id": None,
                "queue_id": queue_id,
                "user_id": user_id,
            }

        except httpx.RequestError as e:
            error_msg = str(e)
            logger.error(f"Erro de conexao ao transferir: {error_msg}")
            return {
                "sucesso": False,
                "mensagem": f"Erro de conexao com Leadbox: {error_msg}",
                "ticket_id": None,
                "queue_id": queue_id,
                "user_id": user_id,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Erro inesperado ao transferir: {error_msg}")
            return {
                "sucesso": False,
                "mensagem": f"Erro inesperado: {error_msg}",
                "ticket_id": None,
                "queue_id": queue_id,
                "user_id": user_id,
            }

    async def send_message(
        self,
        phone: str,
        message: str,
        queue_id: Optional[int] = None,
        external_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envia uma mensagem para um numero via API PUSH do Leadbox.

        Diferente de transfer_to_department, esta funcao apenas envia
        uma mensagem sem forcar transferencia de fila.

        Args:
            phone: Numero de telefone do destinatario
            message: Texto da mensagem
            queue_id: ID da fila (opcional)
            external_key: Chave externa para rastreamento (opcional)

        Returns:
            Dict com resultado da operacao
        """
        try:
            formatted_phone = self._format_phone(phone)

            logger.info(f"Enviando mensagem via Leadbox. phone={formatted_phone[:8]}***")

            endpoint = f"/v1/api/external/{self.api_uuid}"

            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "body": message,
                "externalKey": external_key or f"msg-{formatted_phone}",
            }

            if queue_id:
                payload["queueId"] = queue_id

            response = await self._post(endpoint, payload)

            logger.info(f"Mensagem enviada com sucesso via Leadbox")

            return {
                "success": True,
                "response": response,
            }

        except Exception as e:
            logger.error(f"Erro ao enviar mensagem via Leadbox: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def assign_user_silent(
        self,
        phone: str,
        queue_id: int,
        user_id: int,
        ticket_id: Optional[int] = None
    ) -> TransferResult:
        """
        Atribui userId a um ticket SEM enviar mensagem para o cliente.

        Usa PUT /tickets/{id} que apenas atualiza o ticket sem criar mensagem.
        Diferente de transfer_to_department que usa API PUSH e sempre envia msg.

        Args:
            phone: Numero de telefone (usado para buscar ticket se ticket_id nao informado)
            queue_id: ID da fila
            user_id: ID do usuario a atribuir
            ticket_id: ID do ticket (opcional - se nao informado, busca pelo telefone)

        Returns:
            TransferResult com status da operacao
        """
        try:
            # Se nao tem ticket_id, buscar pelo telefone
            if not ticket_id:
                current_queue = await get_current_queue(
                    api_url=self.base_url,
                    api_token=self.api_key,
                    phone=phone,
                )
                if current_queue and current_queue.get("ticket_id"):
                    ticket_id = current_queue["ticket_id"]
                else:
                    logger.warning(f"[ASSIGN SILENT] Ticket nao encontrado para phone={phone[:8]}***")
                    return {
                        "sucesso": False,
                        "mensagem": "Ticket nao encontrado para este telefone",
                        "ticket_id": None,
                        "queue_id": queue_id,
                        "user_id": user_id,
                    }

            logger.info(
                f"[ASSIGN SILENT] Atribuindo userId={user_id} ao ticket={ticket_id} "
                f"sem enviar mensagem"
            )

            # PUT /tickets/{id} - atualiza ticket sem enviar mensagem (com retry)
            _last_error = None
            response = None
            for _retry in range(3):
                try:
                    response = await self._request(
                        method="PUT",
                        endpoint=f"/tickets/{ticket_id}",
                        data={"queueId": queue_id, "userId": user_id}
                    )
                    _last_error = None
                    break
                except httpx.HTTPStatusError as e:
                    _last_error = e
                    if _retry < 2 and e.response.status_code >= 500:
                        logger.warning(
                            "[ASSIGN SILENT] PUT falhou (HTTP %d), retry %d/3 para ticket %s",
                            e.response.status_code, _retry + 1, ticket_id
                        )
                        await asyncio.sleep(1.5 * (_retry + 1))
                        continue
                    raise
                except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                    _last_error = e
                    if _retry < 2:
                        logger.warning(
                            "[ASSIGN SILENT] Timeout no PUT, retry %d/3 para ticket %s",
                            _retry + 1, ticket_id
                        )
                        await asyncio.sleep(1.5 * (_retry + 1))
                        continue
                    raise

            if _last_error:
                raise _last_error

            logger.info(f"[ASSIGN SILENT] Sucesso! ticket={ticket_id} userId={user_id}")

            return {
                "sucesso": True,
                "mensagem": f"Usuario {user_id} atribuido ao ticket {ticket_id} (silencioso)",
                "ticket_id": str(ticket_id),
                "queue_id": response.get("queueId") or queue_id,
                "user_id": response.get("userId") or user_id,
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"[ASSIGN SILENT] Erro HTTP: {error_msg}")
            return {
                "sucesso": False,
                "mensagem": f"Erro ao atribuir usuario: {error_msg}",
                "ticket_id": str(ticket_id) if ticket_id else None,
                "queue_id": queue_id,
                "user_id": user_id,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[ASSIGN SILENT] Erro: {error_msg}")
            return {
                "sucesso": False,
                "mensagem": f"Erro inesperado: {error_msg}",
                "ticket_id": str(ticket_id) if ticket_id else None,
                "queue_id": queue_id,
                "user_id": user_id,
            }

    async def health_check(self) -> bool:
        """
        Verifica se o servico Leadbox esta acessivel.

        Returns:
            True se acessivel, False caso contrario
        """
        try:
            # Tenta fazer uma requisicao simples
            # A API PUSH nao tem endpoint de health, entao verificamos
            # se conseguimos conectar
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers={"Accept": "application/json"},
                )
                return response.status_code < 500

        except Exception as e:
            logger.error(f"Leadbox health check falhou: {e}")
            return False


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_leadbox_service(config: LeadboxConfig) -> Optional[LeadboxService]:
    """
    Cria uma instancia do LeadboxService a partir de uma configuracao.

    Args:
        config: Configuracao do Leadbox (de um agente)

    Returns:
        Instancia do LeadboxService ou None se nao configurado

    Example:
        config = {
            "enabled": True,
            "api_url": "https://api.leadbox.com",
            "api_uuid": "abc-123",
            "api_token": "token-xyz"
        }
        service = create_leadbox_service(config)
        if service:
            result = await service.transfer_to_department(...)
    """
    if not config.get("enabled"):
        logger.debug("Leadbox nao habilitado na configuracao")
        return None

    api_url = config.get("api_url")
    api_uuid = config.get("api_uuid")
    api_token = config.get("api_token")

    if not api_url or not api_uuid or not api_token:
        logger.warning(
            "Leadbox habilitado mas falta configuracao. "
            f"has_url={bool(api_url)}, has_uuid={bool(api_uuid)}, has_token={bool(api_token)}"
        )
        return None

    return LeadboxService(
        base_url=api_url,
        api_uuid=api_uuid,
        api_key=api_token
    )


# ============================================================================
# QUEUE CHECK FUNCTIONS
# ============================================================================

async def get_current_queue(
    api_url: str,
    api_token: str,
    phone: str,
    ticket_id: Optional[int] = None,
    ia_queue_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Consulta a fila atual de um lead no Leadbox.

    Estratégia:
    1. Se tem ticket_id: faz PUT /tickets/{id} para obter estado atual
    2. Se não tem: busca contato via GET /contacts?searchParam={phone}
       2a. Se encontrar contato, tenta buscar tickets abertos do contato
           via GET /tickets?contactId={id}&status=open (pode falhar por bug da API)
       2b. Se encontrar ticket aberto, retorna queue_id, user_id, ticket_id
       2c. Se API de tickets falhar, retorna contact_found (fail-open)

    Nota sobre a API Leadbox:
        GET /tickets com qualquer filtro retorna erro 500 com "userId undefined"
        quando chamado via token de API externa. Isso é uma limitação conhecida
        da API do Leadbox. Quando ocorre, a função retorna contact_found (sem queue_id)
        e a IA prossegue normalmente (fail-open).

    Returns:
        {"queue_id": int, "user_id": int, "ticket_id": int, "status": str} ou None
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Estratégia 1: Se já tem ticket_id, consulta direto via PUT
        if ticket_id:
            try:
                resp = await client.put(
                    f"{api_url}/tickets/{ticket_id}",
                    headers=headers,
                    json={},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = {
                        "queue_id": data.get("queueId"),
                        "user_id": data.get("userId"),
                        "ticket_id": data.get("id") or ticket_id,
                        "status": data.get("status"),
                    }
                    logger.debug(f"[LEADBOX CHECK] Ticket {ticket_id}: queue={result['queue_id']}, status={result['status']}")
                    return result

                # 409 Conflict: ticket foi substituido por outro
                # O body contem os dados do ticket NOVO no campo "error" como JSON string
                elif resp.status_code == 409:
                    try:
                        import json as json_module
                        error_data = resp.json()
                        error_str = error_data.get("error", "")
                        new_ticket = json_module.loads(error_str)
                        result = {
                            "queue_id": new_ticket.get("queueId"),
                            "user_id": new_ticket.get("userId"),
                            "ticket_id": new_ticket.get("id"),
                            "status": new_ticket.get("status"),
                        }
                        logger.info(
                            f"[LEADBOX CHECK] Ticket {ticket_id} substituido por {result['ticket_id']}: "
                            f"queue={result['queue_id']}, status={result['status']}"
                        )
                        return result
                    except (json_module.JSONDecodeError, TypeError, KeyError) as parse_err:
                        logger.debug(f"[LEADBOX CHECK] 409 com JSON invalido: {parse_err}")
                        # Continua para estrategia 2 (fallback)

            except Exception as e:
                logger.debug(f"[LEADBOX CHECK] Erro ao consultar ticket {ticket_id}: {e}")

        # Estratégia 2: Busca contato pelo telefone, depois tickets abertos
        try:
            clean_phone = "".join(filter(str.isdigit, phone))
            resp = await client.get(
                f"{api_url}/contacts",
                headers=headers,
                params={"searchParam": clean_phone, "pageNumber": 1, "limit": 1},
            )
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get("contacts", [])
                if contacts:
                    contact = contacts[0]
                    contact_id = contact.get("id")
                    logger.info(f"[LEADBOX CHECK] Contato encontrado: id={contact_id}, name={contact.get('name')} - buscando tickets abertos")

                    # Estratégia 2a: Buscar tickets abertos do contato
                    # NOTA: A API Leadbox retorna erro 500 com "userId undefined" para este endpoint
                    # quando chamado via token de API externa. Tentamos mesmo assim para coleta de dados.
                    ticket_found = await _fetch_open_ticket_for_contact(
                        client=client,
                        api_url=api_url,
                        headers=headers,
                        contact_id=contact_id,
                        ia_queue_id=ia_queue_id,
                    )

                    if ticket_found:
                        return ticket_found

                    # Fallback: retorna contact_found sem queue_id (fail-open)
                    logger.debug(f"[LEADBOX CHECK] Contato {contact_id} - sem tickets abertos encontrados via API, retornando contact_found")
                    return {
                        "queue_id": None,
                        "user_id": None,
                        "ticket_id": None,
                        "status": "contact_found",
                        "contact_id": contact_id,
                    }
        except Exception as e:
            logger.debug(f"[LEADBOX CHECK] Erro ao buscar contato {phone}: {e}")

    return None


async def _fetch_open_ticket_for_contact(
    client: httpx.AsyncClient,
    api_url: str,
    headers: dict,
    contact_id: int,
    ia_queue_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Tenta buscar o ticket aberto mais recente de um contato via múltiplas estratégias.

    A API Leadbox tem um bug no endpoint GET /tickets que retorna 500 com
    "userId undefined" quando chamado via token de API externa sem userId explícito.

    Returns:
        {"queue_id": int, "user_id": int, "ticket_id": int, "status": str} ou None
    """
    # Tentativa: GET /tickets?contactId={id}&status=open
    # Pode falhar com erro 500 "userId undefined" - bug conhecido da API Leadbox
    candidate_params_list = [
        {"contactId": contact_id, "status": "open", "pageNumber": 1, "pageSize": 1},
        {"contactId": contact_id, "pageNumber": 1, "pageSize": 1},
    ]

    for params in candidate_params_list:
        try:
            resp = await client.get(
                f"{api_url}/tickets",
                headers=headers,
                params=params,
            )

            if resp.status_code == 200:
                data = resp.json()
                tickets = data.get("tickets", [])

                if not tickets and isinstance(data, list):
                    tickets = data

                if tickets:
                    # Filtrar para pegar apenas tickets abertos se não filtrado
                    open_tickets = [
                        t for t in tickets
                        if t.get("status") in ("open", "pending")
                    ]
                    ticket = (open_tickets or tickets)[0]
                    result_ticket_id = ticket.get("id")
                    result_queue_id = ticket.get("queueId")
                    result_user_id = ticket.get("userId")
                    result_status = ticket.get("status")

                    logger.info(
                        f"[LEADBOX CHECK] Ticket aberto encontrado: "
                        f"id={result_ticket_id}, queue={result_queue_id}, status={result_status}"
                    )
                    return {
                        "queue_id": result_queue_id,
                        "user_id": result_user_id,
                        "ticket_id": result_ticket_id,
                        "status": result_status,
                        "contact_id": contact_id,
                    }
            else:
                # Erro esperado: 500 com "userId undefined" - limitação da API Leadbox
                try:
                    err_data = resp.json()
                    err_msg = err_data.get("error", "")
                except Exception:
                    err_msg = resp.text[:100]
                logger.debug(
                    f"[LEADBOX CHECK] Contato {contact_id} - GET /tickets retornou {resp.status_code}: {err_msg[:80]}"
                )
                break  # Ambas as tentativas falham da mesma forma, não adianta tentar a segunda

        except Exception as e:
            logger.debug(f"[LEADBOX CHECK] Contato {contact_id} - erro ao buscar tickets: {e}")
            break

    return None


# ============================================================================
# DYNAMIC DEPARTMENT RESOLUTION
# ============================================================================

def resolve_department(
    handoff_triggers: Dict[str, Any],
    queue_id: Optional[int] = None,
    motivo: Optional[str] = None,
) -> tuple:
    """
    Resolve qual departamento usar para transferencia.

    Prioridade:
    1. queue_id informado diretamente (match no departments para pegar userId)
    2. Keywords do motivo (busca match nos departments)
    3. Departamento marcado como default
    4. Primeiro departamento configurado

    Args:
        handoff_triggers: Config handoff_triggers do agente
        queue_id: ID da fila (pode ser None se Gemini nao informou)
        motivo: Motivo da transferencia (usado para match de keywords)

    Returns:
        tuple: (final_queue_id, final_user_id, department_name)
    """
    departments = handoff_triggers.get("departments", {})

    if not departments:
        logger.debug("[TRANSFER] Nenhum departamento configurado!")
        return None, None, None

    dept_names = ", ".join(departments.keys())
    logger.debug(f"[TRANSFER] Departamentos configurados: {dept_names}")

    # 1. Se queue_id foi informado, valida e usa
    if queue_id:
        queue_ia = handoff_triggers.get("queue_ia")

        # CRÍTICO: Rejeitar transferência para a própria fila da IA
        if queue_ia and int(queue_id) == int(queue_ia):
            logger.warning(
                f"[TRANSFER] REJEITADO: tentativa de transferir para fila IA "
                f"(queue_id={queue_id} == queue_ia={queue_ia})"
            )
            return None, None, None

        # Buscar departamento correspondente ao queue_id
        for dept_key, dept in departments.items():
            if dept.get("id") == int(queue_id):
                logger.debug(f"[TRANSFER] Usando departamento informado: {dept.get('name')} (queue={queue_id})")
                return int(queue_id), dept.get("userId"), dept.get("name")

        # queue_id nao encontrado nos departments -> usar default (nao aceitar cegamente)
        logger.warning(
            f"[TRANSFER] queue_id={queue_id} nao encontrado nos departments, "
            "usando departamento default"
        )

    # 2. Se nao tem queue_id, busca por keywords no motivo
    if motivo:
        motivo_lower = motivo.lower()
        logger.debug(f"[TRANSFER] Buscando match por keywords no motivo: '{motivo_lower[:80]}'")
        for dept_key, dept in departments.items():
            keywords = dept.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in motivo_lower:
                    logger.debug(f"[TRANSFER] Match por keyword '{keyword}' -> {dept.get('name')} (queue={dept.get('id')})")
                    return dept.get("id"), dept.get("userId"), dept.get("name")
        logger.debug("[TRANSFER] Nenhum match encontrado por keywords")

    # 3. Se nao encontrou match, usa departamento default
    for dept_key, dept in departments.items():
        if dept.get("default") is True:
            logger.debug(f"[TRANSFER] Usando departamento DEFAULT: {dept.get('name')} (queue={dept.get('id')})")
            return dept.get("id"), dept.get("userId"), dept.get("name")

    # 4. Se nao tem default, usa o primeiro departamento
    first_dept = list(departments.values())[0]
    logger.debug(f"[TRANSFER] Sem default configurado, usando primeiro: {first_dept.get('name')} (queue={first_dept.get('id')})")
    return first_dept.get("id"), first_dept.get("userId"), first_dept.get("name")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def transfer_to_department(
    config: LeadboxConfig,
    phone: str,
    queue_id: int,
    user_id: Optional[int] = None,
    notes: Optional[str] = None,
    mensagem: Optional[str] = None
) -> TransferResult:
    """
    Funcao de conveniencia para transferir atendimento.

    Cria uma instancia do LeadboxService e executa a transferencia.

    Args:
        config: Configuracao do Leadbox
        phone: Numero de telefone do cliente
        queue_id: ID da fila/departamento
        user_id: ID do usuario (opcional)
        notes: Observacoes (opcional)

    Returns:
        TransferResult com status da operacao
    """
    service = create_leadbox_service(config)

    if not service:
        return {
            "sucesso": False,
            "mensagem": "Leadbox nao configurado para este agente",
            "ticket_id": None,
            "queue_id": queue_id,
            "user_id": user_id,
        }

    return await service.transfer_to_department(
        phone=phone,
        queue_id=queue_id,
        user_id=user_id,
        notes=notes,
        mensagem=mensagem
    )
