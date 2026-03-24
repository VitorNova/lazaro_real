# tests/test_image_extraction.py

import pytest
from app.domain.messaging.handlers.incoming_message_handler import extract_message_data


class TestImageExtraction:
    """
    TDD — Imagem com caption ignorada pelo sistema (2026-03-24)

    Contexto: UAZAPI envia messageType="ImageMessage" (PascalCase).
              Quando a imagem tem caption, o campo text ja vem preenchido,
              e o placeholder [Imagem recebida] nunca e gerado.
              Sem placeholder, message_processor.py nao baixa a imagem.
    Causa: extract_message_data nao forca placeholder para imagens como faz para audio.
    Correcao: Forcar placeholder + preservar caption no texto.
    """

    def _make_webhook(self, message_type, text="", content=None, message_id="3EB0ABC123"):
        """Monta payload UAZAPI v2 realista."""
        msg = {
            "chatid": "556697194084@s.whatsapp.net",
            "fromMe": False,
            "isGroup": False,
            "messageType": message_type,
            "text": text,
            "messageid": message_id,
            "senderName": "Vitor Hugo",
            "messageTimestamp": 1774362145000,
            "wasSentByApi": False,
        }
        if content:
            msg["content"] = content
        return {"EventType": "messages", "message": msg, "instanceName": "Agent_14e6e5ce"}

    # ── Imagem com caption ────────────────────────────────────────────

    def test_imagem_com_caption_gera_placeholder(self):
        """Imagem com caption deve gerar placeholder E preservar a caption."""
        webhook = self._make_webhook(
            message_type="ImageMessage",
            text="foto do equipamento",
            content={"caption": "foto do equipamento", "URL": "https://mmg.whatsapp.net/img.jpg", "mimetype": "image/jpeg"},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert "[Imagem recebida]" in result["text"], f"Deveria conter placeholder, recebeu: {result['text']}"
        assert "foto do equipamento" in result["text"], "Caption deveria ser preservada no texto"

    # ── Imagem sem caption ────────────────────────────────────────────

    def test_imagem_sem_caption_gera_placeholder(self):
        """Imagem sem caption deve gerar placeholder."""
        webhook = self._make_webhook(
            message_type="ImageMessage",
            text="",
            content={"URL": "https://mmg.whatsapp.net/img.jpg", "mimetype": "image/jpeg"},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert "[Imagem recebida]" in result["text"], f"Deveria conter placeholder, recebeu: {result['text']}"

    # ── URL da midia extraida de content.URL ──────────────────────────

    def test_media_url_extraida_de_content_url(self):
        """URL da midia deve ser extraida de content.URL (UAZAPI usa U maiusculo)."""
        webhook = self._make_webhook(
            message_type="ImageMessage",
            text="",
            content={"URL": "https://mmg.whatsapp.net/foto123.jpg", "mimetype": "image/jpeg"},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert result.get("media_url") == "https://mmg.whatsapp.net/foto123.jpg"

    # ── Documento com caption ─────────────────────────────────────────

    def test_documento_com_caption_gera_placeholder(self):
        """Documento com caption deve gerar placeholder de documento."""
        webhook = self._make_webhook(
            message_type="DocumentMessage",
            text="segue o boleto",
            content={"caption": "segue o boleto", "URL": "https://mmg.whatsapp.net/doc.pdf", "mimetype": "application/pdf", "fileName": "boleto.pdf"},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert "[document" in result["text"].lower() or "[documento" in result["text"].lower(), \
            f"Deveria conter placeholder de documento, recebeu: {result['text']}"
        assert "segue o boleto" in result["text"], "Caption deveria ser preservada"

    # ── Documento sem caption ─────────────────────────────────────────

    def test_documento_sem_caption_gera_placeholder(self):
        """Documento sem caption deve gerar placeholder."""
        webhook = self._make_webhook(
            message_type="DocumentMessage",
            text="",
            content={"URL": "https://mmg.whatsapp.net/doc.pdf", "mimetype": "application/pdf"},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert "[document" in result["text"].lower() or "[documento" in result["text"].lower()

    # ── media_type retornado corretamente ─────────────────────────────

    def test_media_type_retornado_para_imagem(self):
        """media_type deve ser retornado mesmo com PascalCase."""
        webhook = self._make_webhook(message_type="ImageMessage", text="")
        result = extract_message_data(webhook)
        assert result is not None
        assert result.get("media_type") is not None

    # ── Audio continua funcionando ────────────────────────────────────

    def test_audio_continua_gerando_placeholder(self):
        """Regressao: audio deve continuar gerando [AUDIO]."""
        webhook = self._make_webhook(
            message_type="AudioMessage",
            text="",
            content={"URL": "https://mmg.whatsapp.net/audio.ogg", "mimetype": "audio/ogg", "PTT": True},
        )
        result = extract_message_data(webhook)
        assert result is not None
        assert result["text"] == "[AUDIO]"

    # ── Texto normal nao e afetado ────────────────────────────────────

    def test_texto_normal_nao_afetado(self):
        """Regressao: texto normal nao deve ser alterado."""
        webhook = self._make_webhook(message_type="ExtendedTextMessage", text="oi tudo bem")
        result = extract_message_data(webhook)
        assert result is not None
        assert result["text"] == "oi tudo bem"
