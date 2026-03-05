"""
Athena Oraculo API - Analytics com linguagem natural via Gemini.

Permite que usuarios facam perguntas sobre seus dados em linguagem natural.
O Gemini gera SQL seguro (sempre filtrado por agent_id) e responde em portugues.

FASE 1 - CONSULTORA DE NEGOCIOS:
- Responde perguntas sobre saude do negocio
- Calcula e exibe ROI, payback, inadimplencia
- Gera score de saude (0-100) com classificacao
- Da recomendacoes acionaveis

Endpoints:
- POST /api/athena/ask - Faz uma pergunta sobre os dados do usuario

Tabelas disponiveis:
- agents (configuracao dos agentes)
- asaas_clientes (clientes Asaas)
- asaas_contratos (assinaturas/contratos)
- asaas_cobrancas (cobrancas/faturas)
- schedules (agendamentos)
- salvador_scheduled_followups (follow-ups agendados)
- billing_notifications (historico de cobrancas enviadas pela IA - tabela unificada)
- athena_business_metrics (cache de metricas de negocio)
- [agent.table_leads] (leads dinamico por agente)
- [agent.table_messages] (mensagens dinamico por agente)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service
from app.config import settings

# Athena Business Intelligence (Fase 1)
from app.services.athena import (
    get_business_health,
    build_business_system_prompt,
    calculate_business_metrics,
    get_cached_metrics,
    SECTOR_BENCHMARKS,
)

import google.generativeai as genai

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# DETECCAO DE SAUDACAO E CORRECAO
# ============================================================================

# Padroes de saudacao
GREETING_PATTERNS = [
    "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite",
    "eae", "e ai", "e aí", "hey", "hi", "hello", "fala",
    "opa", "salve", "beleza", "tudo bem", "tudo bom"
]

# Padroes de correcao
CORRECTION_PATTERNS = [
    "ta errado", "tá errado", "está errado", "esta errado",
    "incorreto", "não é isso", "nao e isso", "dado errado",
    "valor errado", "não está certo", "nao esta certo",
    "errou", "errado", "erro", "wrong", "incorreto",
    "esse valor está errado", "esse valor esta errado",
    "isso não está certo", "isso nao esta certo"
]


def is_greeting(question: str) -> bool:
    """
    Detecta se a mensagem e uma saudacao.

    Args:
        question: Texto da pergunta

    Returns:
        True se for saudacao
    """
    question_lower = question.lower().strip()
    question_clean = question_lower.rstrip("!?.,:;")

    # Verificar padroes exatos ou inicio da mensagem
    for pattern in GREETING_PATTERNS:
        # Match exato
        if question_clean == pattern:
            return True
        # Comeca com o padrao (ex: "oi, tudo bem?")
        if question_clean.startswith(pattern + " ") or question_clean.startswith(pattern + ","):
            return True
        # Padrao no inicio com pontuacao
        if question_clean.startswith(pattern + "!") or question_clean.startswith(pattern + "?"):
            return True

    return False


def get_greeting_response() -> str:
    """
    Retorna resposta de saudacao com apresentacao do Athena.

    Returns:
        Mensagem de boas-vindas com capacidades
    """
    return """Ola! Sou o Athena Oraculo, seu assistente de analytics.

Posso ajudar voce a entender seus dados de forma simples e direta. Basta perguntar em linguagem natural!

Exemplos do que posso fazer:
- "Quantos leads tenho?"
- "Quais clientes estao em atraso?"
- "Quanto faturei este mes?"
- "Leads quentes para fechar"
- "Agendamentos de hoje"

Como posso ajudar voce agora?"""


def is_correction(question: str) -> bool:
    """
    Detecta se o usuario esta corrigindo uma resposta anterior.

    Args:
        question: Texto da pergunta

    Returns:
        True se for uma correcao
    """
    question_lower = question.lower().strip()

    for pattern in CORRECTION_PATTERNS:
        if pattern in question_lower:
            return True

    return False


def get_correction_response() -> str:
    """
    Retorna resposta para quando o usuario indica que algo esta errado.

    Returns:
        Mensagem pedindo esclarecimento
    """
    return """Entendi que algo nao esta correto. Pode me ajudar a entender melhor?

Por favor, me diga:
1. Qual informacao esta errada?
2. Qual seria o valor correto?

Se quiser, posso mostrar a query SQL que usei para buscar esses dados - assim voce pode verificar se estou olhando na tabela certa."""


# ============================================================================
# DETECCAO DE PERGUNTAS DE NEGOCIO (Fase 1 - Consultora)
# ============================================================================

# Padroes de perguntas que devem usar a tool get_business_health
BUSINESS_HEALTH_PATTERNS = [
    # Saude do negocio
    "como esta meu negocio",
    "como está meu negócio",
    "como esta o negocio",
    "como está o negócio",
    "saude do negocio",
    "saúde do negócio",
    "saude da empresa",
    "saúde da empresa",
    "negocio esta bem",
    "negócio está bem",
    "negocio vai bem",
    "negócio vai bem",
    "situacao do negocio",
    "situação do negócio",
    "resumo do negocio",
    "resumo do negócio",
    "visao geral",
    "visão geral",
    # ROI e retorno
    "qual meu roi",
    "qual o roi",
    "meu roi",
    "retorno sobre investimento",
    "retorno do investimento",
    "quanto estou ganhando",
    "quanto ganho",
    "rentabilidade",
    # Payback
    "payback",
    "tempo para recuperar",
    "recuperar investimento",
    "quando recupero",
    "quanto tempo pra recuperar",
    # Score
    "score de saude",
    "score de saúde",
    "nota do negocio",
    "nota do negócio",
    "avaliacao do negocio",
    "avaliação do negócio",
    # Alertas e riscos
    "o que preciso resolver",
    "quais os riscos",
    "riscos do negocio",
    "riscos do negócio",
    "problemas do negocio",
    "problemas do negócio",
    "alertas",
    "o que esta errado",
    "o que está errado",
    # Recomendacoes
    "o que fazer",
    "o que devo fazer",
    "recomendacoes",
    "recomendações",
    "sugestoes",
    "sugestões",
    "como melhorar",
    # Indicadores gerais
    "indicadores",
    "metricas do negocio",
    "métricas do negócio",
    "kpis",
    "dashboard",
]


def is_business_health_question(question: str) -> bool:
    """
    Detecta se a pergunta e sobre saude do negocio (deve usar tool).

    Estas perguntas serao respondidas pela tool get_business_health
    em vez de gerar SQL direto.

    Args:
        question: Texto da pergunta

    Returns:
        True se for pergunta de saude do negocio
    """
    question_lower = question.lower().strip()
    # Remover acentos para comparacao mais flexivel
    question_clean = question_lower

    for pattern in BUSINESS_HEALTH_PATTERNS:
        if pattern in question_clean:
            return True

    return False


async def format_business_health_response(
    health_data: Dict[str, Any],
    question: str,
    history: Optional[List["HistoryMessage"]] = None
) -> str:
    """
    Formata a resposta de saude do negocio usando Gemini.

    Args:
        health_data: Dados da tool get_business_health
        question: Pergunta original do usuario
        history: Historico de mensagens

    Returns:
        Resposta formatada em portugues
    """
    try:
        genai.configure(api_key=settings.google_api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.5,
                "max_output_tokens": 1500,
            }
        )

        # Formatar historico
        history_context = ""
        if history:
            history_lines = []
            for msg in history[-3:]:  # Ultimas 3 mensagens
                role = "Usuario" if msg.role == "user" else "Athena"
                history_lines.append(f"{role}: {msg.content[:200]}")
            if history_lines:
                history_context = "\n## HISTORICO\n" + "\n".join(history_lines)

        # Construir prompt
        prompt = f"""Voce e a Athena, consultora de negocios especializada em locacao de ar-condicionado.
Responda a pergunta do usuario de forma clara, amigavel e acionavel.

{SECTOR_BENCHMARKS}

{history_context}

## DADOS DO NEGOCIO (calculados agora)
{format_health_data_for_prompt(health_data)}

## PERGUNTA DO USUARIO
{question}

## INSTRUCOES
1. Responda de forma conversacional, nao como relatorio
2. Destaque o score de saude e classificacao
3. Compare com benchmarks (ex: "seu ROI de 62% e EXCELENTE, acima de 60% do setor")
4. Mencione 2-3 indicadores mais relevantes para a pergunta
5. Se houver alertas criticos, destaque-os
6. De 1-2 recomendacoes concretas
7. Use emojis com moderacao para valores importantes
8. Sugira uma pergunta de follow-up se fizer sentido

