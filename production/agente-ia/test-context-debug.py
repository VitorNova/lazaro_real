"""
Teste rápido para verificar se o contexto está sendo detectado
"""
import asyncio
import sys
sys.path.insert(0, '/var/www/phant/agente-ia')

from app.webhooks.whatsapp import detect_conversation_context, get_context_prompt

# Simular conversation_history com context
history = {
    "messages": [
        {
            "role": "user",
            "parts": [{"text": "Olá, recebi aviso de manutenção"}],
            "context": "manutencao_preventiva",
            "timestamp": "2026-02-12T18:24:34.190Z",
            "contract_id": "520bff73-403a-4e1d-92e6-0416f945dc59"
        },
        {
            "role": "model",
            "parts": [{"text": "Oi RODRIGO!..."}],
            "context": "manutencao_preventiva",
            "timestamp": "2026-02-12T18:24:34.190Z",
            "contract_id": "520bff73-403a-4e1d-92e6-0416f945dc59"
        },
        {
            "role": "user",
            "parts": [{"text": "segunda de manha"}],
            "timestamp": "2026-02-12T18:26:13.044119"
        }
    ]
}

# Simular context_prompts
context_prompts = {
    "manutencao_preventiva": {
        "active": True,
        "prompt": "TESTE - Este é o prompt de manutenção"
    }
}

print("=" * 60)
print("TESTE DE DETECÇÃO DE CONTEXTO")
print("=" * 60)

# Testar detect_conversation_context
context, contract_id = detect_conversation_context(history)
print(f"\n[RESULTADO] context='{context}' contract_id='{contract_id}'")

# Testar get_context_prompt
if context:
    prompt = get_context_prompt(context_prompts, context)
    print(f"[RESULTADO] prompt carregado: {bool(prompt)}")
    if prompt:
        print(f"[RESULTADO] prompt content: '{prompt[:50]}...'")
else:
    print("[RESULTADO] Nenhum contexto detectado!")
