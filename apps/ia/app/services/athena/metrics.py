"""
Athena Business Metrics - Calculos de metricas de negocio.

Este modulo calcula metricas financeiras e operacionais para
negocios de locacao de AR (ar-condicionado).

Metricas calculadas:
- Patrimonio (total ARs, valor comercial)
- Receita (faturamento potencial/realizado, ticket medio)
- ROI e Payback
- Inadimplencia (taxa, valor, quantidade)
- Crescimento (mes a mes, churn)
- Score de Saude (0-100)
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.services.supabase import get_supabase_service
from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class BusinessMetrics:
    """Metricas consolidadas do negocio."""

    # Identificacao
    agent_id: str
    calculated_at: str

    # Patrimonio
    total_ars: int = 0
    valor_patrimonio: float = 0.0
    custo_medio_ar: float = 0.0

    # Receita
    faturamento_potencial_mes: float = 0.0
    faturamento_realizado_mes: float = 0.0
    taxa_realizacao: float = 0.0
    ticket_medio: float = 0.0
    receita_por_ar: float = 0.0

    # ROI
    roi_anual_percent: float = 0.0
    payback_meses: float = 0.0

    # Inadimplencia
    taxa_inadimplencia: float = 0.0
    valor_inadimplido: float = 0.0
    qtd_inadimplentes: int = 0

    # Crescimento
    crescimento_mes_percent: float = 0.0
    contratos_novos_mes: int = 0
    churn_percent: float = 0.0

    # Distribuicao BTUs
    distribuicao_btus: Dict[str, int] = None

    # Score de Saude
    score_saude: int = 0
    classificacao: str = "Desconhecido"

    # Alertas
    alertas: List[Dict[str, Any]] = None

    # Totais
    contratos_ativos: int = 0
    total_clientes: int = 0

    def __post_init__(self):
        if self.distribuicao_btus is None:
            self.distribuicao_btus = {}
        if self.alertas is None:
            self.alertas = []

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionario."""
        return asdict(self)


# ============================================================================
# HEALTH SCORE CALCULATION
# ============================================================================

def calculate_health_score(metrics: BusinessMetrics) -> Tuple[int, str]:
    """
    Calcula score de saude do negocio (0-100).

    Dimensoes:
    - Taxa de realizacao (30%): % do faturamento potencial realizado
    - Inadimplencia (25%): % de clientes em atraso
    - ROI (20%): Retorno sobre investimento anual
    - Crescimento (15%): Crescimento mes a mes
    - Manutencoes em dia (10%): % de manutencoes em dia

    Returns:
        Tuple[score, classificacao]
    """
    score = 0.0

    # 1. Taxa de realizacao (30 pontos)
    # 100% realizacao = 30 pontos
    if metrics.faturamento_potencial_mes > 0:
        taxa_real = min(metrics.taxa_realizacao, 100)
        score += (taxa_real / 100) * 30
    else:
        score += 15  # Sem dados, meio termo

    # 2. Inadimplencia (25 pontos)
    # 0% inadimplencia = 25 pontos
    # 10%+ inadimplencia = 0 pontos
    inadimplencia = min(metrics.taxa_inadimplencia, 10)
    score += (1 - inadimplencia / 10) * 25

    # 3. ROI (20 pontos)
    # 60%+ ROI = 20 pontos
    # 0% ROI = 0 pontos
    roi = min(metrics.roi_anual_percent, 60)
    score += (roi / 60) * 20

    # 4. Crescimento (15 pontos)
    # 5%+ crescimento = 15 pontos
    # Negativo = 0 pontos
    crescimento = max(0, min(metrics.crescimento_mes_percent, 5))
    score += (crescimento / 5) * 15

    # 5. Manutencoes em dia (10 pontos)
    # Por enquanto, assumimos 100% se nao temos dados
    # TODO: Implementar verificacao de manutencoes quando disponivel
    score += 10

    # Converter para inteiro
    score_final = int(round(score))

    # Classificacao
    if score_final >= 85:
        classificacao = "Excelente"
    elif score_final >= 70:
        classificacao = "Saudavel"
    elif score_final >= 50:
        classificacao = "Atencao"
    else:
        classificacao = "Critico"

    return score_final, classificacao


