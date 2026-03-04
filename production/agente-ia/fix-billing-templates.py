#!/usr/bin/env python3
"""
Fix Billing Templates - Corrige templates com \\n literais

PROBLEMA:
Os templates de cobrança foram salvos com \\n (backslash-n LITERAIS)
ao invés de quebras de linha reais. Isso faz o WhatsApp exibir "\\n"
na mensagem ao invés de quebrar a linha.

SOLUÇÃO:
Este script:
1. Busca todos os agentes com templates de cobrança
2. Para cada template, substitui \\n por quebras de linha reais
3. Atualiza o JSONB no banco

USO:
    python3 fix-billing-templates.py --dry-run  # Ver o que seria alterado
    python3 fix-billing-templates.py            # Aplicar correções
"""

import argparse
import json
import sys
from typing import Any, Dict, List

sys.path.insert(0, '/var/www/phant/agente-ia')

from app.services.supabase import get_supabase_service


def fix_template_newlines(template: str) -> str:
    """
    Corrige newlines em um template.

    Substitui \\n (backslash-n literais) por quebras de linha reais.
    Também corrige \\t (tabs) se existirem.

    Args:
        template: Template com possíveis \\n literais

    Returns:
        Template com newlines reais
    """
    if not template:
        return template

    # Substitui backslash-n literais por newlines reais
    fixed = template.replace('\\n', '\n')
    fixed = fixed.replace('\\t', '\t')
    fixed = fixed.replace('\\r', '\r')

    return fixed


def fix_messages_dict(messages: Dict[str, str]) -> Dict[str, str]:
    """
    Corrige todos os templates em um dict de mensagens.

    Args:
        messages: Dict com templates de cobrança

    Returns:
        Dict com templates corrigidos
    """
    fixed = {}
    for key, template in messages.items():
        if isinstance(template, str):
            fixed[key] = fix_template_newlines(template)
        else:
            fixed[key] = template
    return fixed


def get_agents_with_billing_templates() -> List[Dict[str, Any]]:
    """
    Busca todos os agentes com templates de cobrança.

    Returns:
        Lista de agentes com asaas_config
    """
    supabase = get_supabase_service()

    response = (
        supabase.client.table("agents")
        .select("id, name, asaas_config")
        .not_.is_("asaas_config", "null")
        .execute()
    )

    agents = []
    for agent in (response.data or []):
        asaas_config = agent.get("asaas_config") or {}
        auto_collection = asaas_config.get("autoCollection") or {}
        messages = auto_collection.get("messages")

        # Só processa se tiver messages
        if messages and isinstance(messages, dict):
            agents.append(agent)

    return agents


def has_literal_newlines(text: str) -> bool:
    """
    Verifica se uma string tem backslash-n literais.

    Args:
        text: String para verificar

    Returns:
        True se tiver \\n literais
    """
    if not text:
        return False

    # Procura por backslash seguido de 'n'
    # (não confundir com newline real que é byte 0x0a)
    return '\\n' in text


def fix_agent_templates(agent_id: str, asaas_config: Dict[str, Any], dry_run: bool = True) -> bool:
    """
    Corrige templates de um agente.

    Args:
        agent_id: ID do agente
        asaas_config: Configuração Asaas do agente
        dry_run: Se True, não aplica mudanças (só mostra)

    Returns:
        True se houve alterações, False caso contrário
    """
    auto_collection = asaas_config.get("autoCollection") or {}
    messages = auto_collection.get("messages")

    if not messages or not isinstance(messages, dict):
        return False

    # Verifica se há templates com problema
    needs_fix = False
    for key, template in messages.items():
        if isinstance(template, str) and has_literal_newlines(template):
            needs_fix = True
            break

    if not needs_fix:
        return False

    # Corrige templates
    fixed_messages = fix_messages_dict(messages)

    # Atualiza asaas_config
    fixed_config = asaas_config.copy()
    fixed_config["autoCollection"]["messages"] = fixed_messages

    if dry_run:
        print(f"  [DRY RUN] Atualizaria agent {agent_id}")

        # Mostra exemplos de correção
        for key in list(messages.keys())[:3]:  # Primeiros 3 templates
            if has_literal_newlines(messages[key]):
                print(f"    Template: {key}")
                print(f"      ANTES: {repr(messages[key][:80])}")
                print(f"      DEPOIS: {repr(fixed_messages[key][:80])}")
    else:
        # Aplica correção no banco
        supabase = get_supabase_service()
        supabase.client.table("agents").update(
            {"asaas_config": fixed_config}
        ).eq("id", agent_id).execute()

        print(f"  ✅ Corrigido agent {agent_id}")

    return True


def main():
    """Entry point do script."""
    parser = argparse.ArgumentParser(
        description="Corrige templates de cobrança com \\n literais"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria alterado sem aplicar mudanças"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("FIX BILLING TEMPLATES")
    print("=" * 60)
    print()

    if args.dry_run:
        print("⚠️  MODO DRY RUN - Nenhuma alteração será aplicada")
    else:
        print("🔧 MODO APLICAR - Alterações serão salvas no banco")

    print()

    # Busca agentes
    print("Buscando agentes com templates de cobrança...")
    agents = get_agents_with_billing_templates()
    print(f"Encontrados {len(agents)} agentes com templates")
    print()

    # Processa cada agente
    fixed_count = 0
    for agent in agents:
        agent_id = agent["id"]
        agent_name = agent.get("name", "Sem nome")
        asaas_config = agent.get("asaas_config", {})

        print(f"Agente: {agent_name} ({agent_id[:8]}...)")

        was_fixed = fix_agent_templates(agent_id, asaas_config, dry_run=args.dry_run)

        if was_fixed:
            fixed_count += 1
        else:
            print("  ✅ Já está correto (sem \\n literais)")

        print()

    # Resumo
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"Total de agentes verificados: {len(agents)}")
    print(f"Agentes que precisaram correção: {fixed_count}")

    if args.dry_run and fixed_count > 0:
        print()
        print("⚠️  Execute novamente SEM --dry-run para aplicar as correções")
    elif fixed_count > 0:
        print()
        print("✅ Correções aplicadas com sucesso!")
        print()
        print("📋 PRÓXIMOS PASSOS:")
        print("1. Teste o envio de uma mensagem de cobrança")
        print("2. Verifique se as quebras de linha aparecem corretamente no WhatsApp")
    else:
        print()
        print("✅ Todos os templates já estão corretos!")


if __name__ == "__main__":
    main()
