"""
Reclassify Origins Job - Reclassifica leads existentes com o novo prompt de origem.

Este script:
1. Busca leads que precisam de reclassificacao (sem campo 'prova' nos insights)
2. Busca o historico de mensagens de cada lead
3. Usa o observer_prompt do agente para reclassificar
4. Atualiza o campo insights do lead com a nova classificacao (incluindo 'prova')

Uso:
    python -m app.jobs.reclassify_origins

Ou importar e chamar:
    from app.jobs.reclassify_origins import run_reclassify_job
    await run_reclassify_job()
"""

import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Adicionar o diretorio raiz ao path para imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory

from app.config import settings
from app.services.supabase import get_supabase_service

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURACAO
# ============================================================================

# Agente Ana
AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
TABLE_LEADS = "LeadboxCRM_Ana_14e6e5ce"
TABLE_MESSAGES = "leadbox_messages_Ana_14e6e5ce"

# Modelo para classificacao
MODEL_NAME = "gemini-2.0-flash"

# Limites
BATCH_SIZE = 50  # Processar em lotes
DELAY_BETWEEN_CALLS = 2.0  # Segundos entre chamadas para evitar rate limit


# ============================================================================
# FUNCOES AUXILIARES
# ============================================================================

def format_messages_for_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    Formata mensagens para o prompt da IA.

    Marca mensagens do lead como [LEAD - ANALISAR] para indicar que são fontes
    válidas de evidência de origem. Mensagens do assistente são marcadas como
    [RESPOSTA - APENAS CONTEXTO] para indicar que NÃO devem ser usadas como
    evidência de origem do lead.
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])
        text = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text += part["text"]
            elif isinstance(part, str):
                text += part

        if role == "user":
            lines.append(f"[LEAD - ANALISAR]: {text}")
        else:
            lines.append(f"[RESPOSTA - APENAS CONTEXTO]: {text}")

    return "\n".join(lines)


def needs_reclassification(lead: Dict[str, Any]) -> bool:
    """
    Verifica se o lead precisa ser reclassificado.

    Criterios:
    - Nao tem insights OU
    - Insights nao tem 'prova' OU
    - lead_origin e 'whatsapp', NULL ou 'null' (string)
    """
    insights = lead.get("insights")
    lead_origin = lead.get("lead_origin")

    # Se nao tem insights, precisa classificar
    if not insights:
        return True

    # Se ja tem prova, nao precisa reclassificar
    if isinstance(insights, dict) and insights.get("prova"):
        return False

    # Se lead_origin e whatsapp, null ou string 'null', precisa reclassificar
    if lead_origin in (None, "null", "whatsapp"):
        return True

    # Se tem origem mas nao tem prova, precisa reclassificar
    if not insights.get("prova"):
        return True

    return False


async def classify_lead_origin(
    observer_prompt: str,
    messages: List[Dict[str, Any]],
    api_key: str,
    max_retries: int = 5,
) -> Optional[Dict[str, Any]]:
    """
    Classifica a origem de um lead usando o prompt do observer.

    Args:
        observer_prompt: Prompt de classificacao do agente
        messages: Lista de mensagens da conversa
        api_key: Chave da API do Gemini
        max_retries: Numero maximo de tentativas em caso de rate limit

    Returns:
        Dict com classificacao ou None se falhar
    """
    # Configurar Gemini
    genai.configure(api_key=api_key)

    # Formatar historico
    historico = format_messages_for_prompt(messages)

    # Instrução explícita sobre análise de roles
    instrucao_roles = """
REGRA CRÍTICA DE ANÁLISE DE ORIGEM:
- Leia TODA a conversa para entender o contexto
- Extraia evidências de origem APENAS das mensagens marcadas como [LEAD - ANALISAR]
- IGNORE links e menções em [RESPOSTA - APENAS CONTEXTO] para fins de identificar origem
- Se o lead envia link do Instagram ou menciona Instagram → origem = instagram
- Se a resposta/assistente menciona Instagram → NÃO É evidência de origem do lead

"""

    # Substituir placeholder no prompt e adicionar instrução
    prompt = instrucao_roles + observer_prompt.replace("{historico}", historico)

    # Safety settings
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Criar modelo
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=GenerationConfig(
            temperature=0.1,  # Baixa temperatura para consistencia
            max_output_tokens=500,
        ),
        safety_settings=safety_settings,
    )

    # Tentar com retry e exponential backoff
    for attempt in range(max_retries):
        try:
            # Gerar resposta
            response = await model.generate_content_async(prompt)
            response_text = response.text.strip()

            # Extrair JSON da resposta
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group())
                return result

            logger.warning(f"Resposta nao contem JSON valido: {response_text[:100]}")
            return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                # Rate limit - esperar com exponential backoff
                wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s, 40s, 80s
                logger.warning(f"Rate limit atingido, aguardando {wait_time}s antes de retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Erro na classificacao: {e}")
                return None

    logger.error(f"Falha apos {max_retries} tentativas")
    return None


