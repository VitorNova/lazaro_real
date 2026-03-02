"""
Athena Business Tools - Function calling tools para consultoria de negocios.

Este modulo fornece tools que o Gemini pode chamar para obter
informacoes de negocio consolidadas.

Tools disponiveis:
- get_business_health: Score de saude + indicadores + alertas + recomendacoes
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .metrics import (
    BusinessMetrics,
    calculate_business_metrics,
    get_cached_metrics,
    save_metrics_to_cache,
)
from .prompts import STANDARD_RECOMMENDATIONS

logger = logging.getLogger(__name__)


# ============================================================================
# TOOL: get_business_health
# ============================================================================

async def get_business_health(agent_id: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Retorna score de saude + indicadores + alertas + recomendacoes.

    Esta tool consolida todas as metricas de negocio em um formato
    facil de interpretar pelo Gemini para responder perguntas como:
    - "Como esta meu negocio?"
    - "Qual a saude da empresa?"
    - "O que preciso resolver?"

    Args:
        agent_id: ID do agente (tenant)
        force_refresh: Se True, recalcula mesmo com cache valido

    Returns:
        {
            "score": 78,  # 0-100
            "classificacao": "Saudavel",  # Critico/Atencao/Saudavel/Excelente
            "indicadores": {
                "roi_anual_percent": 62.5,
                "payback_meses": 19,
                "taxa_inadimplencia_percent": 3.2,
                "taxa_realizacao_percent": 95,
                "crescimento_mes_percent": 5.2,
                "total_ars": 327,
                "valor_patrimonio": 927998,
                "faturamento_potencial_mes": 48346,
                "contratos_ativos": 203,
            },
            "comparativo_mes_anterior": {
                "faturamento": "+8%",
                "inadimplencia": "-2pp",  # pontos percentuais
                "contratos": "+5"
            },
            "alertas": [
                {
                    "tipo": "warning",
                    "titulo": "Inadimplencia alta",
                    "mensagem": "Taxa em 5.2%",
                    "acao": "Revisar regua de cobranca"
                }
            ],
            "recomendacoes": [
                "Manter estrategia atual - ROI excelente",
                "Focar em reducao de inadimplencia"
            ],
            "calculated_at": "2026-02-12T10:30:00"
        }
    """
    logger.info(f"[Athena Tool] get_business_health chamado para agent_id={agent_id[:8]}...")

    try:
        # 1. Tentar buscar do cache
        metrics: Optional[BusinessMetrics] = None

        if not force_refresh:
            metrics = await get_cached_metrics(agent_id)

        # 2. Se nao tem cache valido, calcular
        if not metrics:
            logger.info(f"[Athena Tool] Calculando metricas...")
            metrics = await calculate_business_metrics(agent_id)

            # Salvar no cache para proximas consultas
            await save_metrics_to_cache(metrics)

        # 3. Montar resposta
        response = {
            "score": metrics.score_saude,
            "classificacao": metrics.classificacao,
            "indicadores": {
                "roi_anual_percent": round(metrics.roi_anual_percent, 1),
                "payback_meses": round(metrics.payback_meses, 1),
                "taxa_inadimplencia_percent": round(metrics.taxa_inadimplencia, 1),
                "taxa_realizacao_percent": round(metrics.taxa_realizacao, 1),
                "crescimento_mes_percent": round(metrics.crescimento_mes_percent, 1),
                "total_ars": metrics.total_ars,
                "valor_patrimonio": round(metrics.valor_patrimonio, 2),
                "faturamento_potencial_mes": round(metrics.faturamento_potencial_mes, 2),
                "faturamento_realizado_mes": round(metrics.faturamento_realizado_mes, 2),
                "contratos_ativos": metrics.contratos_ativos,
                "total_clientes": metrics.total_clientes,
                "ticket_medio": round(metrics.ticket_medio, 2),
                "valor_inadimplido": round(metrics.valor_inadimplido, 2),
                "qtd_inadimplentes": metrics.qtd_inadimplentes,
                "churn_percent": round(metrics.churn_percent, 1),
                "contratos_novos_mes": metrics.contratos_novos_mes,
            },
            "distribuicao_btus": metrics.distribuicao_btus,
            "alertas": metrics.alertas,
            "recomendacoes": _generate_recommendations(metrics),
            "calculated_at": metrics.calculated_at,
        }

        # 4. Adicionar comparativo resumido (se temos dados)
        response["comparativo_mes_anterior"] = _generate_comparativo(metrics)

        logger.info(
            f"[Athena Tool] Resposta gerada: score={metrics.score_saude}, "
            f"alertas={len(metrics.alertas)}, recomendacoes={len(response['recomendacoes'])}"
        )

        return response

    except Exception as e:
        logger.error(f"[Athena Tool] Erro em get_business_health: {e}", exc_info=True)
        return {
            "score": 0,
            "classificacao": "Erro",
            "indicadores": {},
            "alertas": [{
                "tipo": "critical",
                "titulo": "Erro ao calcular",
                "mensagem": str(e),
                "acao": "Verificar conexao e tentar novamente",
            }],
            "recomendacoes": ["Tente novamente em alguns minutos"],
            "calculated_at": datetime.utcnow().isoformat(),
        }


