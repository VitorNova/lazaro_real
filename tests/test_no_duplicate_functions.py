# tests/test_no_duplicate_functions.py
"""
TDD - Auditoria de Seguranca 11/03/2026 - Funcoes duplicadas

Contexto:
    mask_phone() duplicada em 3 arquivos causa inconsistencia e
    dificulta manutencao. Se corrigir em um, esquece do outro.

Causa:
    Copy-paste durante desenvolvimento rapido.

Correcao:
    Centralizar em app/core/utils/phone.py e importar onde necessario.
"""

import os
import re


class TestNoDuplicateFunctions:
    """
    Testes para garantir que funcoes utilitarias nao estao duplicadas.

    Funcoes como mask_phone() devem existir em apenas um lugar
    (app/core/utils/) e ser importadas onde necessario.
    """

    def test_mask_phone_so_em_phone_py(self):
        """
        mask_phone() deve ser definida apenas em app/core/utils/phone.py.
        Outros arquivos devem importar, nao redefinir.
        """
        duplicates = []
        canonical_path = "apps/ia/app/core/utils/phone.py"

        # Buscar em todo o codigo
        for root, dirs, files in os.walk("apps/ia/app"):
            # Ignorar __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for file in files:
                if not file.endswith(".py"):
                    continue

                filepath = os.path.join(root, file)

                # Pular o arquivo canonico
                if filepath == canonical_path:
                    continue

                with open(filepath, "r") as f:
                    content = f.read()

                # Buscar definicao de funcao (nao import)
                if re.search(r"^def mask_phone\s*\(", content, re.MULTILINE):
                    duplicates.append(filepath)

        assert len(duplicates) == 0, (
            f"mask_phone() duplicada em {len(duplicates)} arquivo(s):\n"
            + "\n".join(duplicates)
            + "\n\nDeve existir apenas em app/core/utils/phone.py"
        )

    def test_billing_notifier_importa_mask_phone(self):
        """
        billing_notifier.py deve importar mask_phone, nao definir.
        """
        with open("apps/ia/app/domain/billing/services/billing_notifier.py", "r") as f:
            content = f.read()

        # Nao deve ter definicao
        has_definition = re.search(r"^def mask_phone\s*\(", content, re.MULTILINE)
        assert not has_definition, "billing_notifier.py define mask_phone() - deve importar"

        # Deve ter import (se usa a funcao)
        if "mask_phone" in content:
            has_import = "from app.core.utils.phone import" in content
            assert has_import, "billing_notifier.py usa mask_phone mas nao importa de phone.py"

    def test_lead_ensurer_importa_mask_phone(self):
        """
        lead_ensurer.py deve importar mask_phone, nao definir.
        """
        with open("apps/ia/app/domain/billing/services/lead_ensurer.py", "r") as f:
            content = f.read()

        # Nao deve ter definicao
        has_definition = re.search(r"^def mask_phone\s*\(", content, re.MULTILINE)
        assert not has_definition, "lead_ensurer.py define mask_phone() - deve importar"

        # Deve ter import (se usa a funcao)
        if "mask_phone" in content:
            has_import = "from app.core.utils.phone import" in content
            assert has_import, "lead_ensurer.py usa mask_phone mas nao importa de phone.py"