# ============================================================================
# JOB PRINCIPAL
# ============================================================================

async def run_reclassify_job(
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executa o job de reclassificacao de origens.

    Args:
        dry_run: Se True, apenas simula sem salvar
        limit: Limita o numero de leads a processar (para testes)

    Returns:
        Dict com estatisticas da execucao
    """
    stats = {
        "total_leads": 0,
        "needs_reclassification": 0,
        "processed": 0,
        "success": 0,
        "errors": 0,
        "skipped_no_messages": 0,
        "origins_found": {},
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
    }

    logger.info("=" * 60)
    logger.info("INICIANDO JOB DE RECLASSIFICACAO DE ORIGENS")
    logger.info(f"Agente: {AGENT_ID}")
    logger.info(f"Tabela Leads: {TABLE_LEADS}")
    logger.info(f"Tabela Mensagens: {TABLE_MESSAGES}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info(f"Limit: {limit or 'Sem limite'}")
    logger.info("=" * 60)

    try:
        # Inicializar servicos
        supabase = get_supabase_service()

        # Buscar observer_prompt do agente
        agent = supabase.get_agent_by_id(AGENT_ID)
        if not agent:
            logger.error(f"Agente {AGENT_ID} nao encontrado!")
            return stats

        observer_prompt = agent.get("observer_prompt")
        if not observer_prompt:
            logger.error("Agente nao tem observer_prompt configurado!")
            return stats

        # Usar API key global para evitar quota esgotada do agente
        # (o job roda em batch e pode exceder quota do agente)
        api_key = settings.google_api_key

        logger.info(f"Observer prompt encontrado ({len(observer_prompt)} chars)")
        logger.info(f"Usando API key global do projeto")

        # Buscar todos os leads
        all_leads = supabase.get_all_leads(TABLE_LEADS, limit=1000)
        stats["total_leads"] = len(all_leads)
        logger.info(f"Total de leads na tabela: {stats['total_leads']}")

        # Filtrar leads que precisam reclassificacao
        leads_to_process = [lead for lead in all_leads if needs_reclassification(lead)]
        stats["needs_reclassification"] = len(leads_to_process)
        logger.info(f"Leads que precisam reclassificacao: {stats['needs_reclassification']}")

        # Aplicar limite se especificado
        if limit:
            leads_to_process = leads_to_process[:limit]
            logger.info(f"Processando apenas {limit} leads (limite)")

        # Processar cada lead
        for i, lead in enumerate(leads_to_process):
            lead_id = lead.get("id")
            lead_name = lead.get("nome", "Sem nome")
            remotejid = lead.get("remotejid")
            current_origin = lead.get("lead_origin")

            logger.info(f"[{i+1}/{len(leads_to_process)}] Processando lead {lead_id}: {lead_name}")
            logger.info(f"  Origem atual: {current_origin}")

            stats["processed"] += 1

            if not remotejid:
                logger.warning(f"  Lead {lead_id} sem remotejid, pulando...")
                stats["skipped_no_messages"] += 1
                continue

            # Buscar historico de mensagens
            history = supabase.get_conversation_history(TABLE_MESSAGES, remotejid)
            if not history or not history.get("messages"):
                logger.warning(f"  Lead {lead_id} sem historico de mensagens, pulando...")
                stats["skipped_no_messages"] += 1
                continue

            messages = history.get("messages", [])
            logger.info(f"  Mensagens encontradas: {len(messages)}")

            # Classificar origem
            classification = await classify_lead_origin(
                observer_prompt=observer_prompt,
                messages=messages[-30:],  # Ultimas 30 mensagens
                api_key=api_key,
            )

            if not classification:
                logger.error(f"  Falha ao classificar lead {lead_id}")
                stats["errors"] += 1
                continue

            origem = classification.get("origem", "whatsapp")
            confianca = classification.get("confianca", "baixa")
            prova = classification.get("prova")
            motivo = classification.get("motivo")

            logger.info(f"  Classificacao: {origem} (confianca: {confianca})")
            if prova:
                logger.info(f"  Prova: {prova[:80]}...")

            # Atualizar estatisticas de origens
            stats["origins_found"][origem] = stats["origins_found"].get(origem, 0) + 1

            if dry_run:
                logger.info(f"  [DRY RUN] Nao salvando alteracoes")
                stats["success"] += 1
            else:
                # Preparar dados para update
                current_insights = lead.get("insights") or {}

                # Mesclar com insights existentes
                new_insights = {
                    **current_insights,
                    "origem": origem,
                    "origin": origem,  # Compatibilidade
                    "confianca": confianca,
                    "motivo": motivo,
                    "prova": prova,
                    "url_anuncio": classification.get("url_anuncio"),
                    "reclassified_at": datetime.utcnow().isoformat(),
                }

                update_data = {
                    "insights": new_insights,
                }

                # So atualiza lead_origin se for diferente de whatsapp
                if origem and origem != "whatsapp":
                    update_data["lead_origin"] = origem

                try:
                    supabase.update_lead(TABLE_LEADS, lead_id, update_data)
                    logger.info(f"  Lead {lead_id} atualizado com sucesso!")
                    stats["success"] += 1
                except Exception as e:
                    logger.error(f"  Erro ao atualizar lead {lead_id}: {e}")
                    stats["errors"] += 1

            # Delay entre chamadas para evitar rate limit
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

        stats["finished_at"] = datetime.utcnow().isoformat()

        # Log final
        logger.info("=" * 60)
        logger.info("JOB FINALIZADO")
        logger.info(f"Total de leads: {stats['total_leads']}")
        logger.info(f"Precisavam reclassificacao: {stats['needs_reclassification']}")
        logger.info(f"Processados: {stats['processed']}")
        logger.info(f"Sucesso: {stats['success']}")
        logger.info(f"Erros: {stats['errors']}")
        logger.info(f"Sem mensagens: {stats['skipped_no_messages']}")
        logger.info(f"Origens encontradas: {stats['origins_found']}")
        logger.info("=" * 60)

        return stats

    except Exception as e:
        logger.error(f"Erro fatal no job: {e}", exc_info=True)
        stats["errors"] += 1
        stats["finished_at"] = datetime.utcnow().isoformat()
        return stats


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reclassifica origens de leads")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula sem salvar alteracoes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita o numero de leads a processar",
    )

    args = parser.parse_args()

    # Executar job
    stats = asyncio.run(run_reclassify_job(
        dry_run=args.dry_run,
        limit=args.limit,
    ))

    # Imprimir resultado final
    print("\n" + "=" * 60)
    print("RESULTADO FINAL:")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    print("=" * 60)
