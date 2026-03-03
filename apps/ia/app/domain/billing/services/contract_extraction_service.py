"""
Servico de extracao de dados de contratos via PDF/Imagem + Gemini.

Responsavel por:
- Processar CUSTOMER_CREATED em background (busca PDFs de assinaturas)
- Processar SUBSCRIPTION_CREATED em background
- Extrair texto de PDFs com pymupdf
- Extrair dados estruturados com Gemini (texto e visao)
- Corrigir valores comerciais mal interpretados
- Merge de dados de multiplos PDFs

Extraido de: app/webhooks/pagamentos.py (Fase 3.7)
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymupdf
import google.generativeai as genai
from dateutil.relativedelta import relativedelta

from app.config import settings
from app.services.gateway_pagamento import AsaasService
from app.services.supabase import get_supabase_service
from app.core.utils.retry import async_retry
from app.domain.billing.models.payment import SUPPORTED_EXTENSIONS, MIME_TYPES

logger = logging.getLogger(__name__)


async def processar_customer_created_background(
    customer_id: str,
    customer_name: str,
    agent_id: str,
) -> None:
    """
    Processa CUSTOMER_CREATED em background.

    Fluxo:
    1. Busca assinaturas do cliente
    2. Para cada assinatura, busca pagamentos
    3. Para cada pagamento, busca documentos PDF
    4. Extrai texto do PDF com pymupdf
    5. Envia para Gemini extrair dados estruturados
    6. Salva em contract_details
    """
    logger.info("[CUSTOMER_CREATED] Iniciando processamento background para %s (%s)", customer_id, customer_name)

    try:
        # Busca a API key do agente
        supabase = get_supabase_service()
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data or not result.data.get("asaas_api_key"):
            logger.error("[CUSTOMER_CREATED] Agent %s nao tem asaas_api_key", agent_id)
            return

        asaas_api_key = result.data["asaas_api_key"]
        asaas = AsaasService(api_key=asaas_api_key)

        # 1. Listar assinaturas do cliente
        logger.info("[CUSTOMER_CREATED] Buscando assinaturas de %s...", customer_id)
        subscriptions = await asaas.list_subscriptions_by_customer(customer_id)

        if not subscriptions:
            logger.info("[CUSTOMER_CREATED] Cliente %s nao tem assinaturas", customer_id)
            return

        logger.info("[CUSTOMER_CREATED] Encontradas %d assinaturas", len(subscriptions))

        # 2. Para cada assinatura, buscar PDFs
        for sub in subscriptions:
            subscription_id = sub.get("id")
            if not subscription_id:
                continue

            logger.info("[CUSTOMER_CREATED] Processando assinatura %s...", subscription_id)

            # Verificar se ja foi processado
            try:
                existing = (
                    supabase.client
                    .table("contract_details")
                    .select("id")
                    .eq("subscription_id", subscription_id)
                    .eq("agent_id", agent_id)
                    .maybe_single()
                    .execute()
                )

                if existing and existing.data:
                    logger.info("[CUSTOMER_CREATED] Assinatura %s ja processada, pulando", subscription_id)
                    continue
            except Exception as e:
                logger.warning("[CUSTOMER_CREATED] Erro ao verificar contract_details existente: %s", e)

            # Buscar pagamentos
            await asyncio.sleep(0.2)  # Rate limit
            payments = await asaas.list_payments_by_subscription(subscription_id)

            if not payments:
                logger.debug("[CUSTOMER_CREATED] Assinatura %s sem pagamentos", subscription_id)
                continue

            logger.info("[CUSTOMER_CREATED] Encontrados %d pagamentos", len(payments))

            # 3. Buscar PDFs de todos os pagamentos
            all_pdf_data: List[Dict[str, Any]] = []
            all_contract_data: List[Dict[str, Any]] = []

            for payment in payments[:5]:  # Limita a 5 pagamentos
                payment_id = payment.get("id")
                if not payment_id:
                    continue

                await asyncio.sleep(0.2)  # Rate limit
                docs = await asaas.list_payment_documents(payment_id)

                # Filtrar documentos suportados (PDF + imagens)
                supported_docs = [
                    d for d in docs
                    if any(d.get("name", "").lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS)
                ]

                for doc in supported_docs:
                    doc_url = (
                        doc.get("file", {}).get("publicAccessUrl") or
                        doc.get("file", {}).get("downloadUrl")
                    )

                    if not doc_url:
                        continue

                    doc_name = doc.get("name", "")
                    doc_name_lower = doc_name.lower()

                    try:
                        # 4. Baixar documento
                        logger.info("[CUSTOMER_CREATED] Baixando documento %s...", doc_name)
                        doc_bytes = await asaas.download_document(doc_url)

                        # 5. Extrair dados baseado no tipo de arquivo
                        contract_data = None

                        if doc_name_lower.endswith(".pdf"):
                            # Fluxo PDF: pymupdf + Gemini Text
                            pdf_text = extract_text_from_pdf(doc_bytes)

                            if not pdf_text or len(pdf_text.strip()) < 50:
                                logger.warning("[CUSTOMER_CREATED] PDF %s sem texto legivel", doc_name)
                                continue

                            logger.info("[CUSTOMER_CREATED] Extraindo dados do PDF com Gemini...")
                            contract_data = await extract_contract_with_gemini(pdf_text)
                        else:
                            # Fluxo Imagem: Gemini Vision direto
                            logger.info("[CUSTOMER_CREATED] Extraindo dados da imagem com Gemini Vision...")
                            contract_data = await extract_contract_from_image(doc_bytes, doc_name)

                        if contract_data:
                            # Corrigir valores que parecem errados (2.70 -> 2700.00)
                            contract_data = corrigir_valores_comerciais(contract_data)
                            all_contract_data.append(contract_data)
                            all_pdf_data.append({
                                "payment_id": payment_id,
                                "doc_id": doc.get("id"),
                                "doc_name": doc_name,
                                "doc_url": doc_url,
                            })
                            logger.info(
                                "[CUSTOMER_CREATED] Extraidos %d equipamentos de %s",
                                len(contract_data.get("equipamentos", [])),
                                doc_name
                            )

                        await asyncio.sleep(0.5)  # Rate limit Gemini

                    except Exception as e:
                        logger.warning("[CUSTOMER_CREATED] Erro ao processar documento %s: %s", doc_name, e)

            if not all_pdf_data:
                logger.info("[CUSTOMER_CREATED] Nenhum documento encontrado para assinatura %s", subscription_id)
                continue

            # 6. Merge dados de todos os PDFs
            merged_data = merge_contract_data(all_contract_data)

            # Salvar contrato
            await _salvar_contract_details(
                supabase=supabase,
                merged_data=merged_data,
                all_pdf_data=all_pdf_data,
                subscription_id=subscription_id,
                customer_id=customer_id,
                customer_name=customer_name,
                agent_id=agent_id,
                log_prefix="[CUSTOMER_CREATED]"
            )

        logger.info("[CUSTOMER_CREATED] Processamento concluido para cliente %s", customer_id)

    except Exception as e:
        logger.error("[CUSTOMER_CREATED] Erro no processamento background: %s", e, exc_info=True)


@async_retry(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
async def processar_subscription_created_background(
    subscription_id: str,
    customer_id: str,
    agent_id: str,
    force_reprocess: bool = False,
) -> None:
    """
    Processa SUBSCRIPTION_CREATED em background.

    Similar ao CUSTOMER_CREATED, mas parte diretamente da subscription.
    Util quando o cliente ja existe e o Asaas nao envia CUSTOMER_CREATED.

    Fluxo:
    1. Busca pagamentos da subscription
    2. Para cada pagamento, busca documentos PDF
    3. Extrai texto do PDF com pymupdf
    4. Envia para Gemini extrair dados estruturados
    5. Salva em contract_details
    """
    logger.info(
        "[SUBSCRIPTION_CREATED] Iniciando processamento background para subscription %s (customer %s)",
        subscription_id, customer_id
    )

    try:
        # Busca a API key do agente
        supabase = get_supabase_service()
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data or not result.data.get("asaas_api_key"):
            logger.error("[SUBSCRIPTION_CREATED] Agent %s nao tem asaas_api_key", agent_id)
            return

        asaas_api_key = result.data["asaas_api_key"]
        asaas = AsaasService(api_key=asaas_api_key)

        # Verificar se ja foi processado (ignorar se force_reprocess=True)
        if not force_reprocess:
            try:
                existing = (
                    supabase.client
                    .table("contract_details")
                    .select("id")
                    .eq("subscription_id", subscription_id)
                    .eq("agent_id", agent_id)
                    .maybe_single()
                    .execute()
                )

                if existing and existing.data:
                    logger.info("[SUBSCRIPTION_CREATED] Subscription %s ja processada, pulando", subscription_id)
                    return
            except Exception as e:
                logger.warning("[SUBSCRIPTION_CREATED] Erro ao verificar contract_details existente: %s", e)
                # Continua o processamento mesmo com erro na verificacao
        else:
            logger.info("[SUBSCRIPTION_CREATED] Reprocessamento forcado para subscription %s", subscription_id)

        # Buscar pagamentos da subscription
        logger.info("[SUBSCRIPTION_CREATED] Buscando pagamentos da subscription %s...", subscription_id)
        payments = await asaas.list_payments_by_subscription(subscription_id)

        if not payments:
            logger.info("[SUBSCRIPTION_CREATED] Subscription %s sem pagamentos ainda", subscription_id)
            return

        logger.info("[SUBSCRIPTION_CREATED] Encontrados %d pagamentos", len(payments))

        # Buscar PDFs de todos os pagamentos
        all_pdf_data: List[Dict[str, Any]] = []
        all_contract_data: List[Dict[str, Any]] = []

        for payment in payments[:5]:  # Limita a 5 pagamentos
            payment_id = payment.get("id")
            if not payment_id:
                continue

            await asyncio.sleep(0.2)  # Rate limit
            docs = await asaas.list_payment_documents(payment_id)

            # Filtrar documentos suportados (PDF + imagens)
            supported_docs = [
                d for d in docs
                if any(d.get("name", "").lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS)
            ]

            for doc in supported_docs:
                doc_url = (
                    doc.get("file", {}).get("publicAccessUrl") or
                    doc.get("file", {}).get("downloadUrl")
                )

                if not doc_url:
                    continue

                doc_name = doc.get("name", "")
                doc_name_lower = doc_name.lower()

                try:
                    # Baixar documento
                    logger.info("[SUBSCRIPTION_CREATED] Baixando documento %s...", doc_name)
                    doc_bytes = await asaas.download_document(doc_url)

                    # Extrair dados baseado no tipo de arquivo
                    contract_data = None

                    if doc_name_lower.endswith(".pdf"):
                        # Fluxo PDF: pymupdf + Gemini Text
                        pdf_text = extract_text_from_pdf(doc_bytes)

                        if not pdf_text or len(pdf_text.strip()) < 50:
                            logger.warning("[SUBSCRIPTION_CREATED] PDF %s sem texto legivel", doc_name)
                            continue

                        logger.info("[SUBSCRIPTION_CREATED] Extraindo dados do PDF com Gemini...")
                        contract_data = await extract_contract_with_gemini(pdf_text)
                    else:
                        # Fluxo Imagem: Gemini Vision direto
                        logger.info("[SUBSCRIPTION_CREATED] Extraindo dados da imagem com Gemini Vision...")
                        contract_data = await extract_contract_from_image(doc_bytes, doc_name)

                    if contract_data:
                        # Corrigir valores que parecem errados (2.70 -> 2700.00)
                        contract_data = corrigir_valores_comerciais(contract_data)
                        all_contract_data.append(contract_data)
                        all_pdf_data.append({
                            "payment_id": payment_id,
                            "doc_id": doc.get("id"),
                            "doc_name": doc_name,
                            "doc_url": doc_url,
                        })
                        logger.info(
                            "[SUBSCRIPTION_CREATED] Extraidos %d equipamentos de %s",
                            len(contract_data.get("equipamentos", [])),
                            doc_name
                        )

                    await asyncio.sleep(0.5)  # Rate limit Gemini

                except Exception as e:
                    logger.warning("[SUBSCRIPTION_CREATED] Erro ao processar documento %s: %s", doc_name, e)

        if not all_pdf_data:
            logger.info("[SUBSCRIPTION_CREATED] Nenhum documento encontrado para subscription %s", subscription_id)
            return

        # Merge dados de todos os PDFs
        merged_data = merge_contract_data(all_contract_data)

        # Salvar contrato
        await _salvar_contract_details(
            supabase=supabase,
            merged_data=merged_data,
            all_pdf_data=all_pdf_data,
            subscription_id=subscription_id,
            customer_id=customer_id,
            customer_name=None,
            agent_id=agent_id,
            log_prefix="[SUBSCRIPTION_CREATED]"
        )

        logger.info("[SUBSCRIPTION_CREATED] Processamento concluido para subscription %s", subscription_id)

    except Exception as e:
        logger.error("[SUBSCRIPTION_CREATED] Erro no processamento background: %s", e, exc_info=True)


async def _salvar_contract_details(
    supabase: Any,
    merged_data: Dict[str, Any],
    all_pdf_data: List[Dict[str, Any]],
    subscription_id: str,
    customer_id: str,
    customer_name: Optional[str],
    agent_id: str,
    log_prefix: str,
) -> None:
    """
    Salva dados extraidos na tabela contract_details.

    Verifica duplicatas por numero_contrato antes de inserir.
    """
    # Calcular campos derivados
    equipamentos = merged_data.get("equipamentos", [])
    qtd_ars = len(equipamentos)
    valor_comercial_total = sum(eq.get("valor_comercial") or 0 for eq in equipamentos)

    # Calcular proxima_manutencao = data_inicio + 6 meses
    proxima_manutencao = None
    if merged_data.get("data_inicio"):
        try:
            inicio = datetime.strptime(merged_data["data_inicio"], "%Y-%m-%d")
            proxima = inicio + relativedelta(months=6)
            proxima_manutencao = proxima.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning("%s Erro ao calcular proxima_manutencao: %s", log_prefix, e)

    numero_contrato = merged_data.get("numero_contrato")

    # VERIFICAR DUPLICATA: Se ja existe contrato com mesmo numero_contrato, nao criar novo
    contrato_duplicado = False
    if numero_contrato:
        try:
            existing = supabase.client.table("contract_details").select("id, subscription_id").eq(
                "agent_id", agent_id
            ).eq("numero_contrato", numero_contrato).execute()

            if existing.data and len(existing.data) > 0:
                existing_sub = existing.data[0].get("subscription_id")
                if existing_sub != subscription_id:
                    logger.warning(
                        "%s DUPLICATA DETECTADA! Contrato %s ja existe (subscription %s). Ignorando novo (subscription %s)",
                        log_prefix, numero_contrato, existing_sub, subscription_id
                    )
                    contrato_duplicado = True
        except Exception as e:
            logger.debug("%s Erro ao verificar duplicata: %s", log_prefix, e)

    if not contrato_duplicado:
        record = {
            "agent_id": agent_id,
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "payment_id": all_pdf_data[0]["payment_id"],
            "document_id": ",".join(p["doc_id"] for p in all_pdf_data if p.get("doc_id")),
            "numero_contrato": numero_contrato,
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

        try:
            supabase.client.table("contract_details").upsert(
                record,
                on_conflict="subscription_id,agent_id"
            ).execute()

            logger.info(
                "%s Contrato salvo! Subscription: %s | Contrato: %s | %d equipamentos | R$ %.2f valor comercial",
                log_prefix,
                subscription_id,
                numero_contrato or "N/A",
                qtd_ars,
                valor_comercial_total
            )
        except Exception as e:
            logger.error("%s Erro ao salvar contract_details: %s", log_prefix, e)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de um PDF usando pymupdf."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        logger.error("[PDF] Erro ao extrair texto: %s", e)
        return ""


async def extract_contract_with_gemini(pdf_text: str) -> Optional[Dict[str, Any]]:
    """
    Envia texto do PDF para Gemini e extrai dados estruturados.
    """
    try:
        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = _get_contract_extraction_prompt(pdf_text)

        response = await model.generate_content_async(prompt)
        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI] Erro ao extrair dados do contrato: %s", e)
        return None


async def extract_contract_from_image(image_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados de contrato de uma imagem usando Gemini Vision.

    Suporta JPEG, PNG, GIF e WebP.
    """
    try:
        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Detectar MIME type pela extensao
        ext = '.' + filename.lower().split('.')[-1]
        mime_type = MIME_TYPES.get(ext, 'image/jpeg')

        # Converter para base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        prompt = _get_image_extraction_prompt()

        # Criar conteudo multimodal: imagem + prompt
        response = await model.generate_content_async([
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_b64
                }
            },
            prompt
        ])

        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        logger.info("[GEMINI VISION] Resposta extraida com sucesso de %s", filename)
        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI VISION] Erro ao extrair dados da imagem %s: %s", filename, e)
        return None


