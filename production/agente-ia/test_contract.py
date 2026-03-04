import warnings
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client
import os

CONTRACT_ID = '520bff73-403a-4e1d-92e6-0416f945dc59'
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')
client = create_client(url, key)

print('=== DADOS DO CONTRATO ===')
result = client.table('contract_details').select(
    'id, customer_id, locatario_nome, locatario_telefone, equipamentos, endereco_instalacao, proxima_manutencao'
).eq('id', CONTRACT_ID).maybe_single().execute()

if result.data:
    c = result.data
    print('Cliente:', c.get('locatario_nome', 'N/A'))
    print('Telefone:', c.get('locatario_telefone', 'N/A'))
    print('Endereco:', c.get('endereco_instalacao', 'N/A'))
    print('Prox manut:', c.get('proxima_manutencao', 'N/A'))
    eq = c.get('equipamentos', [])
    if eq:
        for e in eq:
            print('Equip:', e.get('marca'), e.get('btus'), 'BTUs')
    else:
        print('Equipamentos: Nenhum')
else:
    print('Contrato NAO encontrado!')
