"""
Gemini Service - Integração com Google Generative AI (Gemini).

Funcionalidades:
- Inicialização do modelo com function declarations (tools)
- Registro dinâmico de handlers para tools
- Envio de mensagens com histórico de conversação
- Processamento de respostas e function calls
- Loop automático de execução de tools
"""

import asyncio
import inspect
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from google.generativeai.types import (
    ContentType,
    GenerationConfig,
    HarmBlockThreshold,
    HarmCategory,
)

from app.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER: Resumir response de tool para não estourar contexto
# =============================================================================

def _summarize_tool_response(response: dict, max_chars: int = 2000) -> dict:
    """
    Resume response de tool para não estourar contexto do Gemini.

    Args:
        response: Dict retornado pela tool
        max_chars: Tamanho máximo em caracteres

    Returns:
        Response resumido se necessário
    """
    try:
        serialized = json.dumps(response, ensure_ascii=False, default=str)
        if len(serialized) <= max_chars:
            return response

        # Manter campos essenciais e truncar o resto
        summary = {}
        for key in ["sucesso", "encontrou", "mensagem", "cliente", "total_equipamentos"]:
            if key in response:
                summary[key] = response[key]

        # Incluir financeiro resumido
        if "financeiro" in response:
            fin = response["financeiro"]
            summary["financeiro"] = {
                "cobrancas_atrasadas": fin.get("cobrancas_atrasadas"),
                "valor_atrasado": fin.get("valor_atrasado"),
                "total_devedor": fin.get("total_devedor"),
            }

        # Incluir contratos resumidos (máx 3)
        if "contratos" in response:
            summary["contratos"] = [
                {
                    "numero": c.get("numero"),
                    "meses_restantes": c.get("meses_restantes"),
                    "equipamentos": c.get("equipamentos", [])[:2],  # Máx 2 equipamentos
                }
                for c in response["contratos"][:3]
            ]

        return summary
    except Exception as e:
        logger.warning(f"Erro ao resumir tool response: {e}")
        return {"resumo": "Dados consultados com sucesso"}


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
            model_name: Nome do modelo (default: gemini-2.0-flash)
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
        audio_data: Optional[Dict[str, Any]] = None,
        image_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Envia mensagens para o Gemini com histórico de conversação.

        Args:
            messages: Lista de mensagens no formato do histórico
            system_prompt: Prompt de sistema opcional (sobrescreve o da inicialização)
            audio_data: Dados de audio para processamento multimodal (base64, mimetype)
            image_data: Dados de imagem para processamento multimodal (base64, mimetype)

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

        # Se tiver áudio, cria conteúdo multimodal
        if audio_data and audio_data.get("base64"):
            user_text = self._extract_content(last_message)
            user_content = [
                {
                    "inline_data": {
                        "mime_type": audio_data.get("mimetype", "audio/mp3"),
                        "data": audio_data["base64"],
                    }
                },
                {"text": f"O usuário enviou um áudio. Transcreva e responda. Contexto: {user_text}" if user_text else "O usuário enviou um áudio. Transcreva e responda de forma natural."},
            ]
            logger.info("Processando mensagem com áudio multimodal")
        # Se tiver imagem ou documento, cria conteúdo multimodal
        elif image_data and image_data.get("base64"):
            user_text = self._extract_content(last_message)
            mime = image_data.get("mimetype", "image/jpeg")
            # Determinar se é documento ou imagem
            if mime.startswith("application/") or mime == "application/pdf":
                base_prompt = "O cliente enviou este documento. Analise o conteúdo e responda apropriadamente."
            else:
                base_prompt = "O cliente enviou esta imagem. Analise o conteúdo e responda apropriadamente."
            prompt_text = f"{base_prompt} Contexto: {user_text}" if user_text else base_prompt.replace("responda apropriadamente.", "descreva o que você vê e responda apropriadamente.")
            user_content = [
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": image_data["base64"],
                    }
                },
                {"text": prompt_text},
            ]
            media_type_label = "documento" if mime.startswith("application/") else "imagem"
            logger.info(f"Processando mensagem com {media_type_label} multimodal")
        else:
            user_content = self._extract_content(last_message)

        logger.info(f"[GEMINI SEND] history_length={len(history)}, user_content={str(user_content)[:150]}")

        # =================================================================
        # RETRY COM BACKOFF EXPONENCIAL PARA ERROS TRANSIENTES
        # =================================================================
        # Retry APENAS para:
        #   - 429 (rate limit)
        #   - 500, 502, 503, 504 (server error)
        #   - Timeout/ConnectionError
        # NÃO retry para:
        #   - 400 (bad request)
        #   - 401/403 (auth)
        #   - 404 (not found)
        # =================================================================
        MAX_RETRIES = 3
        BACKOFF_DELAYS = [2.0, 4.0, 8.0]  # Exponencial: 2s, 4s, 8s
        GLOBAL_TIMEOUT = 60.0  # Timeout total para não ficar preso

        start_time = time.time()
        last_error = None
        last_error_type = None

        for attempt in range(MAX_RETRIES + 1):
            # Verifica timeout global
            elapsed = time.time() - start_time
            if elapsed > GLOBAL_TIMEOUT:
                logger.error(
                    "[GEMINI RETRY] Timeout global atingido",
                    extra={
                        "elapsed_seconds": elapsed,
                        "max_timeout": GLOBAL_TIMEOUT,
                        "attempts": attempt,
                    },
                )
                return {
                    "text": "",
                    "function_calls": [],
                    "usage": {},
                    "error": True,
                    "error_type": "timeout_global",
                    "error_message": f"Timeout global após {elapsed:.1f}s",
                    "attempts": attempt,
                }

            try:
                logger.debug(f"[DEBUG 5/6] GEMINI - Enviando mensagem (tentativa {attempt + 1}/{MAX_RETRIES + 1})...")
                logger.debug(f"[DEBUG 5/6] GEMINI - Model: {self._model_name}")
                logger.debug(f"[DEBUG 5/6] GEMINI - Histórico: {len(history)} mensagens")
                logger.debug(f"[DEBUG 5/6] GEMINI - Conteúdo usuário: {str(user_content)[:150]}...")

                # Envia mensagem
                response = await chat.send_message_async(user_content)

                logger.debug(f"[DEBUG 5/6] GEMINI - Resposta recebida!")

                # Processa resposta
                result = self._process_response(response)

                logger.debug(f"[DEBUG 5/6] GEMINI - Texto processado: {result.get('text', '')[:200]}...")
                logger.debug(f"[DEBUG 5/6] GEMINI - Function calls: {len(result.get('function_calls', []))}")

                # Retry se resposta vazia (sem texto e sem function calls)
                if not result.get('text') and not result.get('function_calls'):
                    if attempt < MAX_RETRIES:
                        logger.warning(f"[GEMINI EMPTY] Resposta vazia na tentativa {attempt + 1}, fazendo retry...")
                        await asyncio.sleep(BACKOFF_DELAYS[attempt] if attempt < len(BACKOFF_DELAYS) else 2.0)
                        continue
                    else:
                        logger.warning(f"[GEMINI EMPTY] Resposta vazia após {MAX_RETRIES + 1} tentativas")

                # Se houver function calls, executa e continua
                if result["function_calls"]:
                    result = await self._handle_function_calls(chat, result["function_calls"])

                # Log de sucesso (com info de retry se aplicável)
                if attempt > 0:
                    logger.info(
                        f"[GEMINI RETRY] Sucesso na tentativa {attempt + 1}/{MAX_RETRIES + 1}",
                        extra={
                            "attempt": attempt + 1,
                            "total_attempts": MAX_RETRIES + 1,
                            "text_length": len(result.get("text", "")),
                        },
                    )
                else:
                    logger.info(
                        "Resposta recebida do Gemini",
                        extra={
                            "text_length": len(result.get("text", "")),
                            "function_calls_count": len(result.get("function_calls", [])),
                        },
                    )

                # Sucesso - retorna sem flag de erro
                result["error"] = False
                return result

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Determinar tipo de erro e se é retriable
                is_retriable = False
                error_type = "unknown"

                # Rate limit (429)
                if isinstance(e, google_exceptions.ResourceExhausted) or "429" in str(e) or "rate" in error_str:
                    is_retriable = True
                    error_type = "rate_limit_429"
                # Server errors (5xx)
                elif isinstance(e, google_exceptions.ServiceUnavailable) or "503" in str(e):
                    is_retriable = True
                    error_type = "service_unavailable_503"
                elif isinstance(e, google_exceptions.InternalServerError) or "500" in str(e):
                    is_retriable = True
                    error_type = "internal_error_500"
                elif "502" in str(e) or "504" in str(e):
                    is_retriable = True
                    error_type = f"server_error_{str(e)[:3]}"
                # Timeout
                elif isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in error_str:
                    is_retriable = True
                    error_type = "timeout"
                # Connection errors
                elif "connection" in error_str or isinstance(e, (ConnectionError, OSError)):
                    is_retriable = True
                    error_type = "connection_error"
                # Deadline exceeded
                elif isinstance(e, google_exceptions.DeadlineExceeded) or "deadline" in error_str:
                    is_retriable = True
                    error_type = "deadline_exceeded"
                # Bad request, auth, not found - NÃO retry
                elif isinstance(e, google_exceptions.InvalidArgument) or "400" in str(e):
                    error_type = "bad_request_400"
                elif isinstance(e, (google_exceptions.Unauthenticated, google_exceptions.PermissionDenied)):
                    error_type = "auth_error"
                elif isinstance(e, google_exceptions.NotFound) or "404" in str(e):
                    error_type = "not_found_404"

                last_error_type = error_type

                logger.warning(
                    f"[GEMINI RETRY] Erro na tentativa {attempt + 1}/{MAX_RETRIES + 1}",
                    extra={
                        "attempt": attempt + 1,
                        "error_type": error_type,
                        "is_retriable": is_retriable,
                        "error": str(e)[:200],
                    },
                )

                # Se não é retriable, falha imediatamente
                if not is_retriable:
                    logger.error(
                        f"[GEMINI RETRY] Erro NÃO retriable - abortando",
                        extra={"error_type": error_type, "error": str(e)},
                    )
                    return {
                        "text": "",
                        "function_calls": [],
                        "usage": {},
                        "error": True,
                        "error_type": error_type,
                        "error_message": str(e)[:500],
                        "attempts": attempt + 1,
                    }

                # Se ainda tem tentativas, espera e tenta novamente
                if attempt < MAX_RETRIES:
                    wait_time = BACKOFF_DELAYS[attempt]
                    logger.info(
                        f"[GEMINI RETRY] Aguardando {wait_time}s antes da tentativa {attempt + 2}...",
                        extra={
                            "wait_seconds": wait_time,
                            "next_attempt": attempt + 2,
                            "error_type": error_type,
                        },
                    )
                    await asyncio.sleep(wait_time)

        # Todas as tentativas falharam
        logger.error(
            f"[GEMINI RETRY] TODAS as {MAX_RETRIES + 1} tentativas falharam!",
            extra={
                "total_attempts": MAX_RETRIES + 1,
                "last_error_type": last_error_type,
                "last_error": str(last_error)[:200] if last_error else None,
            },
        )

        return {
            "text": "",
            "function_calls": [],
            "usage": {},
            "error": True,
            "error_type": last_error_type or "max_retries_exceeded",
            "error_message": str(last_error)[:500] if last_error else "Max retries exceeded",
            "attempts": MAX_RETRIES + 1,
        }

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
            # Log detalhado para debug
            logger.warning(f"[DEBUG] response.candidates: {response.candidates}")
            if hasattr(response, 'prompt_feedback'):
                logger.warning(f"[DEBUG] prompt_feedback: {response.prompt_feedback}")
            return result

        try:
            candidate = response.candidates[0]
        except (IndexError, TypeError) as e:
            logger.warning(f"Erro ao acessar candidato: {e}")
            return result

        # Log detalhado do candidato
        logger.debug(f"[DEBUG] candidate.finish_reason: {getattr(candidate, 'finish_reason', 'N/A')}")
        if hasattr(candidate, 'safety_ratings'):
            logger.debug(f"[DEBUG] safety_ratings: {candidate.safety_ratings}")

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
        else:
            # Log quando não há conteúdo
            logger.warning(f"[DEBUG] Candidato sem content/parts! finish_reason={getattr(candidate, 'finish_reason', 'N/A')}")
            logger.warning(f"[DEBUG] candidate.content: {getattr(candidate, 'content', 'N/A')}")

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
        # =================================================================
        # TIMEOUTS PARA EVITAR TRAVAMENTO
        # =================================================================
        TOOL_TIMEOUT_SECONDS = 15.0   # Timeout individual por tool call
        LOOP_TIMEOUT_SECONDS = 45.0   # Timeout global do loop inteiro

        all_function_calls = list(function_calls)
        tool_interactions = []  # Captura function_call + function_response para histórico
        iteration = 0
        loop_start_time = time.time()

        while function_calls and iteration < max_iterations:
            iteration += 1

            # =============================================================
            # CHECK TIMEOUT GLOBAL DO LOOP
            # =============================================================
            loop_elapsed = time.time() - loop_start_time
            if loop_elapsed > LOOP_TIMEOUT_SECONDS:
                logger.error(
                    f"[TOOL LOOP TIMEOUT] Loop excedeu {LOOP_TIMEOUT_SECONDS}s após {iteration} iterações",
                    extra={
                        "elapsed_seconds": round(loop_elapsed, 2),
                        "iterations": iteration,
                        "pending_tools": len(function_calls),
                    },
                )
                # Retorna o que tem até agora com flag de timeout
                result = {
                    "text": "Desculpe, algumas operações demoraram mais que o esperado. Pode repetir sua solicitação?",
                    "function_calls": all_function_calls,
                    "tool_interactions": tool_interactions,
                    "usage": {},
                    "partial_timeout": True,
                }
                return result

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

                # =============================================================
                # EXECUÇÃO COM TIMEOUT INDIVIDUAL
                # =============================================================
                tool_start_time = time.time()
                logger.info(
                    f"[TOOL START] {name}",
                    extra={"tool": name, "args_keys": list(args.keys())},
                )

                try:
                    # Executa handler (sync ou async) COM TIMEOUT
                    if callable(handler):
                        if inspect.iscoroutinefunction(handler):
                            # Async handler com timeout
                            result = await asyncio.wait_for(
                                handler(**args),
                                timeout=TOOL_TIMEOUT_SECONDS
                            )
                        else:
                            # Sync handler - executa em thread com timeout
                            loop = asyncio.get_event_loop()
                            result = await asyncio.wait_for(
                                loop.run_in_executor(None, lambda: handler(**args)),
                                timeout=TOOL_TIMEOUT_SECONDS
                            )

                        # Converte resultado para dict se necessário
                        if not isinstance(result, dict):
                            result = {"result": result}

                        tool_duration = time.time() - tool_start_time
                        function_responses.append({
                            "name": name,
                            "response": result,
                        })

                        # Determina status para log
                        status = "sucesso" if result.get("sucesso") or result.get("success") or "error" not in result else "falha"
                        logger.info(
                            f"[TOOL END] {name} duration={tool_duration:.2f}s result={status}",
                            extra={
                                "tool": name,
                                "duration_seconds": round(tool_duration, 2),
                                "status": status,
                                "result_keys": list(result.keys()),
                            },
                        )

                except asyncio.TimeoutError:
                    tool_duration = time.time() - tool_start_time
                    logger.error(
                        f"[TOOL TIMEOUT] {name} excedeu {TOOL_TIMEOUT_SECONDS}s",
                        extra={
                            "tool": name,
                            "timeout_seconds": TOOL_TIMEOUT_SECONDS,
                            "duration_seconds": round(tool_duration, 2),
                            "args_keys": list(args.keys()),
                        },
                    )
                    function_responses.append({
                        "name": name,
                        "response": {
                            "error": f"Tool '{name}' excedeu timeout de {TOOL_TIMEOUT_SECONDS}s",
                            "timeout": True,
                        },
                    })

                except Exception as e:
                    tool_duration = time.time() - tool_start_time
                    logger.error(
                        f"[TOOL ERROR] {name} duration={tool_duration:.2f}s error={str(e)[:100]}",
                        extra={
                            "tool": name,
                            "duration_seconds": round(tool_duration, 2),
                            "error": str(e),
                            "args_keys": list(args.keys()),
                        },
                        exc_info=True,
                    )
                    function_responses.append({
                        "name": name,
                        "response": {"error": str(e)},
                    })

            # Captura tool_interactions para histórico (ANTES de enviar ao Gemini)
            for i, fr in enumerate(function_responses):
                fc_original = function_calls[i] if i < len(function_calls) else {"name": fr["name"], "args": {}}
                tool_interactions.append({
                    "function_call": {
                        "name": fc_original.get("name", fr["name"]),
                        "args": fc_original.get("args", {}),
                    },
                    "function_response": {
                        "name": fr["name"],
                        "response": _summarize_tool_response(fr["response"]) if isinstance(fr["response"], dict) else fr["response"],
                    },
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

        # Log do tempo total do loop
        total_loop_time = time.time() - loop_start_time
        logger.info(
            f"[TOOL LOOP END] {iteration} iterações em {total_loop_time:.2f}s",
            extra={
                "iterations": iteration,
                "total_duration_seconds": round(total_loop_time, 2),
                "total_tools_executed": len(all_function_calls),
            },
        )

        # Retorna resultado final com todas as function calls e tool_interactions
        result["function_calls"] = all_function_calls
        result["tool_interactions"] = tool_interactions
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
            # ou (function_call/function_response)
            {"role": "model", "parts": [{"function_call": {"name": "...", "args": {...}}}]},
            {"role": "function", "parts": [{"function_response": {"name": "...", "response": {...}}}]},
        ]

        Args:
            messages: Lista de mensagens do histórico

        Returns:
            Lista formatada para o Gemini
        """
        from google.generativeai.protos import Content, Part, FunctionCall, FunctionResponse
        from google.protobuf.struct_pb2 import Struct

        formatted = []

        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])

            # Normaliza role: "assistant" -> "model"
            if role == "assistant":
                role = "model"

            # Verifica se é mensagem de function_call (role=model com function_call)
            if parts and isinstance(parts[0], dict) and "function_call" in parts[0]:
                try:
                    fc = parts[0]["function_call"]
                    args_struct = Struct()
                    args_struct.update(fc.get("args", {}))
                    formatted.append(Content(
                        role="model",
                        parts=[Part(function_call=FunctionCall(name=fc["name"], args=args_struct))]
                    ))
                    continue
                except Exception as e:
                    logger.warning(f"Erro ao formatar function_call no histórico: {e}")
                    # Fallback: pula esta mensagem
                    continue

            # Verifica se é mensagem de function_response (role=function)
            if role == "function" and parts and isinstance(parts[0], dict) and "function_response" in parts[0]:
                try:
                    fr = parts[0]["function_response"]
                    response_data = fr.get("response", {})
                    # Garante que response_data é dict
                    if not isinstance(response_data, dict):
                        response_data = {"result": str(response_data)}
                    formatted.append(Content(
                        role="function",
                        parts=[Part(function_response=FunctionResponse(name=fr["name"], response=response_data))]
                    ))
                    continue
                except Exception as e:
                    logger.warning(f"Erro ao formatar function_response no histórico: {e}")
                    # Fallback: pula esta mensagem
                    continue

            # Texto normal (existente)
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