# ============================================================================
# ALERTS GENERATION
# ============================================================================

def generate_alerts(metrics: BusinessMetrics) -> List[Dict[str, Any]]:
    """
    Gera alertas baseados nas metricas.

    Tipos de alerta:
    - critical: Acao imediata necessaria
    - warning: Atencao recomendada
    - info: Informativo

    Returns:
        Lista de alertas com tipo, mensagem e acao recomendada
    """
    alertas = []

    # Inadimplencia alta (>5%)
    if metrics.taxa_inadimplencia > 5:
        alertas.append({
            "tipo": "critical" if metrics.taxa_inadimplencia > 10 else "warning",
            "titulo": "Inadimplencia alta",
            "mensagem": f"Taxa de inadimplencia em {metrics.taxa_inadimplencia:.1f}%",
            "valor": f"R$ {metrics.valor_inadimplido:,.2f}",
            "acao": "Revisar regua de cobranca e contatar clientes em atraso",
        })

    # ROI baixo (<30%)
    if metrics.roi_anual_percent < 30 and metrics.valor_patrimonio > 0:
        alertas.append({
            "tipo": "warning",
            "titulo": "ROI abaixo do esperado",
            "mensagem": f"ROI anual de {metrics.roi_anual_percent:.1f}% (meta: >45%)",
            "acao": "Avaliar precificacao e custos operacionais",
        })

    # Payback longo (>30 meses)
    if metrics.payback_meses > 30 and metrics.payback_meses < 999:
        alertas.append({
            "tipo": "warning",
            "titulo": "Payback longo",
            "mensagem": f"Payback em {metrics.payback_meses:.0f} meses (ideal: <24)",
            "acao": "Considerar reajuste de precos ou otimizacao de custos",
        })

    # Crescimento negativo
    if metrics.crescimento_mes_percent < 0:
        alertas.append({
            "tipo": "warning",
            "titulo": "Crescimento negativo",
            "mensagem": f"Reducao de {abs(metrics.crescimento_mes_percent):.1f}% no faturamento",
            "acao": "Analisar churn e estrategias de retencao",
        })

    # Churn alto (>3%)
    if metrics.churn_percent > 3:
        alertas.append({
            "tipo": "critical" if metrics.churn_percent > 5 else "warning",
            "titulo": "Churn elevado",
            "mensagem": f"Taxa de cancelamento de {metrics.churn_percent:.1f}%",
            "acao": "Investigar motivos de cancelamento e melhorar retencao",
        })

    # Taxa de realizacao baixa (<80%)
    if metrics.taxa_realizacao < 80 and metrics.faturamento_potencial_mes > 0:
        alertas.append({
            "tipo": "warning",
            "titulo": "Baixa realizacao",
            "mensagem": f"Apenas {metrics.taxa_realizacao:.1f}% do faturamento potencial realizado",
            "acao": "Verificar cobrancas pendentes e inadimplencia",
        })

    # Alerta positivo - ROI excelente
    if metrics.roi_anual_percent >= 60:
        alertas.append({
            "tipo": "info",
            "titulo": "ROI excelente",
            "mensagem": f"ROI anual de {metrics.roi_anual_percent:.1f}% (acima da media do setor)",
            "acao": "Manter estrategia atual e considerar expansao",
        })

    return alertas


# ============================================================================
# METRICS CALCULATION
# ============================================================================

