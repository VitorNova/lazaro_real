# tests/test_maintenance_context_save.py
"""
TDD - Bug IDALIA 11/03/2026 - Contexto de manutencao nao salvo

Contexto:
    Job de manutencao envia mensagem mas nao salva contexto no conversation_history
    porque telefone no Asaas (5591989650040) difere do Leadbox (559189650040).
    O "9 extra" do celular causa mismatch na busca por remotejid.

Causa:
    notification_service.mark_notification_sent() faz busca simples por remotejid
    sem gerar variantes de telefone (com/sem 9 extra).

Correcao:
    Criar generate_phone_variants() que gera todas variantes possiveis
    e usar busca com OR para encontrar lead independente do formato.
"""

import pytest
from unittest.mock import MagicMock, patch


# ─── Helpers de Mock ────────────────────────────────────────────────────────

def make_supabase_mock(table_data: dict) -> MagicMock:
    """
    Cria mock do Supabase configurado com dados por tabela.
    """
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])

        resp = MagicMock()
        resp.data = data

        # SELECT encadeado padrao
        t.select.return_value.eq.return_value.limit.return_value.execute.return_value = resp
        t.select.return_value.or_.return_value.limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp

        # UPDATE
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # INSERT
        t.insert.return_value.execute.return_value = MagicMock(data=[{"id": "new-id"}])

        return t

    mock.client.table.side_effect = table_side_effect
    return mock


# ─── Testes de generate_phone_variants ──────────────────────────────────────

class TestGeneratePhoneVariants:
    """
    Testes para funcao generate_phone_variants() em phone.py.

    A funcao deve gerar todas variantes possiveis de telefone para busca:
    - Com/sem DDI (55)
    - Com/sem nono digito (9)
    """

    def test_gera_variante_sem_9_quando_telefone_tem_9_extra(self):
        """
        Input: 5591989650040 (com 9 extra)
        Output deve incluir: 559189650040 (sem 9 extra)

        Bug IDALIA: Asaas tinha 5591989650040, Leadbox tinha 559189650040
        """
        from app.core.utils.phone import generate_phone_variants

        variants = generate_phone_variants("5591989650040")

        # Deve incluir versao sem o 9 extra
        assert "559189650040" in variants
        # Deve incluir versao original
        assert "5591989650040" in variants

    def test_gera_variante_com_9_quando_telefone_nao_tem(self):
        """
        Input: 559189650040 (sem 9 extra)
        Output deve incluir: 5591989650040 (com 9 extra)
        """
        from app.core.utils.phone import generate_phone_variants

        variants = generate_phone_variants("559189650040")

        # Deve incluir versao com o 9 extra
        assert "5591989650040" in variants
        # Deve incluir versao original
        assert "559189650040" in variants

    def test_gera_variantes_a_partir_de_telefone_sem_55(self):
        """
        Input: 91989650040 (sem 55)
        Output deve incluir versoes com 55
        """
        from app.core.utils.phone import generate_phone_variants

        variants = generate_phone_variants("91989650040")

        # Deve incluir versoes com 55
        assert "5591989650040" in variants
        assert "559189650040" in variants

    def test_retorna_lista_nao_vazia_para_telefone_valido(self):
        """Deve sempre retornar pelo menos uma variante para telefone valido."""
        from app.core.utils.phone import generate_phone_variants

        variants = generate_phone_variants("5566999887766")

        assert len(variants) >= 1
        assert "5566999887766" in variants


# ─── Testes de find_message_record_by_phone ─────────────────────────────────

