"""
Servico de controle de slots de manutencao preventiva.

Regra de negocio:
- Maximo 1 manutencao por manha (08:00-12:00) por dia
- Maximo 1 manutencao por tarde (14:00-18:00) por dia

Usa a tabela `schedules` existente com service_name='manutencao_preventiva'
para armazenar e consultar agendamentos.
"""

import logging
from datetime import date, datetime, time
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

# Timezone padrao do Lazaro (Cuiaba/MT)
TIMEZONE_LAZARO = ZoneInfo("America/Cuiaba")

# Agent ID padrao do Lazaro
AGENT_ID_LAZARO = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Definicao dos periodos
PERIODOS = {
    "manha": {
        "hora_inicio": time(8, 0),
        "hora_fim": time(12, 0),
        "label": "Manhã (08h-12h)",
    },
    "tarde": {
        "hora_inicio": time(14, 0),
        "hora_fim": time(18, 0),
        "label": "Tarde (14h-18h)",
    },
}

# Identificador de servico na tabela schedules
SERVICE_NAME = "manutencao_preventiva"


def _get_periodo_from_hora(hora_inicio: time) -> Optional[str]:
    """Identifica o periodo com base na hora de inicio."""
    if hora_inicio == PERIODOS["manha"]["hora_inicio"]:
        return "manha"
    if hora_inicio == PERIODOS["tarde"]["hora_inicio"]:
        return "tarde"
    return None


