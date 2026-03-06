# apps/ia/app/integrations/uazapi/client.py
"""
UazapiClient - Cliente HTTP para a API UAZAPI (WhatsApp).

Refatorado de app/services/whatsapp_api.py com:
- Estrutura mais limpa
- Tipos tipados
- Separação de responsabilidades

Uso:
    client = UazapiClient(base_url="https://...", api_key="...")
    result = await client.send_text_message("5511999999999", "Olá!")
"""

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional, Union

import httpx
import structlog

from .types import (
    DEFAULT_TIMEOUT,
    MAX_CHUNK_SIZE,
    MAX_RETRIES,
    RETRY_DELAY_S,
    RETRYABLE_STATUS_CODES,
    ChunkedSendResult,
    InstanceStatus,
    MediaType,
    MessageResponse,
    PresenceType,
)

logger = structlog.get_logger(__name__)


class UazapiClient:
    """
    Cliente para a API UAZAPI (WhatsApp).

    Features:
    - Retry automático para erros transientes
    - Formatação automática de telefone
    - Chunking de mensagens longas
    - Indicadores de digitação

    Uso:
        client = UazapiClient(base_url="https://...", api_key="...")
        result = await client.send_text_message("5511999999999", "Olá!")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Inicializa o cliente UAZAPI.

        Args:
            base_url: URL base da API UAZAPI.
            api_key: Chave de API.
            timeout: Timeout para requisições em segundos.
        """
        if not base_url:
            raise ValueError("base_url é obrigatório")
        if not api_key:
            raise ValueError("api_key é obrigatório")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "apikey": self.api_key,
        }

        logger.info("uazapi_client_initialized",
            integration="uazapi",
            base_url=self.base_url)

    # ========================================================================
    # HTTP CORE
    # ========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retries: int = MAX_RETRIES,
    ) -> Dict[str, Any]:
        """
        Executa requisição HTTP com retry.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=self._headers,
                        json=data,
                        params=params,
                    )
                    response.raise_for_status()

                    try:
                        return response.json()
                    except Exception:
                        return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code

                # Não retry para erros de cliente (exceto 429)
                if status in {400, 401, 403, 404}:
                    logger.error("uazapi_request_client_error",
                        integration="uazapi",
                        method=method,
                        endpoint=endpoint,
                        status_code=status)
                    raise

                # Retry para erros transientes
                if status in RETRYABLE_STATUS_CODES and attempt < retries:
                    delay = RETRY_DELAY_S * (2 ** (attempt - 1))  # Backoff exponencial
                    logger.warning("uazapi_request_retry",
                        integration="uazapi",
                        method=method,
                        endpoint=endpoint,
                        status_code=status,
                        attempt=attempt,
                        delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue

                logger.error("uazapi_request_failed",
                    integration="uazapi",
                    method=method,
                    endpoint=endpoint,
                    status_code=status)
                raise

            except httpx.RequestError as e:
                last_error = e
                error_type = type(e).__name__

                if attempt < retries:
                    delay = RETRY_DELAY_S * (2 ** (attempt - 1))
                    logger.warning("uazapi_request_network_retry",
                        integration="uazapi",
                        method=method,
                        endpoint=endpoint,
                        error_type=error_type,
                        attempt=attempt,
                        delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue

                logger.error("uazapi_request_network_failed",
                    integration="uazapi",
                    method=method,
                    endpoint=endpoint,
                    error=str(e))
                raise

        raise last_error or Exception("UazapiClient request failed")

    async def _get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """GET request."""
        return await self._request("GET", endpoint, params=params)

    async def _post(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """POST request."""
        return await self._request("POST", endpoint, data=data)

    async def _put(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """PUT request."""
        return await self._request("PUT", endpoint, data=data)

    # ========================================================================
    # FORMATAÇÃO DE TELEFONE
    # ========================================================================

    def _format_phone(self, phone: str) -> str:
        """
        Formata telefone para o padrão UAZAPI.

        Remove caracteres especiais, @s.whatsapp.net, e adiciona 55 se necessário.
        """
        # Remove caracteres especiais
        phone = re.sub(r"[^\d]", "", phone)

        # Remove sufixos do WhatsApp
        phone = phone.replace("@s.whatsapp.net", "").replace("@c.us", "")

        # Remove 55 duplicado no início
        if phone.startswith("5555"):
            phone = phone[2:]

        # Adiciona 55 se não começar com ele
        if not phone.startswith("55"):
            phone = f"55{phone}"

        return phone

    # ========================================================================
    # ENVIO DE MENSAGENS
    # ========================================================================

    async def send_text_message(
        self,
        phone: str,
        text: str,
        delay: int = 0,
        link_preview: bool = True,
    ) -> MessageResponse:
        """
        Envia mensagem de texto.

        Args:
            phone: Número do destinatário.
            text: Texto da mensagem.
            delay: Delay em ms antes de enviar.
            link_preview: Se deve mostrar preview de links.

        Returns:
            MessageResponse com success, message_id, error.
        """
        phone = self._format_phone(phone)

        payload = {
            "number": phone,
            "text": text,
            "delay": delay,
            "linkPreview": link_preview,
        }

        try:
            result = await self._post("/message/sendText", payload)

            # Extrair message_id de diferentes formatos de resposta
            message_id = (
                result.get("key", {}).get("id")
                or result.get("messageid")
                or result.get("id")
            )

            return MessageResponse(
                success=True,
                message_id=message_id,
                error=None,
            )

        except Exception as e:
            logger.error("uazapi_send_text_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                error=str(e))
            return MessageResponse(
                success=False,
                message_id=None,
                error=str(e),
            )

    async def send_signed_message(
        self,
        phone: str,
        message: str,
        agent_name: str,
        delay: int = 0,
        link_preview: bool = True,
    ) -> MessageResponse:
        """
        Envia mensagem com assinatura do agente.

        O nome do agente é adicionado em negrito no início.
        """
        signed_text = f"*{agent_name}:*\n{message}"
        return await self.send_text_message(phone, signed_text, delay, link_preview)

    async def send_ai_response(
        self,
        phone: str,
        text: str,
        agent_name: str,
        delay: int = 1500,
    ) -> ChunkedSendResult:
        """
        Envia resposta de IA em chunks com indicador de digitação.

        Args:
            phone: Número do destinatário.
            text: Texto completo da resposta.
            agent_name: Nome do agente para assinatura.
            delay: Delay entre chunks em ms.

        Returns:
            ChunkedSendResult com estatísticas de envio.
        """
        # Enviar indicador de digitação
        await self.send_typing(phone, 2000)

        # Quebrar em chunks
        chunks = self._split_text_for_natural_sending(text)

        if not chunks:
            return ChunkedSendResult(
                all_success=False,
                success_count=0,
                total_chunks=0,
                failed_chunks=[],
                results=[],
                first_error="Texto vazio",
            )

        results: List[MessageResponse] = []
        failed_chunks: List[int] = []
        first_error: Optional[str] = None

        for i, chunk in enumerate(chunks):
            # Adicionar assinatura apenas no primeiro chunk
            if i == 0:
                chunk_text = f"*{agent_name}:*\n{chunk}"
            else:
                chunk_text = chunk

            # Enviar indicador de digitação antes de cada chunk
            await self.send_typing(phone, delay)
            await asyncio.sleep(delay / 1000)  # Converter ms para segundos

            result = await self.send_text_message(phone, chunk_text)
            results.append(result)

            if not result.get("success"):
                failed_chunks.append(i)
                if first_error is None:
                    first_error = result.get("error")

        success_count = len(results) - len(failed_chunks)

        return ChunkedSendResult(
            all_success=len(failed_chunks) == 0,
            success_count=success_count,
            total_chunks=len(chunks),
            failed_chunks=failed_chunks,
            results=results,
            first_error=first_error,
        )

    async def send_text_chunked(
        self,
        phone: str,
        text: str,
        delay: int = 1000,
    ) -> ChunkedSendResult:
        """
        Envia texto em múltiplos chunks (sem assinatura).
        """
        chunks = self._split_text_for_natural_sending(text)

        if not chunks:
            return ChunkedSendResult(
                all_success=False,
                success_count=0,
                total_chunks=0,
                failed_chunks=[],
                results=[],
                first_error="Texto vazio",
            )

        results: List[MessageResponse] = []
        failed_chunks: List[int] = []
        first_error: Optional[str] = None

        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(delay / 1000)

            result = await self.send_text_message(phone, chunk)
            results.append(result)

            if not result.get("success"):
                failed_chunks.append(i)
                if first_error is None:
                    first_error = result.get("error")

        success_count = len(results) - len(failed_chunks)

        return ChunkedSendResult(
            all_success=len(failed_chunks) == 0,
            success_count=success_count,
            total_chunks=len(chunks),
            failed_chunks=failed_chunks,
            results=results,
            first_error=first_error,
        )

    # ========================================================================
    # ENVIO DE MÍDIA
    # ========================================================================

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        caption: Optional[str] = None,
        media_type: Union[MediaType, str] = MediaType.IMAGE,
        filename: Optional[str] = None,
    ) -> MessageResponse:
        """
        Envia mensagem de mídia (imagem, vídeo, documento).

        Args:
            phone: Número do destinatário.
            media_url: URL da mídia ou base64.
            caption: Legenda opcional.
            media_type: Tipo de mídia (image, video, document, etc).
            filename: Nome do arquivo (para documentos).
        """
        phone = self._format_phone(phone)

        if isinstance(media_type, MediaType):
            media_type = media_type.value

        # Determinar endpoint baseado no tipo
        endpoint_map = {
            "image": "/message/sendImage",
            "video": "/message/sendVideo",
            "document": "/message/sendDocument",
            "audio": "/message/sendAudio",
            "sticker": "/message/sendSticker",
        }

        endpoint = endpoint_map.get(media_type, "/message/sendImage")

        payload: Dict[str, Any] = {
            "number": phone,
            "media": media_url,
        }

        if caption:
            payload["caption"] = caption
        if filename:
            payload["fileName"] = filename

        try:
            result = await self._post(endpoint, payload)

            message_id = (
                result.get("key", {}).get("id")
                or result.get("messageid")
                or result.get("id")
            )

            return MessageResponse(
                success=True,
                message_id=message_id,
                error=None,
            )

        except Exception as e:
            logger.error("uazapi_send_media_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                media_type=media_type,
                error=str(e))
            return MessageResponse(
                success=False,
                message_id=None,
                error=str(e),
            )

    async def send_audio_message(
        self,
        phone: str,
        audio_url: str,
        ptt: bool = False,
    ) -> MessageResponse:
        """
        Envia mensagem de áudio.

        Args:
            phone: Número do destinatário.
            audio_url: URL do áudio ou base64.
            ptt: Se é mensagem de voz (push to talk).
        """
        phone = self._format_phone(phone)

        payload = {
            "number": phone,
            "audio": audio_url,
            "ptt": ptt,
        }

        try:
            result = await self._post("/message/sendAudio", payload)

            message_id = (
                result.get("key", {}).get("id")
                or result.get("messageid")
                or result.get("id")
            )

            return MessageResponse(
                success=True,
                message_id=message_id,
                error=None,
            )

        except Exception as e:
            logger.error("uazapi_send_audio_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                ptt=ptt,
                error=str(e))
            return MessageResponse(
                success=False,
                message_id=None,
                error=str(e),
            )

    async def send_buttons_message(
        self,
        phone: str,
        text: str,
        buttons: List[Dict[str, str]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> MessageResponse:
        """
        Envia mensagem com botões interativos.

        Args:
            phone: Número do destinatário.
            text: Texto da mensagem.
            buttons: Lista de botões [{"id": "...", "text": "..."}].
            title: Título opcional.
            footer: Rodapé opcional.
        """
        phone = self._format_phone(phone)

        # Formatar botões para o padrão UAZAPI
        formatted_buttons = [
            {
                "buttonId": btn.get("id", f"btn_{i}"),
                "buttonText": {"displayText": btn.get("text", "")},
                "type": 1,
            }
            for i, btn in enumerate(buttons[:3])  # Máximo 3 botões
        ]

        payload: Dict[str, Any] = {
            "number": phone,
            "description": text,
            "buttons": formatted_buttons,
        }

        if title:
            payload["title"] = title
        if footer:
            payload["footer"] = footer

        try:
            result = await self._post("/message/sendButtons", payload)

            message_id = (
                result.get("key", {}).get("id")
                or result.get("messageid")
                or result.get("id")
            )

            return MessageResponse(
                success=True,
                message_id=message_id,
                error=None,
            )

        except Exception as e:
            logger.error("uazapi_send_buttons_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                button_count=len(buttons),
                error=str(e))
            return MessageResponse(
                success=False,
                message_id=None,
                error=str(e),
            )

    async def send_list_message(
        self,
        phone: str,
        text: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> MessageResponse:
        """
        Envia mensagem com lista de opções.

        Args:
            phone: Número do destinatário.
            text: Texto da mensagem.
            button_text: Texto do botão para abrir a lista.
            sections: Seções da lista.
            title: Título opcional.
            footer: Rodapé opcional.
        """
        phone = self._format_phone(phone)

        payload: Dict[str, Any] = {
            "number": phone,
            "description": text,
            "buttonText": button_text,
            "sections": sections,
        }

        if title:
            payload["title"] = title
        if footer:
            payload["footerText"] = footer

        try:
            result = await self._post("/message/sendList", payload)

            message_id = (
                result.get("key", {}).get("id")
                or result.get("messageid")
                or result.get("id")
            )

            return MessageResponse(
                success=True,
                message_id=message_id,
                error=None,
            )

        except Exception as e:
            logger.error("uazapi_send_list_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                section_count=len(sections),
                error=str(e))
            return MessageResponse(
                success=False,
                message_id=None,
                error=str(e),
            )

    # ========================================================================
    # DOWNLOAD DE MÍDIA
    # ========================================================================

    async def download_media(
        self,
        message_id: str,
        return_base64: bool = True,
        generate_mp3: bool = False,
        return_link: bool = False,
    ) -> Dict[str, Any]:
        """
        Baixa mídia de uma mensagem.

        Args:
            message_id: ID da mensagem.
            return_base64: Se deve retornar em base64.
            generate_mp3: Se deve converter áudio para MP3.
            return_link: Se deve retornar URL.
        """
        payload = {
            "messageId": message_id,
            "returnBase64": return_base64,
            "generateMp3": generate_mp3,
            "returnLink": return_link,
        }

        try:
            return await self._post("/message/downloadMedia", payload)
        except Exception as e:
            logger.error("uazapi_download_media_failed",
                integration="uazapi",
                message_id=message_id,
                error=str(e))
            return {"error": str(e)}

    # ========================================================================
    # RECIBOS E STATUS
    # ========================================================================

    async def mark_as_read(self, phone: str, message_id: str) -> bool:
        """
        Marca mensagens como lidas.
        """
        phone = self._format_phone(phone)

        payload = {
            "number": phone,
            "messageId": message_id,
        }

        try:
            await self._post("/message/markAsRead", payload)
            return True
        except Exception as e:
            logger.error("uazapi_mark_as_read_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                message_id=message_id,
                error=str(e))
            return False

    async def send_typing(self, phone: str, duration: int = 2000) -> bool:
        """
        Envia indicador de "digitando...".

        Args:
            phone: Número do destinatário.
            duration: Duração em ms.
        """
        phone = self._format_phone(phone)

        payload = {
            "number": phone,
            "duration": duration,
        }

        try:
            await self._post("/chat/sendPresence", {"number": phone, "presence": "composing"})
            return True
        except Exception as e:
            logger.debug("uazapi_send_typing_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                error=str(e))
            return False

    async def send_presence(
        self, phone: str, presence: Union[PresenceType, str] = PresenceType.COMPOSING
    ) -> bool:
        """
        Envia indicador de presença.

        Args:
            phone: Número do destinatário.
            presence: Tipo de presença (composing, recording, etc).
        """
        phone = self._format_phone(phone)

        if isinstance(presence, PresenceType):
            presence = presence.value

        payload = {
            "number": phone,
            "presence": presence,
        }

        try:
            await self._post("/chat/sendPresence", payload)
            return True
        except Exception as e:
            logger.debug("uazapi_send_presence_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                presence=presence,
                error=str(e))
            return False

    # ========================================================================
    # STATUS E CONEXÃO
    # ========================================================================

    async def get_instance_status(self) -> InstanceStatus:
        """
        Obtém status da instância UAZAPI.
        """
        try:
            result = await self._get("/instance/connectionState")

            instance = result.get("instance", {})
            state = instance.get("state", "close")

            return InstanceStatus(
                connected=state == "open",
                phone_number=instance.get("phoneNumber"),
                instance_id=instance.get("instanceName"),
                status=state,
                battery=instance.get("battery"),
                plugged=instance.get("plugged"),
            )

        except Exception as e:
            logger.error("uazapi_get_status_failed",
                integration="uazapi",
                error=str(e))
            return InstanceStatus(
                connected=False,
                phone_number=None,
                instance_id=None,
                status="error",
                battery=None,
                plugged=None,
            )

    async def is_connected(self) -> bool:
        """
        Verifica se a instância está conectada ao WhatsApp.
        """
        status = await self.get_instance_status()
        return status.get("connected", False)

    async def get_qr_code(self) -> Optional[str]:
        """
        Obtém QR code em base64 para conectar.

        Returns:
            String base64 do QR code ou None se já conectado.
        """
        try:
            result = await self._get("/instance/qrcode")
            return result.get("qrcode")
        except Exception as e:
            logger.error("uazapi_get_qrcode_failed",
                integration="uazapi",
                error=str(e))
            return None

    async def health_check(self) -> bool:
        """
        Verifica se o serviço está acessível.
        """
        try:
            await self._get("/instance/connectionState")
            return True
        except Exception:
            return False

    # ========================================================================
    # INFORMAÇÕES DE CONTATO
    # ========================================================================

    async def get_contact_info(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Obtém informações de um contato.
        """
        phone = self._format_phone(phone)

        try:
            result = await self._get(f"/chat/contact/{phone}")
            return result
        except Exception as e:
            logger.error("uazapi_get_contact_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                error=str(e))
            return None

    async def check_phone_exists(self, phone: str) -> bool:
        """
        Verifica se um número tem WhatsApp.
        """
        phone = self._format_phone(phone)

        try:
            result = await self._post("/chat/whatsappNumbers", {"numbers": [phone]})
            numbers = result.get("data", [])
            return len(numbers) > 0 and numbers[0].get("exists", False)
        except Exception as e:
            logger.error("uazapi_check_phone_failed",
                integration="uazapi",
                phone=phone[:8] + "***" if len(phone) > 8 else phone,
                error=str(e))
            return False

    # ========================================================================
    # TEXT CHUNKING (MÉTODOS PRIVADOS)
    # ========================================================================

    def _split_text_for_natural_sending(
        self, text: str, max_size: int = MAX_CHUNK_SIZE
    ) -> List[str]:
        """
        Quebra texto em chunks para envio natural.

        Prioriza quebra por parágrafos, depois por frases.
        """
        if len(text) <= max_size:
            return [text]

        chunks: List[str] = []

        # Primeiro, tentar quebrar por parágrafos
        paragraphs = text.split("\n\n")

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Se o parágrafo cabe no chunk atual
            if len(current_chunk) + len(para) + 2 <= max_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                # Salvar chunk atual se houver
                if current_chunk:
                    chunks.append(current_chunk)

                # Se o parágrafo é maior que max_size, quebrar por frases
                if len(para) > max_size:
                    sentence_chunks = self._split_by_sentences(para, max_size)
                    chunks.extend(sentence_chunks[:-1])
                    current_chunk = sentence_chunks[-1] if sentence_chunks else ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_by_sentences(self, text: str, max_size: int) -> List[str]:
        """
        Quebra texto por frases.
        """
        # Padrão para detectar fim de frase
        sentence_pattern = r"(?<=[.!?])\s+"
        sentences = re.split(sentence_pattern, text)

        chunks: List[str] = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) + 1 <= max_size:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                # Se a frase é maior que max_size, forçar quebra
                if len(sentence) > max_size:
                    force_chunks = self._force_split(sentence, max_size)
                    chunks.extend(force_chunks[:-1])
                    current_chunk = force_chunks[-1] if force_chunks else ""
                else:
                    current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _force_split(self, text: str, max_size: int) -> List[str]:
        """
        Força quebra de texto por tamanho quando não há pontuação.
        """
        chunks: List[str] = []

        while len(text) > max_size:
            # Tentar quebrar em espaço
            split_point = text.rfind(" ", 0, max_size)
            if split_point == -1:
                split_point = max_size

            chunks.append(text[:split_point].strip())
            text = text[split_point:].strip()

        if text:
            chunks.append(text)

        return chunks


