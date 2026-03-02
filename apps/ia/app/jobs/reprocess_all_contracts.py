#!/usr/bin/env python3
"""
Job para reprocessar TODOS os contratos e atualizar equipamentos.

Baixa cada PDF/imagem do Asaas e usa Gemini para extrair:
- Marca, modelo, BTUs, patrimonio de cada equipamento
- Dados do locatario, fiador, datas, valores

Uso:
    cd /var/www/phant/agente-ia
    python3 -m app.jobs.reprocess_all_contracts
    python3 -m app.jobs.reprocess_all_contracts --dry-run
    python3 -m app.jobs.reprocess_all_contracts --limit 10
    python3 -m app.jobs.reprocess_all_contracts --contract-id <uuid>
"""
import asyncio
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import aiohttp
import google.generativeai as genai

# Adicionar path do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Carregar .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Credenciais
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

# MIME types suportados
MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.pdf': 'application/pdf',
}


# ============================================================
# PROMPT PARA EXTRACAO DE CONTRATOS (PDF TEXTO)
# ============================================================
PROMPT_PDF_TEXT = """Analise o texto de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da primeira pagina, na PRIMEIRA LINHA do documento.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

Exemplo de onde encontrar (TOPO DO DOCUMENTO):
  ┌──────────────────────────────────────────────┐
  │ CONTRATO DE LOCACAO DE BEM MOVEL **399-1**   │  <-- NUMERO AQUI NO TITULO!
  │ Pelo presente instrumento...                  │
  └──────────────────────────────────────────────┘

Formato: "CONTRATO DE LOCACAO DE BEM MOVEL 399-1" -> numero_contrato = "399-1"
Outros formatos: "Contrato nº 123", "CONTRATO 456-2", "Nº 789"

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
{pdf_text}
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


# ============================================================
# PROMPT PARA EXTRACAO DE CONTRATOS (IMAGEM)
# ============================================================
PROMPT_IMAGE = """Analise esta IMAGEM de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da imagem, na PRIMEIRA LINHA visivel.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

Exemplo de onde encontrar (TOPO DA IMAGEM):
  ┌──────────────────────────────────────────────┐
  │ CONTRATO DE LOCACAO DE BEM MOVEL **399-1**   │  <-- NUMERO AQUI NO TITULO!
  │ Pelo presente instrumento...                  │
  └──────────────────────────────────────────────┘

Formato: "CONTRATO DE LOCACAO DE BEM MOVEL 399-1" -> numero_contrato = "399-1"
Outros formatos: "Contrato nº 123", "CONTRATO 456-2", "Nº 789"

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

Se um campo nao existir, use null. Datas em YYYY-MM-DD. Valores em numero decimal."""


def is_image_file(filename: str) -> bool:
    """Verifica se o arquivo e uma imagem."""
    ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''
    return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']


def is_pdf_file(filename: str) -> bool:
    """Verifica se o arquivo e um PDF."""
    return filename.lower().endswith('.pdf')


async def download_document(url: str, api_key: str) -> bytes:
    """
    Baixa documento do Asaas.

    Args:
        url: URL do documento
        api_key: API key do Asaas

    Returns:
        Bytes do documento
    """
    async with aiohttp.ClientSession() as session:
        headers = {"access_token": api_key}
        async with session.get(url, headers=headers, timeout=60) as response:
            response.raise_for_status()
            return await response.read()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de um PDF usando pymupdf."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        logger.error("[PDF] Erro ao extrair texto: %s", e)
        return ""


async def extract_contract_from_pdf_text(pdf_text: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados do contrato a partir do texto do PDF usando Gemini.
    """
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = PROMPT_PDF_TEXT.format(pdf_text=pdf_text[:8000])

        response = await model.generate_content_async(prompt)
        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI PDF] Erro ao extrair dados: %s", e)
        return None


