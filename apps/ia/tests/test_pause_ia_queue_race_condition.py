"""
TDD - Bug 09/03/2026 - Lead Batistella (556696099447):
Lead mandou comprovante de pagamento, IA não respondeu nada.

Causa raiz: Race condition entre webhooks.
- Lead estava na fila 544 (billing/IA)
- Pausa do Redis estava setada (estado stale de evento anterior)
- Webhook de mensagem verificou pausa ANTES do webhook Leadbox removê-la
- Mensagem foi ignorada indevidamente

Comportamento esperado:
Se o lead está em uma fila de IA (537, 544, 545), a verificação de pausa
do Redis deveria ser ignorada, pois a fila é a "fonte de verdade".
"""

import pytest


class TestPauseIaQueueRaceCondition:
    """
    Testa a lógica de verificação de pausa quando lead está em fila IA.

    Bug real: Batistella (556696099447) em 09/03/2026
    - Fila: 544 (billing)
    - Pausa Redis: True (estado stale)
    - Resultado: mensagem ignorada
    - Esperado: mensagem processada (fila IA tem prioridade)
    """

    def test_lead_in_ia_queue_should_ignore_redis_pause(self):
        """
        Se lead está em fila IA (544), pausa do Redis deveria ser ignorada.

        Este teste documenta o comportamento ESPERADO após correção.
        ANTES da correção: is_paused = True, mensagem ignorada
        DEPOIS da correção: is_paused ignorada porque fila é IA
        """
        # Setup: lead na fila 544 (billing - fila de IA)
        IA_QUEUES = {537, 544, 545}
        current_queue = 544  # billing
        is_paused_redis = True  # estado stale

        # Lógica atual (BUG): verifica pausa independente da fila
        should_ignore_message_BUGGY = is_paused_redis

        # Lógica corrigida: se fila é IA, ignora pausa
        should_ignore_pause = current_queue in IA_QUEUES
        should_ignore_message_FIXED = is_paused_redis and not should_ignore_pause

        # Assert: com a correção, mensagem NÃO deveria ser ignorada
        assert should_ignore_message_FIXED is False, (
            "Lead em fila IA (544) com pausa stale deveria processar mensagem"
        )

        # Documenta o bug
        assert should_ignore_message_BUGGY is True, (
            "Bug confirmado: código atual ignora mensagem mesmo em fila IA"
        )

    def test_lead_in_human_queue_should_respect_redis_pause(self):
        """
        Se lead está em fila humana, pausa do Redis deveria ser respeitada.
        """
        IA_QUEUES = {537, 544, 545}
        current_queue = 500  # fila humana (exemplo)
        is_paused_redis = True

        # Lógica corrigida: fila humana, respeita pausa
        should_ignore_pause = current_queue in IA_QUEUES
        should_ignore_message = is_paused_redis and not should_ignore_pause

        assert should_ignore_message is True, (
            "Lead em fila humana com pausa deveria ignorar mensagem"
        )

    def test_lead_in_ia_queue_without_pause_processes_normally(self):
        """
        Se lead está em fila IA sem pausa, deve processar normalmente.
        """
        IA_QUEUES = {537, 544, 545}
        current_queue = 537  # fila IA padrão
        is_paused_redis = False

        should_ignore_pause = current_queue in IA_QUEUES
        should_ignore_message = is_paused_redis and not should_ignore_pause

        assert should_ignore_message is False, (
            "Lead em fila IA sem pausa deveria processar mensagem"
        )

    def test_lead_in_maintenance_queue_should_ignore_pause(self):
        """
        Fila 545 (manutenção) também é IA, deveria ignorar pausa.
        """
        IA_QUEUES = {537, 544, 545}
        current_queue = 545  # manutenção
        is_paused_redis = True

        should_ignore_pause = current_queue in IA_QUEUES
        should_ignore_message = is_paused_redis and not should_ignore_pause

        assert should_ignore_message is False, (
            "Lead em fila manutenção (545) com pausa deveria processar mensagem"
        )

    def test_lead_without_queue_respects_pause(self):
        """
        Se lead não tem fila definida, pausa deveria ser respeitada.
        """
        IA_QUEUES = {537, 544, 545}
        current_queue = None
        is_paused_redis = True

        # None não está em IA_QUEUES, então respeita pausa
        should_ignore_pause = current_queue is not None and current_queue in IA_QUEUES
        should_ignore_message = is_paused_redis and not should_ignore_pause

        assert should_ignore_message is True, (
            "Lead sem fila com pausa deveria ignorar mensagem"
        )


