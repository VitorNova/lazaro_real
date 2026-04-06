# ╔══════════════════════════════════════════════════════════════╗
# ║  EXTRAIR CONTRATO — Ler PDF e dados do contrato              ║
# ╚══════════════════════════════════════════════════════════════╝
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
                            # Validar e normalizar patrimonios
                            contract_data = validar_patrimonios(contract_data)
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

            # 6. Agrupar por numero_contrato e salvar cada contrato separadamente
            grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

            await _salvar_multiplos_contratos(
                supabase=supabase,
                grupos=grupos,
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
                        # Validar e normalizar patrimonios
                        contract_data = validar_patrimonios(contract_data)
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

        # Agrupar por numero_contrato e salvar cada contrato separadamente
        grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

        await _salvar_multiplos_contratos(
            supabase=supabase,
            grupos=grupos,
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
            # on_conflict inclui numero_contrato para permitir multiplos contratos por subscription
            supabase.client.table("contract_details").upsert(
                record,
                on_conflict="subscription_id,agent_id,numero_contrato"
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


def validar_patrimonios(contract_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Valida e normaliza patrimonios extraidos pelo Gemini.

    Regras:
    1. Patrimonio deve ser numerico (rejeita PRD00xxx, PATRIxx etc)
    2. Normaliza para 4 digitos (196 -> 0196, 5 -> 0005)
    3. Codigos de 5-6 digitos (000196) sao normalizados removendo zeros extras
    4. Patrimonio deve estar entre 1 e 999 (range real dos equipamentos)
    5. Se nenhum equipamento, marca com warning
    """
    if not contract_data:
        return contract_data

    equipamentos = contract_data.get("equipamentos", [])

    if not equipamentos:
        contract_data["_warning_no_equipamentos"] = True
        logger.warning("[VALIDACAO] Contrato sem equipamentos extraidos")
        return contract_data

    validos = []
    for eq in equipamentos:
        pat = str(eq.get("patrimonio", "")).strip()

        # Rejeitar vazio
        if not pat:
            logger.warning("[VALIDACAO] Patrimonio vazio, ignorando equipamento")
            continue

        # Rejeitar não-numérico (PRD00xxx, PATRIxx, etc)
        pat_digits = pat.lstrip("0") or "0"
        if not pat.replace("0", "").replace("1", "").replace("2", "").replace(
            "3", ""
        ).replace("4", "").replace("5", "").replace("6", "").replace(
            "7", ""
        ).replace("8", "").replace("9", "").replace("0", "") == "":
            # Forma mais simples: checar se é só dígitos
            pass

        if not pat.isdigit():
            logger.warning(
                "[VALIDACAO] Patrimonio '%s' nao e numerico, rejeitando", pat
            )
            continue

        # Normalizar: remover zeros à esquerda e repad para 4 dígitos
        num = int(pat)
        if num < 1 or num > 999:
            logger.warning(
                "[VALIDACAO] Patrimonio '%s' fora do range (1-999), rejeitando", pat
            )
            continue

        pat_normalizado = str(num).zfill(4)
        eq["patrimonio"] = pat_normalizado
        validos.append(eq)

    removidos = len(equipamentos) - len(validos)
    if removidos > 0:
        logger.warning(
            "[VALIDACAO] %d patrimonio(s) invalido(s) removido(s) de %d total",
            removidos,
            len(equipamentos),
        )

    contract_data["equipamentos"] = validos
    return contract_data


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


def agrupar_contratos_por_numero(
    all_contract_data: List[Dict[str, Any]],
    all_pdf_data: List[Dict[str, Any]],
) -> Dict[str, tuple]:
    """
    Agrupa PDFs pelo numero_contrato extraido.

    Quando multiplos PDFs tem numeros de contrato DIFERENTES,
    cada grupo sera salvo como um contract_details separado.

    Quando multiplos PDFs tem o MESMO numero de contrato,
    serao mergeados em um unico registro (comportamento anterior).

    Args:
        all_contract_data: Lista de dados extraidos de cada PDF
        all_pdf_data: Lista de metadados de cada PDF (doc_id, doc_name, etc)

    Returns:
        Dict[numero_contrato] = (lista_contract_data, lista_pdf_data)
        PDFs sem numero_contrato vao para chave especial "__sem_numero__"
    """
    grupos: Dict[str, tuple] = {}

    for i, contract_data in enumerate(all_contract_data):
        numero = contract_data.get("numero_contrato") or "__sem_numero__"

        if numero not in grupos:
            grupos[numero] = ([], [])

        grupos[numero][0].append(contract_data)
        grupos[numero][1].append(all_pdf_data[i])

    logger.info(
        "[AGRUPAR] %d PDFs agrupados em %d contratos distintos: %s",
        len(all_contract_data),
        len(grupos),
        list(grupos.keys())
    )

    return grupos


async def _salvar_multiplos_contratos(
    supabase: Any,
    grupos: Dict[str, tuple],
    subscription_id: str,
    customer_id: str,
    customer_name: Optional[str],
    agent_id: str,
    log_prefix: str,
) -> None:
    """
    Salva multiplos contratos quando ha PDFs com numeros diferentes.

    Para cada grupo (por numero_contrato):
    1. Faz merge apenas dos PDFs do mesmo numero_contrato
    2. Salva um contract_details separado

    Args:
        grupos: Dict retornado por agrupar_contratos_por_numero()
        Demais args: mesmos de _salvar_contract_details()
    """
    for numero_contrato, (contract_list, pdf_list) in grupos.items():
        # Merge apenas PDFs do mesmo contrato
        merged_data = merge_contract_data(contract_list)

        # Salvar
        await _salvar_contract_details(
            supabase=supabase,
            merged_data=merged_data,
            all_pdf_data=pdf_list,
            subscription_id=subscription_id,
            customer_id=customer_id,
            customer_name=customer_name,
            agent_id=agent_id,
            log_prefix=f"{log_prefix} [{numero_contrato}]"
        )


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

=== TIPO 2: Tabela com coluna "MARCA" contendo patrimonios (em uma linha) ===
Colunas: MARCA | MODELO | BTUS | VALOR COMERCIAL
Exemplo: "SPRINGER MIDEA, Patrimonios 0329/ 0330/ 0331/ 0332 0333/ 0334  |  CONVENCIONAL  |  9.000 CADA  |  R$2.500,00"
- A marca e "SPRINGER MIDEA"
- Os patrimonios estao apos "Patrimonios" separados por "/" ou espaco: 0329, 0330, 0331, 0332, 0333, 0334
- BTUS: Extraia da coluna BTUS (ex: "9.000 CADA" -> 9000)
- CADA patrimonio = 1 equipamento separado no JSON
- Se ha 11 patrimonios, gere 11 objetos no array "equipamentos" (todos com mesmo btus)

=== TIPO 2B: MARCA e Patrimonio na mesma linha, colunas em linhas separadas ===
Neste formato, as colunas MARCA/MODELO/BTUS/VALOR aparecem como ROTULOS seguidos de valores em LINHAS separadas:
Exemplo real:
  "MARCA
   BRAVOLT Patrimonio 0566
   VG Patrimonio 0518
   MODELO
   INVERTER cada
   BTUS
   12.000 cada
   VALOR COMERCIAL
   R$2.700,00 cada"
- Patrimonio vem JUNTO da marca na mesma linha
- Separar marca ("BRAVOLT") do patrimonio ("0566")
- Se diz "12.000 cada", todos os equipamentos tem 12000 BTUs
- Se diz "R$2.700,00 cada", todos tem esse valor comercial
- Gere 1 objeto por patrimonio

=== TIPO 2C: Patrimonios com quantidades e enderecos multiplos ===
Exemplo real:
  "7 - BRAVOLT 12.000BTUS Inverter Patrimonios 0559/ 0560/ 0561/ 0562/ 0563/ 0564 e 0565
   1- LG 22.000BTUS Inverter Patrimonio 0037"
- O numero antes do "-" indica quantidade (7, 1)
- Patrimonios separados por "/" ou "e"
- CADA patrimonio = 1 equipamento com os BTUs da sua linha
- Pode haver MULTIPLOS blocos com enderecos diferentes no mesmo contrato.
  Exemplo: "6 aparelhos, sendo os patrimonios 0571/0572/0573/0574/0575/0576"
  seguido de "4 aparelhos, sendo os patrimonios 0577/0578/0579/0580"
- Extraia TODOS os patrimonios de TODOS os blocos/enderecos

REGRAS GERAIS:
- Patrimonio e sempre um codigo numerico de 1-4 digitos (ex: "0540", "0329", "155", "37")
- Se aparecer "PATRI", "Patrimonio", "Patrimonios" ou "patrimonio", extraia os numeros que seguem
- Nunca use o "codigo" da primeira coluna como patrimonio (ex: PRD00628, PATRI55 NAO sao patrimonios)
- O patrimonio e o numero APOS a palavra "PATRIMONIO" ou "Patrimonio", nao o codigo REF antes
- BTUS: Sempre extrair como numero inteiro (9.000 -> 9000, 12.000 -> 12000)
- Se o contrato menciona multiplos enderecos com diferentes equipamentos, extraia TODOS

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
