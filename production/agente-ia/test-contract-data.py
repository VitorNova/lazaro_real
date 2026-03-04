"""
Teste para verificar se os dados do contrato são buscados corretamente
"""
import sys
sys.path.insert(0, '/var/www/phant/agente-ia')

# Simular imports necessários
from app.services.supabase import supabase

# Contract ID do teste
CONTRACT_ID = "520bff73-403a-4e1d-92e6-0416f945dc59"

print("=" * 60)
print("TESTE: BUSCAR DADOS DO CONTRATO")
print("=" * 60)
print(f"\nContract ID: {CONTRACT_ID}")

# Buscar contrato
result = supabase.client.table("contract_details").select(
    "id, customer_id, locatario_nome, locatario_telefone, equipamentos, endereco_instalacao, proxima_manutencao"
).eq("id", CONTRACT_ID).maybe_single().execute()

if result.data:
    contract = result.data
    print(f"\n✅ Contrato encontrado!")
    print(f"   Cliente: {contract.get('locatario_nome', 'N/A')}")
    print(f"   Telefone: {contract.get('locatario_telefone', 'N/A')}")
    print(f"   Endereço: {contract.get('endereco_instalacao', 'N/A')}")
    print(f"   Próxima manutenção: {contract.get('proxima_manutencao', 'N/A')}")
    
    equipamentos = contract.get("equipamentos", [])
    if equipamentos:
        print(f"   Equipamentos ({len(equipamentos)}):")
        for i, eq in enumerate(equipamentos, 1):
            marca = eq.get("marca", "N/A")
            btus = eq.get("btus", "N/A")
            tipo = eq.get("tipo", "N/A")
            print(f"      {i}. {marca} {btus} BTUs ({tipo})")
    else:
        print("   Equipamentos: Nenhum cadastrado")
else:
    print(f"\n❌ Contrato NÃO encontrado!")
