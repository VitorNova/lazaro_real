# tests/mocks/manutencao.py
"""
Fixtures e constantes para testes de fluxo de manutenção.

Factories:
- make_cliente_asaas: Cria cliente do Asaas
- make_contract_details: Cria contrato com manutenção
- make_schedule: Cria agendamento de manutenção
- make_conversation_history: Cria histórico de conversa
- make_lead_manutencao: Cria lead em cenário de manutenção

Constantes:
- CLIENTE_COM_CONTRATO: Cliente Letícia com contrato ativo
- CLIENTE_SEM_CONTRATO: Cliente sem contrato
- CONTRATO_NOTIFICADO: Contrato com manutenção notificada (D-7)
- CONTRATO_AGENDADO: Contrato com manutenção já agendada
- AGENDAMENTO_MANHA: Horário preferido manhã
- AGENDAMENTO_TARDE: Horário preferido tarde
- LEAD_PEDINDO_REMARCACAO: Lead pedindo remarcação
- LEAD_CPF_SALVO: Lead após salvar CPF
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid


# =============================================================================
# FACTORIES
# =============================================================================


def make_cliente_asaas(
    id: str = None,
    name: str = "Cliente Teste",
    cpf_cnpj: str = "12345678901",
    mobile_phone: str = "5511999999999",
    email: str = "cliente@teste.com",
    **kwargs,
) -> Dict[str, Any]:
    """
    Cria dados de cliente do Asaas.

    Args:
        id: ID do cliente (gerado se não fornecido)
        name: Nome do cliente
        cpf_cnpj: CPF ou CNPJ (apenas números)
        mobile_phone: Telefone com DDI
        email: Email do cliente
        **kwargs: Campos extras

    Returns:
        Dict com dados do cliente
    """
    return {
        "id": id or f"cus_{uuid.uuid4().hex[:12]}",
        "name": name,
        "cpf_cnpj": cpf_cnpj,
        "mobile_phone": mobile_phone,
        "email": email,
        **kwargs,
    }


def make_contract_details(
    id: str = None,
    customer_id: str = None,
    numero_contrato: str = None,
    maintenance_status: str = "pending",
    proxima_manutencao: str = None,
    endereco_instalacao: str = "Rua Teste, 123",
    equipamentos: List[Dict] = None,
    valor_mensal: float = 150.00,
    agent_id: str = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Cria dados de contrato com manutenção.

    Args:
        id: UUID do contrato
        customer_id: ID do cliente no Asaas
        numero_contrato: Número do contrato (ex: 2024/001)
        maintenance_status: pending, notified, scheduled, done
        proxima_manutencao: Data ISO da próxima manutenção
        endereco_instalacao: Endereço onde equipamento está instalado
        equipamentos: Lista de equipamentos [{marca, btus, tipo, local}]
        valor_mensal: Valor mensal do contrato
        agent_id: UUID do agente
        **kwargs: Campos extras

    Returns:
        Dict com dados do contrato
    """
    if equipamentos is None:
        equipamentos = [
            {"marca": "LG", "btus": 12000, "tipo": "Split", "local": "Sala"}
        ]

    return {
        "id": id or str(uuid.uuid4()),
        "customer_id": customer_id or f"cus_{uuid.uuid4().hex[:12]}",
        "numero_contrato": numero_contrato or f"{date.today().year}/001",
        "maintenance_status": maintenance_status,
        "proxima_manutencao": proxima_manutencao,
        "endereco_instalacao": endereco_instalacao,
        "equipamentos": equipamentos,
        "valor_mensal": valor_mensal,
        "agent_id": agent_id or str(uuid.uuid4()),
        **kwargs,
    }


def make_schedule(
    dia: str = None,
    horario: str = "09:00",
    periodo: str = "manha",
    **kwargs,
) -> Dict[str, Any]:
    """
    Cria dados de agendamento de manutenção.

    Args:
        dia: Data no formato YYYY-MM-DD (default: 7 dias no futuro)
        horario: Horário preferido (ex: 09:00, 14:30)
        periodo: manha, tarde, noite
        **kwargs: Campos extras

    Returns:
        Dict com dados do agendamento
    """
    if dia is None:
        dia = (date.today() + timedelta(days=7)).isoformat()

    return {
        "dia": dia,
        "horario": horario,
        "periodo": periodo,
        **kwargs,
    }


