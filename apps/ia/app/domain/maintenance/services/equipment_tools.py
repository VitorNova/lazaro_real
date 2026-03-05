"""
Tools de Manutenção - Identificação de Equipamentos (Lázaro/Alugar Ar)

Este módulo implementa:
- identificar_equipamento: Detecta qual equipamento do cliente precisa de manutenção
- analisar_foto_equipamento: Usa Gemini Vision para identificar equipamento na foto
- verificar_disponibilidade_manutencao: Verifica slots disponíveis
- confirmar_agendamento_manutencao: Confirma e registra agendamento

Contexto:
- 82% dos clientes têm apenas 1 equipamento (trivial)
- 9% têm múltiplos de marcas diferentes (pergunta marca)
- 9% têm múltiplos mesma marca (pergunta local ou foto)

Integração:
- Busca dados de contract_details no Supabase
- Usa Gemini Vision para análise de fotos
- Retorna informações estruturadas para a ANA responder

Extraido de: apps/ia/app/tools/manutencao.py (Fase 8.5)
"""

import logging
from typing import Any, Dict, List
from datetime import date, datetime

import google.generativeai as genai

from app.config import settings
from app.services.supabase import get_supabase_service
from .slots_service import (
    listar_slots_disponiveis,
    registrar_agendamento,
    verificar_slot,
)


logger = logging.getLogger(__name__)


# ============================================================================
# TOOL: identificar_equipamento
# ============================================================================

