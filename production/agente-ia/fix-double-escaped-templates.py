#!/usr/bin/env python3
"""
Corrige templates de mensagem com double-escape de newlines.

O bug: templates salvos com JSON.stringify(JSON.stringify(...))
Resultado: \n literal em vez de quebra de linha.

Este script:
1. Busca o agente Ana
2. Extrai os templates com \n literal
3. Remove as aspas extras e corrige os newlines
4. Salva de volta no banco
"""

import asyncio
import json
import sys
import os

# Adicionar o diretório do projeto ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import direto do Supabase para evitar dependências desnecessárias
from supabase import create_client, Client
from app.config import settings

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

async def main():
    print("=" * 70)
    print("CORREÇÃO DE TEMPLATES COM DOUBLE-ESCAPE")
    print("=" * 70)

    supabase: Client = create_client(settings.supabase_url, settings.supabase_key)

    # 1. Buscar agente
    print(f"\n1️⃣ Buscando agente {AGENT_ID[:8]}...")
    response = (
        supabase.table("agents")
        .select("id, name, asaas_config")
        .eq("id", AGENT_ID)
        .single()
        .execute()
    )

    agent = response.data
    print(f"✅ Agente encontrado: {agent['name']}")

    asaas_config = agent.get("asaas_config") or {}
    auto_collection = asaas_config.get("autoCollection") or {}
    messages = auto_collection.get("messages") or {}

    print(f"\n2️⃣ Templates encontrados: {len(messages)}")

    # 2. Corrigir cada template
    corrected_messages = {}
    errors = []

    for key, value in messages.items():
        print(f"\n   Processando: {key}")
        print(f"   Valor original (primeiros 80 chars): {str(value)[:80]}...")

        try:
            # Se o valor for uma string que começa e termina com aspas duplas
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                # Remove aspas externas
                cleaned = value[1:-1]

                # Corrige \n literal para quebra de linha real
                # Python interpreta \\n como \n literal
                # Precisamos substituir \\n (dois caracteres) por \n (quebra de linha)
                cleaned = cleaned.replace('\\n', '\n')

                # Corrige outras escapes comuns
                cleaned = cleaned.replace('\\t', '\t')
                cleaned = cleaned.replace('\\"', '"')
                cleaned = cleaned.replace('\\\\', '\\')

                corrected_messages[key] = cleaned
                print(f"   ✅ Corrigido")
                print(f"   Novo valor (primeiros 80 chars): {cleaned[:80]}...")
            else:
                # Já está correto ou não é string
                corrected_messages[key] = value
                print(f"   ⏭️  Já correto ou não é string")

        except Exception as e:
            print(f"   ❌ Erro ao processar {key}: {e}")
            errors.append(f"{key}: {e}")
            corrected_messages[key] = value  # Mantém original em caso de erro

    # 3. Salvar de volta
    print(f"\n3️⃣ Salvando templates corrigidos...")

    new_asaas_config = {
        **asaas_config,
        "autoCollection": {
            **auto_collection,
            "messages": corrected_messages
        }
    }

    try:
        supabase.table("agents").update({
            "asaas_config": new_asaas_config
        }).eq("id", AGENT_ID).execute()

        print(f"✅ Templates salvos com sucesso!")

    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")
        return

    # 4. Resumo
    print(f"\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"Templates processados: {len(corrected_messages)}")
    print(f"Erros: {len(errors)}")

    if errors:
        print("\n⚠️  Erros encontrados:")
        for error in errors:
            print(f"   - {error}")

    print("\n✅ Correção concluída!")
    print("\n⚠️  TESTE: Execute test-billing-dispatch.py para verificar")

if __name__ == "__main__":
    asyncio.run(main())
