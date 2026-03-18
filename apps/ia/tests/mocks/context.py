# tests/mocks/context.py
"""
Mocks para detect_conversation_context e funcoes relacionadas.

Uso:
    from tests.mocks.context import make_context_detector_mock, CONTEXT_MANUTENCAO

    # Mock que retorna contexto de manutencao
    with patch("app.domain.messaging.context.context_detector.detect_conversation_context",
               make_context_detector_mock(CONTEXT_MANUTENCAO, "contract-123")):
        resultado = funcao_que_usa_context()
"""

from typing import Callable, Optional, Tuple


# ============================================================================
# CONSTANTES DE CONTEXTO
# ============================================================================

CONTEXT_MANUTENCAO = "manutencao_preventiva"
CONTEXT_BILLING = "disparo_billing"
CONTEXT_COBRANCA = "disparo_cobranca"
CONTEXT_NENHUM = None


# ============================================================================
# MOCK FACTORY
# ============================================================================

def make_context_detector_mock(
    context_type: Optional[str] = None,
    reference_id: Optional[str] = None
) -> Callable[..., Tuple[Optional[str], Optional[str]]]:
    """
    Cria mock para detect_conversation_context().

    Args:
        context_type: Tipo de contexto a retornar (ex: CONTEXT_MANUTENCAO)
        reference_id: ID de referencia (contract_id ou reference_id)

    Returns:
        Funcao que simula detect_conversation_context()

    Uso:
        # Contexto de manutencao encontrado
        mock = make_context_detector_mock(CONTEXT_MANUTENCAO, "contract-uuid")
        assert mock({}) == ("manutencao_preventiva", "contract-uuid")

        # Nenhum contexto encontrado
        mock = make_context_detector_mock(CONTEXT_NENHUM, None)
        assert mock({}) == (None, None)

        # Em teste com patch:
        with patch(
            "app.domain.messaging.context.context_detector.detect_conversation_context",
            make_context_detector_mock(CONTEXT_BILLING, "payment-123")
        ):
            # codigo que chama detect_conversation_context()
            pass
    """
    def mock_detect_conversation_context(
        conversation_history: dict,
        max_messages: int = 10,
        hours_window: int = 168
    ) -> Tuple[Optional[str], Optional[str]]:
        return context_type, reference_id

    return mock_detect_conversation_context


def make_get_context_prompt_mock(prompt: Optional[str] = None) -> Callable[..., Optional[str]]:
    """
    Cria mock para get_context_prompt().

    Args:
        prompt: Prompt a retornar (None simula contexto nao encontrado)

    Returns:
        Funcao que simula get_context_prompt()

    Uso:
        with patch(
            "app.domain.messaging.context.context_detector.get_context_prompt",
            make_get_context_prompt_mock("## CONTEXTO ESPECIAL...")
        ):
            pass
    """
    def mock_get_context_prompt(
        context_prompts: Optional[dict],
        context_type: str
    ) -> Optional[str]:
        return prompt

    return mock_get_context_prompt


# ============================================================================
# CONVERSATION HISTORY FIXTURES
# ============================================================================

def make_history_with_context(
    context_type: str,
    reference_id: str,
    timestamp: Optional[str] = None
) -> dict:
    """
    Cria conversation_history com mensagem de contexto.

    Args:
        context_type: Tipo de contexto (ex: CONTEXT_MANUTENCAO)
        reference_id: ID de referencia
        timestamp: Timestamp ISO (default: agora)

    Returns:
        Dict no formato esperado por detect_conversation_context()
    """
    from datetime import datetime, timezone

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "messages": [
            {
                "role": "model",
                "parts": [{"text": "Mensagem de disparo automatico"}],
                "timestamp": timestamp,
                "context": context_type,
                "contract_id": reference_id,
            }
        ]
    }


HISTORY_MANUTENCAO = make_history_with_context(
    CONTEXT_MANUTENCAO,
    "contract-test-123"
)

HISTORY_BILLING = make_history_with_context(
    CONTEXT_BILLING,
    "payment-test-456"
)

HISTORY_VAZIO = {"messages": []}