def make_conversation_history(
    messages: List[Dict] = None,
    context: str = None,
    contract_id: str = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Cria histórico de conversa.

    Args:
        messages: Lista de mensagens [{role, parts, context?, contract_id?}]
        context: Contexto especial (manutencao_preventiva, cobranca, etc)
        contract_id: UUID do contrato relacionado
        **kwargs: Campos extras

    Returns:
        Dict com conversation_history
    """
    if messages is None:
        messages = []

    # Adicionar contexto à última mensagem do model se fornecido
    if context and messages:
        for msg in reversed(messages):
            if msg.get("role") == "model":
                msg["context"] = context
                if contract_id:
                    msg["contract_id"] = contract_id
                break

    return {
        "messages": messages,
        **kwargs,
    }


def make_lead_manutencao(
    remotejid: str = "5511999999999@s.whatsapp.net",
    nome: str = "Cliente Teste",
    cpf_cnpj: str = None,
    current_state: str = "ai",
    current_queue_id: int = 537,
    conversation_history: Dict = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Cria lead em cenário de manutenção.

    Args:
        remotejid: JID do WhatsApp
        nome: Nome do lead
        cpf_cnpj: CPF/CNPJ (pode ser None se ainda não coletado)
        current_state: ai, human, paused
        current_queue_id: ID da fila (537=IA, 453=atendimento)
        conversation_history: Histórico de conversa
        **kwargs: Campos extras

    Returns:
        Dict com dados do lead
    """
    if conversation_history is None:
        conversation_history = make_conversation_history()

    return {
        "id": str(uuid.uuid4()),
        "remotejid": remotejid,
        "nome": nome,
        "cpf_cnpj": cpf_cnpj,
        "current_state": current_state,
        "current_queue_id": current_queue_id,
        "conversation_history": conversation_history,
        "Atendimento_Finalizado": False,
        "ticket_id": 864657,
        **kwargs,
    }


# =============================================================================
# CONSTANTES - Cenários Prontos
# =============================================================================


# Cliente Letícia - caso real do bug (556696173197)
CLIENTE_COM_CONTRATO = make_cliente_asaas(
    id="cus_abc123",
    name="Letícia Paula Gusmão",
    cpf_cnpj="08465680107",
    mobile_phone="5566996173197",
    email="leticia@email.com",
)

# Cliente sem contrato ativo
CLIENTE_SEM_CONTRATO = make_cliente_asaas(
    id="cus_xyz789",
    name="Maria Silva",
    cpf_cnpj="98765432100",
    mobile_phone="5511988887777",
    email="maria@teste.com",
)

# Contrato com manutenção notificada (D-7)
CONTRATO_NOTIFICADO = make_contract_details(
    id="contract-uuid-123",
    customer_id="cus_abc123",
    numero_contrato="2024/001",
    maintenance_status="notified",
    proxima_manutencao=(date.today() + timedelta(days=7)).isoformat(),
    endereco_instalacao="Rua das Flores, 123 - Centro",
    equipamentos=[
        {"marca": "LG", "btus": 12000, "tipo": "Split", "local": "Sala"},
        {"marca": "Samsung", "btus": 9000, "tipo": "Split", "local": "Quarto"},
    ],
    valor_mensal=180.00,
)

# Contrato com manutenção já agendada
CONTRATO_AGENDADO = make_contract_details(
    id="contract-uuid-456",
    customer_id="cus_abc123",
    numero_contrato="2024/002",
    maintenance_status="scheduled",
    proxima_manutencao=(date.today() + timedelta(days=3)).isoformat(),
    endereco_instalacao="Av. Brasil, 456 - Sala 10",
    equipamentos=[
        {"marca": "Carrier", "btus": 18000, "tipo": "Split", "local": "Escritório"}
    ],
    valor_mensal=200.00,
)

# Agendamento manhã
AGENDAMENTO_MANHA = make_schedule(
    dia=(date.today() + timedelta(days=7)).isoformat(),
    horario="09:30",
    periodo="manha",
)

# Agendamento tarde
AGENDAMENTO_TARDE = make_schedule(
    dia=(date.today() + timedelta(days=7)).isoformat(),
    horario="14:30",
    periodo="tarde",
)

# Lead pedindo remarcação (antes de dar CPF)
LEAD_PEDINDO_REMARCACAO = make_lead_manutencao(
    remotejid="556696173197@s.whatsapp.net",
    nome=None,  # Ainda não identificado
    cpf_cnpj=None,
    conversation_history=make_conversation_history(
        messages=[
            {
                "role": "user",
                "parts": [{"text": "Poderíamos remarcar a manutenção pra outro horário?"}],
            },
            {
                "role": "model",
                "parts": [{"text": "Claro! Me informa seu CPF e o melhor dia e horário para a visita."}],
            },
        ]
    ),
)

# Lead após salvar CPF (cenário do bug - IA travou aqui)
LEAD_CPF_SALVO = make_lead_manutencao(
    remotejid="556696173197@s.whatsapp.net",
    nome="Letícia Paula Gusmão",
    cpf_cnpj="08465680107",
    conversation_history=make_conversation_history(
        messages=[
            {
                "role": "user",
                "parts": [{"text": "Poderíamos remarcar a manutenção pra outro horário?"}],
            },
            {
                "role": "model",
                "parts": [{"text": "Claro! Me informa seu CPF e o melhor dia e horário para a visita."}],
            },
            {
                "role": "user",
                "parts": [{"text": "084.656.801-07"}],
            },
            {
                "role": "model",
                "parts": [{"function_call": {"name": "salvar_dados_lead", "args": {"cpf": "084.656.801-07"}}}],
            },
            {
                "role": "function",
                "parts": [{"function_response": {"name": "salvar_dados_lead", "response": {"sucesso": True, "cpf": "08465680107"}}}],
            },
            {
                "role": "model",
                "parts": [{"text": "CPF salvo com sucesso"}],  # BUG: resposta literal
            },
            {
                "role": "user",
                "parts": [{"text": "Dia 24 às 13h30"}],
            },
            {
                "role": "model",
                "parts": [{"text": "Vou verificar a disponibilidade. Só um momento..."}],  # BUG: travou
            },
        ],
    ),
)