## RESPOSTA (em portugues brasileiro)"""

        response = model.generate_content(prompt)

        if response and response.text:
            return response.text.strip()

        return "Desculpe, nao consegui formatar a resposta."

    except Exception as e:
        logger.error(f"Erro ao formatar resposta de business health: {e}")
        return format_health_data_fallback(health_data)


def format_health_data_for_prompt(data: Dict[str, Any]) -> str:
    """Formata dados de saude para incluir no prompt."""
    indicadores = data.get("indicadores", {})
    alertas = data.get("alertas", [])
    recomendacoes = data.get("recomendacoes", [])

    lines = [
        f"Score de Saude: {data.get('score', 0)}/100 ({data.get('classificacao', 'N/A')})",
        "",
        "### Indicadores:",
        f"- ROI Anual: {indicadores.get('roi_anual_percent', 0):.1f}%",
        f"- Payback: {indicadores.get('payback_meses', 0):.1f} meses",
        f"- Taxa Inadimplencia: {indicadores.get('taxa_inadimplencia_percent', 0):.1f}%",
        f"- Taxa Realizacao: {indicadores.get('taxa_realizacao_percent', 0):.1f}%",
        f"- Crescimento Mes: {indicadores.get('crescimento_mes_percent', 0):+.1f}%",
        f"- Total ARs: {indicadores.get('total_ars', 0)}",
        f"- Patrimonio: R$ {indicadores.get('valor_patrimonio', 0):,.2f}",
        f"- Faturamento Potencial/Mes: R$ {indicadores.get('faturamento_potencial_mes', 0):,.2f}",
        f"- Contratos Ativos: {indicadores.get('contratos_ativos', 0)}",
        f"- Ticket Medio: R$ {indicadores.get('ticket_medio', 0):,.2f}",
    ]

    if alertas:
        lines.append("")
        lines.append("### Alertas:")
        for alerta in alertas[:3]:
            tipo = alerta.get("tipo", "info").upper()
            titulo = alerta.get("titulo", "")
            mensagem = alerta.get("mensagem", "")
            lines.append(f"- [{tipo}] {titulo}: {mensagem}")

    if recomendacoes:
        lines.append("")
        lines.append("### Recomendacoes:")
        for rec in recomendacoes[:3]:
            lines.append(f"- {rec}")

    return "\n".join(lines)


def format_health_data_fallback(data: Dict[str, Any]) -> str:
    """Fallback se Gemini falhar - formata direto."""
    indicadores = data.get("indicadores", {})

    return f"""## Saude do Negocio

**Score: {data.get('score', 0)}/100** ({data.get('classificacao', 'N/A')})

### Principais Indicadores:
- ROI Anual: {indicadores.get('roi_anual_percent', 0):.1f}%
- Payback: {indicadores.get('payback_meses', 0):.1f} meses
- Inadimplencia: {indicadores.get('taxa_inadimplencia_percent', 0):.1f}%
- Total ARs: {indicadores.get('total_ars', 0)}
- Patrimonio: R$ {indicadores.get('valor_patrimonio', 0):,.2f}
- Faturamento: R$ {indicadores.get('faturamento_potencial_mes', 0):,.2f}/mes

Calculado em: {data.get('calculated_at', 'N/A')[:16]}"""


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class HistoryMessage(BaseModel):
    role: str = Field(..., description="Papel: 'user' ou 'assistant'")
    content: str = Field(..., description="Conteudo da mensagem")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Pergunta em linguagem natural")
    agent_id: Optional[str] = Field(None, description="ID do agente especifico (opcional, usa todos se nao informado)")
    history: Optional[List[HistoryMessage]] = Field(None, description="Historico de mensagens anteriores (maximo 5)")


class AskResponse(BaseModel):
    resposta: str
    dados: Optional[Dict[str, Any]] = None
    sql_executado: Optional[str] = None
    tempo_ms: Optional[int] = None


# ============================================================================
# SCHEMA DAS TABELAS PARA O GEMINI
# ============================================================================

# ============================================================================
# SCHEMA BASE (FIXO) - Tabelas compartilhadas
# ============================================================================

SCHEMA_BASE = """
Voce e o Athena Oraculo, um assistente de analytics. Voce responde perguntas sobre os dados do usuario.

## COMO VOCE FUNCIONA

1. O usuario faz uma pergunta em linguagem natural
2. Voce gera um SQL para buscar os dados nas tabelas disponiveis
3. Os dados sao retornados ao usuario

## FILOSOFIA: BUSQUE OS DADOS, NAO ADIVINHE

- Se o usuario pergunta algo, BUSQUE nas tabelas abaixo
- Se voce nao sabe qual coluna usar, faca uma query exploratoria (SELECT * FROM tabela LIMIT 5)
- NUNCA retorne "sem dados disponiveis" sem antes tentar buscar
- Se a pergunta menciona termos que voce nao conhece, procure nas colunas description, name, equipamentos, etc

## REGRAS CRITICAS DE SEGURANCA

1. TODAS as queries DEVEM filtrar por agent_id do usuario
2. Use os placeholders {agent_id} que sera substituido automaticamente
3. NUNCA retorne dados de outros usuarios
4. Para tabelas com agent_id tipo TEXT, use: agent_id = '{agent_id}'
5. Para tabelas com agent_id tipo UUID, use: agent_id = '{agent_id}'::uuid
6. Para tabelas de leads/messages dinamicas: SEM filtro de agent_id (a tabela ja e exclusiva do agente)

## TABELAS DISPONIVEIS"""


# Template para tabelas dinamicas (sera preenchido em runtime)
DYNAMIC_TABLES_TEMPLATE = """

## TABELAS DINAMICAS DO AGENTE: {agent_name}

### "{table_leads}" (leads/contatos do agente)
{leads_columns}

**Descricao das colunas principais de leads:**
- nome: text (nome completo do lead/contato)
- telefone: text (numero de telefone)
- email: text (email do lead)
- empresa: text (empresa onde o lead trabalha)
- remotejid: text (ID do WhatsApp, formato: 5511999999999@s.whatsapp.net)
- pipeline_step: text (etapa do funil - valores dinamicos por agente, ex: "Leads", "Qualificado", "Negociacao")
- lead_temperature: text (temperatura: "frio", "morno", "quente" - indica probabilidade de fechar)
- valor: numeric (valor potencial do negocio em R$)
- bant_budget: integer (score 0-25: lead tem orcamento?)
- bant_authority: integer (score 0-25: lead e decisor?)
- bant_need: integer (score 0-25: lead tem necessidade real?)
- bant_timing: integer (score 0-25: lead tem urgencia?)
- bant_total: integer (score 0-100: soma dos 4 BANT, quanto maior = mais qualificado)
- bant_notes: text (observacoes sobre qualificacao)
- current_state: text ("ai" = IA atendendo, "human" = humano assumiu)
- journey_stage: text (estagio da jornada: lead, qualificado, cliente)
- lead_origin: text (origem: whatsapp, site, indicacao, etc)
- status: text (status do lead)
- created_date: timestamp (quando o lead entrou)
- updated_date: timestamp (ultima atualizacao)
- follow_count: integer (quantos follow-ups foram enviados)
- ultimo_intent: text (ultima intencao detectada pela IA)
- responsavel: text (vendedor responsavel)
- handoff_reason: text (motivo da transferencia para humano)
- handoff_department: text (departamento que recebeu)
- next_appointment_at: timestamp (proximo agendamento)
- cpf_cnpj: text (documento do lead)
- asaas_customer_id: text (ID do cliente no Asaas se ja cadastrado)

### "{table_messages}" (historico de mensagens)
{messages_columns}

**Descricao das colunas de mensagens:**
- remotejid: text (ID do WhatsApp do contato)
- Msg_user: text (mensagem enviada pelo lead)
- Msg_model: text (resposta da IA)

**IMPORTANTE para tabelas de leads/messages:**
- Essas tabelas NAO tem coluna agent_id (sao exclusivas do agente)
- SEMPRE use aspas duplas no nome: "{table_leads}"
- pipeline_step tem valores dinamicos definidos pelo usuario (nao assuma valores fixos)

## EXEMPLOS DE QUERIES PARA TABELAS DINAMICAS

Pergunta: "Quantos leads tenho?"
SQL: SELECT COUNT(*) as total FROM "{table_leads}"

Pergunta: "Leads quentes" (alta probabilidade de fechar)
SQL: SELECT nome, telefone, lead_temperature, valor FROM "{table_leads}" WHERE lead_temperature = 'quente' LIMIT 50

Pergunta: "Leads frios" (precisam de nurturing)
SQL: SELECT nome, telefone, lead_temperature, created_date FROM "{table_leads}" WHERE lead_temperature = 'frio' LIMIT 50

Pergunta: "Leads por etapa do pipeline/funil"
SQL: SELECT pipeline_step, COUNT(*) as quantidade FROM "{table_leads}" GROUP BY pipeline_step ORDER BY quantidade DESC

Pergunta: "Valor total no pipeline" (soma dos negocios em aberto)
SQL: SELECT COALESCE(SUM(valor), 0) as valor_total FROM "{table_leads}" WHERE valor > 0

Pergunta: "Leads qualificados" (BANT alto = prontos para venda)
SQL: SELECT nome, telefone, bant_total, lead_temperature, valor FROM "{table_leads}" WHERE bant_total >= 70 ORDER BY bant_total DESC LIMIT 30

Pergunta: "Leads nao qualificados" (BANT baixo = precisam de nurturing)
SQL: SELECT nome, telefone, bant_total FROM "{table_leads}" WHERE bant_total < 50 ORDER BY bant_total ASC LIMIT 30

Pergunta: "Leads com decisor" (tem autoridade para comprar)
SQL: SELECT nome, telefone, bant_authority, empresa FROM "{table_leads}" WHERE bant_authority >= 20 LIMIT 30

Pergunta: "Leads com urgencia" (timing alto)
SQL: SELECT nome, telefone, bant_timing, valor FROM "{table_leads}" WHERE bant_timing >= 20 ORDER BY bant_timing DESC LIMIT 30

Pergunta: "Leads criados hoje"
SQL: SELECT nome, telefone, pipeline_step FROM "{table_leads}" WHERE DATE(created_date) = CURRENT_DATE

Pergunta: "Leads criados esta semana"
SQL: SELECT nome, telefone, pipeline_step, created_date FROM "{table_leads}" WHERE created_date >= CURRENT_DATE - INTERVAL '7 days' ORDER BY created_date DESC

Pergunta: "Leads sendo atendidos por humano"
SQL: SELECT nome, telefone, handoff_reason FROM "{table_leads}" WHERE current_state = 'human'

Pergunta: "Leads sendo atendidos pela IA"
SQL: SELECT nome, telefone, ultimo_intent FROM "{table_leads}" WHERE current_state = 'ai'

Pergunta: "Leads com agendamento"
SQL: SELECT nome, telefone, next_appointment_at FROM "{table_leads}" WHERE next_appointment_at IS NOT NULL ORDER BY next_appointment_at

Pergunta: "Leads por origem"
SQL: SELECT lead_origin, COUNT(*) as quantidade FROM "{table_leads}" GROUP BY lead_origin ORDER BY quantidade DESC

Pergunta: "Conversas recentes"
SQL: SELECT remotejid, "Msg_user", "Msg_model" FROM "{table_messages}" ORDER BY "Msg_user" DESC LIMIT 20
"""


