#!/usr/bin/env python3
"""
Script para reprocessar contratos de 21 clientes especificos que nao tem PDF processado.

Uso:
    cd /var/www/phant/agente-ia
    source venv/bin/activate
    python scripts/reprocess_customers_batch.py

Fluxo:
1. Para cada customer_id, busca subscriptions na API Asaas
2. Para cada subscription, busca pagamentos
3. Para cada pagamento, busca documentos PDF
4. Baixa e extrai texto do PDF
5. Envia para Gemini extrair dados estruturados
6. Salva em contract_details
"""

import asyncio
import sys
import os

# Adiciona o diretorio pai ao path para importar app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import Any, Dict, List

from app.config import settings
from app.services.supabase import get_supabase_service
from app.services.asaas import AsaasService
from app.webhooks.asaas import (
    _extract_text_from_pdf,
    _extract_contract_with_gemini,
    _merge_contract_data,
)

# Agent ID do Lazaro
LAZARO_AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# API Key Asaas do Lazaro
ASAAS_API_KEY = "$aact_prod_000MzkwODA2MWY2OGM3MWRlMDU2NWM3MzJlNzZmNGZhZGY6OmE5ZTExNzRkLTA5NjEtNGRjZi05MDlmLTcyZDZkZTVlNDc3Nzo6JGFhY2hfZTVlOTA0NDAtZmNhZi00YTljLWE0ZjgtOGJmZDljZmQwZjk0"

# Delay entre processamentos (segundos)
DELAY_BETWEEN_CUSTOMERS = 2
DELAY_BETWEEN_API_CALLS = 0.3
DELAY_AFTER_GEMINI = 0.8

# Clientes para reprocessar (21)
CUSTOMERS_TO_PROCESS = [
    ("cus_000160786445", "MARI VONE DE FATIMA PASQUETTI"),
    ("cus_000160842964", "ALESSANDRO LUIZ GARDIN"),
    ("cus_000160796328", "ANGELO REIS MOREIRA DELFINO"),
    ("cus_000160799697", "BRENDA CRYSTINA PANIAGO CORREA"),
    ("cus_000160782232", "CARLOS DANIEL DOS SANTOS"),
    ("cus_000160784239", "DESEG SEGURANCA DO TRABALHO LTDA"),
    ("cus_000160792366", "DIEISON SILVA ALVES"),
    ("cus_000160830368", "EPAGANINI CONFEITARIA LTDA"),
    ("cus_000160834742", "FLAVIA CAROLINE ARAUJO DE JESUS"),
    ("cus_000160791069", "GEDER KEMUEL BORGES SANTANA"),
    ("cus_000160790221", "JADERSON RIBEIRO GONCALVES"),
    ("cus_000160788205", "JOAO VITOR LEMES DE OLIVEIRA"),
    ("cus_000160835788", "KALITA VANESSA MATOS SEVERIANO"),
    ("cus_000160789205", "LEILA MARIA DA CRUZ"),
    ("cus_000160797795", "LUCIO JOSE DOMINGUES DA SILVA"),
    ("cus_000160793606", "RAFAEL OLIVEIRA DIAS"),
    ("cus_000160859063", "RL CYCLING INDOOR LTDA"),
    ("cus_000160794589", "SANDRA REGINA PEREIRA BARROS"),
    ("cus_000160798938", "SILVA REFEICOES LTDA"),
    ("cus_000160840620", "VINICIUS CRUVINEL ADVOCACIA"),
    ("cus_000160838286", "WISTON CRISTALDO GOMES CHAVES"),
]


