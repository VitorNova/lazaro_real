# CODIGO FONTE ATUAL - Agente IA Python
## Backup gerado em: 2026-01-27

---

## 1. app/services/gemini.py

```python
"""
Gemini Service - Integração com Google Generative AI (Gemini).

Funcionalidades:
- Inicialização do modelo com function declarations (tools)
- Registro dinâmico de handlers para tools
- Envio de mensagens com histórico de conversação
- Processamento de respostas e function calls
- Loop automático de execução de tools
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

import google.generativeai as genai
from google.generativeai.types import (
    ContentType,
    GenerationConfig,
    HarmBlockThreshold,
    HarmCategory,
)

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiService:
    """Serviço de integração com Google Gemini AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """
        Inicializa o serviço Gemini.

        Args:
            api_key: Chave da API do Google AI (usa settings se não fornecido)
            model_name: Nome do modelo (default: gemini-2.0-flash-exp)
            temperature: Temperatura do modelo (default: 0.7)
            max_tokens: Máximo de tokens na resposta (default: 4096)
        """
        self._api_key = api_key or settings.google_api_key
        self._model_name = model_name or settings.gemini_model
        self._temperature = temperature or settings.gemini_temperature
        self._max_tokens = max_tokens or settings.gemini_max_tokens

        # Configuração da API
        genai.configure(api_key=self._api_key)

        # Modelo e chat
        self._model: Optional[genai.GenerativeModel] = None
        self._tools: Optional[List[Dict[str, Any]]] = None
        self._tool_handlers: Dict[str, Callable[..., Any]] = {}

        # Safety settings - BLOCK_NONE para todas as categorias
        self._safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        logger.info(
            "GeminiService inicializado",
            extra={
                "model": self._model_name,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
        )

    def initialize(
        self,
        function_declarations: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
    ) -> None:
        """
        Inicializa o modelo com function declarations (tools).

        Args:
            function_declarations: Lista de declarações de funções no formato Gemini
            system_instruction: Instrução de sistema (prompt base)
        """
        self._tools = function_declarations

        # Configuração de geração
        generation_config = GenerationConfig(
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
            candidate_count=1,
        )

        # Prepara tools para o modelo
        tools = None
        if function_declarations:
            tools = [{"function_declarations": function_declarations}]
            logger.info(
                "Tools configuradas",
                extra={"count": len(function_declarations)},
            )

        # Cria o modelo
        self._model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=generation_config,
            safety_settings=self._safety_settings,
            tools=tools,
            system_instruction=system_instruction,
        )

        logger.info(
            "Modelo Gemini inicializado",
            extra={
                "model": self._model_name,
                "has_tools": bool(function_declarations),
                "has_system_instruction": bool(system_instruction),
            },
        )

    def register_tool_handler(
        self,
        name: str,
        handler: Callable[..., Any],
    ) -> None:
        """
        Registra um handler para uma tool específica.

        Args:
            name: Nome da função/tool
            handler: Função callable que será executada
        """
        self._tool_handlers[name] = handler
        logger.debug(f"Tool handler registrado: {name}")

    def register_tool_handlers(
        self,
        handlers: Dict[str, Callable[..., Any]],
    ) -> None:
        """
        Registra múltiplos handlers de uma vez.

        Args:
            handlers: Dicionário com nome -> handler
        """
        for name, handler in handlers.items():
            self.register_tool_handler(name, handler)

    async def send_message(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envia mensagens para o Gemini com histórico de conversação.

        Args:
            messages: Lista de mensagens no formato do histórico
            system_prompt: Prompt de sistema opcional (sobrescreve o da inicialização)

        Returns:
            dict com:
                - text: Resposta final em texto
                - function_calls: Lista de function calls executadas
                - usage: Informações de uso de tokens
        """
        if self._model is None:
            raise RuntimeError("Modelo não inicializado. Chame initialize() primeiro.")

        # Se tiver system_prompt específico, recria o modelo
        model = self._model
        if system_prompt:
            model = genai.GenerativeModel(
                model_name=self._model_name,
                generation_config=GenerationConfig(
                    temperature=self._temperature,
                    max_output_tokens=self._max_tokens,
                    candidate_count=1,
                ),
                safety_settings=self._safety_settings,
                tools=[{"function_declarations": self._tools}] if self._tools else None,
                system_instruction=system_prompt,
            )

        # Formata histórico para o Gemini
        history = self.format_message_history(messages[:-1]) if len(messages) > 1 else []

        # Inicia chat com histórico
        chat = model.start_chat(history=history)

        # Última mensagem do usuário
        last_message = messages[-1] if messages else {"role": "user", "parts": [{"text": ""}]}
        user_content = self._extract_content(last_message)

        logger.debug(
            "Enviando mensagem para Gemini",
            extra={
                "history_length": len(history),
                "user_content_preview": str(user_content)[:100],
            },
        )

        try:
            print(f"[DEBUG 5/6] GEMINI - Enviando mensagem...")
            print(f"[DEBUG 5/6] GEMINI - Model: {self._model_name}")
            print(f"[DEBUG 5/6] GEMINI - Histórico: {len(history)} mensagens")
            print(f"[DEBUG 5/6] GEMINI - Conteúdo usuário: {str(user_content)[:150]}...")

            # Envia mensagem
            response = await chat.send_message_async(user_content)

            print(f"[DEBUG 5/6] GEMINI - Resposta recebida!")

            # Processa resposta
            result = self._process_response(response)

            print(f"[DEBUG 5/6] GEMINI - Texto processado: {result.get('text', '')[:200]}...")
            print(f"[DEBUG 5/6] GEMINI - Function calls: {len(result.get('function_calls', []))}")

            # Se houver function calls, executa e continua
            if result["function_calls"]:
                result = await self._handle_function_calls(chat, result["function_calls"])

            logger.info(
                "Resposta recebida do Gemini",
                extra={
                    "text_length": len(result.get("text", "")),
                    "function_calls_count": len(result.get("function_calls", [])),
                },
            )

            return result

        except Exception as e:
            print(f"[DEBUG 5/6] GEMINI - ERRO: {str(e)}")
            logger.error(
                "Erro ao enviar mensagem para Gemini",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    def _process_response(
        self,
        response: Any,
    ) -> Dict[str, Any]:
        """
        Extrai texto e function_calls da resposta do Gemini.

        Args:
            response: Objeto de resposta do Gemini

        Returns:
            dict com text, function_calls e usage
        """
        result: Dict[str, Any] = {
            "text": "",
            "function_calls": [],
            "usage": {},
        }

        # Extrai informações de uso
        if hasattr(response, "usage_metadata"):
            result["usage"] = {
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
            }

        # Processa candidatos - verifica de forma defensiva
        if not response.candidates or len(response.candidates) == 0:
            logger.warning("Resposta sem candidatos (pode ser normal após function call)")
            return result

        try:
            candidate = response.candidates[0]
        except (IndexError, TypeError) as e:
            logger.warning(f"Erro ao acessar candidato: {e}")
            return result

        # Extrai conteúdo
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                # Texto
                if hasattr(part, "text") and part.text:
                    result["text"] += part.text

                # Function call
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    function_call_data = {
                        "name": fc.name,
                        "args": dict(fc.args) if fc.args else {},
                    }
                    result["function_calls"].append(function_call_data)
                    logger.debug(
                        "Function call detectada",
                        extra={"name": fc.name, "args": function_call_data["args"]},
                    )

        return result

    async def _handle_function_calls(
        self,
        chat: Any,
        function_calls: List[Dict[str, Any]],
        max_iterations: int = 10,
    ) -> Dict[str, Any]:
        """
        Executa tools e retorna resultados para o Gemini.
        Implementa loop de execução até obter resposta final.

        Args:
            chat: Objeto de chat do Gemini
            function_calls: Lista de function calls a executar
            max_iterations: Máximo de iterações do loop (evita loops infinitos)

        Returns:
            dict com resposta final
        """
        all_function_calls = list(function_calls)
        iteration = 0

        while function_calls and iteration < max_iterations:
            iteration += 1
            logger.debug(f"Iteration {iteration}: Executando {len(function_calls)} function calls")

            # Executa cada function call
            function_responses = []
            for fc in function_calls:
                name = fc["name"]
                args = fc["args"]

                # Busca handler
                handler = self._tool_handlers.get(name)
                if handler is None:
                    logger.warning(f"Handler não encontrado para tool: {name}")
                    function_responses.append({
                        "name": name,
                        "response": {"error": f"Tool '{name}' não implementada"},
                    })
                    continue

                try:
                    # Executa handler (sync ou async)
                    if callable(handler):
                        import asyncio
                        import inspect

                        if inspect.iscoroutinefunction(handler):
                            result = await handler(**args)
                        else:
                            result = handler(**args)

                        # Converte resultado para dict se necessário
                        if not isinstance(result, dict):
                            result = {"result": result}

                        function_responses.append({
                            "name": name,
                            "response": result,
                        })

                        logger.debug(
                            "Tool executada com sucesso",
                            extra={"name": name, "result_keys": list(result.keys())},
                        )

                except Exception as e:
                    logger.error(
                        f"Erro ao executar tool {name}",
                        extra={"error": str(e), "args": args},
                        exc_info=True,
                    )
                    function_responses.append({
                        "name": name,
                        "response": {"error": str(e)},
                    })

            # Envia resultados de volta ao Gemini
            from google.generativeai.protos import FunctionResponse, Part, Content

            parts = []
            for fr in function_responses:
                parts.append(
                    Part(
                        function_response=FunctionResponse(
                            name=fr["name"],
                            response=fr["response"],
                        )
                    )
                )

            # Envia function responses
            try:
                response = await chat.send_message_async(parts)
                # Processa nova resposta
                result = self._process_response(response)
            except Exception as e:
                logger.warning(f"Erro ao enviar function response ao Gemini: {e}")
                # Usa resultado da function como fallback
                result = {"text": "", "function_calls": [], "usage": {}}

            # Se resposta vazia após function call, usa resultado da function como fallback
            if not result.get("text") and function_responses:
                last_response = function_responses[-1].get("response", {})
                if isinstance(last_response, dict):
                    # Usa mensagem da function se disponível
                    fallback_msg = last_response.get("mensagem") or last_response.get("message", "")
                    if last_response.get("sucesso") or last_response.get("success"):
                        result["text"] = fallback_msg or "Operação realizada com sucesso!"
                    else:
                        result["text"] = fallback_msg or "Houve um problema ao executar a operação."
                logger.info(f"Usando fallback após function call: {result['text'][:50]}...")
                # Importante: limpa function_calls para sair do loop
                result["function_calls"] = []

            # Verifica se há mais function calls
            function_calls = result["function_calls"]
            all_function_calls.extend(function_calls)

        if iteration >= max_iterations:
            logger.warning(
                "Máximo de iterações atingido no loop de function calls",
                extra={"max_iterations": max_iterations},
            )

        # Retorna resultado final com todas as function calls
        result["function_calls"] = all_function_calls
        return result

    def format_message_history(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[ContentType]:
        """
        Formata histórico de mensagens para o formato do Gemini.

        Formato de entrada esperado:
        [
            {"role": "user", "content": "mensagem"},
            {"role": "assistant", "content": "resposta"},
            # ou
            {"role": "user", "parts": [{"text": "mensagem"}]},
            {"role": "model", "parts": [{"text": "resposta"}]},
        ]

        Args:
            messages: Lista de mensagens do histórico

        Returns:
            Lista formatada para o Gemini
        """
        formatted = []

        for msg in messages:
            role = msg.get("role", "user")

            # Normaliza role: "assistant" -> "model"
            if role == "assistant":
                role = "model"

            # Extrai conteúdo
            content = self._extract_content(msg)

            # Formata para Gemini
            formatted.append({
                "role": role,
                "parts": [{"text": content}] if isinstance(content, str) else content,
            })

        return formatted

    def _extract_content(self, message: Dict[str, Any]) -> Union[str, List[Dict[str, Any]]]:
        """
        Extrai o conteúdo de uma mensagem.

        Args:
            message: Mensagem no formato do histórico

        Returns:
            String com o conteúdo ou lista de parts
        """
        # Formato com "content"
        if "content" in message:
            return message["content"]

        # Formato com "parts"
        if "parts" in message:
            parts = message["parts"]
            if isinstance(parts, list):
                # Se for lista de dicts com "text", concatena
                texts = []
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        texts.append(part["text"])
                    elif isinstance(part, str):
                        texts.append(part)
                return " ".join(texts) if texts else ""
            return parts

        return ""

    @property
    def model_name(self) -> str:
        """Retorna o nome do modelo configurado."""
        return self._model_name

    @property
    def is_initialized(self) -> bool:
        """Verifica se o modelo foi inicializado."""
        return self._model is not None

    @property
    def registered_tools(self) -> List[str]:
        """Retorna lista de tools com handlers registrados."""
        return list(self._tool_handlers.keys())


# ===================
# Singleton Instance
# ===================

_gemini_service: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """
    Retorna instância singleton do GeminiService.
    Cria uma nova instância se não existir.
    """
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiService()
    return _gemini_service


def reset_gemini_service() -> None:
    """
    Reseta a instância singleton do GeminiService.
    Útil para testes ou reconfiguração.
    """
    global _gemini_service
    _gemini_service = None
```