async def calculate_business_metrics(agent_id: str) -> BusinessMetrics:
    """
    Calcula todas as metricas de negocio para um agente.

    Busca dados de:
    - asaas_contratos: Contratos ativos e valores
    - asaas_cobrancas: Pagamentos e inadimplencia
    - contract_details: Equipamentos, patrimonio, BTUs

    Args:
        agent_id: ID do agente (tenant)

    Returns:
        BusinessMetrics com todas as metricas calculadas
    """
    logger.info(f"[Athena Metrics] Calculando metricas para agent_id={agent_id[:8]}...")

    svc = get_supabase_service()
    now = datetime.utcnow()
    metrics = BusinessMetrics(
        agent_id=agent_id,
        calculated_at=now.isoformat(),
    )

    try:
        # ====================================================================
        # 1. CONTRATOS ATIVOS E FATURAMENTO POTENCIAL
        # ====================================================================
        contratos_query = svc.client.table("asaas_contratos") \
            .select("id, customer_id, customer_name, value, status") \
            .eq("agent_id", agent_id) \
            .eq("status", "ACTIVE") \
            .eq("deleted_from_asaas", False)

        contratos_result = contratos_query.execute()
        contratos = contratos_result.data or []

        metrics.contratos_ativos = len(contratos)
        metrics.faturamento_potencial_mes = sum(c.get("value", 0) or 0 for c in contratos)

        if metrics.contratos_ativos > 0:
            metrics.ticket_medio = metrics.faturamento_potencial_mes / metrics.contratos_ativos

        logger.debug(f"[Athena Metrics] Contratos ativos: {metrics.contratos_ativos}, Potencial: R$ {metrics.faturamento_potencial_mes:,.2f}")

        # ====================================================================
        # 2. CLIENTES UNICOS (por numero_contrato DISTINTO)
        # ====================================================================
        # ANTES: Contava registros em asaas_clientes (pode duplicar se cliente tiver multiplos contratos)
        # DEPOIS: Conta numero_contrato DISTINTO em contract_details (cada contrato = 1 cliente unico)
        details_clientes = svc.client.rpc(
            "count_distinct_contracts",
            {"p_agent_id": agent_id}
        ).execute()

        # Se a function nao existir, usa fallback
        if details_clientes.data is not None:
            metrics.total_clientes = details_clientes.data
        else:
            # Fallback: buscar no Python e contar unicos
            logger.warning("[Athena Metrics] Function count_distinct_contracts nao existe, usando fallback Python")
            details_all = svc.client.table("contract_details") \
                .select("numero_contrato") \
                .eq("agent_id", agent_id) \
                .execute()

            contratos_unicos = set()
            for d in (details_all.data or []):
                num = d.get("numero_contrato")
                if num:
                    contratos_unicos.add(num)

            metrics.total_clientes = len(contratos_unicos)

        # ====================================================================
        # 3. PATRIMONIO E ARs (de contract_details)
        # ====================================================================
        # ANTES: Somava qtd_ars (conta duplicado se mesmo patrimonio aparece em multiplos contratos)
        # DEPOIS: Extrai patrimonios UNICOS do JSONB equipamentos
        details_query = svc.client.table("contract_details") \
            .select("qtd_ars, valor_comercial_total, equipamentos") \
            .eq("agent_id", agent_id)

        details_result = details_query.execute()
        details = details_result.data or []

        # Coletar patrimonios unicos
        patrimonios_unicos = set()
        valor_patrimonio_total = 0

        for d in details:
            equipamentos = d.get("equipamentos") or []
            if isinstance(equipamentos, list):
                for eq in equipamentos:
                    if isinstance(eq, dict):
                        patrimonio = eq.get("patrimonio")
                        if patrimonio:
                            patrimonios_unicos.add(patrimonio)

            # Valor comercial total continua somando (nao precisa deduplicar)
            valor_patrimonio_total += (d.get("valor_comercial_total", 0) or 0)

        metrics.total_ars = len(patrimonios_unicos)
        metrics.valor_patrimonio = valor_patrimonio_total

        if metrics.total_ars > 0:
            metrics.custo_medio_ar = metrics.valor_patrimonio / metrics.total_ars
            metrics.receita_por_ar = metrics.faturamento_potencial_mes / metrics.total_ars

        # Distribuicao de BTUs
        distribuicao: Dict[str, int] = {}
        for d in details:
            equipamentos = d.get("equipamentos") or []
            if isinstance(equipamentos, list):
                for eq in equipamentos:
                    btus = eq.get("btus") if isinstance(eq, dict) else None
                    if btus:
                        key = str(btus)
                        distribuicao[key] = distribuicao.get(key, 0) + 1

        metrics.distribuicao_btus = distribuicao

        logger.debug(f"[Athena Metrics] Total ARs: {metrics.total_ars}, Patrimonio: R$ {metrics.valor_patrimonio:,.2f}")

        # ====================================================================
        # 4. FATURAMENTO REALIZADO (mes atual)
        # ====================================================================
        inicio_mes = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        cobrancas_query = svc.client.table("asaas_cobrancas") \
            .select("value, net_value, status, due_date, payment_date") \
            .eq("agent_id", agent_id) \
            .eq("deleted_from_asaas", False) \
            .gte("payment_date", inicio_mes.strftime("%Y-%m-%d")) \
            .in_("status", ["RECEIVED", "CONFIRMED"])

        cobrancas_result = cobrancas_query.execute()
        cobrancas_pagas = cobrancas_result.data or []

        metrics.faturamento_realizado_mes = sum(c.get("value", 0) or 0 for c in cobrancas_pagas)

        if metrics.faturamento_potencial_mes > 0:
            metrics.taxa_realizacao = (metrics.faturamento_realizado_mes / metrics.faturamento_potencial_mes) * 100

        logger.debug(f"[Athena Metrics] Faturamento realizado: R$ {metrics.faturamento_realizado_mes:,.2f}")

        # ====================================================================
        # 5. INADIMPLENCIA
        # ====================================================================
        inadimplentes_query = svc.client.table("asaas_cobrancas") \
            .select("id, value, customer_id") \
            .eq("agent_id", agent_id) \
            .eq("deleted_from_asaas", False) \
            .eq("status", "OVERDUE")

        inadimplentes_result = inadimplentes_query.execute()
        inadimplentes = inadimplentes_result.data or []

        metrics.valor_inadimplido = sum(c.get("value", 0) or 0 for c in inadimplentes)
        clientes_inadimplentes = set(c.get("customer_id") for c in inadimplentes if c.get("customer_id"))
        metrics.qtd_inadimplentes = len(clientes_inadimplentes)

        if metrics.total_clientes > 0:
            metrics.taxa_inadimplencia = (metrics.qtd_inadimplentes / metrics.total_clientes) * 100

        logger.debug(f"[Athena Metrics] Inadimplencia: {metrics.taxa_inadimplencia:.1f}%, Valor: R$ {metrics.valor_inadimplido:,.2f}")

        # ====================================================================
        # 6. ROI E PAYBACK
        # ====================================================================
        if metrics.valor_patrimonio > 0:
            faturamento_anual = metrics.faturamento_potencial_mes * 12
            metrics.roi_anual_percent = (faturamento_anual / metrics.valor_patrimonio) * 100

            if metrics.faturamento_potencial_mes > 0:
                metrics.payback_meses = metrics.valor_patrimonio / metrics.faturamento_potencial_mes
            else:
                metrics.payback_meses = 999  # Infinito

        logger.debug(f"[Athena Metrics] ROI: {metrics.roi_anual_percent:.1f}%, Payback: {metrics.payback_meses:.1f} meses")

        # ====================================================================
        # 7. CRESCIMENTO MES A MES
        # ====================================================================
        # Faturamento do mes anterior
        inicio_mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=1)
        fim_mes_anterior = inicio_mes - timedelta(days=1)

        cobrancas_mes_anterior_query = svc.client.table("asaas_cobrancas") \
            .select("value") \
            .eq("agent_id", agent_id) \
            .eq("deleted_from_asaas", False) \
            .gte("payment_date", inicio_mes_anterior.strftime("%Y-%m-%d")) \
            .lte("payment_date", fim_mes_anterior.strftime("%Y-%m-%d")) \
            .in_("status", ["RECEIVED", "CONFIRMED"])

        cobrancas_mes_anterior_result = cobrancas_mes_anterior_query.execute()
        cobrancas_mes_anterior = cobrancas_mes_anterior_result.data or []
        faturamento_mes_anterior = sum(c.get("value", 0) or 0 for c in cobrancas_mes_anterior)

        if faturamento_mes_anterior > 0:
            metrics.crescimento_mes_percent = (
                (metrics.faturamento_realizado_mes - faturamento_mes_anterior) / faturamento_mes_anterior
            ) * 100

        # Contratos novos do mes
        contratos_novos_query = svc.client.table("asaas_contratos") \
            .select("id", count="exact") \
            .eq("agent_id", agent_id) \
            .eq("deleted_from_asaas", False) \
            .gte("created_at", inicio_mes.strftime("%Y-%m-%d"))

        contratos_novos_result = contratos_novos_query.execute()
        metrics.contratos_novos_mes = contratos_novos_result.count or 0

        # Churn (contratos cancelados no mes)
        cancelados_query = svc.client.table("asaas_contratos") \
            .select("id", count="exact") \
            .eq("agent_id", agent_id) \
            .eq("status", "INACTIVE") \
            .gte("updated_at", inicio_mes.strftime("%Y-%m-%d"))

        cancelados_result = cancelados_query.execute()
        cancelados_mes = cancelados_result.count or 0

        total_inicio_mes = metrics.contratos_ativos + cancelados_mes - metrics.contratos_novos_mes
        if total_inicio_mes > 0:
            metrics.churn_percent = (cancelados_mes / total_inicio_mes) * 100

        logger.debug(f"[Athena Metrics] Crescimento: {metrics.crescimento_mes_percent:.1f}%, Churn: {metrics.churn_percent:.1f}%")

        # ====================================================================
        # 8. CALCULAR SCORE E ALERTAS
        # ====================================================================
        metrics.score_saude, metrics.classificacao = calculate_health_score(metrics)
        metrics.alertas = generate_alerts(metrics)

        logger.info(
            f"[Athena Metrics] Score de saude: {metrics.score_saude} ({metrics.classificacao}) | "
            f"ROI: {metrics.roi_anual_percent:.1f}% | Inadimplencia: {metrics.taxa_inadimplencia:.1f}%"
        )

        return metrics

    except Exception as e:
        logger.error(f"[Athena Metrics] Erro ao calcular metricas: {e}", exc_info=True)
        # Retornar metricas vazias com erro
        metrics.alertas = [{
            "tipo": "critical",
            "titulo": "Erro no calculo",
            "mensagem": f"Nao foi possivel calcular metricas: {str(e)}",
            "acao": "Verificar logs e conexao com banco de dados",
        }]
        return metrics