# Cache de colunas das tabelas (evita queries repetidas)
_table_columns_cache: Dict[str, List[Dict[str, str]]] = {}


def get_table_columns(table_name: str) -> List[Dict[str, str]]:
    """
    Busca as colunas de uma tabela no banco.
    Usa cache para evitar queries repetidas.

    Args:
        table_name: Nome da tabela

    Returns:
        Lista de dicts com column_name e data_type
    """
    global _table_columns_cache

    if table_name in _table_columns_cache:
        return _table_columns_cache[table_name]

    try:
        svc = get_supabase_service()

        # Query no information_schema
        import httpx

        headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
        }

        url = f"{settings.supabase_url}/rest/v1/rpc/athena_execute_sql"
        query = f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """

        with httpx.Client() as client:
            response = client.post(
                url,
                json={"query_text": query},
                headers=headers,
                timeout=10.0
            )

            if response.status_code == 200:
                columns = response.json() or []
                _table_columns_cache[table_name] = columns
                return columns

    except Exception as e:
        logger.warning(f"Erro ao buscar colunas de {table_name}: {e}")

    return []


def format_columns_for_schema(columns: List[Dict[str, str]]) -> str:
    """
    Formata lista de colunas para o schema do prompt.

    Args:
        columns: Lista de dicts com column_name e data_type

    Returns:
        String formatada com as colunas
    """
    if not columns:
        return "- (tabela nao encontrada ou sem colunas)"

    lines = []
    for col in columns:
        name = col.get("column_name", "?")
        dtype = col.get("data_type", "?")

        # Simplificar tipos longos
        dtype = dtype.replace("timestamp with time zone", "timestamp")
        dtype = dtype.replace("timestamp without time zone", "timestamp")
        dtype = dtype.replace("character varying", "varchar")

        lines.append(f"- {name}: {dtype}")

    return "\n".join(lines)


def build_dynamic_schema(agents: List[Dict[str, Any]]) -> str:
    """
    Constroi o schema dinamico baseado nos agentes do usuario.

    Args:
        agents: Lista de agentes com table_leads e table_messages

    Returns:
        String com o schema das tabelas dinamicas
    """
    if not agents:
        return ""

    dynamic_parts = []

    for agent in agents:
        table_leads = agent.get("table_leads")
        table_messages = agent.get("table_messages")
        agent_name = agent.get("name", "Desconhecido")

        if not table_leads:
            continue

        # Buscar colunas das tabelas
        leads_columns = get_table_columns(table_leads)
        messages_columns = get_table_columns(table_messages) if table_messages else []

        # Formatar para o schema
        leads_formatted = format_columns_for_schema(leads_columns)
        messages_formatted = format_columns_for_schema(messages_columns)

        # Preencher template
        dynamic_schema = DYNAMIC_TABLES_TEMPLATE.format(
            table_leads=table_leads,
            table_messages=table_messages or "(nao configurada)",
            agent_name=agent_name,
            leads_columns=leads_formatted,
            messages_columns=messages_formatted,
        )

        dynamic_parts.append(dynamic_schema)

    return "\n".join(dynamic_parts)


# Manter compatibilidade - sera substituido por build_full_schema()
SCHEMA_CONTEXT = SCHEMA_BASE + """

## GLOSSARIO DE TERMOS DO NEGOCIO

### Termos Gerais
- **BANT**: Metodologia de qualificacao (Budget, Authority, Need, Timing). Score 0-100.
- **Pipeline/Funil**: Etapas do processo de vendas (Lead -> Qualificado -> Negociacao -> Fechado/Perdido)
- **Lead quente**: Lead com alta probabilidade de fechar (score alto, engajado)
- **Lead frio**: Lead novo ou sem engajamento recente
- **Lead morno**: Lead com interesse medio, precisa de nurturing
- **Follow-up**: Mensagem de acompanhamento enviada pelo Salvador
- **Handoff**: Transferencia do atendimento da IA para humano
- **current_state**: Estado do atendimento (ai = IA atendendo, human = humano atendendo)
- **journey_stage**: Estagio da jornada do cliente no funil

### Termos Especificos - Locacao de Ar-Condicionado (Lazaro)
- **AR/Equipamento**: Aparelho de ar-condicionado
- **BTUs**: Unidade de capacidade do AR (9000, 12000, 18000, 24000, 30000, 36000, 48000, 60000)
- **Locatario**: Cliente que aluga os equipamentos (ARs)
- **Fiador**: Garantidor do contrato de locacao
- **Patrimonio**: Numero de identificacao unico do equipamento
- **Valor comercial**: Valor de mercado do equipamento em R$
- **Mensalidade**: Valor mensal pago pelo cliente (FONTE: asaas_contratos.value)
- **Quebra de contrato**: Cliente que cancelou e esta pagando parcelado o valor residual
- **Locacao**: Aluguel mensal do AR
- **Manutencao preventiva**: Revisao semestral obrigatoria dos equipamentos
- **Proxima manutencao**: Data da proxima revisao (campo proxima_manutencao em contract_details)
- **Contrato ativo**: Status ACTIVE em asaas_contratos = cliente pagando mensalidade
- **Contrato cancelado**: Status INACTIVE em asaas_contratos = cliente nao aluga mais

### Regras de Negocio - Lazaro
- Um contrato pode ter MULTIPLOS equipamentos (ARs)
- Cada AR tem: BTUs, marca, modelo, patrimonio, valor_comercial
- Manutencao preventiva obrigatoria a cada 6 meses
- Cliente em atraso: status = 'OVERDUE' em asaas_cobrancas
- Cliente ativo: status = 'ACTIVE' em asaas_contratos
- Inadimplente = cliente com cobranca OVERDUE

### Queries Especificas - Lazaro (Equipamentos e BTUs)

