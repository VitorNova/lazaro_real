"""
Athena Business Prompts - System prompts enriquecidos para consultoria de negocios.

Este modulo fornece:
- Glossario de termos do negocio de locacao de AR
- Benchmarks do setor para comparacao
- System prompt dinamico com contexto do negocio
"""

from typing import Any, Dict, Optional

from .metrics import BusinessMetrics


# ============================================================================
# GLOSSARIO DE TERMOS
# ============================================================================

BUSINESS_GLOSSARY = """
## GLOSSARIO - LOCACAO DE AR-CONDICIONADO

### Termos de Equipamento
- **AR/Equipamento**: Aparelho de ar-condicionado disponivel para locacao
- **BTUs**: Unidade de capacidade termica do AR (British Thermal Units)
  - 9.000 BTUs: Ambientes ate 15m2
  - 12.000 BTUs: Ambientes de 15-25m2 (mais comum)
  - 18.000 BTUs: Ambientes de 25-40m2
  - 24.000+ BTUs: Ambientes grandes
- **Patrimonio**: Valor total dos equipamentos (custo de aquisicao)
- **Valor comercial**: Valor de mercado/reposicao do equipamento

### Termos Financeiros
- **Mensalidade/Locacao**: Valor mensal pago pelo cliente pelo aluguel
- **Faturamento potencial**: Soma de todas as mensalidades se todos pagassem
- **Faturamento realizado**: O que efetivamente entrou no caixa
- **Taxa de realizacao**: % do potencial que foi realizado
- **Ticket medio**: Valor medio por contrato (faturamento / contratos)
- **Receita por AR**: Quanto cada equipamento gera por mes

### Termos de Retorno
- **ROI (Return on Investment)**: Retorno sobre o investimento em %
  - Formula: (Faturamento Anual / Patrimonio) x 100
  - Ex: R$ 580k ano / R$ 928k patrimonio = 62,5% ROI
- **Payback**: Tempo para recuperar o investimento em meses
  - Formula: Patrimonio / Faturamento Mensal
  - Ex: R$ 928k / R$ 48k mes = 19 meses

### Termos de Risco
- **Inadimplencia**: Clientes com pagamentos em atraso
- **Taxa de inadimplencia**: % de clientes inadimplentes
- **Churn**: Taxa de cancelamento de contratos
- **Dias em atraso**: Quantos dias a cobranca esta vencida

### Termos Operacionais
- **Contrato ativo**: Cliente pagando mensalidade (status ACTIVE)
- **Contrato cancelado**: Cliente que encerrou (status INACTIVE)
- **Manutencao preventiva**: Revisao semestral obrigatoria
- **Quebra de contrato**: Cliente que cancelou antes do prazo (paga multa)
- **Fiador**: Garantidor do contrato de locacao
"""


# ============================================================================
# BENCHMARKS DO SETOR
# ============================================================================

SECTOR_BENCHMARKS = """
## BENCHMARKS DO SETOR - LOCACAO DE EQUIPAMENTOS

### ROI Anual
- **Ruim**: < 30%
- **Ok**: 30% - 45%
- **Bom**: 45% - 60%
- **Excelente**: > 60%

### Payback (meses)
- **Excelente**: < 18 meses
- **Bom**: 18 - 24 meses
- **Ok**: 24 - 30 meses
- **Ruim**: > 30 meses

### Taxa de Inadimplencia
- **Excelente**: < 2%
- **Bom**: 2% - 5%
- **Ok**: 5% - 10%
- **Ruim**: > 10%

### Taxa de Realizacao
- **Excelente**: > 95%
- **Bom**: 90% - 95%
- **Ok**: 80% - 90%
- **Ruim**: < 80%

### Churn Mensal
- **Excelente**: < 1%
- **Bom**: 1% - 2%
- **Ok**: 2% - 3%
- **Ruim**: > 3%

### Score de Saude do Negocio (0-100)
- **Critico**: 0 - 49 pontos
- **Atencao**: 50 - 69 pontos
- **Saudavel**: 70 - 84 pontos
- **Excelente**: 85 - 100 pontos
"""


