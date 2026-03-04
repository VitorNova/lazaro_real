#!/usr/bin/env python3
"""
Script de teste para validar as 4 correções críticas do sistema de cobrança.

Uso:
    python test_billing_critical_fixes.py

Testes:
1. Lock distribuído (Redis)
2. Atomicidade de notificações (stored procedure)
3. Logs sanitizados
4. Dead Letter Queue
"""

import asyncio
import re
import sys
from datetime import datetime

from app.jobs.billing_charge import (
    claim_notification,
    is_billing_charge_running,
    mask_customer_name,
    mask_phone,
    save_to_dead_letter_queue,
)
from app.services.redis import get_redis_service
from app.services.supabase import get_supabase_service


async def test_lock_distribuido():
    """Teste 1: Lock distribuído via Redis"""
    print("\n" + "="*60)
    print("TESTE 1: Lock Distribuído (Redis)")
    print("="*60)

    redis = await get_redis_service()
    lock_key = "lock:billing_job:global"

    # Limpar lock se existir
    await redis.client.delete(lock_key)

    # Tentar adquirir lock
    acquired1 = await redis.client.set(lock_key, "1", nx=True, ex=10)
    print(f"✓ Primeira tentativa de lock: {'SUCESSO' if acquired1 else 'FALHOU'}")

    # Tentar adquirir novamente (deve falhar)
    acquired2 = await redis.client.set(lock_key, "1", nx=True, ex=10)
    print(f"✓ Segunda tentativa de lock: {'BLOQUEADO (correto!)' if not acquired2 else 'SUCESSO (ERRO!)'}")

    # Verificar que lock existe
    is_running = await is_billing_charge_running()
    print(f"✓ Job está rodando? {is_running}")

    # Liberar lock
    await redis.client.delete(lock_key)
    is_running_after = await is_billing_charge_running()
    print(f"✓ Job está rodando após liberar? {is_running_after}")

    # Validar
    if acquired1 and not acquired2 and is_running and not is_running_after:
        print("\n✅ TESTE 1 PASSOU: Lock distribuído funcionando corretamente")
        return True
    else:
        print("\n❌ TESTE 1 FALHOU: Lock distribuído não está funcionando")
        return False


async def test_atomicidade_notificacoes():
    """Teste 2: Atomicidade de notificações (stored procedure)"""
    print("\n" + "="*60)
    print("TESTE 2: Atomicidade de Notificações")
    print("="*60)

    supabase = get_supabase_service()
    test_agent_id = "test_agent_001"
    test_payment_id = f"test_payment_{datetime.now().timestamp()}"
    test_date = "2026-02-19"

    # Limpar notificações de teste antigas
    try:
        supabase.client.table("billing_notifications").delete().eq(
            "agent_id", test_agent_id
        ).execute()
        print("✓ Limpou notificações de teste antigas")
    except Exception as e:
        print(f"⚠ Aviso ao limpar: {e}")

    # Primeira tentativa (deve conseguir clamar)
    claimed1 = await claim_notification(
        agent_id=test_agent_id,
        payment_id=test_payment_id,
        notification_type="overdue",
        scheduled_date=test_date,
        customer_id="test_customer",
        phone="5566991234567",
        days_from_due=-3,
    )
    print(f"✓ Primeira tentativa de clamar: {'CLAMOU' if claimed1 else 'FALHOU'}")

    # Segunda tentativa (deve falhar - já existe)
    claimed2 = await claim_notification(
        agent_id=test_agent_id,
        payment_id=test_payment_id,
        notification_type="overdue",
        scheduled_date=test_date,
        customer_id="test_customer",
        phone="5566991234567",
        days_from_due=-3,
    )
    print(f"✓ Segunda tentativa de clamar: {'BLOQUEADO (correto!)' if not claimed2 else 'CLAMOU (ERRO!)'}")

    # Verificar que existe apenas 1 registro no banco
    response = supabase.client.table("billing_notifications").select("id").eq(
        "agent_id", test_agent_id
    ).eq("payment_id", test_payment_id).execute()

    count = len(response.data or [])
    print(f"✓ Registros no banco: {count} (esperado: 1)")

    # Limpar
    try:
        supabase.client.table("billing_notifications").delete().eq(
            "agent_id", test_agent_id
        ).execute()
        print("✓ Limpou notificações de teste")
    except Exception:
        pass

    # Validar
    if claimed1 and not claimed2 and count == 1:
        print("\n✅ TESTE 2 PASSOU: Atomicidade funcionando (sem duplicatas)")
        return True
    else:
        print("\n❌ TESTE 2 FALHOU: Atomicidade não está funcionando")
        return False


def test_logs_sanitizados():
    """Teste 3: Logs sanitizados"""
    print("\n" + "="*60)
    print("TESTE 3: Logs Sanitizados")
    print("="*60)

    # Testar mask_phone
    phone_original = "5566991234567"
    phone_masked = mask_phone(phone_original)
    print(f"✓ Telefone original: {phone_original}")
    print(f"✓ Telefone mascarado: {phone_masked}")

    # Validar formato (deve ser 5566****4567)
    pattern = r"^\d{4}\*+\d{4}$"
    phone_ok = bool(re.match(pattern, phone_masked))
    print(f"✓ Formato correto? {phone_ok}")

    # Testar mask_customer_name
    name_original = "João da Silva Santos"
    name_masked = mask_customer_name(name_original)
    print(f"✓ Nome original: {name_original}")
    print(f"✓ Nome mascarado: {name_masked}")

    # Validar formato (deve ser J******************)
    name_ok = name_masked[0] == name_original[0] and "*" in name_masked
    print(f"✓ Formato correto? {name_ok}")

    # Validar
    if phone_ok and name_ok:
        print("\n✅ TESTE 3 PASSOU: Mascaramento funcionando corretamente")
        return True
    else:
        print("\n❌ TESTE 3 FALHOU: Mascaramento não está funcionando")
        return False