async def extract_contract_from_image(image_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados de contrato de uma imagem usando Gemini Vision.
    """
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Detectar MIME type pela extensao
        ext = '.' + filename.lower().split('.')[-1] if '.' in filename else '.jpg'
        mime_type = MIME_TYPES.get(ext, 'image/jpeg')

        # Converter para base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        # Criar conteudo multimodal: imagem + prompt
        response = await model.generate_content_async([
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_b64
                }
            },
            PROMPT_IMAGE
        ])

        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI VISION] Erro ao extrair dados da imagem %s: %s", filename, e)
        return None


async def process_contract(
    supabase: Client,
    contract: Dict[str, Any],
    asaas_api_key: str,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Processa um contrato individual.

    Returns:
        Dict com resultado do processamento
    """
    contract_id = contract["id"]
    pdf_url = contract.get("pdf_url")
    pdf_filename = contract.get("pdf_filename", "contrato.pdf")
    locatario = contract.get("locatario_nome", "N/A")
    numero = contract.get("numero_contrato", "N/A")

    result = {
        "id": contract_id,
        "locatario": locatario,
        "numero_contrato": numero,
        "status": "pending",
        "equipamentos_antes": len(contract.get("equipamentos") or []),
        "equipamentos_depois": 0,
        "erro": None
    }

    if not pdf_url:
        result["status"] = "skipped"
        result["erro"] = "Sem PDF URL"
        return result

    try:
        # 1. Baixar documento
        logger.info("  Baixando: %s", pdf_filename)
        doc_bytes = await download_document(pdf_url, asaas_api_key)
        logger.info("  Download: %d bytes", len(doc_bytes))

        # 2. Extrair dados
        contract_data = None

        if is_pdf_file(pdf_filename):
            # Extrair texto do PDF
            pdf_text = extract_text_from_pdf(doc_bytes)
            if pdf_text:
                logger.info("  PDF texto: %d chars", len(pdf_text))
                contract_data = await extract_contract_from_pdf_text(pdf_text)
            else:
                logger.warning("  PDF sem texto, tentando como imagem...")
                contract_data = await extract_contract_from_image(doc_bytes, pdf_filename)
        else:
            # Imagem
            contract_data = await extract_contract_from_image(doc_bytes, pdf_filename)

        if not contract_data:
            result["status"] = "error"
            result["erro"] = "Gemini nao extraiu dados"
            return result

        # 3. Processar equipamentos
        equipamentos = contract_data.get("equipamentos", [])
        result["equipamentos_depois"] = len(equipamentos)

        # Calcular totais
        qtd_ars = len(equipamentos)
        valor_comercial_total = sum(
            eq.get("valor_comercial", 0) or 0 for eq in equipamentos
        )

        # 4. Atualizar banco
        if dry_run:
            result["status"] = "dry-run"
            logger.info("  [DRY-RUN] Seria atualizado: %d equipamentos", qtd_ars)
        else:
            update_data = {
                "equipamentos": equipamentos,
                "qtd_ars": qtd_ars,
                "valor_comercial_total": valor_comercial_total,
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Atualizar outros campos se extraidos
            if contract_data.get("numero_contrato"):
                update_data["numero_contrato"] = contract_data["numero_contrato"]
            if contract_data.get("locatario_nome"):
                update_data["locatario_nome"] = contract_data["locatario_nome"]
            if contract_data.get("locatario_cpf_cnpj"):
                update_data["locatario_cpf_cnpj"] = contract_data["locatario_cpf_cnpj"]
            if contract_data.get("locatario_telefone"):
                update_data["locatario_telefone"] = contract_data["locatario_telefone"]
            if contract_data.get("locatario_endereco"):
                update_data["locatario_endereco"] = contract_data["locatario_endereco"]
            if contract_data.get("fiador_nome"):
                update_data["fiador_nome"] = contract_data["fiador_nome"]
            if contract_data.get("fiador_cpf"):
                update_data["fiador_cpf"] = contract_data["fiador_cpf"]
            if contract_data.get("fiador_telefone"):
                update_data["fiador_telefone"] = contract_data["fiador_telefone"]
            if contract_data.get("endereco_instalacao"):
                update_data["endereco_instalacao"] = contract_data["endereco_instalacao"]
            if contract_data.get("prazo_meses"):
                update_data["prazo_meses"] = contract_data["prazo_meses"]
            if contract_data.get("data_inicio"):
                update_data["data_inicio"] = contract_data["data_inicio"]
            if contract_data.get("data_termino"):
                update_data["data_termino"] = contract_data["data_termino"]
            if contract_data.get("dia_vencimento"):
                update_data["dia_vencimento"] = contract_data["dia_vencimento"]
            if contract_data.get("valor_mensal"):
                update_data["valor_mensal"] = contract_data["valor_mensal"]

            supabase.table("contract_details").update(
                update_data
            ).eq("id", contract_id).execute()

            result["status"] = "success"
            logger.info("  Atualizado: %d equipamentos | R$ %.2f valor comercial",
                       qtd_ars, valor_comercial_total)

        # Log equipamentos
        for eq in equipamentos:
            logger.info("    - Patrim: %s | Marca: %s | Modelo: %s | BTUs: %s",
                       eq.get("patrimonio", "?"),
                       eq.get("marca", "?"),
                       eq.get("modelo", "?"),
                       eq.get("btus", "?"))

        return result

    except Exception as e:
        result["status"] = "error"
        result["erro"] = str(e)
        logger.error("  ERRO: %s", e)
        return result


async def main(
    dry_run: bool = False,
    limit: Optional[int] = None,
    contract_id: Optional[str] = None,
    offset: int = 0
):
    """
    Funcao principal do job.

    Args:
        dry_run: Se True, nao atualiza o banco
        limit: Limitar quantidade de contratos processados
        contract_id: Processar apenas um contrato especifico
        offset: Pular N contratos iniciais
    """
    logger.info("=" * 60)
    logger.info("JOB: Reprocessar Todos os Contratos")
    logger.info("=" * 60)
    logger.info("Modo: %s", "DRY-RUN" if dry_run else "PRODUCAO")
    if limit:
        logger.info("Limite: %d contratos", limit)
    if contract_id:
        logger.info("Contrato especifico: %s", contract_id)
    if offset:
        logger.info("Offset: %d", offset)
    logger.info("=" * 60)

    # Validar credenciais
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("ERRO: SUPABASE_URL ou SUPABASE_KEY nao configuradas")
        return

    if not GOOGLE_API_KEY:
        logger.error("ERRO: GEMINI_API_KEY ou GOOGLE_API_KEY nao configuradas")
        return

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

        # 1. Buscar contratos
        logger.info("[1/3] Buscando contratos...")

        query = supabase.table("contract_details").select(
            "id, agent_id, subscription_id, locatario_nome, numero_contrato, "
            "pdf_url, pdf_filename, equipamentos"
        )

        if contract_id:
            query = query.eq("id", contract_id)
        else:
            query = query.order("created_at", desc=False)
            if offset:
                query = query.range(offset, offset + (limit or 1000) - 1)
            elif limit:
                query = query.limit(limit)

        result = query.execute()
        contracts = result.data or []

        logger.info("Encontrados: %d contratos", len(contracts))

        if not contracts:
            logger.info("Nenhum contrato para processar")
            return

        # 2. Buscar API key do agente (todos sao do mesmo agente ANA)
        agent_id = contracts[0]["agent_id"]
        agent_result = supabase.table("agents").select(
            "asaas_api_key"
        ).eq("id", agent_id).maybe_single().execute()

        if not agent_result.data or not agent_result.data.get("asaas_api_key"):
            logger.error("ERRO: Agente %s nao tem asaas_api_key", agent_id)
            return

        asaas_api_key = agent_result.data["asaas_api_key"]
        logger.info("API Key do Asaas carregada para agente %s", agent_id)

        # 3. Processar cada contrato
        logger.info("[2/3] Processando contratos...")

        stats = {
            "total": len(contracts),
            "success": 0,
            "error": 0,
            "skipped": 0,
            "dry_run": 0
        }
        results = []

        for i, contract in enumerate(contracts):
            logger.info("")
            logger.info("[%d/%d] %s - %s",
                       i + 1 + offset,
                       len(contracts) + offset,
                       contract.get("numero_contrato", "N/A"),
                       contract.get("locatario_nome", "N/A"))

            result = await process_contract(
                supabase=supabase,
                contract=contract,
                asaas_api_key=asaas_api_key,
                dry_run=dry_run
            )

            results.append(result)
            stats[result["status"]] = stats.get(result["status"], 0) + 1

            # Rate limiting para nao sobrecarregar Gemini
            await asyncio.sleep(1)

        # 4. Relatorio final
        logger.info("")
        logger.info("=" * 60)
        logger.info("[3/3] RELATORIO FINAL")
        logger.info("=" * 60)
        logger.info("Total processados: %d", stats["total"])
        logger.info("Sucesso: %d", stats.get("success", 0))
        logger.info("Erros: %d", stats.get("error", 0))
        logger.info("Pulados: %d", stats.get("skipped", 0))
        if dry_run:
            logger.info("Dry-run: %d", stats.get("dry-run", 0))

        # Listar erros
        errors = [r for r in results if r["status"] == "error"]
        if errors:
            logger.info("")
            logger.info("CONTRATOS COM ERRO:")
            for err in errors:
                logger.info("  - %s (%s): %s",
                           err["numero_contrato"],
                           err["locatario"],
                           err["erro"])

        logger.info("=" * 60)
        logger.info("JOB CONCLUIDO")
        logger.info("=" * 60)

    except Exception as e:
        logger.error("ERRO FATAL: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reprocessa todos os contratos")
    parser.add_argument("--dry-run", action="store_true", help="Nao atualiza o banco")
    parser.add_argument("--limit", type=int, help="Limitar quantidade de contratos")
    parser.add_argument("--offset", type=int, default=0, help="Pular N contratos")
    parser.add_argument("--contract-id", type=str, help="Processar contrato especifico")

    args = parser.parse_args()

    asyncio.run(main(
        dry_run=args.dry_run,
        limit=args.limit,
        contract_id=args.contract_id,
        offset=args.offset
    ))