def _generate_recommendations(metrics: BusinessMetrics) -> List[str]:
    """
    Gera lista de recomendacoes baseadas nas metricas.

    Args:
        metrics: Metricas calculadas

    Returns:
        Lista de recomendacoes priorizadas
    """
    recomendacoes = []

    # Prioridade 1: Problemas criticos
    if metrics.taxa_inadimplencia > 5:
        recomendacoes.extend(STANDARD_RECOMMENDATIONS["inadimplencia_alta"][:2])

    if metrics.churn_percent > 3:
        recomendacoes.extend(STANDARD_RECOMMENDATIONS["churn_alto"][:2])

    # Prioridade 2: Melhorias
    if metrics.roi_anual_percent < 45 and metrics.valor_patrimonio > 0:
        recomendacoes.extend(STANDARD_RECOMMENDATIONS["roi_baixo"][:2])

    if metrics.payback_meses > 24 and metrics.payback_meses < 999:
        recomendacoes.extend(STANDARD_RECOMMENDATIONS["payback_longo"][:1])

    if metrics.crescimento_mes_percent < 0:
        recomendacoes.extend(STANDARD_RECOMMENDATIONS["crescimento_negativo"][:2])

    # Prioridade 3: Manutencao do bom (se tudo OK)
    if not recomendacoes:
        if metrics.roi_anual_percent >= 60:
            recomendacoes.append("ROI excelente - manter estrategia atual")
            recomendacoes.append("Considerar expansao da frota com equipamentos de 12k BTUs")
        elif metrics.roi_anual_percent >= 45:
            recomendacoes.append("ROI bom - focar em otimizacao de custos")
            recomendacoes.append("Avaliar reajuste de precos para contratos antigos")

    # Limitar a 4 recomendacoes
    return recomendacoes[:4]


def _generate_comparativo(metrics: BusinessMetrics) -> Dict[str, str]:
    """
    Gera comparativo simplificado com mes anterior.

    Args:
        metrics: Metricas calculadas

    Returns:
        Dict com variacoes formatadas
    """
    comparativo = {}

    # Faturamento
    if metrics.crescimento_mes_percent != 0:
        sinal = "+" if metrics.crescimento_mes_percent > 0 else ""
        comparativo["faturamento"] = f"{sinal}{metrics.crescimento_mes_percent:.1f}%"
    else:
        comparativo["faturamento"] = "0% (estavel)"

    # Contratos novos
    if metrics.contratos_novos_mes > 0:
        comparativo["contratos_novos"] = f"+{metrics.contratos_novos_mes}"
    else:
        comparativo["contratos_novos"] = "0"

    # Churn
    if metrics.churn_percent > 0:
        comparativo["cancelamentos"] = f"{metrics.churn_percent:.1f}%"
    else:
        comparativo["cancelamentos"] = "0%"

    return comparativo


# ============================================================================
# TOOL DECLARATIONS (para Gemini Function Calling)
# ============================================================================

ATHENA_BUSINESS_TOOLS = [
    {
        "name": "get_business_health",
        "description": """
Retorna a saude geral do negocio com score, indicadores e recomendacoes.

Use esta tool quando o usuario perguntar:
- "Como esta meu negocio?"
- "Qual a saude da empresa?"
- "O negocio esta indo bem?"
- "Qual meu ROI?"
- "Quanto tempo para recuperar o investimento?"
- "Como esta a inadimplencia?"
- "O que preciso resolver?"
- "Quais os riscos do negocio?"
- "Me da um resumo do negocio"

NAO use esta tool para:
- Listar clientes especificos (use SQL)
- Buscar detalhes de um contrato (use SQL)
- Perguntas sobre um cliente especifico (use SQL)
""",
        "parameters": {
            "type": "object",
            "properties": {
                "force_refresh": {
                    "type": "boolean",
                    "description": "Se True, recalcula as metricas mesmo com cache valido (use apenas se o usuario pedir dados atualizados)"
                }
            },
            "required": []
        }
    }
]


# ============================================================================
# TOOL EXECUTOR
# ============================================================================

async def execute_athena_tool(
    tool_name: str,
    agent_id: str,
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Executa uma tool da Athena pelo nome.

    Args:
        tool_name: Nome da tool a executar
        agent_id: ID do agente (tenant)
        parameters: Parametros da tool

    Returns:
        Resultado da tool
    """
    if tool_name == "get_business_health":
        force_refresh = parameters.get("force_refresh", False)
        return await get_business_health(agent_id, force_refresh=force_refresh)

    else:
        logger.warning(f"[Athena Tool] Tool desconhecida: {tool_name}")
        return {
            "error": f"Tool '{tool_name}' nao encontrada",
            "available_tools": ["get_business_health"]
        }