async def test_dead_letter_queue():
    """Teste 4: Dead Letter Queue"""
    print("\n" + "="*60)
    print("TESTE 4: Dead Letter Queue")
    print("="*60)

    supabase = get_supabase_service()
    test_agent_id = "test_agent_dlq"
    test_payment_id = f"test_payment_dlq_{datetime.now().timestamp()}"

    # Limpar DLQ de testes antigos
    try:
        supabase.client.table("billing_failed_notifications").delete().eq(
            "agent_id", test_agent_id
        ).execute()
        print("✓ Limpou DLQ de testes antigos")
    except Exception as e:
        print(f"⚠ Aviso ao limpar: {e}")

    # Criar payment fake
    payment = {
        "id": test_payment_id,
        "customer_id": "test_customer",
        "customer_name": "Cliente Teste",
        "value": 100.00,
        "due_date": "2026-02-19",
    }

    # Salvar no DLQ (simular timeout)
    await save_to_dead_letter_queue(
        agent_id=test_agent_id,
        payment=payment,
        phone="5566991234567",
        message="Teste de mensagem",
        notification_type="overdue",
        scheduled_date="2026-02-19",
        days_from_due=-3,
        error_message="Connection timeout after 30 seconds",
        dispatch_method="uazapi",
    )
    print("✓ Salvou falha no DLQ (timeout)")

    # Salvar outra falha (rate limit)
    await save_to_dead_letter_queue(
        agent_id=test_agent_id,
        payment=payment,
        phone="5566991234567",
        message="Teste de mensagem 2",
        notification_type="overdue",
        scheduled_date="2026-02-19",
        days_from_due=-3,
        error_message="HTTP 429: Rate limit exceeded",
        dispatch_method="uazapi",
    )
    print("✓ Salvou falha no DLQ (rate_limit)")

    # Verificar que salvou
    response = supabase.client.table("billing_failed_notifications").select(
        "id, failure_reason"
    ).eq("agent_id", test_agent_id).execute()

    records = response.data or []
    print(f"✓ Registros no DLQ: {len(records)}")

    # Validar classificação de erros
    reasons = {r["failure_reason"] for r in records}
    print(f"✓ Tipos de erro classificados: {reasons}")

    has_timeout = "timeout" in reasons
    has_rate_limit = "rate_limit" in reasons
    print(f"✓ Classificou timeout? {has_timeout}")
    print(f"✓ Classificou rate_limit? {has_rate_limit}")

    # Limpar
    try:
        supabase.client.table("billing_failed_notifications").delete().eq(
            "agent_id", test_agent_id
        ).execute()
        print("✓ Limpou DLQ de testes")
    except Exception:
        pass

    # Validar
    if len(records) == 2 and has_timeout and has_rate_limit:
        print("\n✅ TESTE 4 PASSOU: Dead Letter Queue funcionando")
        return True
    else:
        print("\n❌ TESTE 4 FALHOU: Dead Letter Queue não está funcionando")
        return False


async def run_all_tests():
    """Executa todos os testes"""
    print("\n" + "="*60)
    print("TESTES DAS CORREÇÕES CRÍTICAS DO SISTEMA DE COBRANÇA")
    print("="*60)

    results = []

    try:
        # Teste 1: Lock distribuído
        result1 = await test_lock_distribuido()
        results.append(("Lock Distribuído", result1))
    except Exception as e:
        print(f"\n❌ TESTE 1 ERRO: {e}")
        results.append(("Lock Distribuído", False))

    try:
        # Teste 2: Atomicidade
        result2 = await test_atomicidade_notificacoes()
        results.append(("Atomicidade", result2))
    except Exception as e:
        print(f"\n❌ TESTE 2 ERRO: {e}")
        if "does not exist" in str(e):
            print("\n⚠️  MIGRATION NÃO APLICADA!")
            print("Execute: create_claim_billing_notification.sql no Supabase")
        results.append(("Atomicidade", False))

    try:
        # Teste 3: Logs sanitizados
        result3 = test_logs_sanitizados()
        results.append(("Logs Sanitizados", result3))
    except Exception as e:
        print(f"\n❌ TESTE 3 ERRO: {e}")
        results.append(("Logs Sanitizados", False))

    try:
        # Teste 4: Dead Letter Queue
        result4 = await test_dead_letter_queue()
        results.append(("Dead Letter Queue", result4))
    except Exception as e:
        print(f"\n❌ TESTE 4 ERRO: {e}")
        if "does not exist" in str(e):
            print("\n⚠️  MIGRATION NÃO APLICADA!")
            print("Execute: create_billing_failed_notifications.sql no Supabase")
        results.append(("Dead Letter Queue", False))

    # Resumo
    print("\n" + "="*60)
    print("RESUMO DOS TESTES")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{name}: {status}")

    print(f"\nTotal: {passed}/{total} testes passaram")

    if passed == total:
        print("\n🎉 TODOS OS TESTES PASSARAM!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} teste(s) falharam")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