# ============================================================================
# CACHE FUNCTIONS
# ============================================================================

async def get_cached_metrics(agent_id: str) -> Optional[BusinessMetrics]:
    """
    Busca metricas do cache (tabela athena_business_metrics).

    Se o cache tiver menos de 6 horas, retorna do cache.
    Caso contrario, recalcula.

    Args:
        agent_id: ID do agente

    Returns:
        BusinessMetrics do cache ou None se nao existir/expirado
    """
    try:
        svc = get_supabase_service()

        # Buscar do cache
        result = svc.client.table("athena_business_metrics") \
            .select("*") \
            .eq("agent_id", agent_id) \
            .order("calculated_at", desc=True) \
            .limit(1) \
            .execute()

        if not result.data:
            logger.debug(f"[Athena Cache] Sem cache para agent_id={agent_id[:8]}")
            return None

        cached = result.data[0]

        # Verificar se cache ainda e valido (6 horas)
        calculated_at = datetime.fromisoformat(cached["calculated_at"].replace("Z", "+00:00"))
        age_hours = (datetime.utcnow().replace(tzinfo=calculated_at.tzinfo) - calculated_at).total_seconds() / 3600

        if age_hours > 6:
            logger.debug(f"[Athena Cache] Cache expirado ({age_hours:.1f}h)")
            return None

        # Converter para BusinessMetrics
        metrics = BusinessMetrics(
            agent_id=cached.get("agent_id"),
            calculated_at=cached.get("calculated_at"),
            total_ars=cached.get("total_ars", 0),
            valor_patrimonio=float(cached.get("valor_patrimonio", 0) or 0),
            custo_medio_ar=float(cached.get("custo_medio_ar", 0) or 0),
            faturamento_potencial_mes=float(cached.get("faturamento_potencial_mes", 0) or 0),
            faturamento_realizado_mes=float(cached.get("faturamento_realizado_mes", 0) or 0),
            taxa_realizacao=float(cached.get("taxa_realizacao", 0) or 0),
            ticket_medio=float(cached.get("ticket_medio", 0) or 0),
            receita_por_ar=float(cached.get("receita_por_ar", 0) or 0),
            roi_anual_percent=float(cached.get("roi_anual_percent", 0) or 0),
            payback_meses=float(cached.get("payback_meses", 0) or 0),
            taxa_inadimplencia=float(cached.get("taxa_inadimplencia", 0) or 0),
            valor_inadimplido=float(cached.get("valor_inadimplido", 0) or 0),
            qtd_inadimplentes=cached.get("qtd_inadimplentes", 0),
            crescimento_mes_percent=float(cached.get("crescimento_mes_percent", 0) or 0),
            contratos_novos_mes=cached.get("contratos_novos_mes", 0),
            churn_percent=float(cached.get("churn_percent", 0) or 0),
            distribuicao_btus=cached.get("distribuicao_btus") or {},
            score_saude=cached.get("score_saude", 0),
            classificacao=cached.get("classificacao", "Desconhecido"),
            alertas=cached.get("alertas") or [],
            contratos_ativos=cached.get("contratos_ativos", 0),
            total_clientes=cached.get("total_clientes", 0),
        )

        logger.debug(f"[Athena Cache] Cache valido encontrado ({age_hours:.1f}h)")
        return metrics

    except Exception as e:
        logger.error(f"[Athena Cache] Erro ao buscar cache: {e}")
        return None


