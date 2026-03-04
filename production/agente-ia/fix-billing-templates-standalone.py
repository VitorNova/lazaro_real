#!/usr/bin/env python3
"""
Fix Billing Templates - Corrige templates com \\n literais (STANDALONE)

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
    python3 fix-billing-templates-standalone.py --dry-run  # Ver o que seria alterado
    python3 fix-billing-templates-standalone.py            # Aplicar correções
"""

import argparse
import os
from typing import Any, Dict, List

from supabase import create_client, Client


def get_supabase_client() -> Client:
    """Cria cliente Supabase."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_SERVICE_KEY devem estar definidos")

    return create_client(url, key)


def fix_template_newlines(template: str) -> str:
    """
    Corrige newlines em um template.

    Substitui \\n (backslash-n literais) por quebras de linha reais.
    """
    if not template:
        return template

    fixed = template.replace('\\n', '\n')
    fixed = fixed.replace('\\t', '\t')
    fixed = fixed.replace('\\r', '\r')

    return fixed


def fix_messages_dict(messages: Dict[str, str]) -> Dict[str, str]:
    """Corrige todos os templates em um dict de mensagens."""
    fixed = {}
    for key, template in messages.items():
        if isinstance(template, str):
            fixed[key] = fix_template_newlines(template)
        else:
            fixed[key] = template
    return fixed


def get_agents_with_billing_templates(supabase: Client) -> List[Dict[str, Any]]:
    """Busca todos os agentes com templates de cobrança."""
    response = (
        supabase.table("agents")
        .select("id, name, asaas_config")
        .not_.is_("asaas_config", "null")
        .execute()
    )

    agents = []
    for agent in (response.data or []):
        asaas_config = agent.get("asaas_config") or {}
        auto_collection = asaas_config.get("autoCollection") or {}
        messages = auto_collection.get("messages")

        if messages and isinstance(messages, dict):
            agents.append(agent)

    return agents


def has_literal_newlines(text: str) -> bool:
    """Verifica se uma string tem backslash-n literais."""
    if not text:
        return False
    return '\\n' in text


def fix_agent_templates(
    supabase: Client,
    agent_id: str,
    asaas_config: Dict[str, Any],
    dry_run: bool = True
) -> bool:
    """Corrige templates de um agente."""
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
        for key in list(messages.keys())[:3]:
            if has_literal_newlines(messages[key]):
                print(f"    Template: {key}")
                print(f"      ANTES: {repr(messages[key][:80])}")
                print(f"      DEPOIS: {repr(fixed_messages[key][:80])}")
    else:
        # Aplica correção no banco
        supabase.table("agents").update(
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

    # Conecta ao Supabase
    try:
        supabase = get_supabase_client()
    except ValueError as e:
        print(f"❌ ERRO: {e}")
        return 1

    # Busca agentes
    print("Buscando agentes com templates de cobrança...")
    agents = get_agents_with_billing_templates(supabase)
    print(f"Encontrados {len(agents)} agentes com templates")
    print()

    # Processa cada agente
    fixed_count = 0
    for agent in agents:
        agent_id = agent["id"]
        agent_name = agent.get("name", "Sem nome")
        asaas_config = agent.get("asaas_config", {})

        print(f"Agente: {agent_name} ({agent_id[:8]}...)")

        was_fixed = fix_agent_templates(supabase, agent_id, asaas_config, dry_run=args.dry_run)

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

    return 0


if __name__ == "__main__":
    exit(main())