async def process_customer(
    asaas: AsaasService,
    supabase,
    customer_id: str,
    customer_name: str,
) -> Dict[str, Any]:
    """
    Processa um cliente e extrai dados dos PDFs dos contratos.

    Retorna dicionario com status do processamento.
    """
    result = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "status": "error",
        "subscriptions_found": 0,
        "pdfs_processed": 0,
        "equipamentos_found": 0,
        "error": None,
    }

    try:
        # 1. Buscar subscriptions
        print(f"  Buscando subscriptions...")
        subscriptions = await asaas.list_subscriptions_by_customer(customer_id)
        result["subscriptions_found"] = len(subscriptions)

        if not subscriptions:
            print(f"  [AVISO] Sem subscriptions")
            result["status"] = "no_subscriptions"
            return result

        print(f"  Encontradas {len(subscriptions)} subscriptions")

        # 2. Para cada subscription
        for sub in subscriptions:
            subscription_id = sub.get("id")
            if not subscription_id:
                continue

            # Verificar se ja foi processado
            try:
                existing = (
                    supabase.client
                    .table("contract_details")
                    .select("id")
                    .eq("subscription_id", subscription_id)
                    .eq("agent_id", LAZARO_AGENT_ID)
                    .maybe_single()
                    .execute()
                )

                if existing and existing.data:
                    print(f"  [SKIP] Subscription {subscription_id} ja processada")
                    result["status"] = "already_processed"
                    continue
            except Exception as e:
                print(f"    [AVISO] Erro ao verificar se processado: {e}")
                # Continua mesmo se nao conseguir verificar


            # Buscar pagamentos
            await asyncio.sleep(DELAY_BETWEEN_API_CALLS)
            payments = await asaas.list_payments_by_subscription(subscription_id)

            if not payments:
                print(f"  [AVISO] Subscription {subscription_id} sem pagamentos")
                continue

            print(f"  Subscription {subscription_id}: {len(payments)} pagamentos")

            # 3. Buscar PDFs
            all_pdf_data: List[Dict] = []
            all_contract_data: List[Dict] = []

            for payment in payments[:5]:  # Limita a 5
                payment_id = payment.get("id")
                payment_status = payment.get("status", "")

                if not payment_id:
                    continue

                await asyncio.sleep(DELAY_BETWEEN_API_CALLS)
                docs = await asaas.list_payment_documents(payment_id)

                pdf_docs = [d for d in docs if d.get("name", "").lower().endswith(".pdf")]

                for pdf_doc in pdf_docs:
                    doc_url = (
                        pdf_doc.get("file", {}).get("publicAccessUrl") or
                        pdf_doc.get("file", {}).get("downloadUrl")
                    )

                    if not doc_url:
                        continue

                    try:
                        # Baixar PDF
                        print(f"    Baixando PDF {pdf_doc.get('name')}...")
                        pdf_bytes = await asaas.download_document(doc_url)

                        # Extrair texto
                        pdf_text = _extract_text_from_pdf(pdf_bytes)

                        if not pdf_text or len(pdf_text.strip()) < 50:
                            print(f"    [AVISO] PDF sem texto legivel")
                            continue

                        # Extrair com Gemini
                        print(f"    Extraindo dados com Gemini...")
                        contract_data = await _extract_contract_with_gemini(pdf_text)

                        if contract_data:
                            all_contract_data.append(contract_data)
                            all_pdf_data.append({
                                "payment_id": payment_id,
                                "doc_id": pdf_doc.get("id"),
                                "doc_name": pdf_doc.get("name"),
                                "doc_url": doc_url,
                            })
                            result["pdfs_processed"] += 1
                            eqs = len(contract_data.get("equipamentos", []))
                            print(f"    [OK] Extraidos {eqs} equipamentos")

                        await asyncio.sleep(DELAY_AFTER_GEMINI)

                    except Exception as e:
                        print(f"    [ERRO] Ao processar PDF: {e}")

            if not all_pdf_data:
                print(f"  [AVISO] Nenhum PDF encontrado para subscription {subscription_id}")
                result["status"] = "no_pdfs"
                continue

            # 4. Merge e salvar
            merged_data = _merge_contract_data(all_contract_data)

            equipamentos = merged_data.get("equipamentos", [])
            qtd_ars = len(equipamentos)
            valor_comercial_total = sum(eq.get("valor_comercial", 0) or 0 for eq in equipamentos)
            result["equipamentos_found"] += qtd_ars

            # Proxima manutencao
            proxima_manutencao = None
            if merged_data.get("data_inicio"):
                try:
                    inicio = datetime.strptime(merged_data["data_inicio"], "%Y-%m-%d")
                    proxima = inicio.replace(month=inicio.month + 6 if inicio.month <= 6 else inicio.month - 6)
                    if inicio.month > 6:
                        proxima = proxima.replace(year=proxima.year + 1)
                    proxima_manutencao = proxima.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Salvar
            record = {
                "agent_id": LAZARO_AGENT_ID,
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "payment_id": all_pdf_data[0]["payment_id"],
                "document_id": ",".join(p["doc_id"] for p in all_pdf_data if p.get("doc_id")),
                "numero_contrato": merged_data.get("numero_contrato"),
                "locatario_nome": merged_data.get("locatario_nome") or customer_name,
                "locatario_cpf_cnpj": merged_data.get("locatario_cpf_cnpj"),
                "locatario_telefone": merged_data.get("locatario_telefone"),
                "locatario_endereco": merged_data.get("locatario_endereco"),
                "fiador_nome": merged_data.get("fiador_nome"),
                "fiador_cpf": merged_data.get("fiador_cpf"),
                "fiador_telefone": merged_data.get("fiador_telefone"),
                "equipamentos": equipamentos,
                "qtd_ars": qtd_ars,
                "valor_comercial_total": valor_comercial_total,
                "endereco_instalacao": merged_data.get("endereco_instalacao"),
                "prazo_meses": merged_data.get("prazo_meses"),
                "data_inicio": merged_data.get("data_inicio"),
                "data_termino": merged_data.get("data_termino"),
                "dia_vencimento": merged_data.get("dia_vencimento"),
                "valor_mensal": merged_data.get("valor_mensal"),
                "proxima_manutencao": proxima_manutencao,
                "pdf_url": all_pdf_data[0]["doc_url"],
                "pdf_filename": ", ".join(p["doc_name"] for p in all_pdf_data if p.get("doc_name")),
                "parsed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            supabase.client.table("contract_details").upsert(
                record,
                on_conflict="subscription_id,agent_id"
            ).execute()

            print(f"  [SALVO] {qtd_ars} equipamentos | R$ {valor_comercial_total:.2f}")
            result["status"] = "success"

        if result["status"] == "error":
            result["status"] = "no_payments"

        return result

    except Exception as e:
        print(f"  [ERRO] {e}")
        result["error"] = str(e)
        return result


