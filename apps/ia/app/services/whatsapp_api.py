"""
UazapiService - Servico de integracao com UAZAPI para WhatsApp.

Este servico gerencia:
- Envio de mensagens de texto
- Envio de mensagens de midia (imagem, audio, video, documento)
- Marcacao de mensagens como lidas
- Verificacao de status da instancia
- Typing indicators (digitando...)
"""

import asyncio
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Union

import httpx

from app.config import settings

# Configurar logging
logger = logging.getLogger(__name__)


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

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


class SendTextPayload(TypedDict):
    """Payload para envio de texto."""
    phone: str
    message: str


class SendMediaPayload(TypedDict, total=False):
    """Payload para envio de midia."""
    phone: str
    media: str  # URL da midia
    caption: Optional[str]
    type: str  # image, audio, video, document


class ChunkedSendResult(TypedDict):
    """Resultado agregado do envio de mensagem chunked."""
    all_success: bool
    success_count: int
    total_chunks: int
    failed_chunks: List[int]
    results: List[MessageResponse]
    first_error: Optional[str]


# ============================================================================
# UAZAPI SERVICE
# ============================================================================

class UazapiService:
    """
    Servico para integracao com UAZAPI (WhatsApp API).

    Gerencia:
    - Envio de mensagens (texto e midia)
    - Leitura de mensagens
    - Status da instancia
    - Typing indicators

    Exemplo de uso:
        service = UazapiService()
        await service.send_text_message("5511999999999", "Ola!")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0
    ):
        """
        Inicializa o cliente UAZAPI.

        Args:
            base_url: URL base da API UAZAPI (default: settings.uazapi_base_url)
            api_key: API key para autenticacao (default: settings.uazapi_api_key)
            timeout: Timeout para requisicoes em segundos (default: 30)
        """
        self.base_url = (base_url or settings.uazapi_base_url).rstrip("/")
        self.api_key = api_key or settings.uazapi_api_key
        self.timeout = timeout

        if not self.base_url:
            raise ValueError(
                "UAZAPI_BASE_URL e obrigatorio. "
                "Defina a variavel de ambiente ou passe como parametro."
            )

        if not self.api_key:
            raise ValueError(
                "UAZAPI_API_KEY e obrigatorio. "
                "Defina a variavel de ambiente ou passe como parametro."
            )

        # Headers padrao para todas as requisicoes
        # UAZAPI usa header 'token' para autenticacao (nao Bearer)
        self._headers = {
            "token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.info(f"UazapiService inicializado com base_url: {self.base_url}")

    # ========================================================================
    # HTTP CLIENT
    # ========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa uma requisicao HTTP para a UAZAPI.

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

        logger.debug(f"UAZAPI Request: {method} {url}")
        if data:
            logger.debug(f"UAZAPI Payload: {data}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    params=params
                )

                # Log da resposta
                logger.debug(f"UAZAPI Response: {response.status_code}")

                # Levantar excecao para erros HTTP
                response.raise_for_status()

                # Tentar parsear JSON
                try:
                    return response.json()
                except Exception:
                    # Algumas respostas podem nao ser JSON
                    return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"UAZAPI HTTP Error: {e.response.status_code} - {e.response.text}"
                )
                raise

            except httpx.RequestError as e:
                logger.error(f"UAZAPI Request Error: {e}")
                raise

    async def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao GET."""
        return await self._request("GET", endpoint, params=params)

    async def _post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao POST."""
        return await self._request("POST", endpoint, data=data)

    async def _put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa requisicao PUT."""
        return await self._request("PUT", endpoint, data=data)

    # ========================================================================
    # PHONE NUMBER FORMATTING
    # ========================================================================

    def _format_phone(self, phone: str) -> str:
        """
        Formata o numero de telefone para o padrao UAZAPI.

        Remove caracteres especiais e adiciona codigo do pais se necessario.

        Args:
            phone: Numero de telefone (pode conter @s.whatsapp.net, @lid, etc)

        Returns:
            Numero formatado (apenas digitos)
        """
        # Remover sufixos do WhatsApp
        clean = phone.replace("@s.whatsapp.net", "").replace("@lid", "")

        # Remover caracteres nao-numericos
        clean = "".join(filter(str.isdigit, clean))

        # Adicionar codigo do Brasil se necessario
        if len(clean) == 10 or len(clean) == 11:
            clean = f"55{clean}"

        return clean

    # ========================================================================
    # SEND MESSAGES
    # ========================================================================

    async def send_text_message(
        self,
        phone: str,
        text: str,
        delay: Optional[int] = None,
        link_preview: bool = True
    ) -> MessageResponse:
        """
        Envia uma mensagem de texto via WhatsApp com retry para erros transientes.

        Args:
            phone: Numero de telefone do destinatario
            text: Texto da mensagem
            delay: Delay em milissegundos antes de enviar (simula digitacao)
            link_preview: Se deve mostrar preview de links (default: True)

        Returns:
            MessageResponse com status do envio

        Retry Policy:
            - 3 tentativas com backoff 1s, 2s, 4s
            - Apenas para erros transientes: timeout, 500, 502, 503, 504, connection error
            - NÃO faz retry para: 401, 400, 403, 404 (erros permanentes)

        Example:
            response = await service.send_text_message(
                phone="5511999999999",
                text="Ola! Como posso ajudar?"
            )
        """
        MAX_RETRIES = 3
        BACKOFF_DELAYS = [1.0, 2.0, 4.0]
        RETRIABLE_STATUS_CODES = {500, 502, 503, 504, 429}

        formatted_phone = self._format_phone(phone)

        # UAZAPI v2 usa 'number' e 'text' (nao 'phone' e 'message')
        payload: Dict[str, Any] = {
            "number": formatted_phone,
            "text": text,
            "linkPreview": link_preview,
        }

        if delay:
            payload["delay"] = delay

        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                if attempt > 0:
                    logger.info(f"[UAZAPI RETRY] Tentativa {attempt + 1}/{MAX_RETRIES + 1} para {formatted_phone}")

                logger.debug(f"[UAZAPI] Enviando texto para {formatted_phone}")
                logger.debug(f"[UAZAPI] URL: {self.base_url}/send/text")

                response = await self._post("/send/text", payload)

                logger.debug(f"[UAZAPI] Resposta: {response}")

                # Extrair message_id da resposta
                message_id = None
                if isinstance(response, dict):
                    message_id = response.get("key", {}).get("id") or response.get("id")

                logger.info(f"Mensagem enviada com sucesso. ID: {message_id}")

                return {
                    "success": True,
                    "message_id": message_id,
                    "error": None
                }

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_msg = f"HTTP {status_code}: {e.response.text}"
                last_error = error_msg

                # Verificar se é erro retriable
                if status_code in RETRIABLE_STATUS_CODES:
                    if attempt < MAX_RETRIES:
                        delay_seconds = BACKOFF_DELAYS[attempt]
                        logger.warning(
                            f"[UAZAPI RETRY] Erro transiente {status_code} para {formatted_phone}. "
                            f"Aguardando {delay_seconds}s antes de retry..."
                        )
                        await asyncio.sleep(delay_seconds)
                        continue
                    else:
                        logger.error(
                            f"[UAZAPI SEND FAIL] phone={formatted_phone} tentativas={MAX_RETRIES + 1} "
                            f"erro={status_code} (esgotou retries)"
                        )
                else:
                    # Erro permanente (401, 400, 403, 404) - não fazer retry
                    logger.error(
                        f"[UAZAPI SEND FAIL] phone={formatted_phone} erro_permanente={status_code} "
                        f"(sem retry para este tipo de erro)"
                    )
                    return {
                        "success": False,
                        "message_id": None,
                        "error": error_msg
                    }

            except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as e:
                error_msg = f"Connection error: {type(e).__name__}: {str(e)}"
                last_error = error_msg

                if attempt < MAX_RETRIES:
                    delay_seconds = BACKOFF_DELAYS[attempt]
                    logger.warning(
                        f"[UAZAPI RETRY] Erro de conexão para {formatted_phone}. "
                        f"Aguardando {delay_seconds}s antes de retry..."
                    )
                    await asyncio.sleep(delay_seconds)
                    continue
                else:
                    logger.error(
                        f"[UAZAPI SEND FAIL] phone={formatted_phone} tentativas={MAX_RETRIES + 1} "
                        f"erro=connection_error (esgotou retries)"
                    )

            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"[UAZAPI SEND FAIL] phone={formatted_phone} erro_inesperado={error_msg}")
                # Erro desconhecido - não fazer retry
                return {
                    "success": False,
                    "message_id": None,
                    "error": error_msg
                }

        # Se chegou aqui, esgotou todas as tentativas
        return {
            "success": False,
            "message_id": None,
            "error": last_error or "Esgotou tentativas de envio"
        }

    async def send_ai_response(
        self,
        phone: str,
        text: str,
        agent_name: str,
        delay: float = 2.0,
    ) -> ChunkedSendResult:
        """
        Envia resposta da IA com assinatura do agente.

        Cada chunk recebe o prefixo "{agent_name}:\n" para identificar
        que a mensagem é da IA (ex: "Ana:\nOlá, como posso ajudar?").

        Args:
            phone: Numero de telefone do destinatario
            text: Texto completo da resposta da IA
            agent_name: Nome do agente para assinatura (ex: "Ana")
            delay: Delay em segundos entre cada chunk (default: 2.0)

        Returns:
            ChunkedSendResult com status de cada chunk enviado
        """
        # Quebra o texto em chunks
        chunks = self._split_text_for_natural_sending(text)
        results: List[MessageResponse] = []
        failed_chunks: List[int] = []
        first_error: Optional[str] = None

        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(delay)

            # Adiciona assinatura do agente em CADA chunk (negrito no WhatsApp)
            # .title() formata "ANA" -> "Ana"
            signed_chunk = f"*{agent_name.title()}:*\n{chunk}"

            # Enviar typing antes de cada mensagem
            await self.send_typing(phone, duration=1500)
            await asyncio.sleep(1.0)

            # Enviar texto com assinatura
            result = await self.send_text_message(phone, signed_chunk)
            results.append(result)

            if not result["success"]:
                failed_chunks.append(i)
                if first_error is None:
                    first_error = result.get("error")
                logger.warning(
                    f"[UAZAPI AI RESPONSE FAIL] phone={phone} chunk={i + 1}/{len(chunks)} "
                    f"erro={result.get('error')}"
                )

        success_count = len(chunks) - len(failed_chunks)
        all_success = len(failed_chunks) == 0

        if all_success:
            logger.info(f"[UAZAPI AI RESPONSE OK] phone={phone} agent={agent_name} {success_count}/{len(chunks)} chunks")
        else:
            logger.error(
                f"[UAZAPI AI RESPONSE PARTIAL] phone={phone} agent={agent_name} "
                f"{success_count}/{len(chunks)} chunks, falhas: {failed_chunks}"
            )

        return {
            "all_success": all_success,
            "success_count": success_count,
            "total_chunks": len(chunks),
            "failed_chunks": failed_chunks,
            "results": results,
            "first_error": first_error,
        }

    async def send_text_chunked(
        self,
        phone: str,
        text: str,
        delay: float = 2.0,
    ) -> ChunkedSendResult:
        """
        Envia texto em múltiplas mensagens com delay entre elas.
        Simula digitação humana quebrando por parágrafos.

        Args:
            phone: Numero de telefone do destinatario
            text: Texto completo para enviar
            delay: Delay em segundos entre cada chunk (default: 2.0)

        Returns:
            ChunkedSendResult com:
            - all_success: True se TODOS os chunks foram enviados
            - success_count: Número de chunks enviados com sucesso
            - total_chunks: Número total de chunks
            - failed_chunks: Índices dos chunks que falharam
            - results: Lista de MessageResponse para cada chunk
            - first_error: Primeiro erro encontrado (se houver)
        """
        chunks = self._split_text_for_natural_sending(text)
        results: List[MessageResponse] = []
        failed_chunks: List[int] = []
        first_error: Optional[str] = None

        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(delay)

            # Enviar typing antes de cada mensagem
            await self.send_typing(phone, duration=1500)
            await asyncio.sleep(1.0)

            # Enviar texto
            result = await self.send_text_message(phone, chunk)
            results.append(result)

            if not result["success"]:
                failed_chunks.append(i)
                if first_error is None:
                    first_error = result.get("error")
                logger.warning(
                    f"[UAZAPI CHUNK FAIL] phone={phone} chunk={i + 1}/{len(chunks)} "
                    f"erro={result.get('error')}"
                )
                # Continuar tentando os próximos chunks (best effort)

        success_count = len(chunks) - len(failed_chunks)
        all_success = len(failed_chunks) == 0

        if all_success:
            logger.info(f"[UAZAPI SEND OK] phone={phone} {success_count}/{len(chunks)} chunks enviados")
        else:
            logger.error(
                f"[UAZAPI SEND PARTIAL] phone={phone} {success_count}/{len(chunks)} chunks enviados, "
                f"falhas nos chunks: {failed_chunks}"
            )

        return {
            "all_success": all_success,
            "success_count": success_count,
            "total_chunks": len(chunks),
            "failed_chunks": failed_chunks,
            "results": results,
            "first_error": first_error,
        }

    def _split_text_for_natural_sending(
        self,
        text: str,
        max_chunk_size: int = 200,
        min_chunk_size: int = 50
    ) -> List[str]:
        """
        Quebra texto para envio natural em múltiplas mensagens.

        Regras:
        1. Quebra por \\n\\n (parágrafos)
        2. Se chunk > 200 chars, quebra por frases (". ")
        3. Agrupa frases até no máximo 200 chars por chunk
        4. Mínimo 50 chars por chunk (não quebrar demais)

        Args:
            text: Texto para quebrar
            max_chunk_size: Tamanho máximo de cada chunk (default: 200)
            min_chunk_size: Tamanho mínimo de cada chunk (default: 50)

        Returns:
            Lista de chunks de texto
        """
        text = text.strip()
        if not text:
            return []

        # Se texto curto, retorna direto
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []

        # Primeiro, tenta quebrar por parágrafos
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Se parágrafo cabe no limite, adiciona direto
            if len(para) <= max_chunk_size:
                chunks.append(para)
            else:
                # Parágrafo grande, quebra por frases
                chunks.extend(self._split_by_sentences(para, max_chunk_size, min_chunk_size))

        # Se não conseguiu quebrar, retorna texto original
        if not chunks:
            return [text]

        return chunks

    def _split_by_sentences(
        self,
        text: str,
        max_chunk_size: int = 200,
        min_chunk_size: int = 50
    ) -> List[str]:
        """
        Quebra texto por frases, agrupando até max_chunk_size chars.

        Args:
            text: Texto para quebrar
            max_chunk_size: Tamanho máximo de cada chunk (default: 200)
            min_chunk_size: Tamanho mínimo de cada chunk (default: 50)

        Returns:
            Lista de chunks de texto
        """
        # Se texto cabe no limite, retorna direto
        if len(text) <= max_chunk_size:
            return [text]

        # Divide por fim de frase (. ! ?) seguido de espaço
        # Mantém o delimitador no final da frase
        sentences = re.split(r'(?<=[.!?])\s+', text)

        if len(sentences) <= 1:
            # Não conseguiu dividir por frases, tenta por vírgulas
            sentences = re.split(r',\s+', text)
            if len(sentences) <= 1:
                # Força quebra por tamanho
                return self._force_split(text, max_chunk_size)
            # Adiciona vírgula de volta (exceto última)
            sentences = [s + ',' if i < len(sentences) - 1 else s for i, s in enumerate(sentences)]

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Se adicionar essa frase estoura o limite
            test_chunk = f"{current_chunk} {sentence}".strip() if current_chunk else sentence

            if len(test_chunk) <= max_chunk_size:
                current_chunk = test_chunk
            else:
                # Salva chunk atual se tiver tamanho mínimo
                if current_chunk and len(current_chunk) >= min_chunk_size:
                    chunks.append(current_chunk)
                    current_chunk = sentence
                elif current_chunk:
                    # Chunk atual muito pequeno, tenta juntar mesmo assim
                    if len(test_chunk) <= max_chunk_size * 1.2:  # 20% tolerância
                        current_chunk = test_chunk
                    else:
                        chunks.append(current_chunk)
                        current_chunk = sentence
                else:
                    current_chunk = sentence

        # Adiciona último chunk
        if current_chunk:
            # Se último chunk muito pequeno, junta com anterior
            if len(current_chunk) < min_chunk_size and chunks:
                last_chunk = chunks.pop()
                combined = f"{last_chunk} {current_chunk}"
                if len(combined) <= max_chunk_size * 1.3:  # 30% tolerância para último
                    chunks.append(combined)
                else:
                    chunks.append(last_chunk)
                    chunks.append(current_chunk)
            else:
                chunks.append(current_chunk)

        return chunks

    def _force_split(
        self,
        text: str,
        max_chunk_size: int = 300
    ) -> List[str]:
        """
        Força quebra de texto por tamanho quando não há pontuação.

        Tenta quebrar em espaços para não cortar palavras.

        Args:
            text: Texto para quebrar
            max_chunk_size: Tamanho máximo de cada chunk

        Returns:
            Lista de chunks de texto
        """
        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_chunk_size:
                chunks.append(remaining)
                break

            # Procura último espaço dentro do limite
            chunk = remaining[:max_chunk_size]
            last_space = chunk.rfind(" ")

            if last_space > 0:
                chunks.append(remaining[:last_space].strip())
                remaining = remaining[last_space:].strip()
            else:
                # Sem espaço, força corte
                chunks.append(chunk)
                remaining = remaining[max_chunk_size:].strip()

        return chunks

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        caption: Optional[str] = None,
        media_type: Union[MediaType, str] = MediaType.IMAGE,
        filename: Optional[str] = None
    ) -> MessageResponse:
        """
        Envia uma mensagem de midia via WhatsApp.

        Args:
            phone: Numero de telefone do destinatario
            media_url: URL da midia (imagem, audio, video, documento)
            caption: Legenda da midia (opcional, nao suportado para audio)
            media_type: Tipo da midia (image, audio, video, document, sticker)
            filename: Nome do arquivo (para documentos)

        Returns:
            MessageResponse com status do envio

        Example:
            response = await service.send_media_message(
                phone="5511999999999",
                media_url="https://example.com/image.jpg",
                caption="Confira esta imagem!",
                media_type=MediaType.IMAGE
            )
        """
        try:
            formatted_phone = self._format_phone(phone)

            # Converter enum para string se necessario
            if isinstance(media_type, MediaType):
                media_type_str = media_type.value
            else:
                media_type_str = str(media_type).lower()

            # UAZAPI v2 usa endpoint unico /send/media com campo 'type'
            # Tipos suportados: image, video, document, audio, myaudio, ptt, ptv, sticker
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "type": media_type_str,
                "file": media_url,
            }

            # Caption vai no campo 'text' (nao 'caption')
            if caption and media_type_str not in ["audio", "ptt"]:
                payload["text"] = caption

            # Filename para documentos usa 'docName'
            if filename and media_type_str == "document":
                payload["docName"] = filename

            logger.info(
                f"Enviando {media_type_str} para {formatted_phone[:8]}***"
            )

            response = await self._post("/send/media", payload)

            # Extrair message_id
            message_id = None
            if isinstance(response, dict):
                message_id = response.get("key", {}).get("id") or response.get("id")

            logger.info(f"Midia enviada com sucesso. ID: {message_id}")

            return {
                "success": True,
                "message_id": message_id,
                "error": None
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Erro ao enviar midia: {error_msg}")
            return {
                "success": False,
                "message_id": None,
                "error": error_msg
            }

        except Exception as e:
            logger.error(f"Erro ao enviar midia: {e}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }

    async def send_audio_message(
        self,
        phone: str,
        audio_url: str,
        ptt: bool = True
    ) -> MessageResponse:
        """
        Envia uma mensagem de audio via WhatsApp.

        Args:
            phone: Numero de telefone do destinatario
            audio_url: URL do arquivo de audio
            ptt: Se True, envia como mensagem de voz (push-to-talk)

        Returns:
            MessageResponse com status do envio
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /send/media com type 'ptt' para mensagem de voz
            # ou 'audio' para audio comum
            payload = {
                "number": formatted_phone,
                "type": "ptt" if ptt else "audio",
                "file": audio_url,
            }

            logger.info(f"Enviando audio para {formatted_phone[:8]}***")

            response = await self._post("/send/media", payload)

            message_id = None
            if isinstance(response, dict):
                message_id = response.get("key", {}).get("id") or response.get("id")

            return {
                "success": True,
                "message_id": message_id,
                "error": None
            }

        except Exception as e:
            logger.error(f"Erro ao enviar audio: {e}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }

    async def download_media(
        self,
        message_id: str,
        return_base64: bool = True,
        generate_mp3: bool = True,
        return_link: bool = False,
    ) -> Dict[str, Any]:
        """
        Baixa midia de uma mensagem.

        Args:
            message_id: ID da mensagem com midia
            return_base64: Se True, retorna conteudo em base64
            generate_mp3: Se True, converte audio para MP3
            return_link: Se True, retorna URL publica

        Returns:
            Dict com base64Data, mimetype, fileURL
        """
        try:
            payload = {
                "id": message_id,
                "return_base64": return_base64,
                "generate_mp3": generate_mp3,
                "return_link": return_link,
            }

            logger.info(f"Baixando midia: {message_id[:20]}...")

            response = await self._post("/message/download", payload)

            logger.info(f"Midia baixada com sucesso")

            return {
                "success": True,
                "base64Data": response.get("base64Data"),
                "mimetype": response.get("mimetype"),
                "fileURL": response.get("fileURL"),
            }

        except Exception as e:
            logger.error(f"Erro ao baixar midia: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def send_buttons_message(
        self,
        phone: str,
        text: str,
        buttons: List[Dict[str, str]],
        title: Optional[str] = None,
        footer: Optional[str] = None
    ) -> MessageResponse:
        """
        Envia uma mensagem com botoes via WhatsApp.

        Args:
            phone: Numero de telefone do destinatario
            text: Texto principal da mensagem
            buttons: Lista de botoes [{"id": "btn1", "text": "Opcao 1"}, ...]
            title: Titulo da mensagem (opcional)
            footer: Rodape da mensagem (opcional)

        Returns:
            MessageResponse com status do envio

        Note:
            WhatsApp Business API limita a 3 botoes por mensagem.
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /send/interactive para mensagens interativas
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "message": text,
                "buttons": buttons[:3],  # Limitar a 3 botoes
            }

            if title:
                payload["title"] = title

            if footer:
                payload["footer"] = footer

            logger.info(f"Enviando botoes para {formatted_phone[:8]}***")

            response = await self._post("/send/interactive", payload)

            message_id = None
            if isinstance(response, dict):
                message_id = response.get("key", {}).get("id") or response.get("id")

            return {
                "success": True,
                "message_id": message_id,
                "error": None
            }

        except Exception as e:
            logger.error(f"Erro ao enviar botoes: {e}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }

    async def send_list_message(
        self,
        phone: str,
        text: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None
    ) -> MessageResponse:
        """
        Envia uma mensagem com lista de opcoes via WhatsApp.

        Args:
            phone: Numero de telefone do destinatario
            text: Texto principal da mensagem
            button_text: Texto do botao que abre a lista
            sections: Lista de secoes com opcoes
            title: Titulo da mensagem (opcional)
            footer: Rodape da mensagem (opcional)

        Returns:
            MessageResponse com status do envio

        Example:
            sections = [
                {
                    "title": "Produtos",
                    "rows": [
                        {"id": "prod1", "title": "Produto 1", "description": "Desc 1"},
                        {"id": "prod2", "title": "Produto 2", "description": "Desc 2"}
                    ]
                }
            ]
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /send/interactive para mensagens interativas
            payload: Dict[str, Any] = {
                "number": formatted_phone,
                "message": text,
                "buttonText": button_text,
                "sections": sections,
            }

            if title:
                payload["title"] = title

            if footer:
                payload["footer"] = footer

            logger.info(f"Enviando lista para {formatted_phone[:8]}***")

            response = await self._post("/send/interactive", payload)

            message_id = None
            if isinstance(response, dict):
                message_id = response.get("key", {}).get("id") or response.get("id")

            return {
                "success": True,
                "message_id": message_id,
                "error": None
            }

        except Exception as e:
            logger.error(f"Erro ao enviar lista: {e}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e)
            }

    # ========================================================================
    # READ RECEIPTS
    # ========================================================================

    async def mark_as_read(
        self,
        phone: str,
        message_id: Optional[str] = None
    ) -> bool:
        """
        Marca mensagens como lidas.

        Args:
            phone: Numero de telefone ou remotejid do remetente
            message_id: ID da mensagem especifica (opcional)

        Returns:
            True se marcado com sucesso, False caso contrario
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /chat/read com 'number' e 'read'
            # number deve incluir @s.whatsapp.net
            chat_id = formatted_phone
            if not chat_id.endswith("@s.whatsapp.net") and not chat_id.endswith("@g.us"):
                chat_id = f"{formatted_phone}@s.whatsapp.net"

            payload: Dict[str, Any] = {
                "number": chat_id,
                "read": True,
            }

            logger.debug(f"Marcando como lido: {formatted_phone[:8]}***")

            await self._post("/chat/read", payload)

            logger.debug("Mensagem marcada como lida")
            return True

        except Exception as e:
            logger.error(f"Erro ao marcar como lido: {e}")
            return False

    # ========================================================================
    # TYPING INDICATOR
    # ========================================================================

    async def send_typing(
        self,
        phone: str,
        duration: int = 3000
    ) -> bool:
        """
        Envia indicador de digitacao (typing...).

        Args:
            phone: Numero de telefone do destinatario
            duration: Duracao em milissegundos (default: 3000)

        Returns:
            True se enviado com sucesso, False caso contrario
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /message/presence com 'presence' e 'delay'
            payload = {
                "number": formatted_phone,
                "presence": "composing",
                "delay": duration,
            }

            logger.debug(f"[UAZAPI] Enviando typing para {formatted_phone}")
            logger.debug(f"[UAZAPI] URL: {self.base_url}/message/presence")
            logger.debug(f"[UAZAPI] Payload: {payload}")

            response = await self._post("/message/presence", payload)
            logger.debug(f"[UAZAPI] Typing resposta: {response}")

            return True

        except Exception as e:
            logger.error(f"Erro ao enviar typing: {e}")
            return False

    async def send_presence(
        self,
        phone: str,
        presence: str = "composing"
    ) -> bool:
        """
        Envia indicador de presenca.

        Args:
            phone: Numero de telefone do destinatario
            presence: Tipo de presenca (composing, recording, available, unavailable)

        Returns:
            True se enviado com sucesso, False caso contrario
        """
        try:
            formatted_phone = self._format_phone(phone)

            # UAZAPI v2 usa /message/presence
            # Tipos validos: composing, recording, paused
            payload = {
                "number": formatted_phone,
                "presence": presence,
            }

            await self._post("/message/presence", payload)

            return True

        except Exception as e:
            logger.error(f"Erro ao enviar presenca: {e}")
            return False

    # ========================================================================
    # INSTANCE STATUS
    # ========================================================================

    async def get_instance_status(self) -> InstanceStatus:
        """
        Obtem o status da instancia UAZAPI.

        Returns:
            InstanceStatus com informacoes da conexao

        Example:
            status = await service.get_instance_status()
            if status["connected"]:
                print(f"Conectado: {status['phone_number']}")
        """
        try:
            logger.debug("Obtendo status da instancia")

            response = await self._get("/instance/status")

            # Parsear resposta
            connected = response.get("connected", False) or response.get("status") == "open"
            phone_number = response.get("phoneNumber") or response.get("phone")
            instance_id = response.get("instanceId") or response.get("instance", {}).get("id", "")
            status = response.get("status", "unknown")
            battery = response.get("battery")
            plugged = response.get("plugged")

            result: InstanceStatus = {
                "connected": connected,
                "phone_number": phone_number,
                "instance_id": instance_id,
                "status": status,
                "battery": battery,
                "plugged": plugged,
            }

            logger.info(f"Status da instancia: connected={connected}, status={status}")

            return result

        except Exception as e:
            logger.error(f"Erro ao obter status: {e}")
            return {
                "connected": False,
                "phone_number": None,
                "instance_id": "",
                "status": "error",
                "battery": None,
                "plugged": None,
            }

    async def is_connected(self) -> bool:
        """
        Verifica se a instancia esta conectada ao WhatsApp.

        Returns:
            True se conectado, False caso contrario
        """
        status = await self.get_instance_status()
        return status["connected"]

    # ========================================================================
    # QR CODE
    # ========================================================================

    async def get_qr_code(self) -> Optional[str]:
        """
        Obtem o QR code para conectar ao WhatsApp.

        Returns:
            QR code como string base64 ou None se ja conectado
        """
        try:
            response = await self._get("/instance/qrcode")

            qr_code = response.get("qrcode") or response.get("base64")

            if qr_code:
                logger.info("QR code obtido com sucesso")
                return qr_code

            logger.debug("QR code nao disponivel (possivelmente ja conectado)")
            return None

        except Exception as e:
            logger.error(f"Erro ao obter QR code: {e}")
            return None

    # ========================================================================
    # CONTACT INFO
    # ========================================================================

    async def get_contact_info(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Obtem informacoes de um contato.

        Args:
            phone: Numero de telefone do contato

        Returns:
            Informacoes do contato ou None
        """
        try:
            formatted_phone = self._format_phone(phone)

            response = await self._get(
                "/contact/info",
                params={"phone": formatted_phone}
            )

            return response

        except Exception as e:
            logger.error(f"Erro ao obter info do contato: {e}")
            return None

    async def check_phone_exists(self, phone: str) -> bool:
        """
        Verifica se um numero de telefone tem WhatsApp.

        Args:
            phone: Numero de telefone para verificar

        Returns:
            True se o numero tem WhatsApp, False caso contrario
        """
        try:
            formatted_phone = self._format_phone(phone)

            response = await self._post(
                "/contact/check",
                {"phone": formatted_phone}
            )

            exists = response.get("exists", False) or response.get("numberExists", False)

            logger.debug(f"Numero {formatted_phone[:8]}*** existe: {exists}")

            return exists

        except Exception as e:
            logger.error(f"Erro ao verificar numero: {e}")
            return False

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self) -> bool:
        """
        Verifica se o servico UAZAPI esta acessivel.

        Returns:
            True se acessivel, False caso contrario
        """
        try:
            status = await self.get_instance_status()
            return status["status"] != "error"

        except Exception as e:
            logger.error(f"Health check falhou: {e}")
            return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_uazapi_service: Optional[UazapiService] = None


def get_uazapi_service() -> UazapiService:
    """
    Retorna instancia singleton do UazapiService.

    Returns:
        Instancia do UazapiService
    """
    global _uazapi_service

    if _uazapi_service is None:
        _uazapi_service = UazapiService()

    return _uazapi_service


async def close_uazapi_service() -> None:
    """
    Fecha a instancia singleton do UazapiService.

    Util para cleanup em shutdown da aplicacao.
    """
    global _uazapi_service

    if _uazapi_service is not None:
        logger.info("Fechando UazapiService")
        _uazapi_service = None


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def send_text_message(
    phone: str,
    text: str,
    delay: Optional[int] = None
) -> MessageResponse:
    """Wrapper para send_text_message."""
    return await get_uazapi_service().send_text_message(phone, text, delay)


async def send_media_message(
    phone: str,
    media_url: str,
    caption: Optional[str] = None,
    media_type: Union[MediaType, str] = MediaType.IMAGE
) -> MessageResponse:
    """Wrapper para send_media_message."""
    return await get_uazapi_service().send_media_message(
        phone, media_url, caption, media_type
    )


async def mark_as_read(phone: str, message_id: Optional[str] = None) -> bool:
    """Wrapper para mark_as_read."""
    return await get_uazapi_service().mark_as_read(phone, message_id)


async def get_instance_status() -> InstanceStatus:
    """Wrapper para get_instance_status."""
    return await get_uazapi_service().get_instance_status()


async def send_typing(phone: str, duration: int = 3000) -> bool:
    """Wrapper para send_typing."""
    return await get_uazapi_service().send_typing(phone, duration)


async def is_connected() -> bool:
    """Wrapper para is_connected."""
    return await get_uazapi_service().is_connected()
