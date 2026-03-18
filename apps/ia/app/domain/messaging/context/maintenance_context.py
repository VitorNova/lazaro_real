"""
Contexto de Manutencao - Funcoes para buscar e formatar dados de manutencao preventiva.

Extraido de mensagens.py (Fase 2.3)
- get_contract_data_for_maintenance: Busca dados do contrato para contexto de manutencao
- build_maintenance_context_prompt: Constroi prompt de contexto com dados do contrato
"""

import logging
from typing import Any, Dict, Optional

from app.core.security.prompt_sanitizer import escape_prompt_value
from app.services.supabase import SupabaseService

logger = logging.getLogger(__name__)


def get_contract_data_for_maintenance(supabase: SupabaseService, contract_id: str) -> Optional[Dict[str, Any]]:
    """
    Busca dados do contrato para contexto de manutencao preventiva.

    Quando o Job D-7 dispara a notificacao, ele salva o contract_id no conversation_history.
    Esta funcao busca os dados completos do contrato para injetar no prompt,
    evitando que a Ana peca dados que ela ja tem.

    Args:
        supabase: Instancia do SupabaseService
        contract_id: UUID do contrato em contract_details

    Returns:
        Dict com dados do contrato ou None se nao encontrar
        {
            "cliente_nome": str,
            "cliente_telefone": str,
            "equipamentos": List[Dict],  # [{marca, btus, patrimonio}, ...]
            "endereco_instalacao": str,
            "proxima_manutencao": str,  # YYYY-MM-DD
        }
    """
    logger.debug(f"[CONTRACT] Buscando dados do contrato {contract_id}")

    if not contract_id:
        logger.debug("[CONTRACT] contract_id vazio")
        return None

    try:
        # Buscar contrato com JOIN em asaas_clientes
        result = supabase.client.table("contract_details").select(
            "id, locatario_nome, locatario_telefone, equipamentos, endereco_instalacao, proxima_manutencao, customer_id"
        ).eq("id", contract_id).maybe_single().execute()

        if not result.data:
            logger.warning(f"[CONTRACT] Contrato {contract_id} nao encontrado")
            return None

        contract = result.data
        logger.debug("[CONTRACT] Contrato encontrado")

        # Dados basicos do contrato
        data = {
            "contract_id": contract.get("id"),
            "cliente_nome": contract.get("locatario_nome") or "Cliente",
            "cliente_telefone": contract.get("locatario_telefone"),
            "equipamentos": contract.get("equipamentos") or [],
            "endereco_instalacao": contract.get("endereco_instalacao"),
            "proxima_manutencao": str(contract.get("proxima_manutencao")) if contract.get("proxima_manutencao") else None,
        }

        # Se nao tem telefone no contrato, buscar em asaas_clientes
        if not data["cliente_telefone"] and contract.get("customer_id"):
            try:
                customer_result = supabase.client.table("asaas_clientes").select(
                    "phone, mobile_phone"
                ).eq("id", contract.get("customer_id")).maybe_single().execute()

                if customer_result.data:
                    data["cliente_telefone"] = (
                        customer_result.data.get("mobile_phone") or
                        customer_result.data.get("phone")
                    )
                    logger.debug("[CONTRACT] Telefone obtido de asaas_clientes")
            except Exception as e:
                logger.warning(f"[CONTRACT] Erro ao buscar telefone em asaas_clientes: {e}")

        logger.info(f"[CONTRACT] Dados carregados para contrato {contract_id}: {data['cliente_nome']}, {len(data['equipamentos'])} equipamento(s)")
        return data

    except Exception as e:
        logger.error(f"[CONTRACT] Erro ao buscar contrato {contract_id}: {e}")
        return None


def build_maintenance_context_prompt(contract_data: Dict[str, Any]) -> str:
    """
    Constroi o prompt de contexto com os dados do contrato.

    Este prompt e injetado ALEM do prompt de manutencao do context_prompts,
    adicionando os dados especificos do contrato do cliente.

    Args:
        contract_data: Dict retornado por get_contract_data_for_maintenance()

    Returns:
        String com o prompt formatado
    """
    # Formatar equipamentos (sanitizar valores do banco)
    equipamentos_str = ""
    for i, equip in enumerate(contract_data.get("equipamentos", []), 1):
        marca = escape_prompt_value(equip.get("marca", "N/I"), "default")
        btus = equip.get("btus", "N/I")  # numérico, não precisa sanitizar
        patrimonio = escape_prompt_value(equip.get("patrimonio", ""), "default")
        patrimonio_str = f" (patrimonio {patrimonio})" if patrimonio and patrimonio != "(não informado)" else ""
        equipamentos_str += f"  {i}. {marca} {btus} BTUs{patrimonio_str}\n"

    if not equipamentos_str:
        equipamentos_str = "  (nao informado)\n"

    # Formatar endereco (sanitizar valor do banco)
    endereco = escape_prompt_value(
        contract_data.get("endereco_instalacao") or "(nao informado no contrato)",
        "endereco"
    )

    # Formatar data da manutencao
    prox_manut = contract_data.get("proxima_manutencao") or "(a definir)"

    # Criar string do equipamento principal para exemplos (sanitizar)
    equip_principal = ""
    if contract_data.get("equipamentos"):
        eq = contract_data["equipamentos"][0]
        marca_sanitizada = escape_prompt_value(eq.get("marca", "seu ar"), "default")
        equip_principal = f"{marca_sanitizada} {eq.get('btus', '')} BTUs".strip()
    else:
        equip_principal = "seu ar-condicionado"

    # Sanitizar nome do cliente
    cliente_nome = escape_prompt_value(contract_data.get("cliente_nome", "Cliente"), "nome")

    prompt = f"""
## DADOS DO CONTRATO (JA CARREGADOS - NAO PERGUNTE)

**Cliente:** {cliente_nome}
**Contract ID:** {contract_data.get("contract_id", "")}
**Equipamento(s):**
{equipamentos_str}
**Endereco de instalacao:** {endereco}
**Proxima manutencao prevista:** {prox_manut}

## INSTRUCOES IMPORTANTES

VOCE JA TEM TODAS AS INFORMACOES DO CONTRATO ACIMA.

### O QUE VOCE DEVE FAZER:

**SEMPRE MENCIONE O EQUIPAMENTO** nas suas respostas!

### O QUE VOCE NAO DEVE FAZER:

**NAO PECA** telefone, CPF, endereco ou dados do cliente - voce ja os tem.
**NAO PECA** marca, modelo ou BTUs do ar-condicionado - voce ja sabe.

### FLUXO PARA MANUTENCAO:

1. Confirme com o cliente qual equipamento esta com problema (se tiver mais de um)
2. Pergunte QUAL O PROBLEMA (pingando, nao gela, barulho, nao liga, etc)
3. Pergunte DIA e PERIODO preferido para a visita tecnica (manha ou tarde)
4. Apos coletar tudo, transfira para o departamento usando `transferir_departamento`

### IMPORTANTE:

- Voce so COLETA as informacoes. O agendamento real sera feito pela equipe.
- Se o cliente perguntar sobre cobrancas ou pagamento, use `consultar_cliente`.
- Sempre mencione o equipamento nas suas respostas.

### EXEMPLO DE RESPOSTA:

"Entendi, o seu {equip_principal} esta pingando. Vou passar para nossa equipe tecnica agendar a visita. Tem preferencia de dia e horario?"

Se o cliente mencionar DEFEITO, PROBLEMA ou CONSERTO (nao manutencao preventiva):
- Transfira para a Nathalia (setor tecnico) usando `transferir_departamento`
"""

    return prompt