def verificar_slot(
    data: date,
    periodo: str,
    agent_id: str = AGENT_ID_LAZARO,
) -> bool:
    """
    Verifica se o slot de manutencao esta disponivel.

    Args:
        data: Data do agendamento (objeto date)
        periodo: 'manha' ou 'tarde'
        agent_id: ID do agente (default: Lazaro)

    Returns:
        True se o slot esta disponivel, False se ja esta ocupado.
    """
    if periodo not in PERIODOS:
        logger.error(f"Periodo invalido: {periodo}. Use 'manha' ou 'tarde'.")
        return False

    try:
        supabase = get_supabase_service()
        config = PERIODOS[periodo]

        # Constroi o timestamp de inicio do periodo na timezone do Lazaro
        # Ex: 2026-02-20 08:00:00-04:00 para manha
        hora_inicio = config["hora_inicio"]
        dt_inicio = datetime(
            data.year, data.month, data.day,
            hora_inicio.hour, hora_inicio.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        hora_fim = config["hora_fim"]
        dt_fim = datetime(
            data.year, data.month, data.day,
            hora_fim.hour, hora_fim.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        # Busca agendamentos de manutencao no slot especifico
        # Slot ocupado = existe registro com:
        #   - mesmo agent_id
        #   - service_name = 'manutencao_preventiva'
        #   - scheduled_at = hora exata do inicio do periodo
        #   - status != 'cancelled' (valores: scheduled, confirmed, completed, no_show)
        response = supabase.client.from_("schedules").select(
            "id, scheduled_at, status"
        ).eq(
            "agent_id", agent_id
        ).eq(
            "service_name", SERVICE_NAME
        ).eq(
            "scheduled_at", dt_inicio.isoformat()
        ).neq(
            "status", "cancelled"
        ).execute()

        count = len(response.data) if response.data else 0

        if count > 0:
            logger.info(
                f"Slot {periodo} do dia {data} OCUPADO "
                f"(agent {agent_id}): {count} agendamento(s)"
            )
            return False

        logger.info(
            f"Slot {periodo} do dia {data} DISPONIVEL (agent {agent_id})"
        )
        return True

    except Exception as e:
        logger.error(
            f"Erro ao verificar slot {periodo} em {data}: {e}",
            exc_info=True
        )
        # Em caso de erro, retorna False (nao confirma slot por seguranca)
        return False


def listar_slots_disponiveis(
    data: date,
    agent_id: str = AGENT_ID_LAZARO,
) -> Dict[str, Any]:
    """
    Lista a disponibilidade dos slots de um dia.

    Args:
        data: Data a consultar (objeto date)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        Dict com:
            - manha: True se disponivel, False se ocupado
            - tarde: True se disponivel, False se ocupado
            - data: Data consultada (YYYY-MM-DD)
            - algum_disponivel: True se ao menos um slot esta livre
    """
    manha_ok = verificar_slot(data, "manha", agent_id)
    tarde_ok = verificar_slot(data, "tarde", agent_id)

    resultado = {
        "data": data.isoformat(),
        "manha": manha_ok,
        "tarde": tarde_ok,
        "algum_disponivel": manha_ok or tarde_ok,
    }

    logger.info(
        f"Slots em {data}: manha={'OK' if manha_ok else 'OCUPADO'}, "
        f"tarde={'OK' if tarde_ok else 'OCUPADO'}"
    )
    return resultado


def registrar_agendamento(
    data: date,
    periodo: str,
    contract_id: str,
    cliente_nome: str,
    telefone: str,
    agent_id: str = AGENT_ID_LAZARO,
) -> Dict[str, Any]:
    """
    Registra um agendamento de manutencao no slot especificado.

    Antes de registrar, verifica novamente se o slot ainda esta disponivel
    (prevencao de race condition).

    Args:
        data: Data do agendamento
        periodo: 'manha' ou 'tarde'
        contract_id: ID do contrato no Supabase
        cliente_nome: Nome do cliente
        telefone: Telefone do cliente (remote_jid)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        Dict com:
            - sucesso: True/False
            - agendamento_id: UUID do agendamento criado (se sucesso)
            - mensagem: Mensagem de status
            - slot_ocupado: True se o slot ja estava ocupado
    """
    if periodo not in PERIODOS:
        return {
            "sucesso": False,
            "agendamento_id": None,
            "mensagem": f"Periodo invalido: '{periodo}'. Use 'manha' ou 'tarde'.",
            "slot_ocupado": False,
        }

    try:
        # Verificacao dupla - evita race condition
        disponivel = verificar_slot(data, periodo, agent_id)
        if not disponivel:
            logger.warning(
                f"Tentativa de agendamento em slot ocupado: "
                f"{data} {periodo} (agent {agent_id})"
            )
            return {
                "sucesso": False,
                "agendamento_id": None,
                "mensagem": (
                    f"O slot de {PERIODOS[periodo]['label']} "
                    f"em {data.strftime('%d/%m/%Y')} ja esta ocupado."
                ),
                "slot_ocupado": True,
            }

        config = PERIODOS[periodo]
        hora_inicio = config["hora_inicio"]
        hora_fim = config["hora_fim"]

        dt_inicio = datetime(
            data.year, data.month, data.day,
            hora_inicio.hour, hora_inicio.minute,
            tzinfo=TIMEZONE_LAZARO
        )
        dt_fim = datetime(
            data.year, data.month, data.day,
            hora_fim.hour, hora_fim.minute,
            tzinfo=TIMEZONE_LAZARO
        )

        supabase = get_supabase_service()

        registro = {
            "agent_id": agent_id,
            "remote_jid": telefone,
            "customer_name": cliente_nome,
            "scheduled_at": dt_inicio.isoformat(),
            "ends_at": dt_fim.isoformat(),
            "service_name": SERVICE_NAME,
            "status": "scheduled",
            "notes": f"contract_id={contract_id} | periodo={periodo}",
        }

        response = supabase.client.from_("schedules").insert(registro).execute()

        if not response.data or len(response.data) == 0:
            logger.error(
                f"Falha ao inserir agendamento no banco: {response}"
            )
            return {
                "sucesso": False,
                "agendamento_id": None,
                "mensagem": "Erro ao registrar agendamento no banco de dados.",
                "slot_ocupado": False,
            }

        agendamento_id = response.data[0]["id"]
        logger.info(
            f"Agendamento registrado: {agendamento_id} | "
            f"{data} {periodo} | {cliente_nome} | contract={contract_id}"
        )

        return {
            "sucesso": True,
            "agendamento_id": agendamento_id,
            "mensagem": (
                f"Manutencao agendada para {data.strftime('%d/%m/%Y')} "
                f"no periodo da {PERIODOS[periodo]['label']}."
            ),
            "slot_ocupado": False,
        }

    except Exception as e:
        logger.error(
            f"Erro ao registrar agendamento {data} {periodo}: {e}",
            exc_info=True
        )
        return {
            "sucesso": False,
            "agendamento_id": None,
            "mensagem": f"Erro interno ao registrar agendamento: {str(e)}",
            "slot_ocupado": False,
        }
