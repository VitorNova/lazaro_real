"""
File upload endpoints for CRM uploads.

This module provides:
- POST /api/upload: Upload a file
- GET /api/uploads: List all uploaded files
- DELETE /api/upload/{filename}: Delete a file
"""

import os
import uuid
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, File, UploadFile

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["uploads"])

UPLOAD_DIR = "/var/www/phant/crm/uploads"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".txt", ".csv", ".json"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a file to the CRM uploads directory."""
    try:
        if not file.filename:
            return {"success": False, "error": "Nome do arquivo ausente"}

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"success": False, "error": f"Tipo de arquivo nao permitido: {ext}"}

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return {"success": False, "error": "Arquivo muito grande. Max 5MB."}

        # Gerar nome unico para evitar colisoes
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename.replace(' ', '_')}"
        filepath = os.path.join(UPLOAD_DIR, safe_name)

        os.makedirs(UPLOAD_DIR, exist_ok=True)

        with open(filepath, "wb") as f:
            f.write(content)

        logger.debug("[UPLOAD] Arquivo salvo: %s (%s bytes)", safe_name, len(content))
        return {"success": True, "filename": safe_name, "url": f"/uploads/{safe_name}"}

    except Exception as e:
        logger.debug("[UPLOAD] Erro: %s", e)
        return {"success": False, "error": str(e)}


@router.get("/uploads")
async def list_uploads() -> List[Dict[str, str]]:
    """List all uploaded files."""
    try:
        if not os.path.exists(UPLOAD_DIR):
            return []

        files = []
        for filename in sorted(os.listdir(UPLOAD_DIR)):
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(filepath):
                files.append({
                    "filename": filename,
                    "url": f"/uploads/{filename}",
                })
        return files

    except Exception as e:
        logger.debug("[UPLOAD] Erro ao listar: %s", e)
        return []


@router.delete("/upload/{filename}")
async def delete_upload(filename: str) -> Dict[str, Any]:
    """Delete an uploaded file."""
    try:
        filepath = os.path.join(UPLOAD_DIR, filename)

        # Prevenir path traversal
        if not os.path.abspath(filepath).startswith(os.path.abspath(UPLOAD_DIR)):
            return {"success": False, "error": "Caminho invalido"}

        if not os.path.exists(filepath):
            return {"success": False, "error": "Arquivo nao encontrado"}

        os.remove(filepath)
        logger.debug("[UPLOAD] Arquivo removido: %s", filename)
        return {"success": True}

    except Exception as e:
        logger.debug("[UPLOAD] Erro ao remover: %s", e)
        return {"success": False, "error": str(e)}