Pergunta: "Quantos ARs/equipamentos tenho?"
SQL: SELECT COALESCE(SUM(qtd_ars), 0) as total_ars FROM contract_details WHERE agent_id = '{agent_id}'::uuid

Pergunta: "Quantos ARs de X BTUs tenho?" (ex: 12000)
SQL: SELECT COUNT(*) as quantidade FROM contract_details cd, jsonb_array_elements(cd.equipamentos) e WHERE cd.agent_id = '{agent_id}'::uuid AND (e->>'btus')::int = X

Pergunta: "Distribuicao de ARs por BTUs"
SQL: SELECT (e->>'btus')::int as btus, COUNT(*) as quantidade FROM contract_details cd, jsonb_array_elements(cd.equipamentos) e WHERE cd.agent_id = '{agent_id}'::uuid GROUP BY (e->>'btus')::int ORDER BY btus

Pergunta: "Qual o valor total do meu patrimonio?"
SQL: SELECT COALESCE(SUM(valor_comercial_total), 0) as patrimonio_total FROM contract_details WHERE agent_id = '{agent_id}'::uuid

Pergunta: "Marcas de AR mais comuns"
SQL: SELECT e->>'marca' as marca, COUNT(*) as quantidade FROM contract_details cd, jsonb_array_elements(cd.equipamentos) e WHERE cd.agent_id = '{agent_id}'::uuid GROUP BY e->>'marca' ORDER BY quantidade DESC LIMIT 10

Pergunta: "Clientes com manutencao vencida/atrasada"
SQL: SELECT locatario_nome, locatario_telefone, proxima_manutencao FROM contract_details WHERE agent_id = '{agent_id}'::uuid AND proxima_manutencao < CURRENT_DATE ORDER BY proxima_manutencao

Pergunta: "Proximas manutencoes"
SQL: SELECT locatario_nome, locatario_telefone, proxima_manutencao FROM contract_details WHERE agent_id = '{agent_id}'::uuid AND proxima_manutencao >= CURRENT_DATE ORDER BY proxima_manutencao LIMIT 20

### Queries Especificas - Lazaro (Financeiro)

Pergunta: "Quanto faturei esse mes?"
SQL: SELECT COALESCE(SUM(value), 0) as faturamento_bruto, COALESCE(SUM(net_value), 0) as faturamento_liquido FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status IN ('RECEIVED', 'CONFIRMED') AND deleted_from_asaas = false AND payment_date >= date_trunc('month', CURRENT_DATE)

Pergunta: "Faturamento do mes passado"
SQL: SELECT COALESCE(SUM(value), 0) as faturamento_bruto, COALESCE(SUM(net_value), 0) as faturamento_liquido FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status IN ('RECEIVED', 'CONFIRMED') AND deleted_from_asaas = false AND payment_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') AND payment_date < date_trunc('month', CURRENT_DATE)

Pergunta: "Comparativo faturamento mes atual vs anterior"
SQL: SELECT COALESCE(SUM(value) FILTER (WHERE payment_date >= date_trunc('month', CURRENT_DATE)), 0) as mes_atual, COALESCE(SUM(value) FILTER (WHERE payment_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') AND payment_date < date_trunc('month', CURRENT_DATE)), 0) as mes_anterior FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status IN ('RECEIVED', 'CONFIRMED') AND deleted_from_asaas = false

Pergunta: "Taxa de inadimplencia"
SQL: SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'OVERDUE') / NULLIF(COUNT(*), 0), 1) as taxa_inadimplencia_percent FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND deleted_from_asaas = false AND due_date >= CURRENT_DATE - INTERVAL '90 days'

Pergunta: "Quem esta devendo/em atraso/inadimplente?"
SQL: SELECT customer_name, value, due_date, dias_atraso FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status = 'OVERDUE' AND deleted_from_asaas = false ORDER BY dias_atraso DESC LIMIT 50

Pergunta: "Valor total em atraso/atrasado"
SQL: SELECT COALESCE(SUM(value), 0) as valor_atrasado, COUNT(*) as quantidade_cobrancas FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status = 'OVERDUE' AND deleted_from_asaas = false

Pergunta: "Quantos contratos ativos tenho?"
SQL: SELECT COUNT(*) as contratos_ativos FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false

Pergunta: "Valor total mensal (receita recorrente)"
SQL: SELECT COALESCE(SUM(value), 0) as receita_mensal FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false

Pergunta: "Maiores pagadores/clientes mais valiosos"
SQL: SELECT customer_name, value as mensalidade FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false ORDER BY value DESC LIMIT 20

Pergunta: "Me fala sobre o cliente X" ou "Detalhes do cliente"
SQL: SELECT c.customer_name, c.value as mensalidade, c.status, c.next_due_date, cd.qtd_ars, cd.valor_comercial_total, cd.locatario_telefone, cd.proxima_manutencao FROM asaas_contratos c LEFT JOIN contract_details cd ON c.id = cd.subscription_id WHERE c.agent_id = '{agent_id}' AND c.customer_name ILIKE '%X%' AND c.deleted_from_asaas = false

### contract_details (contratos de locacao de equipamentos/ARs)
- id: uuid (PK)
- agent_id: uuid (FK para agents)
- subscription_id: text (ID do contrato no Asaas)
- customer_id: text (ID do cliente no Asaas)
- numero_contrato: text (numero legivel do contrato)
- locatario_nome: text (nome do cliente que aluga)
- locatario_cpf_cnpj: text (documento do locatario)
- locatario_telefone: text
- locatario_endereco: text
- fiador_nome: text (garantidor do contrato)
- fiador_cpf: text
- fiador_telefone: text
- equipamentos: jsonb (array de ARs: btus, marca, modelo, patrimonio, valor_comercial)
- qtd_ars: integer (quantidade total de equipamentos)
- valor_comercial_total: numeric (soma do valor de todos equipamentos em R$)
- endereco_instalacao: text (onde os ARs estao instalados)
- prazo_meses: integer (duracao do contrato)
- data_inicio: date
- data_termino: date
- dia_vencimento: integer (1-31)
- valor_mensal: numeric (NAO USAR! Vem de parsing de PDF, pode estar ERRADO. Use asaas_contratos.value como FONTE DE VERDADE para mensalidades)
- proxima_manutencao: date
- pdf_url: text (link do contrato PDF)
- created_at: timestamp

### agents (configuracao dos agentes de IA)
- id: uuid (PK)
- user_id: uuid (dono/proprietario do agente)
- name: text (nome do agente, ex: "Agnes", "Salvador")
- type: text (tipo: agnes, salvador, diana, athena)
- status: text (ativo, pausado, etc)
- empresa: text (nome da empresa do cliente)
- asaas_enabled: boolean (integracao Asaas ativa?)
- google_calendar_enabled: boolean (integracao Google Calendar ativa?)
- follow_up_enabled: boolean (Salvador ativo para follow-ups?)
- table_leads: text (nome da tabela dinamica de leads)
- table_messages: text (nome da tabela dinamica de mensagens)
- created_at: timestamp

### asaas_clientes (clientes cadastrados no Asaas para cobranca)
- id: varchar (PK, ID unico do Asaas)
- agent_id: uuid (FK para agents)
- name: text (nome completo do cliente)
- cpf_cnpj: varchar (CPF ou CNPJ do cliente)
- email: varchar
- phone: varchar (telefone fixo)
- mobile_phone: varchar (celular)
- city: varchar
- state: varchar (UF, ex: SP, RJ)
- date_created: date (data de cadastro no Asaas)
- deleted_from_asaas: boolean (true = cliente excluido, SEMPRE filtrar = false)

### asaas_contratos (assinaturas/contratos recorrentes no Asaas) *** FONTE DE VERDADE PARA MENSALIDADES ***
- id: text (PK, ID do Asaas)
- agent_id: text (FK) *** ATENCAO: tipo TEXT, nao UUID ***
- customer_id: text (ID do cliente)
- customer_name: text (nome do cliente)
- value: numeric *** FONTE DE VERDADE para valor mensal em R$ - SEMPRE use esta coluna para perguntas sobre mensalidade/valor de contrato ***
- status: text (ACTIVE = ativo, INACTIVE = cancelado)
- cycle: text (MONTHLY = mensal, WEEKLY = semanal)
- next_due_date: date (proxima cobranca)
- description: text (descricao do servico)
- billing_type: text (BOLETO, PIX, CREDIT_CARD)
- deleted_from_asaas: boolean (SEMPRE filtrar = false)

