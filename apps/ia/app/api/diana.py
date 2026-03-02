"""
Diana v2 - API REST para campanhas de prospecao.

Endpoints:
- POST /api/diana/campaigns - Criar campanha + importar CSV + disparar
- GET /api/diana/campaigns/{agent_id} - Listar campanhas do agente
- GET /api/diana/campaigns/{agent_id}/{campaign_id}/stats - Estatisticas
- GET /api/diana/campaigns/{agent_id}/{campaign_id}/prospects - Listar prospects
- POST /api/diana/campaigns/{agent_id}/{campaign_id}/pause - Pausar
- POST /api/diana/campaigns/{agent_id}/{campaign_id}/resume - Retomar
"""

import logging
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from pydantic import BaseModel

from app.services.diana import (
    DianaCampaignService,
    get_diana_campaign_service,
)

logger = logging.getLogger("diana.api")

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateCampaignResponse(BaseModel):
    """Resposta da criacao de campanha."""

    success: bool
    campaign_id: Optional[str] = None
    total: int = 0
    queued: int = 0
    errors: int = 0
    invalid_phones: list = []
    uazapi_folder_id: Optional[str] = None
    error: Optional[str] = None


class CampaignStatsResponse(BaseModel):
    """Estatisticas de campanha."""

    total_campanhas: int = 0
    total_prospects: int = 0
    total_enviados: int = 0
    total_respondidos: int = 0
    total_interessados: int = 0
    campanhas: Optional[list] = None


class ActionResponse(BaseModel):
    """Resposta de acao (pause/resume)."""

    success: bool
    error: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/campaigns", response_model=CreateCampaignResponse)
async def create_campaign(
    file: UploadFile = File(..., description="Arquivo CSV com lista de contatos"),
    agent_id: str = Form(..., description="ID do agente"),
    campaign_name: str = Form(..., description="Nome da campanha"),
    system_prompt: str = Form(..., description="System prompt para a IA"),
    mensagem_template: str = Form(..., description="Template da mensagem inicial"),
    uazapi_base_url: str = Form(..., description="URL da UAZAPI"),
    uazapi_token: str = Form(..., description="Token da UAZAPI"),
    delay_min: int = Form(30, description="Delay minimo entre mensagens (segundos)"),
    delay_max: int = Form(60, description="Delay maximo entre mensagens (segundos)"),
    auto_dispatch: bool = Form(True, description="Disparar imediatamente"),
):
    """
    Cria uma nova campanha de prospecao.

    Fluxo:
    1. Faz upload do CSV
    2. Parseia e valida contatos
    3. Cria campanha e prospects no banco
    4. Se auto_dispatch=True, dispara via UAZAPI

    O arquivo CSV deve ter pelo menos uma coluna de telefone.
    Colunas reconhecidas automaticamente:
    - nome, name, Nome
    - telefone, phone, celular, whatsapp
    - empresa, company
    - email, e-mail
    - cargo, position

    O mensagem_template pode ter variaveis:
    "Oi {nome}! Vi que a {empresa} atua em {segmento}..."

    As variaveis sao substituidas pelos dados do CSV de cada prospect.
    """
    logger.info(f"Criando campanha: {campaign_name} para agente {agent_id}")

    # Valida arquivo
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Arquivo deve ser um CSV",
        )

    # Le conteudo do CSV
    try:
        content = await file.read()
        # Tenta decodificar como UTF-8, se falhar tenta latin-1
        try:
            csv_content = content.decode("utf-8")
        except UnicodeDecodeError:
            csv_content = content.decode("latin-1")
    except Exception as e:
        logger.error(f"Erro ao ler arquivo: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao ler arquivo: {e}",
        )

    # Cria campanha
    service = get_diana_campaign_service()

    result = await service.create_campaign_from_csv(
        agent_id=agent_id,
        csv_content=csv_content,
        campaign_name=campaign_name,
        system_prompt=system_prompt,
        mensagem_template=mensagem_template,
        uazapi_base_url=uazapi_base_url,
        uazapi_token=uazapi_token,
        delay_min=delay_min,
        delay_max=delay_max,
        auto_dispatch=auto_dispatch,
    )

    return CreateCampaignResponse(**result)


@router.get("/campaigns/{agent_id}")
async def list_campaigns(agent_id: str):
    """Lista todas as campanhas de um agente."""
    service = get_diana_campaign_service()
    campaigns = service.list_campaigns(agent_id)
    return {"campaigns": campaigns}


@router.get("/campaigns/{agent_id}/{campaign_id}/stats", response_model=CampaignStatsResponse)
async def get_campaign_stats(agent_id: str, campaign_id: str):
    """Retorna estatisticas de uma campanha."""
    service = get_diana_campaign_service()
    stats = service.get_campaign_stats(agent_id, campaign_id)
    return CampaignStatsResponse(**stats)


@router.get("/campaigns/{agent_id}/{campaign_id}/prospects")
async def list_prospects(
    agent_id: str,
    campaign_id: str,
    status: Optional[str] = Query(None, description="Filtrar por status"),
    limit: int = Query(100, ge=1, le=1000, description="Limite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginacao"),
):
    """Lista prospects de uma campanha com filtros opcionais."""
    service = get_diana_campaign_service()
    prospects = service.list_prospects(
        agent_id=agent_id,
        campaign_id=campaign_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"prospects": prospects, "count": len(prospects)}


@router.post("/campaigns/{agent_id}/{campaign_id}/pause", response_model=ActionResponse)
async def pause_campaign(
    agent_id: str,
    campaign_id: str,
    uazapi_base_url: str = Form(...),
    uazapi_token: str = Form(...),
):
    """Pausa uma campanha em andamento."""
    service = get_diana_campaign_service()
    result = await service.pause_campaign(
        agent_id=agent_id,
        campaign_id=campaign_id,
        uazapi_base_url=uazapi_base_url,
        uazapi_token=uazapi_token,
    )
    return ActionResponse(**result)


@router.post("/campaigns/{agent_id}/{campaign_id}/resume", response_model=ActionResponse)
async def resume_campaign(
    agent_id: str,
    campaign_id: str,
    uazapi_base_url: str = Form(...),
    uazapi_token: str = Form(...),
):
    """Retoma uma campanha pausada."""
    service = get_diana_campaign_service()
    result = await service.resume_campaign(
        agent_id=agent_id,
        campaign_id=campaign_id,
        uazapi_base_url=uazapi_base_url,
        uazapi_token=uazapi_token,
    )
    return ActionResponse(**result)


# ============================================================================
# Endpoint de teste
# ============================================================================


@router.get("/health")
async def health():
    """Health check do modulo Diana."""
    return {"status": "ok", "module": "diana"}