class TestFindMessageRecordByPhone:
    """
    Testes para funcao find_message_record_by_phone() em phone.py.

    A funcao deve buscar registro de mensagem usando multiplas variantes de telefone.
    """

    def test_encontra_lead_quando_telefone_tem_9_extra(self):
        """
        Cenario: Asaas tem 5591989650040, Leadbox tem 559189650040
        Busca por 5591989650040 deve encontrar lead com 559189650040
        """
        from app.core.utils.phone import find_message_record_by_phone

        # Lead existe com telefone SEM o 9 extra
        mock_db = make_supabase_mock({
            "leadbox_messages_Ana_14e6e5ce": [{
                "id": "msg-123",
                "remotejid": "559189650040@s.whatsapp.net",
                "conversation_history": {"messages": []}
            }]
        })

        # Buscar com telefone COM o 9 extra
        result = find_message_record_by_phone(
            supabase=mock_db,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone="5591989650040"
        )

        assert result is not None
        assert result["id"] == "msg-123"

    def test_encontra_lead_por_customer_id_quando_remotejid_falha(self):
        """
        Fallback: se nao encontrar por telefone, buscar por customer_id.
        """
        from app.core.utils.phone import find_message_record_by_phone

        # Configurar mock para retornar vazio no primeiro select (por remotejid)
        # e retornar dados no segundo select (por customer_id)
        mock = MagicMock()

        def table_side_effect(table_name):
            t = MagicMock()

            # Primeira chamada (por remotejid): vazio
            # Segunda chamada (por customer_id): encontra
            call_count = [0]

            def select_side_effect(*args):
                s = MagicMock()

                def or_side_effect(*args):
                    o = MagicMock()
                    o.limit.return_value.execute.return_value = MagicMock(data=[])
                    return o

                def eq_side_effect(field, value):
                    e = MagicMock()
                    if field == "asaas_customer_id":
                        e.limit.return_value.execute.return_value = MagicMock(data=[{
                            "id": "msg-456",
                            "remotejid": "559999999999@s.whatsapp.net",
                            "asaas_customer_id": "cus_123",
                            "conversation_history": {"messages": []}
                        }])
                    else:
                        e.limit.return_value.execute.return_value = MagicMock(data=[])
                    return e

                s.or_ = or_side_effect
                s.eq = eq_side_effect
                return s

            t.select = select_side_effect
            return t

        mock.client.table.side_effect = table_side_effect

        result = find_message_record_by_phone(
            supabase=mock,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone="5511999999999",
            customer_id="cus_123"
        )

        assert result is not None
        assert result["asaas_customer_id"] == "cus_123"


# ─── Testes de Integracao com notification_service ──────────────────────────

class TestMarkNotificationSentContextSave:
    """
    Testes para garantir que mark_notification_sent() salva contexto corretamente.
    """

    def test_formato_mensagem_compativel_com_detect_conversation_context(self):
        """
        Mensagem salva deve ter campo 'context' que detect_conversation_context() encontra.
        """
        # Simular formato da mensagem que seria salva
        from app.domain.messaging.context.context_detector import detect_conversation_context

        # Formato esperado apos correcao
        history = {
            "messages": [
                {
                    "role": "model",
                    "parts": [{"text": "Mensagem de manutencao preventiva"}],
                    "timestamp": "2026-03-11T10:00:00.000000",
                    "context": "manutencao_preventiva",
                    "contract_id": "contract-123"
                }
            ]
        }

        context, ref_id = detect_conversation_context(history)

        assert context == "manutencao_preventiva"
        assert ref_id == "contract-123"

    def test_contexto_detectado_mesmo_com_formato_simplificado(self):
        """
        detect_conversation_context() deve funcionar com formato 'text' direto tambem.
        (compatibilidade com mensagens antigas)
        """
        from app.domain.messaging.context.context_detector import detect_conversation_context

        # Formato antigo (sem parts)
        history = {
            "messages": [
                {
                    "role": "model",
                    "text": "Mensagem de manutencao",
                    "timestamp": "2026-03-11T10:00:00.000000",
                    "context": "manutencao_preventiva",
                    "contract_id": "contract-456"
                }
            ]
        }

        context, ref_id = detect_conversation_context(history)

        assert context == "manutencao_preventiva"
        assert ref_id == "contract-456"