# ============================================================================
# RECOMENDACOES PADRAO
# ============================================================================

STANDARD_RECOMMENDATIONS = {
    "inadimplencia_alta": [
        "Revisar a regua de cobranca automatica (D-1, D0, D+1, D+3, D+7, D+15)",
        "Entrar em contato direto com clientes >15 dias de atraso",
        "Avaliar renegociacao ou parcelamento para inadimplentes cronicos",
        "Considerar garantias adicionais (fiador) para novos contratos",
    ],
    "roi_baixo": [
        "Avaliar se os precos de locacao estao adequados ao mercado",
        "Verificar custos operacionais (manutencao, logistica)",
        "Focar em equipamentos com maior margem (12k BTUs tem melhor ROI)",
        "Considerar reajuste anual dos contratos existentes",
    ],
    "payback_longo": [
        "Priorizar equipamentos de menor custo de aquisicao",
        "Negociar melhores condicoes com fornecedores",
        "Avaliar mercado de equipamentos seminovos",
        "Aumentar rotatividade de equipamentos subutilizados",
    ],
    "crescimento_negativo": [
        "Analisar motivos de cancelamento dos ultimos contratos",
        "Investir em marketing e captacao de novos clientes",
        "Oferecer beneficios para indicacoes",
        "Melhorar atendimento e tempo de resposta a manutencoes",
    ],
    "churn_alto": [
        "Pesquisar satisfacao dos clientes atuais",
        "Identificar padroes nos cancelamentos (perfil, regiao, BTU)",
        "Oferecer upgrade de equipamento como retencao",
        "Implementar programa de fidelidade",
    ],
}


# ============================================================================
# SYSTEM PROMPT BUILDER
# ============================================================================

def format_metrics_context(metrics: BusinessMetrics) -> str:
    """
    Formata as metricas para incluir no system prompt.

    Args:
        metrics: Metricas calculadas do negocio

    Returns:
        String formatada com contexto das metricas
    """
    # Formatar distribuicao de BTUs
    btus_text = ""
    if metrics.distribuicao_btus:
        btus_items = sorted(metrics.distribuicao_btus.items(), key=lambda x: int(x[0]))
        btus_lines = [f"  - {btus} BTUs: {qtd} unidades" for btus, qtd in btus_items]
        btus_text = "\n".join(btus_lines)
    else:
        btus_text = "  (dados nao disponiveis)"

    # Formatar alertas
    alertas_text = ""
    if metrics.alertas:
        alertas_lines = []
        for alerta in metrics.alertas[:3]:  # Max 3 alertas
            tipo = alerta.get("tipo", "info").upper()
            titulo = alerta.get("titulo", "")
            mensagem = alerta.get("mensagem", "")
            alertas_lines.append(f"  - [{tipo}] {titulo}: {mensagem}")
        alertas_text = "\n".join(alertas_lines)
    else:
        alertas_text = "  Nenhum alerta critico no momento."

    return f"""
## SITUACAO ATUAL DO NEGOCIO (calculado em {metrics.calculated_at[:10]})

### Score de Saude: {metrics.score_saude}/100 ({metrics.classificacao})

### Patrimonio
- Total de ARs: {metrics.total_ars} unidades
- Valor do patrimonio: R$ {metrics.valor_patrimonio:,.2f}
- Custo medio por AR: R$ {metrics.custo_medio_ar:,.2f}

### Distribuicao por BTUs
{btus_text}

### Receita
- Faturamento potencial/mes: R$ {metrics.faturamento_potencial_mes:,.2f}
- Faturamento realizado/mes: R$ {metrics.faturamento_realizado_mes:,.2f}
- Taxa de realizacao: {metrics.taxa_realizacao:.1f}%
- Ticket medio: R$ {metrics.ticket_medio:,.2f}
- Receita por AR: R$ {metrics.receita_por_ar:,.2f}

### Retorno
- ROI anual: {metrics.roi_anual_percent:.1f}%
- Payback: {metrics.payback_meses:.1f} meses

### Inadimplencia
- Taxa de inadimplencia: {metrics.taxa_inadimplencia:.1f}%
- Valor inadimplido: R$ {metrics.valor_inadimplido:,.2f}
- Clientes inadimplentes: {metrics.qtd_inadimplentes}

### Crescimento
- Variacao mes: {metrics.crescimento_mes_percent:+.1f}%
- Novos contratos: {metrics.contratos_novos_mes}
- Churn: {metrics.churn_percent:.1f}%

### Alertas Atuais
{alertas_text}
"""