# ============================================================================
# FACTORY & SINGLETON
# ============================================================================

_uazapi_client: Optional[UazapiClient] = None


def get_uazapi_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> UazapiClient:
    """
    Retorna instância singleton do UazapiClient.

    Na primeira chamada, requer base_url e api_key (ou usa config).
    """
    global _uazapi_client

    if _uazapi_client is None:
        if not base_url or not api_key:
            # Import config apenas quando necessário
            from app.config import settings
            base_url = base_url or settings.uazapi_base_url
            api_key = api_key or settings.uazapi_api_key

        if not base_url or not api_key:
            raise ValueError("UAZAPI_BASE_URL e UAZAPI_API_KEY são obrigatórios")

        _uazapi_client = UazapiClient(base_url=base_url, api_key=api_key)

    return _uazapi_client


def create_uazapi_client(
    base_url: str,
    api_key: str,
) -> UazapiClient:
    """
    Cria nova instância do UazapiClient (não singleton).
    """
    return UazapiClient(base_url=base_url, api_key=api_key)


async def close_uazapi_client() -> None:
    """
    Fecha a instância singleton (para cleanup).
    """
    global _uazapi_client
    _uazapi_client = None


# ============================================================================
# HELPERS
# ============================================================================

def sign_message(message: str, agent_name: str) -> str:
    """
    Assina mensagem com nome do agente em negrito.

    Exemplo: sign_message("Olá!", "Agnes") -> "*Agnes:*\nOlá!"
    """
    return f"*{agent_name}:*\n{message}"
