# tests/test_no_print_in_production.py
"""
TDD - Auditoria de Seguranca 11/03/2026 - print() em producao

Contexto:
    30+ print() statements em codigo de producao expondo telefones
    e nomes de clientes em PM2 logs. Violacao LGPD.

Causa:
    Debug code nao removido em billing_context.py, maintenance_context.py
    e message_processor.py.

Correcao:
    Substituir print() por logger.debug() ou remover completamente.
"""

import re


class TestNoPrintStatements:
    """
    Testes para garantir que nao ha print() em codigo de producao.

    print() vai direto para stdout/PM2 logs e pode expor dados sensiveis.
    Deve usar logger.debug() ou logger.info() com mascaramento.
    """

    def test_billing_context_sem_print(self):
        """
        billing_context.py nao deve ter print() statements.
        """
        with open("apps/ia/app/domain/messaging/context/billing_context.py", "r") as f:
            content = f.read()

        # Encontra print( mas ignora comentarios e strings
        lines = content.split("\n")
        print_lines = []

        for i, line in enumerate(lines, 1):
            # Ignora linhas comentadas
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Busca print( no codigo
            if re.search(r'\bprint\s*\(', line):
                print_lines.append(f"Linha {i}: {stripped[:60]}")

        assert len(print_lines) == 0, (
            f"billing_context.py tem {len(print_lines)} print() statements:\n"
            + "\n".join(print_lines[:5])
        )

    def test_maintenance_context_sem_print(self):
        """
        maintenance_context.py nao deve ter print() statements.
        """
        with open("apps/ia/app/domain/messaging/context/maintenance_context.py", "r") as f:
            content = f.read()

        lines = content.split("\n")
        print_lines = []

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\bprint\s*\(', line):
                print_lines.append(f"Linha {i}: {stripped[:60]}")

        assert len(print_lines) == 0, (
            f"maintenance_context.py tem {len(print_lines)} print() statements:\n"
            + "\n".join(print_lines[:5])
        )

    def test_message_processor_sem_print(self):
        """
        message_processor.py nao deve ter print() statements.
        """
        with open("apps/ia/app/domain/messaging/services/message_processor.py", "r") as f:
            content = f.read()

        lines = content.split("\n")
        print_lines = []

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\bprint\s*\(', line):
                print_lines.append(f"Linha {i}: {stripped[:60]}")

        assert len(print_lines) == 0, (
            f"message_processor.py tem {len(print_lines)} print() statements:\n"
            + "\n".join(print_lines[:5])
        )


class TestNoPrintWithSensitiveData:
    """
    Testes adicionais para garantir que nenhum print() expoe dados sensiveis.
    """

    def test_nenhum_print_com_phone_em_domain(self):
        """
        Nenhum print() no diretorio domain/ deve conter 'phone'.
        """
        import os

        violations = []
        domain_path = "apps/ia/app/domain"

        for root, dirs, files in os.walk(domain_path):
            # Ignora __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for file in files:
                if not file.endswith(".py"):
                    continue

                filepath = os.path.join(root, file)
                with open(filepath, "r") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(r'\bprint\s*\(', line) and "phone" in line.lower():
                            violations.append(f"{filepath}:{i}")

        assert len(violations) == 0, (
            f"Encontrado print() com 'phone' em:\n" + "\n".join(violations[:10])
        )