async def main():
    """Funcao principal."""
    print("=" * 70)
    print("REPROCESSAMENTO DE CONTRATOS - 21 CLIENTES LAZARO")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Inicializar clientes
    asaas = AsaasService(api_key=ASAAS_API_KEY)
    supabase = get_supabase_service()

    print(f"\nTotal de clientes para processar: {len(CUSTOMERS_TO_PROCESS)}")
    print("-" * 70)

    # Estatisticas
    stats = {
        "total": len(CUSTOMERS_TO_PROCESS),
        "success": 0,
        "no_subscriptions": 0,
        "no_payments": 0,
        "no_pdfs": 0,
        "already_processed": 0,
        "errors": 0,
        "total_pdfs": 0,
        "total_equipamentos": 0,
    }

    # Processar cada cliente
    for i, (customer_id, customer_name) in enumerate(CUSTOMERS_TO_PROCESS, 1):
        print(f"\n[{i}/{stats['total']}] {customer_name}")
        print(f"         Customer ID: {customer_id}")

        result = await process_customer(asaas, supabase, customer_id, customer_name)

        # Atualizar estatisticas
        status = result["status"]
        if status == "success":
            stats["success"] += 1
        elif status == "no_subscriptions":
            stats["no_subscriptions"] += 1
        elif status == "no_payments":
            stats["no_payments"] += 1
        elif status == "no_pdfs":
            stats["no_pdfs"] += 1
        elif status == "already_processed":
            stats["already_processed"] += 1
        else:
            stats["errors"] += 1

        stats["total_pdfs"] += result["pdfs_processed"]
        stats["total_equipamentos"] += result["equipamentos_found"]

        # Delay entre clientes
        if i < len(CUSTOMERS_TO_PROCESS):
            await asyncio.sleep(DELAY_BETWEEN_CUSTOMERS)

    # Relatorio final
    print("\n" + "=" * 70)
    print("RELATORIO FINAL")
    print("=" * 70)
    print(f"Total de clientes:            {stats['total']}")
    print(f"Processados com sucesso:      {stats['success']}")
    print(f"Ja processados anteriormente: {stats['already_processed']}")
    print(f"Sem subscriptions:            {stats['no_subscriptions']}")
    print(f"Sem pagamentos:               {stats['no_payments']}")
    print(f"Sem PDFs:                     {stats['no_pdfs']}")
    print(f"Erros:                        {stats['errors']}")
    print("-" * 70)
    print(f"Total de PDFs processados:    {stats['total_pdfs']}")
    print(f"Total de equipamentos:        {stats['total_equipamentos']}")
    print("=" * 70)
    print(f"Fim: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
