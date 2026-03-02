#!/usr/bin/env python3
"""
Job para reprocessar contrato sem numero_contrato.

Busca o registro especifico, baixa a imagem (JPEG) e usa Gemini Vision
para extrair o numero_contrato.

Atualiza o registro no banco com o numero extraido.

Uso:
    cd /var/www/phant/agente-ia
    python3 app/jobs/reread_missing_contract.py
    python3 app/jobs/reread_missing_contract.py --dry-run
"""
import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any

import aiohttp
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Configuracao do contrato faltante
CONTRACT_ID = "48eb993b-124e-4e03-996d-2fcd81236b84"
PDF_URL = "https://www.asaas.com/file/public/download/srA31Q7ccEtaokuV9VzJZjpeHIHz9BCqFHagfUlTmZHz4DOoDFSxIRym2uAJWhWZ"
FILENAME = "contrato.jpeg"  # Assumindo JPEG como mencionado

# Credenciais (carregadas do .env ou ambiente)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


async def extract_contract_from_image(image_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados de contrato de uma imagem usando Gemini Vision.

    Funcao copiada de app/webhooks/asaas.py
    """
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Usar mesmo modelo do webhook asaas.py
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Detectar MIME type pela extensao
        ext = '.' + filename.lower().split('.')[-1]
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        mime_type = mime_types.get(ext, 'image/jpeg')

        # Converter para base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        prompt = """ANALISE A IMAGEM com ATENÇÃO.

Esta imagem contém um documento. Leia TODO o texto visível na imagem.

PRIMEIRA LINHA: Geralmente tem o número do contrato. Exemplos:
- "CONTRATO DE LOCAÇÃO 399-1" → numero_contrato = "399-1"
- "Contrato Nº 123-2" → numero_contrato = "123-2"
- "CONTRATO 456" → numero_contrato = "456"

EXTRAIA TODOS OS DADOS VISÍVEIS:
- Número do contrato (procure no cabeçalho/título)
- Nome da pessoa (LOCATÁRIO)
- CPF ou CNPJ
- Equipamentos listados (marca, modelo, patrimônio, BTUS, valores)
- Endereço de instalação
- Datas (início, término, vencimento)
- Valores (mensal, comercial)

NÃO retorne null sem antes ler a imagem com atenção!

Retorne APENAS JSON válido (sem markdown, sem ```)
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
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.read()


async def main(dry_run: bool = False):
    """
    Funcao principal do job.

    Args:
        dry_run: Se True, nao atualiza o banco, apenas mostra o que seria feito
    """
    logger.info("========================================")
    logger.info("JOB: Reprocessar Contrato sem numero_contrato")
    logger.info("========================================")
    logger.info("Contract ID: %s", CONTRACT_ID)
    logger.info("PDF URL: %s", PDF_URL)
    logger.info("Modo: %s", "DRY-RUN (nao atualiza banco)" if dry_run else "PRODUCAO (atualiza banco)")
    logger.info("========================================")

    # Validar credenciais
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("ERRO: SUPABASE_URL ou SUPABASE_KEY nao configuradas")
        logger.error("Configure as variaveis de ambiente ou crie .env")
        return

    if not GOOGLE_API_KEY:
        logger.error("ERRO: GEMINI_API_KEY ou GOOGLE_API_KEY nao configuradas")
        logger.error("Configure as variaveis de ambiente ou crie .env")
        return

    try:
        # 1. Buscar registro no banco
        logger.info("[1/4] Buscando registro no banco...")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

        result = (
            supabase.table("contract_details")
            .select("*")
            .eq("id", CONTRACT_ID)
            .maybe_single()
            .execute()
        )

        if not result.data:
            logger.error("ERRO: Contrato %s nao encontrado no banco", CONTRACT_ID)
            return

        contract = result.data
        agent_id = contract.get("agent_id")
        subscription_id = contract.get("subscription_id")
        customer_id = contract.get("customer_id")
        locatario_nome = contract.get("locatario_nome")
        numero_contrato_atual = contract.get("numero_contrato")

        logger.info("Contrato encontrado:")
        logger.info("  - Agent ID: %s", agent_id)
        logger.info("  - Subscription ID: %s", subscription_id)
        logger.info("  - Customer ID: %s", customer_id)
        logger.info("  - Locatario: %s", locatario_nome)
        logger.info("  - Numero Contrato Atual: %s", numero_contrato_atual or "(VAZIO)")

        # 2. Baixar imagem
        logger.info("[2/4] Baixando imagem do contrato...")

        # Buscar API key do agente
        agent_result = (
            supabase.table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not agent_result.data or not agent_result.data.get("asaas_api_key"):
            logger.error("ERRO: Agent %s nao tem asaas_api_key configurada", agent_id)
            return

        asaas_api_key = agent_result.data["asaas_api_key"]

        logger.info("Baixando de %s...", PDF_URL)
        image_bytes = await download_document(PDF_URL, asaas_api_key)
        logger.info("Download concluido: %d bytes", len(image_bytes))

        # DEBUG: Salvar imagem baixada para inspecao
        debug_path = "/tmp/contrato_debug.jpeg"
        with open(debug_path, "wb") as f:
            f.write(image_bytes)
        logger.info("DEBUG: Imagem salva em %s para inspecao", debug_path)

        # 3. Extrair dados com Gemini Vision
        logger.info("[3/4] Extraindo dados do contrato com Gemini Vision...")
        contract_data = await extract_contract_from_image(image_bytes, FILENAME)

        if not contract_data:
            logger.error("ERRO: Falha ao extrair dados do contrato com Gemini")
            return

        # DEBUG: Mostrar JSON completo retornado pelo Gemini
        logger.info("DEBUG: JSON completo retornado pelo Gemini:")
        logger.info(json.dumps(contract_data, indent=2, ensure_ascii=False))

        numero_contrato_extraido = contract_data.get("numero_contrato")

        logger.info("Dados extraidos com sucesso!")
        logger.info("  - Numero Contrato: %s", numero_contrato_extraido or "(NAO ENCONTRADO)")
        logger.info("  - Locatario Nome: %s", contract_data.get("locatario_nome") or "(NAO ENCONTRADO)")
        logger.info("  - Equipamentos: %d", len(contract_data.get("equipamentos", [])))

        if contract_data.get("equipamentos"):
            logger.info("  - Equipamentos extraidos:")
            for eq in contract_data["equipamentos"]:
                logger.info(
                    "    * Patrimonio: %s | Marca: %s | BTUS: %s | Valor: R$ %.2f",
                    eq.get("patrimonio") or "?",
                    eq.get("marca") or "?",
                    eq.get("btus") or 0,
                    eq.get("valor_comercial") or 0
                )

        if not numero_contrato_extraido:
            logger.warning("AVISO: Numero do contrato nao foi extraido pelo Gemini")
            logger.warning("O campo 'numero_contrato' continuara vazio no banco")

        # 4. Atualizar banco (se nao for dry-run)
        if dry_run:
            logger.info("[4/4] DRY-RUN: Nao atualizando banco")
            logger.info("O que seria atualizado:")
            logger.info("  - numero_contrato: '%s' -> '%s'", numero_contrato_atual or "(vazio)", numero_contrato_extraido or "(vazio)")
            logger.info("  - updated_at: '%s'", datetime.utcnow().isoformat())
        else:
            logger.info("[4/4] Atualizando registro no banco...")

            update_data = {
                "numero_contrato": numero_contrato_extraido,
                "updated_at": datetime.utcnow().isoformat(),
            }

            supabase.table("contract_details").update(
                update_data
            ).eq("id", CONTRACT_ID).execute()

            logger.info("Registro atualizado com sucesso!")
            logger.info("  - numero_contrato: '%s' -> '%s'", numero_contrato_atual or "(vazio)", numero_contrato_extraido or "(vazio)")

        logger.info("========================================")
        logger.info("JOB CONCLUIDO COM SUCESSO")
        logger.info("========================================")

    except Exception as e:
        logger.error("ERRO FATAL: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    # Verificar se --dry-run foi passado
    dry_run = "--dry-run" in sys.argv

    # Executar job
    asyncio.run(main(dry_run=dry_run))
