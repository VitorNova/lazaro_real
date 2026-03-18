#!/usr/bin/env python3
"""
Script de teste manual — Validar busca de telefone no Leadbox.

Uso:
    cd /var/www/lazaro-real/apps/ia
    source venv/bin/activate
    python scripts/test_leadbox_phone_lookup.py 5566992028039

O script vai:
1. Buscar config do Leadbox do agente ANA no Supabase
2. Chamar GET /contacts no Leadbox com o telefone informado
3. Mostrar a resposta raw da API
4. Testar a função get_leadbox_phone
5. Comparar telefone original vs normalizado
"""

import asyncio
import sys
import os
import json

# Adicionar app ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from app.services.supabase import get_supabase_service


def get_agent_config():
    """Busca config do agente ANA no Supabase."""
    supabase = get_supabase_service()
    result = (
        supabase.client.table("agents")
        .select("id, name, handoff_triggers")
        .eq("name", "ANA")
        .limit(1)
        .execute()
    )

    if not result.data:
        print("❌ Agente ANA não encontrado no Supabase")
        sys.exit(1)

    return result.data[0]


async def call_leadbox_raw(api_url: str, api_token: str, phone: str):
    """Chama Leadbox diretamente e retorna resposta raw."""
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Limpar telefone
    clean_phone = phone.replace("@s.whatsapp.net", "").replace("@c.us", "")
    clean_phone = "".join(filter(str.isdigit, clean_phone))

    url = f"{api_url.rstrip('/')}/contacts"
    params = {"searchParam": clean_phone, "limit": 5}  # limit 5 para ver se retorna múltiplos

    print(f"\n📡 Chamando Leadbox...")
    print(f"   URL: {url}")
    print(f"   Params: {params}")
    print(f"   Headers: Authorization: Bearer {api_token[:10]}...")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params, headers=headers)

        print(f"\n📥 Resposta HTTP: {resp.status_code}")

        try:
            data = resp.json()
            print(f"\n📄 JSON Response:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return data
        except Exception as e:
            print(f"❌ Erro ao parsear JSON: {e}")
            print(f"   Body raw: {resp.text[:500]}")
            return None


async def test_get_leadbox_phone(handoff_triggers: dict, phone: str):
    """Testa a função get_leadbox_phone do dispatcher."""
    from app.billing.dispatcher import get_leadbox_phone

    print(f"\n🔧 Testando get_leadbox_phone()")
    print(f"   Input: {phone}")

    result = await get_leadbox_phone(handoff_triggers, phone)

    print(f"   Output: {result}")

    if result != phone:
        print(f"   ✅ Telefone NORMALIZADO: {phone} → {result}")
    else:
        print(f"   ⚠️  Telefone NÃO ALTERADO (fallback ou igual)")

    return result


async def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/test_leadbox_phone_lookup.py <telefone>")
        print("Exemplo: python scripts/test_leadbox_phone_lookup.py 5566992028039")
        sys.exit(1)

    phone = sys.argv[1]

    print("=" * 60)
    print("🧪 TESTE MANUAL — Leadbox Phone Lookup")
    print("=" * 60)
    print(f"\n📱 Telefone de teste: {phone}")

    # 1. Buscar config do agente
    print("\n" + "-" * 40)
    print("1️⃣  Buscando config do agente ANA...")
    agent = get_agent_config()
    handoff_triggers = agent.get("handoff_triggers", {})

    api_url = handoff_triggers.get("api_url")
    api_token = handoff_triggers.get("api_token")

    if not api_url or not api_token:
        print("❌ Leadbox não configurado no agente ANA")
        print(f"   handoff_triggers: {json.dumps(handoff_triggers, indent=2)}")
        sys.exit(1)

    print(f"   ✅ api_url: {api_url}")
    print(f"   ✅ api_token: {api_token[:15]}...")

    # 2. Chamar Leadbox diretamente
    print("\n" + "-" * 40)
    print("2️⃣  Chamando API do Leadbox diretamente...")
    leadbox_response = await call_leadbox_raw(api_url, api_token, phone)

    # 3. Analisar resposta
    print("\n" + "-" * 40)
    print("3️⃣  Análise da resposta...")

    if leadbox_response:
        contacts = leadbox_response.get("contacts", [])
        print(f"   Contatos encontrados: {len(contacts)}")

        for i, contact in enumerate(contacts):
            print(f"\n   Contato [{i}]:")
            print(f"      id: {contact.get('id')}")
            print(f"      name: {contact.get('name')}")
            print(f"      number: {contact.get('number')}")
            print(f"      email: {contact.get('email')}")

    # 4. Testar função do dispatcher
    print("\n" + "-" * 40)
    print("4️⃣  Testando função get_leadbox_phone()...")
    normalized = await test_get_leadbox_phone(handoff_triggers, phone)

    # 5. Resumo
    print("\n" + "=" * 60)
    print("📊 RESUMO")
    print("=" * 60)
    print(f"   Telefone original (Asaas): {phone}")
    print(f"   Telefone normalizado:      {normalized}")

    if normalized != phone:
        print(f"\n   ✅ SUCESSO — A função normalizou o telefone!")
        print(f"   Isso evitará duplicação de leads no billing.")
    else:
        if leadbox_response and leadbox_response.get("contacts"):
            number_in_leadbox = leadbox_response["contacts"][0].get("number")
            if number_in_leadbox == phone:
                print(f"\n   ✅ OK — Telefones já são iguais (sem necessidade de normalização)")
            else:
                print(f"\n   ⚠️  ATENÇÃO — Leadbox retornou {number_in_leadbox} mas função retornou original")
                print(f"   Verificar lógica da função get_leadbox_phone()")
        else:
            print(f"\n   ⚠️  Contato não encontrado no Leadbox")
            print(f"   Fallback para telefone original (comportamento esperado)")


if __name__ == "__main__":
    asyncio.run(main())