---

## 2. app/services/leadbox.py

```python
"""
LeadboxService - Servico de integracao com Leadbox para transferencia de atendimento.

Este servico gerencia:
- Transferencia de atendimento para departamentos/filas
- Atribuicao de tickets para usuarios especificos

Usa a API PUSH do Leadbox.
"""

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
        print(f"[LEADBOX API] URL: {url}")
        print(f"[LEADBOX API] Headers: {self._headers}")
        print(f"[LEADBOX API] Payload: {data}")

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
                print(f"[LEADBOX API] Status: {response.status_code}")
                print(f"[LEADBOX API] Response: {response.text}")

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
        external_key: Optional[str] = None
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
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "body": notes or "Transferindo atendimento...",
                "externalKey": external_key or f"transfer-{formatted_phone}-{queue_id}",
                "forceTicketToDepartment": True,
                "queueId": queue_id,
            }

            # Se tiver userId, atribuir ao usuario especifico
            if user_id:
                payload["forceTicketToUser"] = True
                payload["userId"] = user_id

            logger.debug(f"Payload de transferencia: {payload}")

            response = await self._post(endpoint, payload)

            logger.info(
                f"Transferencia realizada com sucesso. response={response}"
            )

            # Extrair ticket_id da resposta se disponivel
            ticket_id = None
            if isinstance(response, dict):
                ticket_id = response.get("ticketId") or response.get("id")

            return {
                "sucesso": True,
                "mensagem": f"Atendimento transferido para a fila {queue_id}" + (
                    f" e atribuido ao usuario {user_id}" if user_id else ""
                ),
                "ticket_id": str(ticket_id) if ticket_id else None,
                "queue_id": queue_id,
                "user_id": user_id,
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
# CONVENIENCE FUNCTIONS
# ============================================================================

async def transfer_to_department(
    config: LeadboxConfig,
    phone: str,
    queue_id: int,
    user_id: Optional[int] = None,
    notes: Optional[str] = None
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
        notes=notes
    )
```

