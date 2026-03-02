"""
Sync Billing Job - Sincroniza billing_notifications -> ia_cobrancas_enviadas.

Preenche retroativamente os dados que faltam nas cobrancas ja enviadas:
- customer_name (nome do cliente, via asaas_cobrancas cache)
- message_text (reconstruido a partir do template + dados)
- payment_link (invoice_url ou bank_slip_url do cache)
- due_date, billing_type, subscription_id, valor

Pode ser executado:
- Manualmente: python -m app.jobs.sync_billing
- Via API: POST /api/jobs/sync-billing
- Via cron: todo dia as 4h
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)


# ============================================================================
# TEMPLATES (mesmo do billing_charge.py)
# ============================================================================

DEFAULT_MESSAGES = {
    "reminder": (
        "Ola {nome}! Lembrete: sua fatura de {valor} vence em {vencimento}. "
        "Evite juros pagando em dia."
    ),
    "dueDate": (
        "Ola {nome}! Hoje e o dia do vencimento da sua fatura de {valor}. "
        "Efetue o pagamento para evitar juros."
    ),
    "overdue": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento} e esta "
        "ha {dias_atraso} dias em atraso. Regularize sua situacao."
    ),
    "overdue1": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento}. "
        "Evite juros, regularize: {link}"
    ),
    "overdue2": (
        "Ola {nome}! Sua fatura de {valor} esta ha {dias_atraso} dias em atraso. "
        "Regularize agora: {link}"
    ),
    "overdue3": (
        "Ola {nome}! URGENTE: Sua fatura de {valor} esta ha {dias_atraso} dias vencida. "
        "Ultimo aviso antes de medidas adicionais: {link}"
    ),
}


# ============================================================================
# HELPERS
# ============================================================================

def _log(msg: str) -> None:
    logger.info(f"[SYNC_BILLING] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[SYNC_BILLING] {msg}")


def format_brl(value: float) -> str:
    """Formata valor em Real brasileiro (R$ 1.234,56)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date_br(date_str: str) -> str:
    """Converte YYYY-MM-DD para DD/MM/YYYY."""
    if not date_str:
        return ""
    parts = date_str.split("T")[0].split("-")
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return date_str


def reconstruct_message(
    notification_type: str,
    days_from_due: int,
    customer_name: str,
    value: float,
    due_date: str,
    payment_link: Optional[str] = None,
) -> str:
    """
    Reconstroi o texto da mensagem a partir dos dados e templates.
    Usa a mesma logica do billing_charge.py.
    """
    # Selecionar template baseado no tipo e dias
    if notification_type == "reminder":
        template = DEFAULT_MESSAGES["reminder"]
    elif notification_type == "due_date":
        template = DEFAULT_MESSAGES["dueDate"]
    elif notification_type == "overdue":
        days_overdue = abs(days_from_due)
        if days_overdue <= 5:
            template = DEFAULT_MESSAGES["overdue1"]
        elif days_overdue <= 10:
            template = DEFAULT_MESSAGES["overdue2"]
        else:
            template = DEFAULT_MESSAGES["overdue3"]
    else:
        template = DEFAULT_MESSAGES["overdue"]

    # Formatar valores
    formatted_value = format_brl(value) if value else "R$ 0,00"
    formatted_date = format_date_br(due_date) if due_date else ""
    days_overdue = abs(days_from_due)

    # Substituir variaveis
    message = template
    message = re.sub(r"\{\{?nome\}\}?", customer_name or "Cliente", message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?valor\}\}?", formatted_value, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?vencimento\}\}?", formatted_date, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?dias_atraso\}\}?", str(days_overdue), message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?dias\}\}?", str(abs(days_from_due)), message, flags=re.IGNORECASE)

    if payment_link:
        message = re.sub(r"\{\{?link\}\}?", payment_link, message, flags=re.IGNORECASE)
    else:
        message = re.sub(r"\s*\{\{?link\}\}?", "", message, flags=re.IGNORECASE)

    return message


# ============================================================================
# MAIN SYNC LOGIC
# ============================================================================