def corrigir_valores_comerciais(contract_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Corrige valores comerciais que parecem estar errados devido a confusao de separador decimal.

    O Gemini as vezes interpreta "2.700" (formato BR) como 2.70 (formato US).
    Valores de aluguel de AR-condicionado sao tipicamente entre R$ 1.000 e R$ 10.000.
    Se o valor extraido for < 100, provavelmente esta errado e deve ser multiplicado por 1000.
    """
    if not contract_data:
        return contract_data

    # Corrigir valores comerciais dos equipamentos
    equipamentos = contract_data.get("equipamentos", [])
    for eq in equipamentos:
        valor_comercial = eq.get("valor_comercial")
        if valor_comercial is not None and valor_comercial > 0 and valor_comercial < 100:
            valor_corrigido = valor_comercial * 1000
            logger.warning(
                "[CORRECAO VALOR] Equipamento patrimonio %s: valor_comercial %.2f -> %.2f (multiplicado por 1000)",
                eq.get("patrimonio", "?"),
                valor_comercial,
                valor_corrigido
            )
            eq["valor_comercial"] = valor_corrigido

    # Corrigir valor_mensal se muito baixo
    valor_mensal = contract_data.get("valor_mensal")
    if valor_mensal is not None and valor_mensal > 0 and valor_mensal < 50:
        valor_corrigido = valor_mensal * 1000
        logger.warning(
            "[CORRECAO VALOR] valor_mensal %.2f -> %.2f (multiplicado por 1000)",
            valor_mensal,
            valor_corrigido
        )
        contract_data["valor_mensal"] = valor_corrigido

    return contract_data


def merge_contract_data(data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge dados de multiplos PDFs em um unico registro.
    Campos escalares: usa primeiro valor nao-null.
    Equipamentos: concatena todos os arrays.
    """
    if not data_list:
        return {}

    if len(data_list) == 1:
        return data_list[0]

    result: Dict[str, Any] = {}

    scalar_fields = [
        "numero_contrato", "locatario_nome", "locatario_cpf_cnpj",
        "locatario_telefone", "locatario_endereco", "fiador_nome",
        "fiador_cpf", "fiador_telefone", "endereco_instalacao",
        "prazo_meses", "data_inicio", "data_termino",
        "dia_vencimento", "valor_mensal",
    ]

    for field in scalar_fields:
        for data in data_list:
            if data.get(field) is not None:
                result[field] = data[field]
                break

    # Merge equipamentos
    all_equipamentos = []
    for data in data_list:
        if data.get("equipamentos") and isinstance(data["equipamentos"], list):
            all_equipamentos.extend(data["equipamentos"])

    result["equipamentos"] = all_equipamentos

    return result


def _get_contract_extraction_prompt(pdf_text: str) -> str:
    """Retorna o prompt para extracao de dados de contrato via texto."""
    return f"""Analise o texto de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da primeira pagina, na PRIMEIRA LINHA do documento.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

Exemplo de onde encontrar (TOPO DO DOCUMENTO):
  +----------------------------------------------+
  | CONTRATO DE LOCACAO DE BEM MOVEL **399-1**   |  <-- NUMERO AQUI NO TITULO!
  | Pelo presente instrumento...                  |
  +----------------------------------------------+

Formato: "CONTRATO DE LOCACAO DE BEM MOVEL 399-1" -> numero_contrato = "399-1"
Outros formatos: "Contrato n 123", "CONTRATO 456-2", "N 789"

INSTRUCOES:
- LEIA AS PRIMEIRAS LINHAS do documento para encontrar este numero
- O numero SEMPRE aparece junto ao titulo "CONTRATO DE LOCACAO..."
- NAO procure no meio ou final do documento - o numero esta no TOPO/CABECALHO
- Se nao encontrar no topo, retorne null
- Este numero identifica o contrato de forma unica

IMPORTANTE - Existem DOIS tipos de contrato. Identifique qual e e extraia corretamente:

=== TIPO 1: Tabela com coluna "item" (descricao) ===
Colunas: codigo | item (descricao) | Valor Locacao | Valor Comercial
Exemplo: "000307  PATRIMONIO 0540 - AR CONDICIONADO VG 12.000 BTUS INVERTER   189,00   2.700,00"
- O codigo "000307" NAO e o patrimonio
- Extraia "0540" do texto "PATRIMONIO 0540" na descricao
- BTUS: Extraia da descricao do item (ex: "12.000 BTUS" -> 12000)
- Cada linha = 1 equipamento

=== TIPO 2: Tabela com coluna "MARCA" contendo patrimonios ===
Colunas: MARCA | MODELO | BTUS | VALOR COMERCIAL
Exemplo: "SPRINGER MIDEA, Patrimonios 0329/ 0330/ 0331/ 0332 0333/ 0334  |  CONVENCIONAL  |  9.000 CADA  |  R$2.500,00"
- A marca e "SPRINGER MIDEA"
- Os patrimonios estao apos "Patrimonios" separados por "/" ou espaco: 0329, 0330, 0331, 0332, 0333, 0334
- BTUS: Extraia da coluna BTUS (ex: "9.000 CADA" -> 9000)
- CADA patrimonio = 1 equipamento separado no JSON
- Se ha 11 patrimonios, gere 11 objetos no array "equipamentos" (todos com mesmo btus)

REGRAS GERAIS:
- Patrimonio e sempre um codigo numerico de 3-4 digitos (ex: "0540", "0329", "155")
- Se aparecer "PATRI", "Patrimonio" ou "Patrimonios", extraia os numeros que seguem
- Nunca use o "codigo" da primeira coluna como patrimonio
- BTUS: Sempre extrair como numero inteiro (9.000 -> 9000, 12.000 -> 12000)

Texto do contrato:
---
{pdf_text[:8000]}
---

Retorne APENAS um JSON valido (sem markdown, sem ```) com esta estrutura:
{{
  "numero_contrato": "string ou null",
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {{
      "patrimonio": "string (codigo numerico extraido, ex: '0540' ou '0329')",
      "marca": "string (nome da marca sem os patrimonios)",
      "modelo": "string ou null",
      "btus": 12000,
      "valor_comercial": 2700.00
    }}
  ],
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "YYYY-MM-DD",
  "data_termino": "YYYY-MM-DD",
  "dia_vencimento": 15,
  "valor_mensal": 189.00
}}

Se um campo nao existir, use null. Datas em YYYY-MM-DD. Valores em numero decimal."""


def _get_image_extraction_prompt() -> str:
    """Retorna o prompt para extracao de dados de contrato via imagem."""
    return """Analise esta IMAGEM de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da imagem, na PRIMEIRA LINHA visivel.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

INSTRUCOES:
- OLHE PARA O TOPO DA IMAGEM para encontrar este numero
- O numero SEMPRE aparece junto ao titulo "CONTRATO DE LOCACAO..."
- NAO procure no meio ou final - o numero esta no TOPO/CABECALHO
- Se nao encontrar no topo, retorne null

IMPORTANTE - Leia todo o texto visivel na imagem e extraia:

1. DADOS DO LOCATARIO: Nome, CPF/CNPJ, telefone, endereco
2. DADOS DO FIADOR: Nome, CPF, telefone (se houver)
3. EQUIPAMENTOS: Para cada ar-condicionado, extraia:
   - Patrimonio: codigo numerico de 3-4 digitos (ex: "0540", "0329")
   - Marca: nome da marca (ex: "SPRINGER", "LG", "SAMSUNG")
   - Modelo: modelo do equipamento (ex: "INVERTER", "CONVENCIONAL")
   - BTUS: potencia como numero inteiro (ex: 9000, 12000, 18000)
   - Valor comercial: valor do equipamento em reais

4. CONTRATO: numero, endereco instalacao, prazo em meses, data inicio/termino, dia vencimento, valor mensal

REGRAS:
- Patrimonio e sempre um codigo numerico (NAO e codigo de produto)
- Se aparecer "PATRI", "Patrimonio" ou "Patrimonios", extraia os numeros que seguem
- BTUS: 9.000 -> 9000, 12.000 -> 12000
- Valores monetarios: extraia como numero decimal (2.700,00 -> 2700.00)

Retorne APENAS um JSON valido (sem markdown, sem ```) com esta estrutura:
{
  "numero_contrato": "string ou null",
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {
      "patrimonio": "string (codigo numerico extraido)",
      "marca": "string",
      "modelo": "string ou null",
      "btus": 12000,
      "valor_comercial": 2700.00
    }
  ],
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "YYYY-MM-DD",
  "data_termino": "YYYY-MM-DD",
  "dia_vencimento": 15,
  "valor_mensal": 189.00
}

Se um campo nao existir ou nao for legivel, use null. Datas em YYYY-MM-DD. Valores em numero decimal."""