### asaas_cobrancas (faturas/boletos gerados)
- id: text (PK, ID do Asaas)
- agent_id: text (FK) *** ATENCAO: tipo TEXT, nao UUID ***
- customer_id: text
- customer_name: text
- subscription_id: text (ID do contrato se recorrente)
- value: numeric (valor da cobranca em R$)
- net_value: numeric (valor liquido apos taxas)
- status: text (ver STATUS DE COBRANCA abaixo)
- billing_type: text (BOLETO, PIX, CREDIT_CARD)
- due_date: date (data de vencimento)
- payment_date: date (data do pagamento, null se nao pago)
- dias_atraso: integer (dias em atraso, 0 se em dia)
- invoice_url: text (link do boleto/fatura)
- deleted_from_asaas: boolean (SEMPRE filtrar = false)

### schedules (agendamentos de reunioes/visitas)
- id: uuid (PK)
- agent_id: uuid (FK)
- remote_jid: varchar (telefone WhatsApp do lead)
- customer_name: varchar (nome do cliente)
- company_name: varchar (empresa do cliente)
- scheduled_at: timestamp (data/hora do agendamento)
- ends_at: timestamp (fim do agendamento)
- status: varchar (pending, confirmed, cancelled, completed)
- google_event_id: varchar (ID do evento no Google Calendar)
- meeting_link: text (link do Google Meet)
- notes: text (observacoes)

### salvador_scheduled_followups (follow-ups agendados pelo Salvador)
- id: uuid (PK)
- agent_id: uuid (FK)
- lead_id: text (ID do lead na tabela dinamica)
- remotejid: text (telefone WhatsApp)
- step_number: integer (numero do follow-up: 1, 2, 3...)
- delay_minutes: integer (tempo de espera antes de enviar)
- scheduled_at: timestamp (quando sera enviado)
- status: text (pending = aguardando, sent = enviado, cancelled = cancelado)
- sent_at: timestamp (quando foi enviado)
- message_sent: text (mensagem que foi enviada)

### billing_notifications (historico de cobrancas enviadas pela Agnes - TABELA UNIFICADA)
- id: uuid (PK)
- agent_id: uuid (FK)
- payment_id: text (ID da cobranca no Asaas)
- customer_id: text
- customer_name: text
- phone: text (WhatsApp do cliente)
- valor: numeric (valor cobrado em R$)
- due_date: date (vencimento)
- notification_type: text (reminder, due_date, overdue)
- days_from_due: integer (dias do vencimento: negativo = antes, positivo = apos)
- scheduled_date: date (data agendada para envio)
- sent_at: timestamp (quando foi enviado)
- status: text (pending, sent, failed, skipped, paid, overdue, deleted, refunded, dunning)
- message_text: text (mensagem enviada)
- billing_type: text (tipo de cobranca: BOLETO, PIX, etc)
- subscription_id: text (ID da assinatura)

## STATUS DE COBRANCA (Asaas) - Valores possiveis para status em asaas_cobrancas
- PENDING = Aguardando pagamento (boleto gerado, ainda nao venceu)
- RECEIVED = Recebido via transferencia/deposito
- RECEIVED_IN_CASH = Recebido em dinheiro (confirmado manual)
- CONFIRMED = Confirmado (pagamento em processamento)
- OVERDUE = Vencido e nao pago (em atraso!)
- REFUNDED = Estornado/reembolsado
- DUNNING_REQUESTED = Enviado para protesto/negativacao

## STATUS DE CONTRATO (Asaas) - Valores possiveis para status em asaas_contratos
- ACTIVE = Contrato ativo, gerando cobrancas
- INACTIVE = Contrato cancelado/pausado

## EXEMPLOS DE QUERIES

Pergunta: "Quantos clientes tenho?"
SQL: SELECT COUNT(*) as total FROM asaas_clientes WHERE agent_id = '{agent_id}'::uuid AND deleted_from_asaas = false

Pergunta: "Quantos equipamentos/produtos/itens tenho?" (se existir contract_details)
SQL: SELECT COALESCE(SUM(qtd_ars), 0) as total FROM contract_details WHERE agent_id = '{agent_id}'::uuid

Pergunta: "Lista de equipamentos/itens" (se existir contract_details com JSONB)
SQL: SELECT locatario_nome, e->>'marca' as marca, e->>'modelo' as modelo FROM contract_details, jsonb_array_elements(equipamentos) as e WHERE agent_id = '{agent_id}'::uuid LIMIT 50

Pergunta: "Cobrancas atrasadas"
SQL: SELECT customer_name, value, due_date, dias_atraso FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status = 'OVERDUE' AND deleted_from_asaas = false ORDER BY dias_atraso DESC

Pergunta: "Quanto faturei este mes?"
SQL: SELECT COALESCE(SUM(value), 0) as total FROM asaas_cobrancas WHERE agent_id = '{agent_id}' AND status IN ('RECEIVED', 'CONFIRMED') AND deleted_from_asaas = false AND payment_date >= date_trunc('month', CURRENT_DATE)

Pergunta: "Contratos ativos"
SQL: SELECT customer_name, value, next_due_date, description FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false ORDER BY value DESC

Pergunta: "Quanto o cliente X paga por mes?" ou "Qual a mensalidade do cliente?"
SQL: SELECT customer_name, value as mensalidade FROM asaas_contratos WHERE agent_id = '{agent_id}' AND customer_name ILIKE '%X%' AND status = 'ACTIVE' AND deleted_from_asaas = false

Pergunta: "Qual o valor total mensal de todos os contratos?"
SQL: SELECT COALESCE(SUM(value), 0) as total_mensal FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false

Pergunta: "Clientes por valor de mensalidade (maiores pagadores)"
SQL: SELECT customer_name, value as mensalidade FROM asaas_contratos WHERE agent_id = '{agent_id}' AND status = 'ACTIVE' AND deleted_from_asaas = false ORDER BY value DESC LIMIT 20

Pergunta: "Agendamentos de hoje"
SQL: SELECT customer_name, scheduled_at, status FROM schedules WHERE agent_id = '{agent_id}'::uuid AND DATE(scheduled_at) = CURRENT_DATE ORDER BY scheduled_at

Pergunta: Se nao souber qual tabela usar, explore:
SQL: SELECT * FROM contract_details WHERE agent_id = '{agent_id}'::uuid LIMIT 3

## INSTRUCOES

1. Gere APENAS o SQL, sem explicacoes
2. Use sempre o placeholder {agent_id} - sera substituido automaticamente
3. Para tabelas asaas_contratos, asaas_cobrancas: agent_id e TEXT
4. Para tabelas agents, asaas_clientes, schedules, salvador_scheduled_followups, contract_details: agent_id e UUID (use ::uuid cast)
5. Sempre filtre deleted_from_asaas = false para tabelas Asaas
6. Limite resultados com LIMIT 100 para evitar respostas muito grandes
7. Use COALESCE para evitar NULL em agregacoes
8. Para campos JSONB, use: jsonb_array_elements(campo) e notacao ->>
9. Se nao souber a resposta, EXPLORE os dados com SELECT * LIMIT 5 em vez de retornar "sem dados"
10. Entenda sinonimos: "ar/ars/equipamento" pode ser qtd_ars ou equipamentos; "cliente/locatario" pode ser customer_name ou locatario_nome
11. **TABELAS DINAMICAS de leads/messages NAO tem agent_id** - use diretamente com aspas: SELECT * FROM "NomeDaTabela"
12. Nomes de tabelas dinamicas devem SEMPRE estar entre aspas duplas por causa de maiusculas/minusculas

## REGRA CRITICA: FONTE DE VERDADE PARA VALORES

**PARA PERGUNTAS SOBRE MENSALIDADE, VALOR DE CONTRATO, QUANTO PAGA, FATURAMENTO:**
- SEMPRE use: asaas_contratos.value (FONTE DE VERDADE - vem direto da API do Asaas)
- NUNCA use: contract_details.valor_mensal (vem de parsing de PDF, frequentemente ERRADO)

Exemplos de perguntas que DEVEM usar asaas_contratos.value:
- "Quanto o cliente X paga por mes?" -> asaas_contratos.value
- "Qual a mensalidade do contrato?" -> asaas_contratos.value
- "Qual o valor mensal?" -> asaas_contratos.value
- "Quanto faturamos com cliente X?" -> asaas_contratos.value ou asaas_cobrancas.value

