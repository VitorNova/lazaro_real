#!/usr/bin/env python3
"""
Script de teste para envio de cobrança via WhatsApp
Testa a função de envio usando uma cobrança real do agente Ana
"""

import asyncio
import sys
import os
import logging
from datetime import date

# Adicionar o diretório do projeto ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.supabase import get_supabase_service
from app.services.uazapi import UazapiService
from app.jobs.billing_charge import (
    format_message,
    get_customer_phone,
    phone_to_remotejid,
    DEFAULT_MESSAGES,
    format_brl,
)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# NÚMERO DE TESTE (não envia para o cliente real)
TEST_PHONE = "556697194084"

# ID do agente Ana
AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

async def get_agent_config():
    """Busca configuração do agente Ana"""
    supabase = get_supabase_service()
    response = (
        supabase.client.table("agents")
        .select("id, name, uazapi_base_url, uazapi_token, uazapi_instance_id, asaas_config")
        .eq("id", AGENT_ID)
        .single()
        .execute()
    )
    return response.data

async def get_test_cobranca():
    """Busca a cobrança de teste do banco"""
    supabase = get_supabase_service()
    response = (
        supabase.client.table("asaas_cobrancas")
        .select("id, customer_id, customer_name, value, due_date, status, invoice_url, bank_slip_url, billing_type")
        .eq("agent_id", AGENT_ID)
        .eq("status", "PENDING")
        .limit(1)
        .execute()
    )

    if not response.data:
        logger.error("Nenhuma cobrança PENDING encontrada para o agente Ana")
        return None

    return response.data[0]

async def main():
    logger.info("=" * 60)
    logger.info("TESTE DE ENVIO DE COBRANÇA VIA WHATSAPP")
    logger.info("=" * 60)

    # 1. Buscar configuração do agente
    logger.info(f"\n1️⃣ Buscando configuração do agente Ana ({AGENT_ID[:8]}...)")
    agent = await get_agent_config()

    if not agent:
        logger.error("❌ Agente não encontrado")
        return

    logger.info(f"✅ Agente encontrado: {agent['name']}")
    logger.info(f"   UAZAPI URL: {agent.get('uazapi_base_url')}")
    logger.info(f"   UAZAPI Token: {'*' * 20 if agent.get('uazapi_token') else 'NÃO CONFIGURADO'}")

    # 2. Buscar cobrança de teste
    logger.info(f"\n2️⃣ Buscando cobrança PENDING do agente...")
    payment = await get_test_cobranca()

    if not payment:
        logger.error("❌ Nenhuma cobrança encontrada")
        return

    logger.info(f"✅ Cobrança encontrada:")
    logger.info(f"   ID: {payment['id']}")
    logger.info(f"   Cliente: {payment['customer_name']}")
    logger.info(f"   Valor: {format_brl(float(payment['value']))}")
    logger.info(f"   Vencimento: {payment['due_date']}")
    logger.info(f"   Link: {payment.get('invoice_url') or payment.get('bank_slip_url') or 'Sem link'}")

    # 3. Montar mensagem
    logger.info(f"\n3️⃣ Montando mensagem de cobrança...")

    # Pegar template da configuração do agente ou usar default
    asaas_config = agent.get("asaas_config") or {}
    auto_collection = asaas_config.get("autoCollection") or {}
    messages = auto_collection.get("messages") or {}

    # Usar template de "vencimento hoje" (D0)
    template = messages.get("dueDateTemplate") or DEFAULT_MESSAGES["dueDate"]

    message = format_message(
        template,
        payment["customer_name"],
        float(payment["value"]),
        payment["due_date"],
        payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
    )

    logger.info(f"✅ Mensagem montada:")
    logger.info(f"   Template usado: {'dueDateTemplate (customizado)' if 'dueDateTemplate' in messages else 'dueDateTemplate (default)'}")
    logger.info(f"\n   Texto da mensagem:")
    logger.info(f"   {'-' * 50}")
    for line in message.split('\n'):
        logger.info(f"   {line}")
    logger.info(f"   {'-' * 50}")

    # 4. Enviar mensagem
    logger.info(f"\n4️⃣ Enviando mensagem via WhatsApp...")
    logger.info(f"   ⚠️  ATENÇÃO: Enviando para número de TESTE: {TEST_PHONE}")
    logger.info(f"   (não será enviado para o número real do cliente)")

    if not agent.get("uazapi_base_url") or not agent.get("uazapi_token"):
        logger.error("❌ Configuração UAZAPI incompleta no agente")
        return

    # Criar cliente UAZAPI
    uazapi_client = UazapiService(
        base_url=agent["uazapi_base_url"],
        api_key=agent["uazapi_token"],
    )

    try:
        result = await uazapi_client.send_text_message(TEST_PHONE, message)

        if result.get("success"):
            logger.info(f"✅ Mensagem enviada com sucesso!")
            logger.info(f"   Response: {result}")
        else:
            logger.error(f"❌ Erro ao enviar mensagem: {result.get('error')}")
            logger.error(f"   Response completo: {result}")

    except Exception as e:
        logger.error(f"❌ Exceção ao enviar mensagem: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info(f"\n" + "=" * 60)
    logger.info("TESTE FINALIZADO")
    logger.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