async def identificar_equipamento(
    telefone: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Identifica qual equipamento do cliente precisa de manutenção.

    Lógica de identificação:
    1. Busca contratos do cliente pelo telefone
    2. Se 1 equipamento → retorna direto (82% dos casos)
    3. Se múltiplos com marcas diferentes → retorna lista para perguntar
    4. Se múltiplos mesma marca → retorna lista para perguntar local/BTUs

    Args:
        telefone: Telefone do cliente (formato: 5565999999999)
        agent_id: ID do agente (default: Lázaro)

    Returns:
        dict:
            - cenario: "unico" | "multiplos_marcas" | "multiplos_mesmo"
            - equipamentos: Lista de equipamentos encontrados
            - pergunta_sugerida: Texto sugerido para a ANA perguntar (opcional)
            - total: Quantidade de equipamentos
            - sucesso: True/False
            - mensagem: Mensagem de status
    """
    try:
        logger.info(f"Identificando equipamento para telefone {telefone}")

        supabase = get_supabase_service()

        # Limpar telefone (apenas números)
        telefone_clean = telefone.replace("+", "").replace("-", "").replace(" ", "")

        # Buscar contratos do cliente via join com asaas_clientes
        response = supabase.client.from_('contract_details').select(
            """
            id,
            customer_id,
            equipamentos,
            endereco_instalacao,
            asaas_clientes!customer_id(mobile_phone)
            """
        ).eq('agent_id', agent_id).execute()

        if not response.data:
            logger.warning(f"Nenhum contrato encontrado para agent {agent_id}")
            return {
                "cenario": "sem_equipamento",
                "equipamentos": [],
                "total": 0,
                "sucesso": False,
                "mensagem": "Não encontrei equipamentos cadastrados para este telefone."
            }

        # Filtrar contratos por telefone
        contratos_cliente = []
        for contrato in response.data:
            # Verificar se o contrato tem cliente associado
            if contrato.get("asaas_clientes") and len(contrato["asaas_clientes"]) > 0:
                cliente_phone = contrato["asaas_clientes"][0].get("mobile_phone", "")
                cliente_phone_clean = cliente_phone.replace("+", "").replace("-", "").replace(" ", "")

                if cliente_phone_clean == telefone_clean:
                    contratos_cliente.append(contrato)

        if not contratos_cliente:
            logger.info(f"Nenhum contrato encontrado para telefone {telefone}")
            return {
                "cenario": "sem_equipamento",
                "equipamentos": [],
                "total": 0,
                "sucesso": False,
                "mensagem": "Não encontrei equipamentos cadastrados para este telefone."
            }

        # Consolidar equipamentos de todos os contratos
        todos_equipamentos = []
        for contrato in contratos_cliente:
            equipamentos = contrato.get("equipamentos", [])
            endereco = contrato.get("endereco_instalacao", "")

            if isinstance(equipamentos, list):
                for equip in equipamentos:
                    if isinstance(equip, dict):
                        equip_info = {
                            "marca": equip.get("marca", "Não informado"),
                            "btus": equip.get("btus", 0),
                            "tipo": equip.get("tipo", "Split"),
                            "local": equip.get("local", endereco),
                            "contract_id": contrato["id"]
                        }
                        todos_equipamentos.append(equip_info)

        total = len(todos_equipamentos)

        # ===================================================================
        # CENÁRIO 1: Apenas 1 equipamento (82% dos casos)
        # ===================================================================
        if total == 1:
            equip = todos_equipamentos[0]
            logger.info(f"Cenário ÚNICO: {equip['marca']} {equip['btus']} BTUs")

            return {
                "cenario": "unico",
                "equipamentos": todos_equipamentos,
                "total": 1,
                "sucesso": True,
                "mensagem": f"Encontrei 1 equipamento: {equip['marca']} {equip['btus']} BTUs ({equip['tipo']}). É esse?",
                "equipamento_confirmado": equip
            }

        # ===================================================================
        # CENÁRIO 2: Múltiplos equipamentos
        # ===================================================================
        if total > 1:
            # Agrupar por marca
            marcas = set(e["marca"] for e in todos_equipamentos)

            # Se marcas DIFERENTES → perguntar marca
            if len(marcas) > 1:
                marcas_lista = ", ".join(sorted(marcas))
                logger.info(f"Cenário MÚLTIPLOS MARCAS: {marcas_lista}")

                return {
                    "cenario": "multiplos_marcas",
                    "equipamentos": todos_equipamentos,
                    "total": total,
                    "sucesso": True,
                    "mensagem": f"Vi que você tem {total} equipamentos de marcas diferentes. Qual deles está com problema?",
                    "pergunta_sugerida": f"É o {marcas_lista}?"
                }

            # Se MESMA marca → perguntar local ou BTUs
            logger.info(f"Cenário MÚLTIPLOS MESMA MARCA: {total} equipamentos")

            # Construir lista de opções
            opcoes = []
            for i, equip in enumerate(todos_equipamentos, 1):
                local = equip.get("local", "")
                btus = equip.get("btus", 0)

                if local:
                    opcoes.append(f"{i}. {equip['marca']} {btus} BTUs ({local})")
                else:
                    opcoes.append(f"{i}. {equip['marca']} {btus} BTUs")

            lista_opcoes = "\n".join(opcoes)

            return {
                "cenario": "multiplos_mesmo",
                "equipamentos": todos_equipamentos,
                "total": total,
                "sucesso": True,
                "mensagem": f"Vi que você tem {total} equipamentos {todos_equipamentos[0]['marca']}. Qual deles?",
                "pergunta_sugerida": f"Opções:\n{lista_opcoes}\n\nPode me dizer qual?"
            }

        # ===================================================================
        # FALLBACK: Nenhum equipamento
        # ===================================================================
        logger.warning(f"Nenhum equipamento encontrado para {telefone}")
        return {
            "cenario": "sem_equipamento",
            "equipamentos": [],
            "total": 0,
            "sucesso": False,
            "mensagem": "Não encontrei equipamentos cadastrados. Pode me informar a marca e o modelo?"
        }

    except Exception as e:
        logger.error(f"Erro ao identificar equipamento: {e}", exc_info=True)
        return {
            "cenario": "erro",
            "equipamentos": [],
            "total": 0,
            "sucesso": False,
            "mensagem": f"Erro ao buscar equipamentos: {str(e)}"
        }


# ============================================================================
# TOOL: analisar_foto_equipamento
# ============================================================================

async def analisar_foto_equipamento(
    foto_url: str,
    equipamentos_cliente: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Usa Gemini Vision para identificar equipamento na foto.

    O Gemini Vision analisa a foto do ar-condicionado e tenta identificar:
    - Marca (procura logo na frente do aparelho)
    - Tipo (Split, Janela, Portátil)

    Depois, compara com os equipamentos cadastrados do cliente para
    confirmar qual é o equipamento da foto.

    Args:
        foto_url: URL da imagem do equipamento (base64 data URL ou HTTP URL)
        equipamentos_cliente: Lista de equipamentos do cliente (do identificar_equipamento)

    Returns:
        dict:
            - marca_identificada: Marca detectada na foto
            - tipo: Tipo de equipamento (Split, Janela, etc)
            - confianca: Nível de confiança (0.0 a 1.0)
            - equipamento_id: ID do equipamento correspondente (ou None)
            - sucesso: True/False
            - mensagem: Explicação da análise
    """
    try:
        logger.info(f"Analisando foto de equipamento (URL: {foto_url[:50]}...)")

        # Validar entrada
        if not equipamentos_cliente or len(equipamentos_cliente) == 0:
            return {
                "marca_identificada": None,
                "tipo": None,
                "confianca": 0.0,
                "equipamento_id": None,
                "sucesso": False,
                "mensagem": "Nenhum equipamento cadastrado para comparação."
            }

        # Configurar Gemini Vision
        genai.configure(api_key=settings.google_api_key)

        # Criar prompt estruturado
        equipamentos_texto = "\n".join([
            f"- {e['marca']} {e['btus']} BTUs ({e['tipo']}) - Local: {e.get('local', 'não informado')}"
            for e in equipamentos_cliente
        ])

        prompt = f"""Analise esta foto de ar-condicionado e identifique:

1. **MARCA**: Procure o logo ou nome do fabricante na frente do aparelho (exemplos: LG, Samsung, Midea, Britânia, Agratto, Gree, Elgin, Springer, Consul, etc.)

2. **TIPO**: Identifique o tipo do aparelho:
   - Split (composto por evaporadora interna + condensadora externa)
   - Janela (aparelho único instalado na janela)
   - Portátil (aparelho móvel com mangueira)

**Equipamentos cadastrados do cliente:**
{equipamentos_texto}

**Sua tarefa:**
Identifique a marca e o tipo do aparelho na foto e indique qual dos equipamentos cadastrados corresponde à foto.

Responda em formato JSON:
{{
  "marca": "nome da marca",
  "tipo": "Split/Janela/Portátil",
  "confianca": 0.95,
  "equipamento_correspondente": "marca btus tipo"
}}

Se não conseguir identificar, retorne confianca < 0.5 e explique o motivo.
"""

        # Processar a foto
        # Se for data URL (base64), extrair apenas a parte base64
        if foto_url.startswith("data:"):
            # Formato: data:image/jpeg;base64,/9j/4AAQ...
            try:
                mime_part, base64_part = foto_url.split(";base64,")
                mime_type = mime_part.replace("data:", "")
            except ValueError:
                return {
                    "marca_identificada": None,
                    "tipo": None,
                    "confianca": 0.0,
                    "equipamento_id": None,
                    "sucesso": False,
                    "mensagem": "Formato de imagem inválido (esperado data URL base64)"
                }

            # Upload da imagem para o Gemini
            import base64
            import tempfile
            import os

            # Decodificar base64
            image_data = base64.b64decode(base64_part)

            # Criar arquivo temporário
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                tmp_file.write(image_data)
                tmp_path = tmp_file.name

            try:
                # Upload para Gemini Files API
                uploaded_file = genai.upload_file(tmp_path)
                logger.info(f"Imagem enviada para Gemini: {uploaded_file.uri}")

                # Criar modelo com vision
                model = genai.GenerativeModel('gemini-2.0-flash')

                # Enviar prompt com imagem
                response = model.generate_content([prompt, uploaded_file])

                # Extrair resposta
                result_text = response.text.strip()
                logger.debug(f"Resposta do Gemini Vision: {result_text}")

                # Tentar parsear JSON da resposta
                import json
                import re

                # Remover markdown code blocks se houver
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_text, re.DOTALL)
                if json_match:
                    result_text = json_match.group(1)

                # Parsear JSON
                analysis = json.loads(result_text)

                marca = analysis.get("marca", "")
                tipo = analysis.get("tipo", "")
                confianca = float(analysis.get("confianca", 0.0))
                equipamento_match = analysis.get("equipamento_correspondente", "")

                # Buscar equipamento correspondente
                equipamento_id = None
                for equip in equipamentos_cliente:
                    equip_str = f"{equip['marca']} {equip['btus']} {equip['tipo']}".lower()
                    if equipamento_match.lower() in equip_str or equip['marca'].lower() in marca.lower():
                        equipamento_id = equip.get("contract_id")
                        logger.info(f"Equipamento correspondente encontrado: {equip['marca']} {equip['btus']} BTUs")
                        break

                return {
                    "marca_identificada": marca,
                    "tipo": tipo,
                    "confianca": confianca,
                    "equipamento_id": equipamento_id,
                    "sucesso": confianca >= 0.5,
                    "mensagem": f"Identifiquei um {tipo} da marca {marca} (confiança: {int(confianca * 100)}%).",
                    "analise_completa": analysis
                }

            finally:
                # Limpar arquivo temporário
                os.unlink(tmp_path)

        else:
            # URL HTTP/HTTPS - baixar e processar
            logger.warning("URL HTTP não implementado ainda - usando fallback")
            return {
                "marca_identificada": None,
                "tipo": None,
                "confianca": 0.0,
                "equipamento_id": None,
                "sucesso": False,
                "mensagem": "Envie a imagem diretamente pelo WhatsApp para análise."
            }

    except Exception as e:
        if "json" in str(type(e).__name__).lower():
            logger.error(f"Erro ao parsear resposta JSON do Gemini: {e}")
            return {
                "marca_identificada": None,
                "tipo": None,
                "confianca": 0.0,
                "equipamento_id": None,
                "sucesso": False,
                "mensagem": "Erro ao processar análise da imagem. Tente enviar outra foto mais clara."
            }

        logger.error(f"Erro ao analisar foto: {e}", exc_info=True)
        return {
            "marca_identificada": None,
            "tipo": None,
            "confianca": 0.0,
            "equipamento_id": None,
            "sucesso": False,
            "mensagem": f"Erro ao analisar foto: {str(e)}"
        }