A tabela contract_details serve para: equipamentos, endereco de instalacao, prazo, fiador, PDF.
A tabela asaas_contratos serve para: valor mensal, status do contrato, ciclo de cobranca.
"""


# ============================================================================
# FUNCOES AUXILIARES
# ============================================================================

def get_user_agent_ids(user_id: str) -> List[Dict[str, Any]]:
    """
    Busca todos os agentes do usuario.

    Returns:
        Lista de dicts com id, name, table_leads, table_messages
    """
    try:
        svc = get_supabase_service()
        result = svc.client.table("agents").select(
            "id, name, table_leads, table_messages, asaas_enabled"
        ).eq("user_id", user_id).execute()

        return result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar agentes do usuario: {e}")
        return []


def build_full_schema(agents: List[Dict[str, Any]]) -> str:
    """
    Constroi o schema completo: base + dinamico.

    Args:
        agents: Lista de agentes do usuario

    Returns:
        Schema completo para o prompt
    """
    dynamic_schema = build_dynamic_schema(agents)
    return SCHEMA_CONTEXT + dynamic_schema


def format_history_for_prompt(history: Optional[List[HistoryMessage]], max_messages: int = 5) -> str:
    """
    Formata o historico de mensagens para incluir no prompt.

    Args:
        history: Lista de mensagens anteriores
        max_messages: Numero maximo de mensagens a incluir (default 5)

    Returns:
        String formatada com o historico ou string vazia
    """
    if not history:
        return ""

    # Limitar ao maximo de mensagens (ultimas N)
    recent_history = history[-max_messages:]

    lines = ["## HISTORICO DA CONVERSA (use para contexto)"]
    for msg in recent_history:
        role_label = "Usuario" if msg.role == "user" else "Athena"
        # Truncar mensagens longas
        content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
        lines.append(f"{role_label}: {content}")

    lines.append("")  # Linha em branco apos historico
    return "\n".join(lines)


def is_conversational_question(question: str, history: Optional[List[HistoryMessage]] = None) -> bool:
    """
    Detecta se a pergunta e conversacional (nao requer SQL).

    Exemplos:
    - "como chegou a essa conclusao?"
    - "explique melhor"
    - "por que?"
    - "o que significa isso?"
    - "ta errado" (correcao)

    Returns:
        True se for pergunta conversacional
    """
    question_lower = question.lower().strip()

    # Padroes de perguntas conversacionais
    conversational_patterns = [
        "como chegou",
        "como voce chegou",
        "explique",
        "explicar",
        "por que",
        "porque",
        "o que significa",
        "o que quer dizer",
        "nao entendi",
        "pode explicar",
        "como calculou",
        "de onde veio",
        "como sabe",
        "como descobriu",
        "me explica",
        "como assim",
        # Padroes de correcao
        "ta errado",
        "tá errado",
        "está errado",
        "esta errado",
        "incorreto",
        "não é isso",
        "nao e isso",
        "dado errado",
        "valor errado",
        "não está certo",
        "nao esta certo",
        "errou",
    ]

    for pattern in conversational_patterns:
        if pattern in question_lower:
            return True

    return False


def is_valid_sql(text: str) -> bool:
    """
    Verifica se o texto parece ser SQL valido.

    Returns:
        True se parecer SQL, False se for texto explicativo
    """
    if not text:
        return False

    text_upper = text.upper().strip()

    # Deve comecar com um comando SQL
    sql_starters = ["SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]
    starts_with_sql = any(text_upper.startswith(cmd) for cmd in sql_starters)

    if not starts_with_sql:
        return False

    # Nao deve conter frases explicativas longas
    non_sql_indicators = [
        "nao consigo",
        "nao posso",
        "desculpe",
        "preciso de mais",
        "nao entendi",
        "poderia",
        "por favor",
    ]

    text_lower = text.lower()
    for indicator in non_sql_indicators:
        if indicator in text_lower:
            return False

    return True


def generate_sql_with_gemini(
    question: str,
    agent_id: str,
    agents: Optional[List[Dict[str, Any]]] = None,
    history: Optional[List[HistoryMessage]] = None
) -> Optional[str]:
    """
    Usa Gemini para gerar SQL a partir da pergunta.

    Args:
        question: Pergunta em linguagem natural
        agent_id: ID do agente para filtro de seguranca
        agents: Lista de agentes do usuario (para schema dinamico)
        history: Historico de mensagens anteriores para contexto

    Returns:
        SQL gerado, "NO_SQL" para perguntas conversacionais, ou None se falhar
    """
    try:
        # Configurar Gemini
        genai.configure(api_key=settings.google_api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.1,  # Baixa para SQL deterministico
                "max_output_tokens": 1024,
            }
        )

        # Usar schema dinamico se temos agentes
        if agents:
            schema = build_full_schema(agents)
        else:
            schema = SCHEMA_CONTEXT

        # Formatar historico se existir
        history_context = format_history_for_prompt(history)

        prompt = f"""{schema}

{history_context}## PERGUNTA ATUAL DO USUARIO
{question}

## INSTRUCOES ESPECIAIS PARA HISTORICO
- Se a pergunta atual faz referencia a perguntas anteriores (ex: "e a segunda?", "e o total?", "quais sao?"), use o HISTORICO acima para entender o contexto
- Se o usuario perguntou sobre "marcas" antes e agora pergunta "e a segunda?", gere SQL para a segunda marca mais frequente
- Se o usuario perguntou sobre "leads quentes" e agora pergunta "quantos?", refira-se aos leads quentes
- Mantenha consistencia com as queries anteriores quando fizer sentido

## PERGUNTAS CONVERSACIONAIS
Se o usuario fizer uma pergunta que NAO requer busca no banco de dados, como:
- "como chegou a essa conclusao?" (pergunta sobre raciocinio)
- "explique melhor" (pedido de explicacao)
- "por que?" (pergunta sobre motivo)
- "o que significa isso?" (pedido de definicao)

Nesses casos, responda EXATAMENTE assim:
NO_SQL: [sua resposta explicativa em portugues]

## RESPOSTA
Se for pergunta sobre dados: Gere APENAS o SQL (sem markdown, sem explicacoes, sem ```sql)
Se for pergunta conversacional: Responda com NO_SQL: seguido da explicacao"""

        response = model.generate_content(prompt)

        if not response or not response.text:
            return None

        result = response.text.strip()

        # Limpar markdown se presente
        result = re.sub(r'^```sql\s*', '', result, flags=re.MULTILINE)
        result = re.sub(r'^```\s*', '', result, flags=re.MULTILINE)
        result = re.sub(r'\s*```$', '', result, flags=re.MULTILINE)
        result = result.strip()

        # Verificar se e resposta conversacional (NO_SQL:)
        if result.upper().startswith("NO_SQL:"):
            logger.debug(f"Resposta conversacional detectada")
            return result  # Retorna com o prefixo NO_SQL: para tratamento especial

        # Validar se parece SQL
        if not is_valid_sql(result):
            logger.warning(f"Gemini retornou texto que nao parece SQL: {result[:100]}")
            # Tentar tratar como resposta conversacional
            return f"NO_SQL: {result}"

        # Substituir placeholder pelo agent_id real
        result = result.replace("{agent_id}", agent_id)
        result = result.replace("{agent_ids}", agent_id)

        logger.debug(f"SQL gerado: {result}")

        return result

    except Exception as e:
        logger.error(f"Erro ao gerar SQL com Gemini: {e}")
        return None


def execute_sql_safely(sql: str) -> Dict[str, Any]:
    """
    Executa SQL de forma segura no Supabase.

    Args:
        sql: Query SQL a executar

    Returns:
        Dict com dados ou erro
    """
    try:
        # Validar que nao e uma operacao de escrita
        sql_upper = sql.upper().strip()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]

        for cmd in forbidden:
            if sql_upper.startswith(cmd) or f" {cmd} " in sql_upper:
                return {"error": f"Operacao {cmd} nao permitida"}

        svc = get_supabase_service()

        # Executar via RPC ou query direta
        # Supabase Python nao tem execute_sql direto, usar postgrest
        # Vamos usar a funcao RPC se existir, ou raw SQL via httpx

        import httpx

        # Usar API REST do Supabase para executar SQL via PostgREST RPC
        # Precisamos de uma funcao RPC ou usar a REST API diretamente

        # Abordagem: usar supabase-py com rpc se tiver, senao httpx direto
        headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

        # Usar endpoint /rest/v1/rpc para chamar funcao ou /sql
        # Supabase nao tem /sql endpoint publico, precisamos usar pg_query RPC
        # Alternativa: construir query PostgREST equivalente

        # Vamos executar via a API de banco direto (precisa de pg funcao)
        # Por simplicidade, vamos usar httpx com raw SQL endpoint

        url = f"{settings.supabase_url}/rest/v1/rpc/athena_execute_sql"

        with httpx.Client() as client:
            response = client.post(
                url,
                json={"query_text": sql},
                headers=headers,
                timeout=30.0
            )

            if response.status_code == 404:
                # Funcao RPC nao existe - fallback para queries simples via PostgREST
                # Tentar parsear SQL SELECT simples e converter para PostgREST
                return execute_via_postgrest(sql, svc)

            if response.status_code != 200:
                logger.warning(f"Erro ao executar SQL: {response.status_code} - {response.text}")
                return {"error": f"Erro ao executar consulta: {response.text[:200]}"}

            # O resultado da funcao RPC vem como JSONB (lista ou null)
            result = response.json()

            # Se resultado for None, retornar lista vazia
            if result is None:
                return {"data": []}

            # Se for lista, retornar diretamente
            if isinstance(result, list):
                return {"data": result}

            # Se for outro tipo, encapsular em lista
            return {"data": [result] if result else []}

    except Exception as e:
        logger.error(f"Erro ao executar SQL: {e}")
        return {"error": str(e)}