---

## 3. app/services/uazapi.py

```python
"""
UazapiService - Servico de integracao com UAZAPI para WhatsApp.

Este servico gerencia:
- Envio de mensagens de texto
- Envio de mensagens de midia (imagem, audio, video, documento)
- Marcacao de mensagens como lidas
- Verificacao de status da instancia
- Typing indicators (digitando...)
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Union

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MediaType(str, Enum):
    """Tipos de midia suportados pela UAZAPI."""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"


class MessageResponse(TypedDict):
    """Resposta de envio de mensagem."""
    success: bool
    message_id: Optional[str]
    error: Optional[str]


class InstanceStatus(TypedDict):
    """Status da instancia UAZAPI."""
    connected: bool
    phone_number: Optional[str]
    instance_id: str
    status: str
    battery: Optional[int]
    plugged: Optional[bool]


class UazapiService:
    """Servico para integracao com UAZAPI (WhatsApp API)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.base_url = (base_url or settings.uazapi_base_url).rstrip("/")
        self.api_key = api_key or settings.uazapi_api_key
        self.timeout = timeout

        if not self.base_url:
            raise ValueError("UAZAPI_BASE_URL e obrigatorio.")
        if not self.api_key:
            raise ValueError("UAZAPI_API_KEY e obrigatorio.")

        self._headers = {
            "token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        logger.info(f"UazapiService inicializado com base_url: {self.base_url}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug(f"UAZAPI Request: {method} {url}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    params=params
                )
                response.raise_for_status()
                try:
                    return response.json()
                except Exception:
                    return {"success": True, "raw": response.text}
            except httpx.HTTPStatusError as e:
                logger.error(f"UAZAPI HTTP Error: {e.response.status_code}")
                raise

    async def _post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("POST", endpoint, data=data)

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("GET", endpoint, params=params)

    def _format_phone(self, phone: str) -> str:
        clean = phone.replace("@s.whatsapp.net", "").replace("@lid", "")
        clean = "".join(filter(str.isdigit, clean))
        if len(clean) == 10 or len(clean) == 11:
            clean = f"55{clean}"
        return clean

    async def send_text_message(
        self,
        phone: str,
        text: str,
        delay: Optional[int] = None,
        link_preview: bool = True
    ) -> MessageResponse:
        try:
            formatted_phone = self._format_phone(phone)
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "text": text,
                "linkPreview": link_preview,
            }
            if delay:
                payload["delay"] = delay

            print(f"[UAZAPI] Enviando texto para {formatted_phone}")
            response = await self._post("/send/text", payload)
            message_id = response.get("key", {}).get("id") or response.get("id") if isinstance(response, dict) else None
            return {"success": True, "message_id": message_id, "error": None}
        except Exception as e:
            logger.error(f"Erro ao enviar texto: {e}")
            return {"success": False, "message_id": None, "error": str(e)}

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        caption: Optional[str] = None,
        media_type: Union[MediaType, str] = MediaType.IMAGE,
        filename: Optional[str] = None
    ) -> MessageResponse:
        try:
            formatted_phone = self._format_phone(phone)
            media_type_str = media_type.value if isinstance(media_type, MediaType) else str(media_type).lower()
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "type": media_type_str,
                "file": media_url,
            }
            if caption and media_type_str not in ["audio", "ptt"]:
                payload["text"] = caption
            if filename and media_type_str == "document":
                payload["docName"] = filename

            response = await self._post("/send/media", payload)
            message_id = response.get("key", {}).get("id") or response.get("id") if isinstance(response, dict) else None
            return {"success": True, "message_id": message_id, "error": None}
        except Exception as e:
            return {"success": False, "message_id": None, "error": str(e)}

    async def send_typing(self, phone: str, duration: int = 3000) -> bool:
        try:
            formatted_phone = self._format_phone(phone)
            payload = {"number": formatted_phone, "presence": "composing", "delay": duration}
            await self._post("/message/presence", payload)
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar typing: {e}")
            return False

    async def mark_as_read(self, phone: str, message_id: Optional[str] = None) -> bool:
        try:
            formatted_phone = self._format_phone(phone)
            chat_id = formatted_phone if formatted_phone.endswith("@s.whatsapp.net") else f"{formatted_phone}@s.whatsapp.net"
            payload = {"number": chat_id, "read": True}
            await self._post("/chat/read", payload)
            return True
        except Exception:
            return False

    async def get_instance_status(self) -> InstanceStatus:
        try:
            response = await self._get("/instance/status")
            return {
                "connected": response.get("connected", False) or response.get("status") == "open",
                "phone_number": response.get("phoneNumber") or response.get("phone"),
                "instance_id": response.get("instanceId") or response.get("instance", {}).get("id", ""),
                "status": response.get("status", "unknown"),
                "battery": response.get("battery"),
                "plugged": response.get("plugged"),
            }
        except Exception:
            return {"connected": False, "phone_number": None, "instance_id": "", "status": "error", "battery": None, "plugged": None}

    async def is_connected(self) -> bool:
        status = await self.get_instance_status()
        return status["connected"]


_uazapi_service: Optional[UazapiService] = None


def get_uazapi_service() -> UazapiService:
    global _uazapi_service
    if _uazapi_service is None:
        _uazapi_service = UazapiService()
    return _uazapi_service
```