async def save_metrics_to_cache(metrics: BusinessMetrics) -> bool:
    """
    Salva metricas no cache (upsert na tabela athena_business_metrics).

    Args:
        metrics: Metricas calculadas

    Returns:
        True se salvo com sucesso
    """
    try:
        svc = get_supabase_service()

        data = {
            "agent_id": metrics.agent_id,
            "calculated_at": metrics.calculated_at,
            "total_ars": metrics.total_ars,
            "valor_patrimonio": metrics.valor_patrimonio,
            "custo_medio_ar": metrics.custo_medio_ar,
            "faturamento_potencial_mes": metrics.faturamento_potencial_mes,
            "faturamento_realizado_mes": metrics.faturamento_realizado_mes,
            "taxa_realizacao": metrics.taxa_realizacao,
            "ticket_medio": metrics.ticket_medio,
            "receita_por_ar": metrics.receita_por_ar,
            "roi_anual_percent": metrics.roi_anual_percent,
            "payback_meses": metrics.payback_meses,
            "taxa_inadimplencia": metrics.taxa_inadimplencia,
            "valor_inadimplido": metrics.valor_inadimplido,
            "qtd_inadimplentes": metrics.qtd_inadimplentes,
            "crescimento_mes_percent": metrics.crescimento_mes_percent,
            "contratos_novos_mes": metrics.contratos_novos_mes,
            "churn_percent": metrics.churn_percent,
            "distribuicao_btus": metrics.distribuicao_btus,
            "score_saude": metrics.score_saude,
            "classificacao": metrics.classificacao,
            "alertas": metrics.alertas,
            "contratos_ativos": metrics.contratos_ativos,
            "total_clientes": metrics.total_clientes,
        }

        # Upsert (insert ou update se ja existir)
        svc.client.table("athena_business_metrics") \
            .upsert(data, on_conflict="agent_id") \
            .execute()

        logger.info(f"[Athena Cache] Metricas salvas no cache para agent_id={metrics.agent_id[:8]}")
        return True

    except Exception as e:
        logger.error(f"[Athena Cache] Erro ao salvar cache: {e}")
        return False