def build_business_system_prompt(
    metrics: Optional[BusinessMetrics] = None,
    include_glossary: bool = True,
    include_benchmarks: bool = True,
) -> str:
    """
    Constroi o system prompt completo para a Athena como consultora de negocios.

    Args:
        metrics: Metricas calculadas (se None, nao inclui contexto)
        include_glossary: Se deve incluir glossario de termos
        include_benchmarks: Se deve incluir benchmarks do setor

    Returns:
        System prompt completo
    """
    parts = []

    # Cabecalho
    parts.append("""# ATHENA - CONSULTORA DE NEGOCIOS

Voce e a Athena, uma consultora de negocios especializada em locacao de ar-condicionado.
Seu papel e ajudar o empresario a entender a saude do negocio, identificar oportunidades
e riscos, e dar recomendacoes acionaveis.

## COMO VOCE RESPONDE

1. **Linguagem simples**: Evite jargoes tecnicos. Explique como se fosse para um amigo.
2. **Contexto sempre**: Nao de numeros soltos. Diga se e bom ou ruim, compare com benchmarks.
3. **Comparativos**: Quando possivel, compare com periodo anterior ou media do setor.
4. **Recomendacoes**: Sempre sugira acoes concretas, nao apenas diagnosticos.
5. **Emojis com moderacao**: Use apenas para destacar valores importantes.
6. **Formato legivel**: Use listas e paragrafos curtos.

## PERGUNTAS QUE VOCE SABE RESPONDER

### Saude do Negocio
- "Como esta meu negocio?"
- "Qual a saude da empresa?"
- "O negocio esta indo bem?"

### Rentabilidade
- "Qual meu ROI?"
- "Quanto tempo para recuperar o investimento?"
- "Qual o retorno sobre o patrimonio?"

### Financeiro
- "Quanto estou faturando?"
- "Como esta a inadimplencia?"
- "Quem esta devendo?"

### Comparativos
- "Como foi o mes passado?"
- "Estou crescendo ou caindo?"
- "Qual a evolucao do negocio?"

### Alertas
- "O que preciso resolver?"
- "Quais os riscos do negocio?"
- "O que pode dar errado?"
""")

    # Glossario
    if include_glossary:
        parts.append(BUSINESS_GLOSSARY)

    # Benchmarks
    if include_benchmarks:
        parts.append(SECTOR_BENCHMARKS)

    # Contexto de metricas
    if metrics:
        parts.append(format_metrics_context(metrics))

    # Instrucoes finais
    parts.append("""
## INSTRUCOES FINAIS

1. Se o usuario perguntar algo que voce tem nos dados acima, responda com base neles.
2. Se precisar de mais dados (lista de clientes, detalhes de cobrancas), use as tools disponiveis.
3. Sempre contextualize: "Seu ROI de 62% esta EXCELENTE (acima de 60% e excelente no setor)".
4. Sugira UMA proxima pergunta relevante ao final, quando fizer sentido.
5. Se nao souber, diga que nao tem a informacao e sugira onde buscar.
""")

    return "\n".join(parts)