def execute_via_postgrest(sql: str, svc) -> Dict[str, Any]:
    """
    Tenta executar queries simples via PostgREST.
    Suporta apenas SELECT basicos.
    """
    try:
        sql_upper = sql.upper().strip()

        # Extrair tabela do SELECT
        # Pattern: SELECT ... FROM table_name WHERE ...
        match = re.search(r'FROM\s+(\w+)', sql, re.IGNORECASE)
        if not match:
            return {"error": "Nao foi possivel identificar a tabela na query"}

        table_name = match.group(1)

        # Para queries simples, usar o cliente Supabase
        # Isso e limitado mas funciona para a maioria dos casos

        # Verificar se e uma query de contagem
        if "COUNT(*)" in sql_upper or "COUNT(" in sql_upper:
            # Extrair condicoes WHERE
            where_match = re.search(r'WHERE\s+(.+?)(?:ORDER|GROUP|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)

            result = svc.client.table(table_name).select("*", count="exact")

            # Aplicar filtros basicos se possivel
            if where_match:
                conditions = where_match.group(1).strip()
                # Parsear condicoes simples (muito basico)
                # Ex: agent_id = 'xxx' AND status = 'ACTIVE'
                result = apply_basic_filters(result, conditions)

            result = result.limit(1).execute()

            return {"data": [{"total": result.count or 0}]}

        # Query normal - executar select
        result = svc.client.table(table_name).select("*")

        # Extrair WHERE
        where_match = re.search(r'WHERE\s+(.+?)(?:ORDER|GROUP|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            conditions = where_match.group(1).strip()
            result = apply_basic_filters(result, conditions)

        # Extrair LIMIT
        limit_match = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else 100

        result = result.limit(limit).execute()

        return {"data": result.data or []}

    except Exception as e:
        logger.error(f"Erro no fallback PostgREST: {e}")
        return {"error": f"Erro ao processar consulta: {str(e)}"}


def apply_basic_filters(query, conditions: str):
    """
    Aplica filtros basicos a uma query PostgREST.
    Suporta: =, IN, AND, deleted_from_asaas = false
    """
    try:
        # Dividir por AND
        parts = re.split(r'\s+AND\s+', conditions, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()

            # agent_id = 'xxx'::uuid ou agent_id = 'xxx'
            if "agent_id" in part.lower():
                match = re.search(r"agent_id\s*=\s*'([^']+)'", part, re.IGNORECASE)
                if match:
                    query = query.eq("agent_id", match.group(1))
                continue

            # deleted_from_asaas = false
            if "deleted_from_asaas" in part.lower():
                if "false" in part.lower():
                    query = query.eq("deleted_from_asaas", False)
                continue

            # status = 'XXX'
            if "status" in part.lower() and "=" in part:
                match = re.search(r"status\s*=\s*'([^']+)'", part, re.IGNORECASE)
                if match:
                    query = query.eq("status", match.group(1))
                continue

            # status IN ('XXX', 'YYY')
            if "status" in part.lower() and " IN " in part.upper():
                match = re.search(r"status\s+IN\s*\(([^)]+)\)", part, re.IGNORECASE)
                if match:
                    values = [v.strip().strip("'\"") for v in match.group(1).split(",")]
                    query = query.in_("status", values)
                continue

        return query

    except Exception as e:
        logger.debug(f"Erro ao aplicar filtros: {e}")
        return query


def format_response_with_gemini(
    question: str,
    data: Any,
    history: Optional[List[HistoryMessage]] = None,
    source_table: Optional[str] = None
) -> str:
    """
    Usa Gemini para formatar a resposta em linguagem natural.

    Args:
        question: Pergunta original
        data: Dados retornados pela query
        history: Historico de mensagens para contexto
        source_table: Tabela de onde vieram os dados (opcional)

    Returns:
        Resposta formatada em portugues
    """
    try:
        genai.configure(api_key=settings.google_api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.5,  # Reduzido de 0.7 para mais consistencia
                "max_output_tokens": 1024,
            }
        )

        # Limitar dados para nao estourar contexto
        data_str = str(data)
        if len(data_str) > 5000:
            data_str = data_str[:5000] + "... (dados truncados)"

        # Formatar historico se existir
        history_context = format_history_for_prompt(history)

        # Detectar se e correcao
        is_correction_context = is_correction(question)

        # Determinar se tem historico
        has_history = bool(history and len(history) > 0)

        # Contexto de fonte se disponivel
        source_context = f"\n## FONTE DOS DADOS\nTabela: {source_table}" if source_table else ""

        prompt = f"""Voce e o Athena Oraculo, assistente de analytics do PHANT.
Responda a pergunta do usuario de forma clara e direta em portugues brasileiro.

{history_context}## PERGUNTA ATUAL
{question}

## DADOS RETORNADOS
{data_str}
{source_context}

## REGRAS DE FORMATACAO

### SOBRE SAUDACAO NA RESPOSTA
- Se NAO houver historico de conversa: pode iniciar com uma saudacao breve e natural
- Se HOUVER historico de conversa: va direto ao ponto, SEM "Ola!", SEM saudacao
- Historico atual: {"SIM - NAO cumprimente, va direto ao ponto" if has_history else "NAO - pode cumprimentar brevemente se fizer sentido"}

### SOBRE FONTE DOS DADOS
- SEMPRE mencione de onde veio a informacao quando relevante
- Exemplos: "Segundo a tabela de leads...", "De acordo com os contratos no Asaas...", "Com base nos agendamentos..."
- Isso aumenta a confianca do usuario na resposta

### SOBRE CONTEXTO ANTERIOR
- Se a pergunta faz referencia ao historico (ex: "e a segunda?", "e o total?"), responda no contexto
- Faca referencias ao que foi perguntado antes quando relevante
- Exemplo: "Sobre os leads quentes que voce perguntou..."

### SOBRE SUGESTOES
- Quando fizer sentido, sugira UMA pergunta relacionada que o usuario pode fazer
- Exemplo: "Quer saber quantos desses leads tem reuniao agendada?"
- NAO sugira sempre, apenas quando for natural e util

### SOBRE CORRECOES
{"- O usuario indicou que algo esta ERRADO. Seja receptivo e ofereca ajuda para entender o problema." if is_correction_context else ""}

### INSTRUCOES GERAIS
1. Responda de forma conversacional e amigavel
2. Destaque numeros importantes (valores, totais, contagens)
3. Se os dados estiverem vazios, diga que nao ha dados disponiveis
4. Se houver erro, explique de forma simples
5. Use emojis com moderacao (apenas para valores de dinheiro ou contagens importantes)
6. Formate valores monetarios em reais (R$)
7. Seja conciso - maximo 3-4 frases para respostas simples
8. Para listas, mostre os primeiros itens e mencione o total

## RESPOSTA"""

        response = model.generate_content(prompt)

        if response and response.text:
            return response.text.strip()

        return "Desculpe, nao consegui formatar a resposta."

    except Exception as e:
        logger.error(f"Erro ao formatar resposta: {e}")

        # Fallback: resposta basica
        if isinstance(data, list):
            if len(data) == 0:
                return "Nao encontrei dados para sua pergunta."
            if len(data) == 1 and "total" in data[0]:
                return f"O total e: {data[0]['total']}"
            return f"Encontrei {len(data)} resultados."

        return f"Resultado: {data}"


# ============================================================================
# ENDPOINTS
# ============================================================================

def extract_table_from_sql(sql: str) -> Optional[str]:
    """
    Extrai o nome da tabela principal de uma query SQL.

    Args:
        sql: Query SQL

    Returns:
        Nome da tabela ou None
    """
    if not sql:
        return None

    # Pattern para FROM "tabela" ou FROM tabela
    match = re.search(r'FROM\s+["\']?(\w+)["\']?', sql, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def is_short_question_needing_context(question: str, history: Optional[List[HistoryMessage]]) -> bool:
    """
    Verifica se a pergunta e muito curta e precisa de contexto do historico.

    Args:
        question: Pergunta atual
        history: Historico de mensagens

    Returns:
        True se a pergunta e curta demais e nao tem historico para dar contexto
    """
    # Perguntas muito curtas (1-3 caracteres) sem historico precisam de esclarecimento
    if len(question.strip()) <= 3 and not history:
        return True
    return False


@router.post("/ask", response_model=AskResponse)
async def ask_athena(
    body: AskRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Faz uma pergunta ao Athena Oraculo.

    O Athena gera SQL automaticamente, executa no banco,
    e retorna a resposta em linguagem natural.

    Args:
        body: Pergunta, agent_id opcional e historico opcional
        user: Usuario autenticado (via JWT)

    Returns:
        Resposta formatada com dados e SQL executado
    """
    start_time = datetime.utcnow()

    try:
        user_id = user["id"]
        question = body.question.strip()
        history = body.history

        # Limitar historico a 5 mensagens
        if history and len(history) > 5:
            history = history[-5:]

        print(f"[ATHENA] Pergunta de {user.get('email')} (user_id={user_id}): {question[:100]}...")
        if history:
            print(f"[ATHENA] Historico: {len(history)} mensagens")

        # =====================================================================
        # TRATAMENTO ESPECIAL: SAUDACAO
        # =====================================================================
        if is_greeting(question):
            print(f"[ATHENA] Detectada saudacao, retornando apresentacao")
            return AskResponse(
                resposta=get_greeting_response(),
                dados=None,
                sql_executado=None,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        # =====================================================================
        # TRATAMENTO ESPECIAL: CORRECAO
        # =====================================================================
        if is_correction(question) and not any(kw in question.lower() for kw in ["quantos", "qual", "liste", "mostre", "busque"]):
            # So trata como correcao se nao tiver keywords de busca
            print(f"[ATHENA] Detectada correcao, pedindo esclarecimento")
            return AskResponse(
                resposta=get_correction_response(),
                dados=None,
                sql_executado=None,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        # Verificar se pergunta e muito curta sem contexto
        if is_short_question_needing_context(question, history):
            return AskResponse(
                resposta="Pode detalhar um pouco mais sua pergunta? Nao entendi o que voce quer saber.",
                dados=None,
                sql_executado=None,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        # =====================================================================
        # TRATAMENTO ESPECIAL: PERGUNTAS DE NEGOCIO (Fase 1 - Consultora)
        # =====================================================================
        if is_business_health_question(question):
            print(f"[ATHENA] Detectada pergunta de negocio, usando tool get_business_health")

            # Buscar agentes do usuario primeiro
            agents = get_user_agent_ids(user_id)
            if not agents:
                return AskResponse(
                    resposta="Voce ainda nao tem nenhum agente configurado. Crie um agente primeiro.",
                    dados=None,
                    sql_executado=None,
                    tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
                )

            # Determinar agent_id (prioriza Asaas)
            asaas_agents = [a for a in agents if a.get("asaas_enabled")]
            if body.agent_id:
                agent_id = body.agent_id
            elif asaas_agents:
                agent_id = asaas_agents[0]["id"]
            else:
                agent_id = agents[0]["id"]

            # Chamar tool de business health
            try:
                health_data = await get_business_health(agent_id)

                # Formatar resposta com Gemini
                resposta = await format_business_health_response(health_data, question, history)

                tempo_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                logger.info(f"[ATHENA] Resposta de negocio gerada em {tempo_ms}ms")

                return AskResponse(
                    resposta=resposta,
                    dados={"business_health": health_data},
                    sql_executado=None,  # Nao usou SQL
                    tempo_ms=tempo_ms,
                )

            except Exception as e:
                logger.error(f"[ATHENA] Erro em business health: {e}", exc_info=True)
                return AskResponse(
                    resposta=f"Desculpe, ocorreu um erro ao calcular as metricas do negocio. Tente novamente.",
                    dados={"error": str(e)},
                    sql_executado=None,
                    tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
                )

        # 1. Buscar agentes do usuario
        agents = get_user_agent_ids(user_id)
        print(f"[ATHENA] Agentes encontrados: {len(agents)} - {[a.get('name') for a in agents]}")

        if not agents:
            return AskResponse(
                resposta="Voce ainda nao tem nenhum agente configurado. Crie um agente primeiro para comecar a usar o Athena.",
                dados=None,
                sql_executado=None,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        # 2. Determinar agent_id a usar
        if body.agent_id:
            # Verificar se o agent_id pertence ao usuario
            agent_ids = [a["id"] for a in agents]
            if body.agent_id not in agent_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "FORBIDDEN", "message": "Agente nao pertence a voce"},
                )
            agent_id = body.agent_id
            agent_name = next((a["name"] for a in agents if a["id"] == agent_id), "Agente")
        else:
            # Usar primeiro agente (ou o que tem Asaas habilitado)
            asaas_agents = [a for a in agents if a.get("asaas_enabled")]
            if asaas_agents:
                agent_id = asaas_agents[0]["id"]
                agent_name = asaas_agents[0]["name"]
            else:
                agent_id = agents[0]["id"]
                agent_name = agents[0]["name"]

        print(f"[ATHENA] Usando agente: {agent_name} ({agent_id})")

        # 3. Gerar SQL com Gemini (agora com schema dinamico e historico)
        sql_or_response = generate_sql_with_gemini(question, agent_id, agents=agents, history=history)
        print(f"[ATHENA] Resultado Gemini: {sql_or_response[:200] if sql_or_response else 'None'}...")

        if not sql_or_response:
            return AskResponse(
                resposta="Desculpe, nao consegui entender sua pergunta. Tente reformular de outra forma.",
                dados=None,
                sql_executado=None,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        # 3.1. Verificar se e resposta conversacional (NO_SQL:)
        if sql_or_response.upper().startswith("NO_SQL:"):
            # Resposta direta, sem necessidade de SQL
            resposta_direta = sql_or_response[7:].strip()  # Remove "NO_SQL: "
            print(f"[ATHENA] Resposta conversacional (sem SQL)")

            tempo_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.info(f"[ATHENA] Resposta conversacional gerada em {tempo_ms}ms")

            return AskResponse(
                resposta=resposta_direta,
                dados=None,
                sql_executado=None,
                tempo_ms=tempo_ms,
            )

        # E um SQL - continuar fluxo normal
        sql = sql_or_response
        logger.debug(f"[ATHENA] SQL: {sql}")

        # 4. Executar SQL
        result = execute_sql_safely(sql)
        print(f"[ATHENA] Resultado SQL: {result}")

        if "error" in result:
            logger.warning(f"[ATHENA] Erro SQL: {result['error']}")
            return AskResponse(
                resposta=f"Ocorreu um erro ao buscar os dados. Tente uma pergunta mais simples.",
                dados={"error": result["error"]},
                sql_executado=sql,
                tempo_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
            )

        data = result.get("data", [])

        # 5. Extrair tabela de origem para contexto
        source_table = extract_table_from_sql(sql)

        # 6. Formatar resposta com Gemini (incluindo historico e fonte para contexto)
        resposta = format_response_with_gemini(question, data, history=history, source_table=source_table)

        tempo_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        logger.info(f"[ATHENA] Resposta gerada em {tempo_ms}ms")

        return AskResponse(
            resposta=resposta,
            dados={"resultados": data, "total": len(data) if isinstance(data, list) else 1},
            sql_executado=sql,
            tempo_ms=tempo_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ATHENA] Erro: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao processar pergunta"},
        )


@router.get("/agents")
async def list_athena_agents(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Lista os agentes disponiveis para consulta do usuario.

    Returns:
        Lista de agentes com id, nome e recursos habilitados
    """
    try:
        agents = get_user_agent_ids(user["id"])

        return {
            "success": True,
            "agents": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "asaas_enabled": a.get("asaas_enabled", False),
                    "has_leads": bool(a.get("table_leads")),
                }
                for a in agents
            ],
        }

    except Exception as e:
        logger.error(f"Erro ao listar agentes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Erro ao listar agentes"},
        )


@router.get("/health")
async def athena_health():
    """Health check do Athena."""
    return {
        "status": "ok",
        "service": "athena-oraculo",
        "timestamp": datetime.utcnow().isoformat(),
    }