# ============================================================================
# TOOL: verificar_disponibilidade_manutencao
# ============================================================================

async def verificar_disponibilidade_manutencao(
    data: str,
    periodo: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Verifica se existe slot disponivel para manutencao em uma data e periodo.

    Args:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        periodo: 'manha' ou 'tarde'
        agent_id: ID do agente (default: Lazaro)

    Returns:
        dict:
            - disponivel: True se o slot esta livre, False se ocupado
            - data: Data consultada (YYYY-MM-DD)
            - periodo: Periodo consultado
            - label_periodo: Descricao amigavel do periodo
            - mensagem: Mensagem descritiva
            - alternativas: Quais outros slots estao disponiveis no mesmo dia
    """
    try:
        logger.info(f"Verificando disponibilidade: {data} {periodo}")

        # Validar periodo
        if periodo not in ("manha", "tarde"):
            return {
                "disponivel": False,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": "Periodo invalido. Use 'manha' (08h-12h) ou 'tarde' (14h-18h).",
                "alternativas": [],
            }

        # Converter string para date
        try:
            data_obj = date.fromisoformat(data)
        except ValueError:
            return {
                "disponivel": False,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "alternativas": [],
            }

        # Verificar slot solicitado
        disponivel = verificar_slot(data_obj, periodo, agent_id)

        # Verificar alternativas no mesmo dia
        todos_slots = listar_slots_disponiveis(data_obj, agent_id)
        alternativas = []
        for p in ("manha", "tarde"):
            if p != periodo and todos_slots.get(p):
                label = "Manhã (08h-12h)" if p == "manha" else "Tarde (14h-18h)"
                alternativas.append({"periodo": p, "label": label})

        labels = {"manha": "Manhã (08h-12h)", "tarde": "Tarde (14h-18h)"}
        label_periodo = labels.get(periodo, periodo)
        data_br = data_obj.strftime("%d/%m/%Y")

        if disponivel:
            mensagem = (
                f"Otimo! O periodo da {label_periodo} em {data_br} "
                f"esta disponivel para manutencao."
            )
        else:
            if alternativas:
                alts_str = " ou ".join(a["label"] for a in alternativas)
                mensagem = (
                    f"O periodo da {label_periodo} em {data_br} ja esta ocupado. "
                    f"Mas ainda temos disponibilidade: {alts_str}."
                )
            else:
                mensagem = (
                    f"O dia {data_br} esta totalmente ocupado. "
                    f"Por favor, escolha outra data."
                )

        return {
            "disponivel": disponivel,
            "data": data,
            "periodo": periodo,
            "label_periodo": label_periodo,
            "mensagem": mensagem,
            "alternativas": alternativas,
        }

    except Exception as e:
        logger.error(f"Erro ao verificar disponibilidade: {e}", exc_info=True)
        return {
            "disponivel": False,
            "data": data,
            "periodo": periodo,
            "label_periodo": periodo,
            "mensagem": f"Erro ao verificar disponibilidade: {str(e)}",
            "alternativas": [],
        }


# ============================================================================
# TOOL: confirmar_agendamento_manutencao
# ============================================================================

async def confirmar_agendamento_manutencao(
    data: str,
    periodo: str,
    contract_id: str,
    cliente_nome: str,
    telefone: str,
    agent_id: str = '14e6e5ce-4627-4e38-aac8-f0191669ff53'
) -> Dict[str, Any]:
    """
    Confirma e registra o agendamento de manutencao no slot solicitado.

    Deve ser chamada APOS verificar_disponibilidade_manutencao retornar
    disponivel=True e o cliente confirmar o horario.

    Args:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        periodo: 'manha' ou 'tarde'
        contract_id: ID do contrato no Supabase
        cliente_nome: Nome do cliente
        telefone: Telefone do cliente (ex: 5565999999999)
        agent_id: ID do agente (default: Lazaro)

    Returns:
        dict:
            - sucesso: True se agendado, False se falhou
            - agendamento_id: UUID do registro criado (se sucesso)
            - data: Data agendada (YYYY-MM-DD)
            - periodo: Periodo agendado
            - label_periodo: Descricao amigavel
            - mensagem: Mensagem de confirmacao ou erro
            - slot_ocupado: True se o slot ja estava ocupado no momento do registro
    """
    try:
        logger.info(
            f"Confirmando agendamento: {data} {periodo} | "
            f"cliente={cliente_nome} | contract={contract_id}"
        )

        # Validar periodo
        if periodo not in ("manha", "tarde"):
            return {
                "sucesso": False,
                "agendamento_id": None,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": "Periodo invalido. Use 'manha' ou 'tarde'.",
                "slot_ocupado": False,
            }

        # Converter string para date
        try:
            data_obj = date.fromisoformat(data)
        except ValueError:
            return {
                "sucesso": False,
                "agendamento_id": None,
                "data": data,
                "periodo": periodo,
                "label_periodo": periodo,
                "mensagem": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "slot_ocupado": False,
            }

        # Registrar agendamento (inclui verificacao dupla interna)
        resultado = registrar_agendamento(
            data=data_obj,
            periodo=periodo,
            contract_id=contract_id,
            cliente_nome=cliente_nome,
            telefone=telefone,
            agent_id=agent_id,
        )

        # Atualizar contract_details com status 'scheduled' se agendamento foi bem-sucedido
        if resultado.get("sucesso") and contract_id:
            try:
                supabase = get_supabase_service()
                supabase.client.table("contract_details").update({
                    "maintenance_status": "scheduled",
                    "agendamento_confirmado_at": datetime.utcnow().isoformat(),
                }).eq("id", contract_id).execute()
                logger.info(f"[MANUT] Contract {contract_id} atualizado para 'scheduled'")
            except Exception as e:
                logger.error(f"[MANUT] Erro ao atualizar contract_details: {e}")

        labels = {"manha": "Manhã (08h-12h)", "tarde": "Tarde (14h-18h)"}
        label_periodo = labels.get(periodo, periodo)

        return {
            "sucesso": resultado["sucesso"],
            "agendamento_id": resultado.get("agendamento_id"),
            "data": data,
            "periodo": periodo,
            "label_periodo": label_periodo,
            "mensagem": resultado["mensagem"],
            "slot_ocupado": resultado.get("slot_ocupado", False),
        }

    except Exception as e:
        logger.error(f"Erro ao confirmar agendamento: {e}", exc_info=True)
        return {
            "sucesso": False,
            "agendamento_id": None,
            "data": data,
            "periodo": periodo,
            "label_periodo": periodo,
            "mensagem": f"Erro interno ao confirmar agendamento: {str(e)}",
            "slot_ocupado": False,
        }


# ============================================================================
# FUNCTION DECLARATIONS - Formato Gemini
# ============================================================================

MAINTENANCE_FUNCTION_DECLARATIONS = [
    {
        "name": "identificar_equipamento",
        "description": "Identifica qual equipamento de ar-condicionado do cliente precisa de manutenção. Use quando o cliente reportar problema ou solicitar agendamento de manutenção.",
        "parameters": {
            "type": "object",
            "properties": {
                "telefone": {
                    "type": "string",
                    "description": "Telefone do cliente (formato: 5565999999999)"
                }
            },
            "required": ["telefone"]
        }
    },
    {
        "name": "analisar_foto_equipamento",
        "description": "Analisa foto enviada pelo cliente para identificar marca e tipo do equipamento. Use quando o cliente enviar imagem do ar-condicionado e houver múltiplos equipamentos cadastrados.",
        "parameters": {
            "type": "object",
            "properties": {
                "foto_url": {
                    "type": "string",
                    "description": "URL ou base64 data URL da foto do equipamento"
                },
                "equipamentos_cliente": {
                    "type": "array",
                    "description": "Lista de equipamentos do cliente (resultado de identificar_equipamento)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "marca": {
                                "type": "string",
                                "description": "Marca do equipamento (ex: LG, Samsung, Midea)"
                            },
                            "btus": {
                                "type": "integer",
                                "description": "Capacidade em BTUs (ex: 9000, 12000, 18000)"
                            },
                            "tipo": {
                                "type": "string",
                                "description": "Tipo do equipamento (Split, Janela, Portátil)"
                            },
                            "local": {
                                "type": "string",
                                "description": "Local de instalação (ex: Sala, Quarto)"
                            },
                            "contract_id": {
                                "type": "string",
                                "description": "ID do contrato associado"
                            }
                        },
                        "required": ["marca", "btus", "tipo"]
                    }
                }
            },
            "required": ["foto_url", "equipamentos_cliente"]
        }
    },
    {
        "name": "verificar_disponibilidade_manutencao",
        "description": (
            "Verifica se existe slot disponivel para agendamento de manutencao preventiva "
            "em uma data e periodo especificos. "
            "SEMPRE use esta tool antes de confirmar um agendamento. "
            "Se o slot estiver ocupado, informe o cliente e sugira as alternativas retornadas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Data desejada no formato YYYY-MM-DD (ex: 2026-02-20)"
                },
                "periodo": {
                    "type": "string",
                    "enum": ["manha", "tarde"],
                    "description": (
                        "Periodo desejado: 'manha' (08h-12h) ou 'tarde' (14h-18h). "
                        "Interprete 'de manha', 'antes do meio dia', 'cedo' como 'manha'. "
                        "Interprete 'de tarde', 'depois do almoco', 'a tarde' como 'tarde'."
                    )
                }
            },
            "required": ["data", "periodo"]
        }
    },
    {
        "name": "confirmar_agendamento_manutencao",
        "description": (
            "Confirma e registra o agendamento de manutencao preventiva. "
            "Use SOMENTE apos verificar_disponibilidade_manutencao retornar disponivel=True "
            "e o cliente confirmar o dia e periodo. "
            "Apos confirmar com sucesso, informe o cliente e transfira para o departamento."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Data do agendamento no formato YYYY-MM-DD (ex: 2026-02-20)"
                },
                "periodo": {
                    "type": "string",
                    "enum": ["manha", "tarde"],
                    "description": "Periodo: 'manha' (08h-12h) ou 'tarde' (14h-18h)"
                },
                "contract_id": {
                    "type": "string",
                    "description": "ID do contrato do cliente no Supabase (UUID)"
                },
                "cliente_nome": {
                    "type": "string",
                    "description": "Nome completo do cliente"
                },
                "telefone": {
                    "type": "string",
                    "description": "Telefone do cliente no formato WhatsApp (ex: 5565999999999)"
                }
            },
            "required": ["data", "periodo", "contract_id", "cliente_nome", "telefone"]
        }
    }
]
