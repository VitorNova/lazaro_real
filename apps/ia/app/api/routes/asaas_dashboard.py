# ╔══════════════════════════════════════════════════════════════╗
# ║  DASHBOARD ASAAS — Implementação nativa Python             ║
# ╚══════════════════════════════════════════════════════════════╝
# apps/ia/app/api/routes/asaas_dashboard.py
"""
Dashboard Asaas — consulta direta ao Supabase (substituiu proxy agnes-agent).

Endpoints:
- GET  /api/dashboard/asaas                       -> dashboard principal
- GET  /api/dashboard/asaas/payment-timeline       -> timeline pagamentos por cliente
- GET  /api/dashboard/asaas/contratos-encerrados   -> lista encerrados
- POST /api/dashboard/asaas/encerrar-contrato      -> encerrar contrato
"""

from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import structlog

from app.middleware.auth import get_current_user
from app.services.supabase import get_supabase_service
from app.core.utils.dias_uteis import parse_date

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/dashboard/asaas", tags=["asaas-dashboard"])

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


# ============================================================================
# GET /api/dashboard/asaas — Dashboard principal
# ============================================================================

@router.get("")
async def get_asaas_dashboard(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Dashboard Asaas — cards, cobranças, contratos, equipamentos, alertas."""
    try:
        supabase = get_supabase_service()
        sb = supabase.client

        # ── Clientes ativos (não deletados) ──
        clientes_resp = sb.table("asaas_clientes").select(
            "id, name, mobile_phone, cpf_cnpj"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null").execute()
        clientes = clientes_resp.data or []
        cliente_map = {c["id"]: c for c in clientes}

        # ── Cobranças (todas, não deletadas) ──
        cobrancas_resp = sb.table("asaas_cobrancas").select(
            "id, customer_id, customer_name, subscription_id, value, status, "
            "due_date, payment_date, dias_atraso, billing_type, invoice_url, "
            "bank_slip_url, updated_at, ia_cobrou, ia_recebeu, ia_recebeu_at"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null").execute()
        cobrancas_raw = cobrancas_resp.data or []

        # ── Contratos Asaas (subscriptions) ──
        contratos_resp = sb.table("asaas_contratos").select(
            "id, customer_id, customer_name, value, status, cycle, "
            "next_due_date, description"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null").execute()
        contratos_raw = contratos_resp.data or []

        # ── Contract details (PDFs parseados) ──
        details_resp = sb.table("contract_details").select(
            "id, subscription_id, customer_id, locatario_nome, "
            "numero_contrato, equipamentos, qtd_ars, valor_mensal, "
            "valor_comercial_total, data_inicio, data_termino, "
            "proxima_manutencao, maintenance_status, endereco_instalacao"
        ).eq("agent_id", AGENT_ID).execute()
        details = details_resp.data or []
        # Agregar múltiplos contract_details por subscription (ex: 3 contratos na mesma sub)
        details_by_sub = {}
        for d in details:
            sub_id = d.get("subscription_id")
            if not sub_id:
                continue
            if sub_id not in details_by_sub:
                details_by_sub[sub_id] = d
            else:
                # Merge: concatenar equipamentos de contratos adicionais
                existing = details_by_sub[sub_id]
                existing_eqs = existing.get("equipamentos") or []
                new_eqs = d.get("equipamentos") or []
                if isinstance(existing_eqs, list) and isinstance(new_eqs, list):
                    existing["equipamentos"] = existing_eqs + new_eqs
                    existing["qtd_ars"] = len(existing["equipamentos"])
                    existing["valor_comercial_total"] = (
                        (existing.get("valor_comercial_total") or 0)
                        + (d.get("valor_comercial_total") or 0)
                    )

        # ── Calcular cards ──
        hoje = date.today()
        mes_atual = hoje.month
        ano_atual = hoje.year
        mes_nome = MONTH_NAMES.get(mes_atual, "")

        # Contratos ativos
        contratos_ativos = [c for c in contratos_raw if (c.get("status") or "").upper() == "ACTIVE"]
        cliente_ids_com_contrato = {c["customer_id"] for c in contratos_ativos if c.get("customer_id")}

        # Equipamentos de TODOS os contract_details ativos
        all_equipamentos = []
        for c in contratos_ativos:
            d = details_by_sub.get(c["id"])
            if d and d.get("equipamentos"):
                eqs = d["equipamentos"]
                if isinstance(eqs, list):
                    all_equipamentos.extend(eqs)

        total_ars = len(all_equipamentos)

        # Cobranças do mês atual (PENDING)
        cobrancas_mes = [
            c for c in cobrancas_raw
            if c.get("due_date") and c["due_date"][:7] == f"{ano_atual}-{mes_atual:02d}"
            and c.get("status") in ("PENDING", "OVERDUE")
        ]
        valor_receber = sum(float(c.get("value") or 0) for c in cobrancas_mes)
        qtd_cobrancas_mes = len(cobrancas_mes)

        # Cobranças atrasadas
        cobrancas_atrasadas = [c for c in cobrancas_raw if c.get("status") == "OVERDUE"]
        valor_atrasado = sum(float(c.get("value") or 0) for c in cobrancas_atrasadas)
        qtd_atrasadas = len(cobrancas_atrasadas)

        # Quebras (atraso >= 30 dias)
        quebras = len([c for c in cobrancas_atrasadas if (c.get("dias_atraso") or 0) >= 30])

        # Clientes sem contrato
        clientes_sem_contrato = [
            c for c in clientes
            if c["id"] not in cliente_ids_com_contrato
        ]

        # Última sync (updated_at mais recente das cobranças)
        ultima_sync = None
        for c in cobrancas_raw:
            ua = c.get("updated_at")
            if ua and (not ultima_sync or ua > ultima_sync):
                ultima_sync = ua

        # Transferidos Leadbox (leads com Atendimento_Finalizado)
        transferidos = 0
        try:
            agent_resp = sb.table("agents").select(
                "table_leads"
            ).eq("id", AGENT_ID).limit(1).execute()
            if agent_resp.data:
                table_leads = agent_resp.data[0].get("table_leads")
                if table_leads:
                    trans_resp = sb.table(table_leads).select(
                        "id", count="exact"
                    ).eq("Atendimento_Finalizado", "true").execute()
                    transferidos = trans_resp.count or 0
        except Exception as e:
            logger.warning("transferidos_count_error", error=str(e))

        cards = {
            "clientesFevereiro": len(contratos_ativos),
            "totalARs": total_ars,
            "quebrasContrato": quebras,
            "transferidosLeadbox": transferidos,
            "clientesSemContrato": len(clientes_sem_contrato),
            "mesAtualNome": mes_nome,
            "valorReceberMesAtual": valor_receber,
            "qtdCobrancasMesAtual": qtd_cobrancas_mes,
            "valorAtrasadoTotal": valor_atrasado,
            "qtdCobrancasAtrasadas": qtd_atrasadas,
            "ultimaSync": ultima_sync,
        }

        # ── Cobranças formatadas ──
        cobrancas_fmt = []
        for c in cobrancas_raw:
            cobrancas_fmt.append({
                "id": c.get("id"),
                "customer": c.get("customer_id"),
                "customerId": c.get("customer_id"),
                "customerName": c.get("customer_name") or "",
                "subscriptionId": c.get("subscription_id"),
                "status": c.get("status"),
                "value": float(c.get("value") or 0),
                "paymentDate": c.get("payment_date"),
                "dueDate": c.get("due_date"),
                "diasAtraso": c.get("dias_atraso") or 0,
                "billingType": c.get("billing_type"),
                "invoiceUrl": c.get("invoice_url"),
                "bankSlipUrl": c.get("bank_slip_url"),
                "iaCobrou": c.get("ia_cobrou") or False,
                "iaRecebeu": c.get("ia_recebeu") or False,
                "iaRecebeuAt": c.get("ia_recebeu_at"),
            })

        # ── Contratos formatados ──
        contratos_fmt = []
        for c in contratos_ativos:
            d = details_by_sub.get(c["id"], {})
            eqs = d.get("equipamentos") or [] if d else []

            contratos_fmt.append({
                "id": c.get("id"),
                "name": c.get("customer_name") or c.get("description") or "",
                "customerName": c.get("customer_name") or "",
                "customer": c.get("customer_id"),
                "customerId": c.get("customer_id"),
                "status": (c.get("status") or "").lower(),
                "value": float(c.get("value") or 0),
                "contractDetails": {
                    "equipamentos": eqs,
                    "numero_contrato": d.get("numero_contrato") if d else None,
                    "dataInicio": d.get("data_inicio") if d else None,
                    "dataTermino": d.get("data_termino") if d else None,
                    "valorMensal": float(d.get("valor_mensal") or 0) if d else 0,
                    "proximaManutencao": d.get("proxima_manutencao") if d else None,
                    "maintenanceStatus": d.get("maintenance_status") if d else None,
                    "enderecoInstalacao": d.get("endereco_instalacao") if d else None,
                },
            })

        # ── Equipamentos flat ──
        all_equip_fmt = []
        for eq in all_equipamentos:
            if isinstance(eq, dict):
                all_equip_fmt.append({
                    "patrimonio": eq.get("patrimonio", ""),
                    "btus": eq.get("btus") or 0,
                    "marca": eq.get("marca", ""),
                    "valor_comercial": eq.get("valor_comercial") or eq.get("valorComercial") or 0,
                })

        # ── Relatório BTUs ──
        btus_map: Dict[int, dict] = defaultdict(lambda: {"quantidade": 0, "valorComercialTotal": 0})
        for eq in all_equip_fmt:
            b = eq.get("btus") or 0
            if b > 0:
                btus_map[b]["quantidade"] += 1
                btus_map[b]["valorComercialTotal"] += eq.get("valor_comercial") or 0

        total_eq = len(all_equip_fmt)
        valor_comercial_total = sum(eq.get("valor_comercial") or 0 for eq in all_equip_fmt)

        relatorio_btus = sorted([
            {
                "btus": btus,
                "quantidade": info["quantidade"],
                "percentual": f"{(info['quantidade'] / total_eq * 100):.1f}" if total_eq > 0 else "0",
                "valorComercialTotal": info["valorComercialTotal"],
            }
            for btus, info in btus_map.items()
        ], key=lambda x: x["quantidade"], reverse=True)

        equipamentos_totais = {
            "quantidade": total_eq,
            "valorComercialTotal": valor_comercial_total,
        }

        # ── Alertas ──
        alerts: List[dict] = []
        if qtd_atrasadas > 0:
            alerts.append({
                "type": "warning",
                "text": f"{qtd_atrasadas} cobrança(s) vencida(s) totalizando R$ {valor_atrasado:,.2f}",
                "action": "cobrancas-atrasadas",
            })
        if len(clientes_sem_contrato) > 0:
            alerts.append({
                "type": "info",
                "text": f"{len(clientes_sem_contrato)} cliente(s) sem contrato cadastrado",
                "action": "sem-contrato",
            })
        if quebras > 0:
            alerts.append({
                "type": "error",
                "text": f"{quebras} contrato(s) com atraso crítico (≥30 dias)",
                "action": "quebras",
            })

        # ── Clientes sem contrato detalhes ──
        clientes_sem_contrato_detalhes = [
            {
                "id": c.get("id"),
                "name": c.get("name") or "",
                "customer": c.get("id"),
                "status": "sem_contrato",
            }
            for c in clientes_sem_contrato
        ]

        return JSONResponse(content={
            "status": "success",
            "data": {
                "cards": cards,
                "cobrancas": cobrancas_fmt,
                "contratos": contratos_fmt,
                "allEquipamentos": all_equip_fmt,
                "equipamentosTotais": equipamentos_totais,
                "relatorioBTUs": relatorio_btus,
                "alerts": alerts,
                "clientesSemContratoDetalhes": clientes_sem_contrato_detalhes,
            },
        })

    except Exception as e:
        logger.exception("asaas_dashboard_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )


# ============================================================================
# GET /api/dashboard/asaas/customers — Lista clientes com subscription_id
# ============================================================================

@router.get("/customers")
async def get_asaas_customers(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Lista clientes ativos com subscription_id vinculado."""
    try:
        supabase = get_supabase_service()
        sb = supabase.client

        clientes_resp = sb.table("asaas_clientes").select(
            "id, name, cpf_cnpj, email, mobile_phone, phone"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null").execute()
        clientes = clientes_resp.data or []

        contratos_resp = sb.table("asaas_contratos").select(
            "id, customer_id"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null").eq(
            "status", "ACTIVE"
        ).execute()
        contrato_map = {
            c["customer_id"]: c["id"]
            for c in (contratos_resp.data or [])
        }

        result = []
        for c in clientes:
            result.append({
                "id": c.get("id"),
                "name": c.get("name") or "",
                "cpfCnpj": c.get("cpf_cnpj") or "",
                "email": c.get("email") or "",
                "mobilePhone": c.get("mobile_phone") or "",
                "phone": c.get("phone") or "",
                "subscriptionId": contrato_map.get(c.get("id")),
            })

        return JSONResponse(content={"status": "success", "data": result})

    except Exception as e:
        logger.exception("customers_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )


# ============================================================================
# GET /api/dashboard/asaas/payment-timeline — Timeline de pagamento por cliente
# ============================================================================

@router.get("/payment-timeline")
async def get_payment_timeline(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Timeline de pagamento por cliente — delta entre vencimento e pagamento."""
    try:
        supabase = get_supabase_service()
        sb = supabase.client

        # Filtro opcional por cliente
        customer_id_filter = request.query_params.get("customer_id")

        query = sb.table("asaas_cobrancas").select(
            "customer_id, customer_name, value, status, due_date, "
            "payment_date, billing_type"
        ).eq("agent_id", AGENT_ID).is_("deleted_at", "null")

        if customer_id_filter:
            query = query.eq("customer_id", customer_id_filter)

        cobrancas_resp = query.execute()
        cobrancas = cobrancas_resp.data or []

        # Agrupar por cliente
        by_customer: Dict[str, List[dict]] = defaultdict(list)
        for c in cobrancas:
            cid = c.get("customer_id")
            if not cid:
                continue
            by_customer[cid].append(c)

        customers_out = []
        for cid, payments_raw in by_customer.items():
            payments_raw.sort(key=lambda p: p.get("due_date") or "")

            payments = []
            deltas_paid: List[int] = []

            for p in payments_raw:
                due = p.get("due_date")
                paid = p.get("payment_date")

                delta_days = None
                delta_label = None

                if due and paid:
                    try:
                        d_due = parse_date(due)
                        d_paid = parse_date(paid)
                        delta_days = (d_paid - d_due).days
                        sign = "+" if delta_days >= 0 else ""
                        delta_label = f"D{sign}{delta_days}"
                        deltas_paid.append(delta_days)
                    except (ValueError, TypeError):
                        pass

                payments.append({
                    "due_date": due,
                    "payment_date": paid,
                    "delta_days": delta_days,
                    "delta": delta_label,
                    "value": float(p.get("value") or 0),
                    "status": p.get("status"),
                    "billing_type": p.get("billing_type"),
                })

            # Stats
            avg_delta = None
            trend = None
            total_paid = len(deltas_paid)
            total_pending = len(payments) - total_paid

            if deltas_paid:
                avg_delta = round(sum(deltas_paid) / len(deltas_paid), 1)

            # Trend: compara média da 1ª metade vs 2ª metade
            if len(deltas_paid) >= 2:
                mid = len(deltas_paid) // 2
                avg_first = sum(deltas_paid[:mid]) / mid
                avg_second = sum(deltas_paid[mid:]) / (len(deltas_paid) - mid)
                if avg_second > avg_first + 0.5:
                    trend = "worsening"
                elif avg_second < avg_first - 0.5:
                    trend = "improving"
                else:
                    trend = "stable"

            customer_name = payments_raw[0].get("customer_name") or "Desconhecido"
            customers_out.append({
                "customer_id": cid,
                "customer_name": customer_name,
                "payments": payments,
                "stats": {
                    "avg_delta_days": avg_delta,
                    "total_payments": total_paid,
                    "total_pending": total_pending,
                    "trend": trend,
                },
            })

        # Ordenar por avg_delta desc (piores pagadores primeiro)
        customers_out.sort(
            key=lambda c: c["stats"]["avg_delta_days"]
            if c["stats"]["avg_delta_days"] is not None else -999,
            reverse=True,
        )

        return JSONResponse(content={
            "status": "success",
            "data": {"customers": customers_out},
        })

    except Exception as e:
        logger.exception("payment_timeline_error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)},
        )


# ============================================================================
# ENDPOINTS NATIVOS (já existiam)
# ============================================================================

@router.post("/encerrar-contrato")
async def encerrar_contrato_endpoint(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """POST /api/dashboard/asaas/encerrar-contrato"""
    from app.domain.billing.services.contract_termination_service import encerrar_contrato
    from app.integrations.supabase.client import SupabaseClient

    body = await request.json()
    subscription_id = body.get("subscription_id")
    motivo = body.get("motivo")
    observacoes = body.get("observacoes")
    agent_id = body.get("agent_id")

    if not subscription_id or not motivo:
        return JSONResponse(
            status_code=400,
            content={"error": "subscription_id e motivo sao obrigatorios"}
        )

    supabase = SupabaseClient()
    result = await encerrar_contrato(
        supabase=supabase,
        subscription_id=subscription_id,
        motivo=motivo,
        agent_id=agent_id or "",
        user_id=user["id"],
        observacoes=observacoes,
    )

    if result.get("success"):
        return JSONResponse(content=result)
    else:
        return JSONResponse(status_code=400, content=result)


@router.get("/contratos-encerrados")
async def listar_contratos_encerrados_endpoint(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """GET /api/dashboard/asaas/contratos-encerrados"""
    from app.domain.billing.services.contract_termination_service import listar_contratos_encerrados
    from app.integrations.supabase.client import SupabaseClient

    supabase = SupabaseClient()
    result = await listar_contratos_encerrados(supabase=supabase)
    return JSONResponse(content=result)