---

## 4. app/tools/functions.py

```python
"""
Function declarations and handlers for Gemini AI tools.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


FUNCTION_DECLARATIONS = [
    {
        "name": "consulta_agenda",
        "description": "Consulta horarios disponiveis na agenda para agendamento.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string", "description": "Data/hora de inicio (ISO 8601)"},
                "data_fim": {"type": "string", "description": "Data/hora de fim (ISO 8601)"},
                "duracao_minutos": {"type": "integer", "description": "Duracao em minutos (padrao: 30)"}
            },
            "required": ["data_inicio", "data_fim"]
        }
    },
    {
        "name": "agendar",
        "description": "Cria um novo agendamento na agenda. Gera link do Google Meet.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_hora": {"type": "string", "description": "Data/hora (ISO 8601)"},
                "nome_cliente": {"type": "string", "description": "Nome completo do cliente"},
                "telefone": {"type": "string", "description": "Telefone com DDD"},
                "email": {"type": "string", "description": "Email do cliente"},
                "observacoes": {"type": "string", "description": "Observacoes adicionais"},
                "duracao_minutos": {"type": "integer", "description": "Duracao em minutos"}
            },
            "required": ["data_hora", "nome_cliente", "telefone"]
        }
    },
    {
        "name": "cancelar_agendamento",
        "description": "Cancela um agendamento existente.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID do evento a cancelar"},
                "motivo": {"type": "string", "description": "Motivo do cancelamento"}
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "reagendar",
        "description": "Reagenda um agendamento existente.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID do evento"},
                "nova_data_hora": {"type": "string", "description": "Nova data/hora (ISO 8601)"},
                "motivo": {"type": "string", "description": "Motivo do reagendamento"}
            },
            "required": ["event_id", "nova_data_hora"]
        }
    },
    {
        "name": "transferir_departamento",
        "description": "Transfere o atendimento para outro departamento ou atendente humano.",
        "parameters": {
            "type": "object",
            "properties": {
                "departamento": {"type": "string", "description": "Nome do departamento (ex: financeiro, vendas)"},
                "queue_id": {"type": "integer", "description": "ID da fila/departamento no sistema"},
                "user_id": {"type": "integer", "description": "ID do usuario/atendente"},
                "motivo": {"type": "string", "description": "Motivo da transferencia"},
                "observacoes": {"type": "string", "description": "Observacoes para o atendente"}
            },
            "required": ["motivo"]
        }
    }
]


class FunctionHandlers:
    """Handles execution of AI tool function calls."""

    def __init__(self, calendar_service: Any, leadbox_service: Any, supabase_service: Any):
        self.calendar = calendar_service
        self.leadbox = leadbox_service
        self.supabase = supabase_service

    async def consulta_agenda(self, data_inicio: str, data_fim: str, duracao_minutos: int = 30) -> Dict[str, Any]:
        try:
            start = datetime.fromisoformat(data_inicio.replace('Z', '+00:00'))
            end = datetime.fromisoformat(data_fim.replace('Z', '+00:00'))
            available_slots = await self.calendar.get_available_slots(start, end, duracao_minutos)
            if not available_slots:
                return {"sucesso": True, "horarios_disponiveis": [], "mensagem": "Nao ha horarios disponiveis."}
            formatted_slots = [{"inicio": s["start"].isoformat(), "fim": s["end"].isoformat()} for s in available_slots]
            return {"sucesso": True, "horarios_disponiveis": formatted_slots, "mensagem": f"{len(formatted_slots)} horarios encontrados."}
        except Exception as e:
            return {"sucesso": False, "horarios_disponiveis": [], "mensagem": str(e)}

    async def agendar(self, data_hora: str, nome_cliente: str, telefone: str, email: Optional[str] = None, observacoes: Optional[str] = None, duracao_minutos: int = 30) -> Dict[str, Any]:
        try:
            start_time = datetime.fromisoformat(data_hora.replace('Z', '+00:00'))
            event = await self.calendar.create_event(f"Reuniao - {nome_cliente}", start_time, duracao_minutos, email, f"Cliente: {nome_cliente}\nTelefone: {telefone}")
            meet_link = event.get("hangoutLink")
            return {"sucesso": True, "event_id": event.get("id"), "link_meet": meet_link, "mensagem": "Agendamento criado!"}
        except Exception as e:
            return {"sucesso": False, "event_id": None, "link_meet": None, "mensagem": str(e)}

    async def cancelar_agendamento(self, event_id: str, motivo: Optional[str] = None) -> Dict[str, Any]:
        try:
            await self.calendar.delete_event(event_id)
            return {"sucesso": True, "mensagem": "Agendamento cancelado."}
        except Exception as e:
            return {"sucesso": False, "mensagem": str(e)}

    async def reagendar(self, event_id: str, nova_data_hora: str, motivo: Optional[str] = None) -> Dict[str, Any]:
        try:
            new_time = datetime.fromisoformat(nova_data_hora.replace('Z', '+00:00'))
            await self.calendar.update_event(event_id, new_time)
            return {"sucesso": True, "mensagem": "Reagendado com sucesso."}
        except Exception as e:
            return {"sucesso": False, "mensagem": str(e)}

    async def transferir_departamento(self, motivo: str, departamento: Optional[str] = None, queue_id: Optional[int] = None, user_id: Optional[int] = None, observacoes: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        try:
            if not self.leadbox:
                return {"sucesso": False, "mensagem": "Servico de transferencia nao configurado."}
            result = await self.leadbox.transfer_to_department(department=departamento, queue_id=queue_id, user_id=user_id, reason=motivo)
            return {"sucesso": True, "mensagem": f"Transferido para {departamento or queue_id}."}
        except Exception as e:
            return {"sucesso": False, "mensagem": str(e)}

    async def execute(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "consulta_agenda": self.consulta_agenda,
            "agendar": self.agendar,
            "cancelar_agendamento": self.cancelar_agendamento,
            "reagendar": self.reagendar,
            "transferir_departamento": self.transferir_departamento
        }
        handler = handlers.get(function_name)
        if not handler:
            return {"sucesso": False, "mensagem": f"Funcao '{function_name}' nao encontrada."}
        return await handler(**arguments)
```

---

## 5. app/webhooks/whatsapp.py

(Arquivo muito extenso - veja versao completa separada ou no repositorio)
