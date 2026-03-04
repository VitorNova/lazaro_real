#!/usr/bin/env python3
"""
Testa renderização de template corrigido
"""

import os
from supabase import create_client

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Pegar credenciais do ambiente
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    print("❌ Erro: variáveis de ambiente não definidas")
    exit(1)

supabase = create_client(supabase_url, supabase_key)

# Buscar template
response = (
    supabase.table("agents")
    .select("asaas_config")
    .eq("id", AGENT_ID)
    .single()
    .execute()
)

asaas_config = response.data.get("asaas_config") or {}
auto_collection = asaas_config.get("autoCollection") or {}
messages = auto_collection.get("messages") or {}
template = messages.get("dueDateTemplate", "")

print("=" * 70)
print("TEMPLATE BRUTO DO BANCO:")
print("=" * 70)
print(repr(template))
print("\n")

print("=" * 70)
print("TEMPLATE RENDERIZADO:")
print("=" * 70)
print(template)
print("\n")

# Substituir variáveis
customer_name = "João Silva"
value = "R$ 150,00"
due_date = "20/02/2026"
link = "https://example.com/pay/123"

rendered = template
rendered = rendered.replace("{{nome}}", customer_name)
rendered = rendered.replace("{{valor}}", value)
rendered = rendered.replace("{{vencimento}}", due_date)
rendered = rendered.replace("{{link}}", link)

print("=" * 70)
print("TEMPLATE FINAL (COMO SERÁ ENVIADO):")
print("=" * 70)
print(rendered)
print("\n")

# Verificar se tem \n literal
if "\\n" in rendered:
    print("❌ ERRO: Ainda contém \\n literal!")
else:
    print("✅ Correto: Newlines estão como quebra de linha real")

# Contar quebras de linha
newline_count = rendered.count("\n")
print(f"\n📊 Quebras de linha: {newline_count}")
