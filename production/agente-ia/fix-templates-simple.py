#!/usr/bin/env python3
"""
Corrige templates de mensagem com double-escape de newlines.
Versão simplificada sem dependências complexas.
"""

import os
from supabase import create_client

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

def main():
    print("=" * 70)
    print("CORREÇÃO DE TEMPLATES COM DOUBLE-ESCAPE")
    print("=" * 70)

    # Pegar credenciais do ambiente
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("❌ Erro: SUPABASE_URL e SUPABASE_SERVICE_KEY devem estar definidas")
        return

    supabase = create_client(supabase_url, supabase_key)

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
    corrected_count = 0

    for key, value in messages.items():
        print(f"\n   Processando: {key}")

        try:
            # Se o valor for uma string que começa e termina com aspas duplas
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                # Remove aspas externas
                cleaned = value[1:-1]

                # Corrige \n literal para quebra de linha real
                cleaned = cleaned.replace('\\n', '\n')

                # Corrige outras escapes comuns
                cleaned = cleaned.replace('\\t', '\t')
                cleaned = cleaned.replace('\\"', '"')
                cleaned = cleaned.replace('\\\\', '\\')

                corrected_messages[key] = cleaned
                corrected_count += 1
                print(f"   ✅ Corrigido ({len(cleaned)} chars)")
            else:
                # Já está correto ou não é string
                corrected_messages[key] = value
                print(f"   ⏭️  Já correto")

        except Exception as e:
            print(f"   ❌ Erro: {e}")
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
    print(f"Templates corrigidos: {corrected_count}")
    print("\n✅ Correção concluída!")
    print("\n⚠️  TESTE: Execute test-billing-dispatch.py para verificar")

if __name__ == "__main__":
    main()
