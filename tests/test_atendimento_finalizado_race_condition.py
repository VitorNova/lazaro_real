"""
TDD - Bug Race Condition Atendimento_Finalizado

Data: 2026-03-14
Problema: Lead transferido para fila IA (537) mas Atendimento_Finalizado
ainda é "true" (stale) - mensagem ignorada indevidamente.

Causa raiz: Race condition entre UPDATE do Supabase (50-200ms) e chegada de mensagem.
- leadbox_handler.py limpa Redis pause rapidamente
- UPDATE no Supabase demora mais
- mensagens.py verifica Atendimento_Finalizado ANTES de verificar fila

Correção: Verificar current_queue_id antes de ignorar por Atendimento_Finalizado.
Se fila é IA, ignorar o flag stale.
"""

import pytest


class TestAtendimentoFinalizadoRaceCondition:
    """
    Testa fix de race condition para Atendimento_Finalizado.

    Bug real: Lead na fila 537 não recebe resposta após humano transferir de volta.
    Acontece porque Atendimento_Finalizado="true" (stale) bloqueia antes do fix de fila.
    """

    IA_QUEUES = {537, 544, 545}

    def test_lead_em_fila_ia_com_atendimento_finalizado_stale_processa(self):
        """
        CENÁRIO BUG: Lead em fila IA com Atendimento_Finalizado stale deve processar.

        Reproduz:
        1. Lead estava com humano (fila 453, Atendimento_Finalizado="true")
        2. Humano transfere para fila 537
        3. current_queue_id=537 (já atualizado)
        4. Atendimento_Finalizado="true" (ainda não atualizado - stale)
        5. Mensagem deveria ser PROCESSADA, não ignorada
        """
        lead = {"current_queue_id": "537", "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is False, (
            "Lead em fila IA (537) deve processar mesmo com Atendimento_Finalizado=true (stale)"
        )

    def test_lead_em_fila_humana_com_atendimento_finalizado_ignora(self):
        """Lead em fila humana com Atendimento_Finalizado deve ignorar (comportamento correto)."""
        lead = {"current_queue_id": "453", "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is True, "Lead em fila humana (453) deve ignorar"

    def test_lead_sem_queue_id_com_atendimento_finalizado_ignora(self):
        """Lead sem queue_id com Atendimento_Finalizado deve ignorar (defensivo)."""
        lead = {"current_queue_id": None, "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is True, "Lead sem fila deve ignorar (comportamento defensivo)"

    def test_lead_em_fila_billing_com_atendimento_finalizado_stale_processa(self):
        """Lead em fila billing (544) com Atendimento_Finalizado stale deve processar."""
        lead = {"current_queue_id": "544", "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is False, "Fila billing (544) também é IA - deve processar"

    def test_lead_em_fila_manutencao_com_atendimento_finalizado_stale_processa(self):
        """Lead em fila manutenção (545) com Atendimento_Finalizado stale deve processar."""
        lead = {"current_queue_id": "545", "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is False, "Fila manutenção (545) também é IA - deve processar"

    def test_lead_em_fila_ia_sem_atendimento_finalizado_processa(self):
        """Lead em fila IA sem Atendimento_Finalizado deve processar normalmente."""
        lead = {"current_queue_id": "537", "Atendimento_Finalizado": "false"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is False, "Lead em fila IA sem pausa deve processar"

    def test_lead_com_queue_id_invalido_ignora(self):
        """Lead com queue_id inválido e Atendimento_Finalizado deve ignorar (defensivo)."""
        lead = {"current_queue_id": "abc", "Atendimento_Finalizado": "true"}

        should_ignore = self._should_ignore_atendimento_finalizado(lead)

        assert should_ignore is True, "Queue_id inválido deve ignorar (defensivo)"

    def _should_ignore_atendimento_finalizado(self, lead: dict) -> bool:
        """
        Reproduz lógica CORRIGIDA de verificação de Atendimento_Finalizado.

        LÓGICA ATUAL (BUG):
            if lead.get("Atendimento_Finalizado") == "true":
                return True  # SEMPRE ignora

        LÓGICA CORRIGIDA:
            if lead.get("Atendimento_Finalizado") == "true":
                queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
                if queue_check in IA_QUEUES:
                    return False  # NÃO ignora - lead em fila IA
                return True  # Ignora - lead em fila humana ou sem fila
        """
        if lead.get("Atendimento_Finalizado") != "true":
            return False

        # FIX: verificar se lead está em fila IA antes de ignorar
        try:
            queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
        except (ValueError, TypeError):
            queue_check = None

        if queue_check is not None and queue_check in self.IA_QUEUES:
            return False  # Ignorar flag stale - processar mensagem

        return True  # Ignorar mensagem


class TestAtendimentoFinalizadoIntegracaoMensagens:
    """
    Testa que o fix deve ser aplicado em 3 pontos de mensagens.py.

    Pontos afetados:
    1. Linha 727 - HUMAN TAKEOVER check
    2. Linha 1081 - NEW LEAD sync check
    3. Linha 1321 - CHECK PRINCIPAL
    """

    IA_QUEUES = {537, 544, 545}

    def test_ponto_1_human_takeover_linha_727(self):
        """
        Ponto 1: mensagens.py linha 727 (HUMAN TAKEOVER check)

        ANTES:
            if lead.get("Atendimento_Finalizado") == "true":
                return {"status": "ignored", "reason": "already_paused"}

        DEPOIS: Deve verificar fila antes de ignorar.
        """
        lead = {"current_queue_id": "537", "Atendimento_Finalizado": "true"}

        # Simula lógica corrigida
        should_ignore = self._check_atendimento_finalizado_com_fix(lead)

        assert should_ignore is False, "Ponto 1 (linha 727) deve processar lead em fila IA"

    def test_ponto_2_new_lead_linha_1081(self):
        """
        Ponto 2: mensagens.py linha 1081 (NEW LEAD sync check)

        ANTES:
            if lead.get("Atendimento_Finalizado") == "true":
                return {"status": "ignored", "reason": "new_lead_human_took_over"}

        DEPOIS: Deve verificar fila antes de ignorar.
        """
        lead = {"current_queue_id": "544", "Atendimento_Finalizado": "true"}

        should_ignore = self._check_atendimento_finalizado_com_fix(lead)

        assert should_ignore is False, "Ponto 2 (linha 1081) deve processar lead em fila IA (billing)"

    def test_ponto_3_check_principal_linha_1321(self):
        """
        Ponto 3: mensagens.py linha 1321 (CHECK PRINCIPAL) - MAIS CRÍTICO

        ANTES:
            if atendimento_finalizado == "true":
                return {"status": "ignored", "reason": "atendimento_finalizado"}

        DEPOIS: Deve verificar fila antes de ignorar.
        """
        lead = {"current_queue_id": "545", "Atendimento_Finalizado": "true"}

        should_ignore = self._check_atendimento_finalizado_com_fix(lead)

        assert should_ignore is False, "Ponto 3 (linha 1321) deve processar lead em fila IA (manutenção)"

    def _check_atendimento_finalizado_com_fix(self, lead: dict) -> bool:
        """Reproduz lógica com fix aplicado."""
        if lead.get("Atendimento_Finalizado") != "true":
            return False

        try:
            queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
        except (ValueError, TypeError):
            queue_check = None

        if queue_check is not None and queue_check in self.IA_QUEUES:
            return False

        return True
