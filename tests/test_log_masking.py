# tests/test_log_masking.py
"""
TDD - Auditoria de Seguranca 11/03/2026 - Telefones sem mask em logs

Contexto:
    40+ logs com phone={phone} expondo telefone completo em PM2 logs.
    Violacao LGPD.

Causa:
    Logs em message_processor.py nao usam mask_phone().

Correcao:
    Substituir phone={phone} por phone={mask_phone(phone)} em todos os logs.
"""

import re


class TestLogMasking:
    """
    Testes para garantir que telefones sao mascarados em logs.

    Telefone completo em logs viola LGPD. Deve usar mask_phone()
    para exibir apenas ultimos 4 digitos: 5511999999999 -> ***9999
    """

    def test_message_processor_importa_mask_phone(self):
        """
        message_processor.py deve importar mask_phone de app.core.utils.phone.
        """
        with open("apps/ia/app/domain/messaging/services/message_processor.py", "r") as f:
            content = f.read()

        # Deve ter import de mask_phone
        has_import = "from app.core.utils.phone import" in content and "mask_phone" in content
        assert has_import, "message_processor.py nao importa mask_phone de app.core.utils.phone"

    def test_logs_nao_expoe_telefone_completo(self):
        """
        Nenhum log com 'phone=' deve ter variavel direta {phone}.
        Deve usar {mask_phone(phone)} ou similar.
        """
        with open("apps/ia/app/domain/messaging/services/message_processor.py", "r") as f:
            content = f.read()

        lines = content.split("\n")
        violations = []

        for i, line in enumerate(lines, 1):
            # Ignora comentarios
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Busca logger com phone={phone} SEM mask_phone
            # Padrao: logger.xxx(...phone={phone}...) onde phone nao tem mask_phone ao redor
            if "logger." in line and "phone={phone}" in line:
                # Verifica se tem mask_phone(phone) na mesma linha
                if "mask_phone(phone)" not in line:
                    violations.append(f"Linha {i}: {stripped[:80]}")

        assert len(violations) == 0, (
            f"Encontrado {len(violations)} log(s) expondo telefone completo:\n"
            + "\n".join(violations[:10])
        )

    def test_logs_nao_expoe_remotejid_completo(self):
        """
        Logs com remotejid tambem podem expor telefone.
        Deve mascarar quando possivel.
        """
        with open("apps/ia/app/domain/messaging/services/message_processor.py", "r") as f:
            content = f.read()

        lines = content.split("\n")
        violations = []

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Busca logger com remotejid={remotejid} sem mask
            if "logger." in line and "remotejid={remotejid}" in line:
                if "mask_phone" not in line:
                    violations.append(f"Linha {i}: {stripped[:80]}")

        # Pode haver casos legitimos, entao so avisa se tiver muitos
        assert len(violations) <= 3, (
            f"Encontrado {len(violations)} log(s) expondo remotejid completo:\n"
            + "\n".join(violations[:10])
        )


class TestMaskPhoneFunction:
    """
    Testes para verificar que mask_phone() existe e funciona.
    """

    def test_mask_phone_existe_em_phone_py(self):
        """
        mask_phone deve estar definida em app/core/utils/phone.py
        """
        with open("apps/ia/app/core/utils/phone.py", "r") as f:
            content = f.read()

        assert "def mask_phone" in content, "mask_phone nao encontrada em phone.py"

    def test_mask_phone_funciona_corretamente(self):
        """
        mask_phone deve mascarar telefone mostrando apenas ultimos digitos.
        """
        from app.core.utils.phone import mask_phone

        # Telefone com 13 digitos (55 + DDD + 9 digitos)
        result = mask_phone("5511987654321")
        assert "4321" in result, f"mask_phone deve mostrar ultimos digitos: {result}"
        assert "987" not in result, f"mask_phone nao deve mostrar digitos do meio: {result}"