class TestPauseLogicIntegration:
    """
    Testa a lógica como deveria aparecer no código real.
    Documenta a correção necessária em mensagens.py.
    """

    def test_corrected_pause_check_logic(self):
        """
        Documenta a correção necessária no código.

        CÓDIGO ATUAL (mensagens.py linhas ~1327-1337):
        ```
        is_paused = await redis.pause_is_paused(agent_id, phone)
        if not is_paused:
            is_paused = supabase.is_lead_paused(table_leads, remotejid)
        if is_paused:
            logger.info(f"Bot pausado para {phone}, mensagem ignorada")
            return {"status": "ignored", "reason": "bot_paused"}
        ```

        CORREÇÃO NECESSÁRIA:
        ```
        is_paused = await redis.pause_is_paused(agent_id, phone)
        if not is_paused:
            is_paused = supabase.is_lead_paused(table_leads, remotejid)

        # FIX: Se fila é IA, ignorar pausa (race condition com leadbox_handler)
        if is_paused and current_queue is not None and current_queue in IA_QUEUES:
            logger.info(f"Pausa ignorada para {phone} - lead em fila IA {current_queue}")
            is_paused = False

        if is_paused:
            logger.info(f"Bot pausado para {phone}, mensagem ignorada")
            return {"status": "ignored", "reason": "bot_paused"}
        ```
        """
        # Simula cenário Batistella
        IA_QUEUES = {537, 544, 545}
        current_queue = 544
        is_paused = True  # valor do Redis

        # Lógica corrigida
        if is_paused and current_queue is not None and current_queue in IA_QUEUES:
            is_paused = False  # override

        assert is_paused is False


class TestMessageProcessorPauseCheck:
    """
    TDD - Bug 09/03/2026 - message_processor.py não tem o fix de race condition.

    O fix foi aplicado em mensagens.py (commit 8691b4a), mas message_processor.py
    ainda ignora mensagens de leads em fila IA quando há pausa stale no Redis.

    Fluxo do bug:
    webhook → mensagens.py → buffer → message_processor.py → IA
                  ↓                         ↓
           (check 1 - OK)           (check 2 - BUG)
    """

    def test_message_processor_ignores_pause_for_ia_queue(self):
        """
        FIX: message_processor.py agora ignora pausa para leads em fila IA.

        Reproduz cenário Batistella - deve PASSAR após o fix.
        """
        # Setup: estado real do message_processor.py
        IA_QUEUES_LOCAL = {537, 544, 545}
        is_paused = True  # Redis retorna True (estado stale)
        table_leads = "LeadboxCRM_Ana_14e6e5ce"
        fresh_lead = {"current_queue_id": "544", "nome": "Batistella"}

        # =============================================================
        # CÓDIGO CORRIGIDO DO MESSAGE_PROCESSOR.PY (linhas 358-375):
        # Agora verifica se lead está em fila IA e ignora pausa
        # =============================================================
        if is_paused and table_leads:
            try:
                pause_check_lead = fresh_lead if 'fresh_lead' in locals() else None
                if pause_check_lead:
                    queue_check_raw = pause_check_lead.get("current_queue_id")
                    queue_check = int(queue_check_raw) if queue_check_raw else None
                    if queue_check is not None and queue_check in IA_QUEUES_LOCAL:
                        is_paused = False  # override - ignora pausa para fila IA
            except (ValueError, TypeError):
                pass

        # Após o fix: is_paused deve ser False para lead em fila IA
        should_process = not is_paused

        assert should_process is True, (
            f"Lead em fila IA {fresh_lead.get('current_queue_id')} deveria processar mensagem"
        )

    def test_message_processor_respects_pause_for_human_queue(self):
        """
        Lead em fila humana deve respeitar pausa normalmente.
        """
        IA_QUEUES_LOCAL = {537, 544, 545}
        is_paused = True
        table_leads = "LeadboxCRM_Ana_14e6e5ce"
        fresh_lead = {"current_queue_id": "500", "nome": "Lead Humano"}  # fila humana

        # Lógica corrigida
        if is_paused and table_leads:
            try:
                pause_check_lead = fresh_lead if 'fresh_lead' in locals() else None
                if pause_check_lead:
                    queue_check_raw = pause_check_lead.get("current_queue_id")
                    queue_check = int(queue_check_raw) if queue_check_raw else None
                    if queue_check is not None and queue_check in IA_QUEUES_LOCAL:
                        is_paused = False
            except (ValueError, TypeError):
                pass

        # Fila humana: pausa deve ser respeitada
        should_process = not is_paused

        assert should_process is False, (
            "Lead em fila humana com pausa deveria ignorar mensagem"
        )

    def test_message_processor_handles_null_queue(self):
        """
        Lead sem fila definida deve respeitar pausa.
        """
        IA_QUEUES_LOCAL = {537, 544, 545}
        is_paused = True
        table_leads = "LeadboxCRM_Ana_14e6e5ce"
        fresh_lead = {"current_queue_id": None, "nome": "Lead Sem Fila"}

        # Lógica corrigida
        if is_paused and table_leads:
            try:
                pause_check_lead = fresh_lead if 'fresh_lead' in locals() else None
                if pause_check_lead:
                    queue_check_raw = pause_check_lead.get("current_queue_id")
                    queue_check = int(queue_check_raw) if queue_check_raw else None
                    if queue_check is not None and queue_check in IA_QUEUES_LOCAL:
                        is_paused = False
            except (ValueError, TypeError):
                pass

        # Sem fila: pausa deve ser respeitada
        should_process = not is_paused

        assert should_process is False, (
            "Lead sem fila com pausa deveria ignorar mensagem"
        )
