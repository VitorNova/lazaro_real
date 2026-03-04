"""
Diana v2 - Servico de mensagens.

Integracao com UAZAPI e Gemini para:
- Enviar mensagens individuais
- Enviar em massa via /sender/advanced
- Gerar respostas com IA
"""

import logging
from typing import Optional, Dict, List, Any

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory
import httpx

from app.config import settings

logger = logging.getLogger("diana.message")


class DianaMessageService:
    """
    Servico para envio de mensagens e geracao de respostas IA.

    Usa UAZAPI para WhatsApp e Gemini para IA.
    """

    def __init__(
        self,
        uazapi_base_url: str,
        uazapi_token: str,
        gemini_api_key: Optional[str] = None,
    ):
        """
        Inicializa o servico.

        Args:
            uazapi_base_url: URL base da instancia UAZAPI
            uazapi_token: Token de autenticacao da instancia
            gemini_api_key: API key do Gemini (usa settings se nao fornecido)
        """
        self.base_url = uazapi_base_url.rstrip("/")
        self.token = uazapi_token
        self.gemini_api_key = gemini_api_key or settings.google_api_key

        # Headers UAZAPI
        self._headers = {
            "token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        logger.info(f"DianaMessageService inicializado: {self.base_url}")

    # ========================================================================
    # UAZAPI - Envio Individual
    # ========================================================================

    async def send_text(
        self,
        phone: str,
        text: str,
        delay: int = 0,
        link_preview: bool = False,
    ) -> Dict[str, Any]:
        """
        Envia mensagem de texto via UAZAPI.

        Endpoint: POST /send/text

        Args:
            phone: Numero formatado (5566999887766)
            text: Texto da mensagem
            delay: Delay em ms antes de enviar (simula digitacao)
            link_preview: Se deve mostrar preview de links

        Returns:
            Dict com success, message_id, error
        """
        try:
            payload = {
                "number": phone,
                "text": text,
                "linkPreview": link_preview,
            }
            if delay > 0:
                payload["delay"] = delay

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/send/text",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            message_id = data.get("key", {}).get("id") or data.get("messageid")
            logger.info(f"Mensagem enviada para {phone[:8]}***: {message_id}")

            return {
                "success": True,
                "message_id": message_id,
                "error": None,
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Erro ao enviar texto: {error_msg}")
            return {
                "success": False,
                "message_id": None,
                "error": error_msg,
            }

        except Exception as e:
            logger.error(f"Erro ao enviar texto: {e}")
            return {
                "success": False,
                "message_id": None,
                "error": str(e),
            }

    # ========================================================================
    # UAZAPI - Envio em Massa (Campanha)
    # ========================================================================

    async def send_bulk(
        self,
        messages: List[Dict[str, str]],
        campaign_name: str,
        delay_min: int = 30,
        delay_max: int = 60,
        scheduled_minutes: int = 1,
    ) -> Dict[str, Any]:
        """
        Envia mensagens em massa via UAZAPI /sender/advanced.

        A UAZAPI cuida da fila, delay entre mensagens, e controle.

        Args:
            messages: Lista de mensagens [{"phone": "55...", "text": "msg"}, ...]
            campaign_name: Nome da campanha para identificacao
            delay_min: Delay minimo entre mensagens (segundos)
            delay_max: Delay maximo entre mensagens (segundos)
            scheduled_minutes: Minutos para iniciar a campanha (default: 1)

        Returns:
            Dict com folder_id, count, status, error
        """
        try:
            # Formata mensagens para o formato UAZAPI
            formatted_messages = [
                {
                    "number": msg["phone"],
                    "type": "text",
                    "text": msg["text"],
                }
                for msg in messages
            ]

            payload = {
                "delayMin": delay_min,
                "delayMax": delay_max,
                "info": campaign_name,
                "scheduled_for": scheduled_minutes,
                "messages": formatted_messages,
            }

            logger.info(
                f"Criando campanha UAZAPI: {campaign_name} "
                f"({len(messages)} mensagens, delay {delay_min}-{delay_max}s)"
            )

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/sender/advanced",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            folder_id = data.get("folder_id")
            count = data.get("count", len(messages))
            status = data.get("status", "created")

            logger.info(
                f"Campanha criada: folder_id={folder_id}, "
                f"count={count}, status={status}"
            )

            return {
                "success": True,
                "folder_id": folder_id,
                "count": count,
                "status": status,
                "error": None,
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Erro ao criar campanha: {error_msg}")
            return {
                "success": False,
                "folder_id": None,
                "count": 0,
                "status": "error",
                "error": error_msg,
            }

        except Exception as e:
            logger.error(f"Erro ao criar campanha: {e}")
            return {
                "success": False,
                "folder_id": None,
                "count": 0,
                "status": "error",
                "error": str(e),
            }

    async def control_campaign(
        self,
        folder_id: str,
        action: str,
    ) -> Dict[str, Any]:
        """
        Controla uma campanha (stop, continue, delete).

        Endpoint: POST /sender/edit

        Args:
            folder_id: ID da campanha na UAZAPI
            action: Acao a executar (stop, continue, delete)

        Returns:
            Dict com success, error
        """
        try:
            payload = {
                "folder_id": folder_id,
                "action": action,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/sender/edit",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()

            logger.info(f"Campanha {folder_id}: {action}")

            return {"success": True, "error": None}

        except Exception as e:
            logger.error(f"Erro ao controlar campanha: {e}")
            return {"success": False, "error": str(e)}

    async def list_campaigns(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lista campanhas na UAZAPI.

        Endpoint: GET /sender/listfolders

        Args:
            status: Filtrar por status (opcional)

        Returns:
            Lista de campanhas
        """
        try:
            url = f"{self.base_url}/sender/listfolders"
            if status:
                url += f"?status={status}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._headers)
                response.raise_for_status()
                return response.json() or []

        except Exception as e:
            logger.error(f"Erro ao listar campanhas: {e}")
            return []

    # ========================================================================
    # Gemini - Geracao de Respostas IA
    # ========================================================================

    async def generate_ai_response(
        self,
        system_prompt: str,
        user_message: str,
        history: List[Dict[str, str]],
        prospect_data: Dict[str, str],
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> str:
        """
        Gera resposta usando Gemini.

        O system_prompt pode ter variaveis do prospect:
        "Voce e uma consultora conversando com {nome} da {empresa}..."

        Args:
            system_prompt: Prompt de sistema (da campanha)
            user_message: Mensagem do usuario
            history: Historico de mensagens [{"role": "user/assistant", "content": "..."}]
            prospect_data: Dados do prospect para substituir variaveis
            temperature: Temperatura do modelo (0.0 a 2.0)
            max_tokens: Maximo de tokens na resposta

        Returns:
            Texto da resposta gerada
        """
        try:
            # Configura API
            genai.configure(api_key=self.gemini_api_key)

            # Substitui variaveis no system_prompt
            formatted_prompt = self._substitute_variables(system_prompt, prospect_data)

            # Safety settings - BLOCK_NONE para todas as categorias
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # Configuracao de geracao
            generation_config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                candidate_count=1,
            )

            # Cria modelo
            model = genai.GenerativeModel(
                model_name=settings.gemini_model,
                generation_config=generation_config,
                safety_settings=safety_settings,
                system_instruction=formatted_prompt,
            )

            # Formata historico para Gemini
            gemini_history = []
            for msg in history:
                role = "model" if msg.get("role") == "assistant" else "user"
                content = msg.get("content", "")
                gemini_history.append({
                    "role": role,
                    "parts": [{"text": content}],
                })

            # Inicia chat com historico
            chat = model.start_chat(history=gemini_history)

            # Envia mensagem
            response = await chat.send_message_async(user_message)

            # Extrai texto da resposta
            if response.candidates and response.candidates[0].content.parts:
                text = response.candidates[0].content.parts[0].text
                logger.info(f"Resposta Gemini gerada: {len(text)} chars")
                return text

            logger.warning("Resposta Gemini sem conteudo")
            return ""

        except Exception as e:
            logger.error(f"Erro ao gerar resposta Gemini: {e}")
            raise

    def _substitute_variables(
        self,
        template: str,
        variables: Dict[str, str],
    ) -> str:
        """
        Substitui variaveis no template.

        Template: "Oi {nome}! Vi que a {empresa} atua em {segmento}..."
        Variables: {"nome": "Joao", "empresa": "Acme", "segmento": "tech"}

        Args:
            template: Template com {variaveis}
            variables: Dict de variaveis

        Returns:
            Template com variaveis substituidas
        """
        result = template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, value or "")
        return result

    # ========================================================================
    # Presenca (Typing)
    # ========================================================================

    async def send_typing(self, phone: str, duration: int = 3000) -> bool:
        """
        Envia indicador de digitacao.

        Args:
            phone: Numero formatado
            duration: Duracao em ms

        Returns:
            True se enviado, False caso contrario
        """
        try:
            payload = {
                "number": phone,
                "presence": "composing",
                "delay": duration,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/message/presence",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()

            return True

        except Exception as e:
            logger.debug(f"Erro ao enviar typing (nao critico): {e}")
            return False
