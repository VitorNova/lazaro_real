"""
Maintenance slots availability endpoints.

This module provides:
- GET /api/manutencao/slots: Check slot availability for a specific date
- GET /api/manutencao/slots/semana: Check slot availability for a week
"""

from datetime import date as date_type, timedelta
from typing import Any, Dict

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/manutencao", tags=["manutencao"])


@router.get("/slots")
async def get_slots_manutencao(
    data: str,
    agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
) -> Dict[str, Any]:
    """
    Retorna a disponibilidade de slots de manutencao em uma data.

    Query params:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        agent_id: ID do agente (default: Lazaro)

    Response 200:
        {
            "success": true,
            "data": {
                "data": "2026-02-20",
                "manha": true,
                "tarde": false,
                "algum_disponivel": true
            }
        }

    Response 400:
        { "success": false, "error": "mensagem", "statusCode": 400 }
    """
    from app.services.manutencao_slots import listar_slots_disponiveis

    try:
        data_obj = date_type.fromisoformat(data)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "statusCode": 400,
            }
        )

    slots = listar_slots_disponiveis(data_obj, agent_id)
    return {
        "success": True,
        "data": slots,
    }


@router.get("/slots/semana")
async def get_slots_semana(
    data_inicio: str,
    agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
) -> Dict[str, Any]:
    """
    Retorna a disponibilidade de slots de manutencao para os proximos 7 dias.

    Query params:
        data_inicio: Data inicial no formato YYYY-MM-DD
        agent_id: ID do agente (default: Lazaro)

    Response 200:
        {
            "success": true,
            "data": {
                "dias": [
                    { "data": "2026-02-20", "manha": true, "tarde": false, "algum_disponivel": true },
                    ...
                ]
            }
        }
    """
    from app.services.manutencao_slots import listar_slots_disponiveis

    try:
        data_obj = date_type.fromisoformat(data_inicio)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"Data invalida: '{data_inicio}'. Use o formato YYYY-MM-DD.",
                "statusCode": 400,
            }
        )

    dias = []
    for i in range(7):
        d = data_obj + timedelta(days=i)
        slots = listar_slots_disponiveis(d, agent_id)
        dias.append(slots)

    return {
        "success": True,
        "data": {"dias": dias},
    }