def sync_billing_notifications(
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sincroniza billing_notifications -> ia_cobrancas_enviadas.

    Para cada notificacao enviada (status=sent) que ainda nao tem registro
    correspondente em ia_cobrancas_enviadas, cria um registro completo
    enriquecido com dados do cache asaas_cobrancas.

    Returns:
        Dict com estatisticas: synced, skipped, errors
    """
    # Conectar ao Supabase
    if not supabase_url or not supabase_key:
        try:
            from app.config import settings
            supabase_url = settings.supabase_url
            supabase_key = settings.supabase_service_key
        except Exception:
            supabase_url = os.environ.get("SUPABASE_URL")
            supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        _log_error("SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorios")
        return {"status": "error", "message": "Missing Supabase credentials"}

    sb: Client = create_client(supabase_url, supabase_key)

    stats = {"synced": 0, "skipped": 0, "errors": 0, "total_notifications": 0}

    _log("Iniciando sincronizacao billing_notifications -> ia_cobrancas_enviadas")

    # 1. Buscar todas as billing_notifications enviadas
    response = (
        sb.table("billing_notifications")
        .select("*")
        .eq("status", "sent")
        .order("created_at", desc=False)
        .execute()
    )
    notifications = response.data or []
    stats["total_notifications"] = len(notifications)
    _log(f"Encontradas {len(notifications)} notificacoes enviadas")

    if not notifications:
        _log("Nenhuma notificacao para sincronizar")
        return {"status": "completed", "stats": stats}

    # 2. Buscar payment_ids ja registrados em ia_cobrancas_enviadas
    existing_response = (
        sb.table("ia_cobrancas_enviadas")
        .select("payment_id, notification_type, enviado_em")
        .execute()
    )
    existing_records = existing_response.data or []

    # Criar set de (payment_id, notification_type) ja existentes
    existing_keys = set()
    for rec in existing_records:
        key = f"{rec['payment_id']}|{rec.get('notification_type', '')}"
        existing_keys.add(key)

    _log(f"Ja existem {len(existing_keys)} registros em ia_cobrancas_enviadas")

    # 3. Buscar cache de cobrancas (asaas_cobrancas) para enriquecimento
    cobrancas_response = (
        sb.table("asaas_cobrancas")
        .select("id, customer_id, customer_name, value, due_date, billing_type, "
                "invoice_url, bank_slip_url, subscription_id, status")
        .execute()
    )
    cobrancas = cobrancas_response.data or []

    # Mapear payment_id -> dados da cobranca
    cobranca_map: Dict[str, Dict[str, Any]] = {}
    for c in cobrancas:
        cobranca_map[c["id"]] = c

    _log(f"Cache de cobrancas: {len(cobranca_map)} registros")

    # 4. Processar cada notificacao
    batch_records: List[Dict[str, Any]] = []

    for notif in notifications:
        payment_id = notif["payment_id"]
        notification_type = notif["notification_type"]
        notif_key = f"{payment_id}|{notification_type}"

        # Pular se ja existe
        if notif_key in existing_keys:
            stats["skipped"] += 1
            continue

        # Buscar dados de enriquecimento do cache
        cobranca = cobranca_map.get(payment_id, {})
        customer_name = cobranca.get("customer_name", "")
        value = cobranca.get("value", 0)
        due_date = cobranca.get("due_date", "")
        billing_type = cobranca.get("billing_type", "")
        subscription_id = cobranca.get("subscription_id")
        payment_link = cobranca.get("invoice_url") or cobranca.get("bank_slip_url")

        # Reconstruir mensagem
        days_from_due = notif.get("days_from_due", 0)
        message_text = reconstruct_message(
            notification_type=notification_type,
            days_from_due=days_from_due,
            customer_name=customer_name,
            value=value,
            due_date=due_date,
            payment_link=payment_link,
        )

        # Montar registro
        record = {
            "agent_id": notif["agent_id"],
            "payment_id": payment_id,
            "customer_id": notif.get("customer_id") or cobranca.get("customer_id"),
            "customer_phone": notif.get("phone"),
            "customer_name": customer_name or None,
            "valor": value or None,
            "due_date": due_date or None,
            "billing_type": billing_type or None,
            "subscription_id": subscription_id,
            "message_text": message_text,
            "payment_link": payment_link,
            "notification_type": notification_type,
            "days_from_due": days_from_due,
            "canal": "whatsapp",
            "status": "enviado",
            "enviado_em": notif.get("sent_at") or notif.get("created_at"),
        }

        batch_records.append(record)
        existing_keys.add(notif_key)  # Evitar duplicatas no mesmo batch

    _log(f"Novos registros para inserir: {len(batch_records)}")

    # 5. Inserir em lotes de 50
    BATCH_SIZE = 50
    for i in range(0, len(batch_records), BATCH_SIZE):
        batch = batch_records[i:i + BATCH_SIZE]
        try:
            sb.table("ia_cobrancas_enviadas").insert(batch).execute()
            stats["synced"] += len(batch)
            _log(f"Lote {i // BATCH_SIZE + 1}: {len(batch)} registros inseridos")
        except Exception as e:
            _log_error(f"Erro ao inserir lote {i // BATCH_SIZE + 1}: {e}")
            # Tentar um por um no caso de erro
            for record in batch:
                try:
                    sb.table("ia_cobrancas_enviadas").insert(record).execute()
                    stats["synced"] += 1
                except Exception as e2:
                    _log_error(f"Erro ao inserir {record['payment_id']}: {e2}")
                    stats["errors"] += 1

    _log(
        f"Sincronizacao concluida: {stats['synced']} sincronizados, "
        f"{stats['skipped']} pulados, {stats['errors']} erros"
    )

    return {"status": "completed", "stats": stats}


# ============================================================================
# ENTRY POINTS
# ============================================================================

async def run_sync_billing_job() -> Dict[str, Any]:
    """Entry point async para o scheduler."""
    _log("Executando sync billing job...")
    return sync_billing_notifications()


# ============================================================================
# STANDALONE EXECUTION
# ============================================================================

if __name__ == "__main__":
    import os
    import sys

    # Configurar logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.debug("=" * 60)
    logger.debug("SYNC BILLING - Sincronizar billing_notifications")
    logger.debug("=" * 60)

    # Tentar carregar do .env ou variaveis de ambiente
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not url or not key:
        # Tentar carregar via dotenv
        try:
            from dotenv import load_dotenv
            env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
            load_dotenv(env_path)
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_SERVICE_KEY")
        except ImportError:
            pass

    if not url or not key:
        logger.debug("ERRO: SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorios")
        logger.debug("Configure via .env ou variaveis de ambiente")
        sys.exit(1)

    result = sync_billing_notifications(supabase_url=url, supabase_key=key)
    logger.debug(f"\nResultado: {result}")
