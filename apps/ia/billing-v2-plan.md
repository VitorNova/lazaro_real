# Plano de Refatoração: Billing V2

## Resumo Executivo

Refatorar o monolito `cobrar_clientes.py` (1840L) em um pipeline modular de 5 etapas, corrigindo 6 bugs conhecidos. Os arquivos antigos (`cobrar_clientes.py`, `billing_job.py`) continuam rodando até validação completa.

**Decisão:** Criar nova pasta `app/billing/` conforme spec, separada de `app/domain/billing/`.

---

## Estrutura Existente (reusar via imports, NÃO alterar)

```
app/domain/billing/services/
├── billing_notifier.py   → claim_notification, update_notification_status, get_sent_count
├── billing_formatter.py  → format_message, format_consolidated_message
├── lead_ensurer.py       → save_message_to_conversation_history
└── billing_rules.py      → get_agents_with_asaas, should_skip_payment

app/core/utils/phone.py   → mask_phone, mask_customer_name, get_customer_phone, phone_to_remotejid, normalize_phone
                           (TODAS funções necessárias JÁ EXISTEM - NÃO criar shared/phone.py)

app/utils/dias_uteis.py   → is_business_day, add_business_days, etc.
```

---

## Arquivos a Criar

```
app/
├── billing/                        ← NOVO diretório
│   ├── __init__.py                 ← VAZIO (evitar imports circulares)
│   ├── models.py                   ← NOVO: dataclasses tipadas (~80L)
│   ├── collector.py                ← NOVO: ETAPA 1 (~120L)
│   ├── normalizer.py               ← NOVO: ETAPA 2 (~60L)
│   ├── eligibility.py              ← NOVO: ETAPA 3 (~130L)
│   ├── ruler.py                    ← NOVO: ETAPA 4 (~80L)
│   ├── dispatcher.py               ← NOVO: ETAPA 5 (~120L)
│   ├── agent_processor.py          ← NOVO: lógica por agente (~100L)
│   └── templates.py                ← NOVO: templates humanizados (~80L)
│
├── shared/
│   ├── __init__.py                 ← já existe (vazio)
│   └── formatters.py               ← NOVO: format_brl extraído (~30L)
│
├── utils/
│   └── dias_uteis.py               ← MODIFICAR: +count_business_days (~15L)
│
└── jobs/
    └── billing_job_v2.py           ← NOVO: entry point apenas (~50L)

+ Migração SQL: billing_exceptions table
```

**Total estimado:** ~845 linhas novas

---

## FASE 1: Fundação (sem dependências)

### 1.1 `app/billing/models.py` (~80L)

```python
"""Dataclasses tipadas para o pipeline de cobrança."""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class Payment:
    """Representa uma cobrança normalizada."""
    id: str
    customer_id: str
    customer_name: str
    value: float
    due_date: date
    status: str  # "PENDING" | "OVERDUE"
    billing_type: str
    invoice_url: Optional[str]
    bank_slip_url: Optional[str]
    subscription_id: Optional[str]
    source: str  # "api" | "cache"


@dataclass
class CollectorResult:
    """Resultado da coleta de pagamentos."""
    payments: List[Payment]
    source: str  # "api" | "cache"
    cache_age_hours: float
    degraded: bool  # True = cache > 6h, NÃO COBRA


@dataclass
class EligiblePayment:
    """Pagamento que passou em todos os checks."""
    payment: Payment
    phone: str  # normalizado, com 55
    customer_name: str


@dataclass
class RejectedPayment:
    """Pagamento rejeitado por um check."""
    payment: Payment
    reason: str  # "contract_cancelled", "customer_deleted", etc
    check_name: str


@dataclass
class EligibilityResult:
    """Resultado do funil de elegibilidade."""
    eligible: List[EligiblePayment]
    rejected: List[RejectedPayment]


@dataclass
class RulerDecision:
    """Decisão da régua de cobrança."""
    should_send: bool
    offset: int  # D-1, D0, D+3...
    template_key: str
    phase: str  # "pre" | "due" | "post"


@dataclass
class DispatchResult:
    """Resultado do envio de notificação."""
    status: str  # "sent" | "duplicate" | "error"
    payment_id: str
    template_used: str
    offset: int
    error: Optional[str]
```

---

### 1.2 `app/shared/formatters.py` (~30L)

```python
"""Formatadores reutilizáveis."""


def format_brl(value: float) -> str:
    """Formata valor em Real brasileiro (R$ 1.234,56)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
```

---

### 1.3 `app/billing/templates.py` (~80L)

**Templates humanizados com emojis:**

```python
"""Templates de mensagem para cobrança."""
from typing import Any, Dict

DEFAULT_MESSAGES = {
    "reminder": (
        "Olá, {nome}! 😊 Tudo bem?\n\n"
        "Passando para lembrar que sua mensalidade de {valor} vence em {vencimento}.\n\n"
        "Para sua comodidade, segue o link de pagamento:\n"
        "🔗 {link}\n\n"
        "Qualquer dúvida, estamos à disposição!"
    ),
    "dueDate": (
        "Olá, {nome}! 😊\n\n"
        "Sua mensalidade de {valor} vence hoje ({vencimento}).\n\n"
        "Efetue o pagamento para manter tudo em dia:\n"
        "🔗 {link}\n\n"
        "Caso já tenha pago, por favor desconsidere esta mensagem."
    ),
    "overdue": (
        "Olá, {nome}! Tudo bem?\n\n"
        "Notamos que a mensalidade de {valor} com vencimento em {vencimento} "
        "ainda permanece em aberto.\n\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Caso já tenha pago, por favor desconsidere esta mensagem. 💙"
    ),
    "overdue1": (
        "Olá, {nome}! Tudo bem?\n\n"
        "Notamos que a mensalidade de {valor} com vencimento em {vencimento} "
        "ainda permanece em aberto.\n\n"
        "Gostaríamos de lembrar gentilmente sobre o pagamento, "
        "a fim de evitar qualquer inconveniente.\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Caso já tenha pago, por favor desconsidere esta mensagem. 💙"
    ),
    "overdue2": (
        "Olá, {nome}.\n\n"
        "Sua mensalidade de {valor} está em atraso há {dias_atraso} dias "
        "(vencimento: {vencimento}).\n\n"
        "Pedimos que regularize o quanto antes para evitar interrupção no serviço.\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Teve algum problema? Responda esta mensagem que podemos ajudar. 🤝"
    ),
    "overdue3": (
        "{nome}, atenção! ⚠️\n\n"
        "Sua mensalidade de {valor} está vencida há {dias_atraso} dias.\n\n"
        "Essa é nossa última tentativa de contato antes de medidas adicionais. "
        "Regularize agora:\n"
        "🔗 {link}\n\n"
        "Está com dificuldades? Responda para negociarmos uma solução."
    ),
    "overdueConsolidated1": (
        "Olá, {nome}! Tudo bem?\n\n"
        "Identificamos que você possui {qtd} faturas em aberto, "
        "totalizando {total}.\n\n"
        "Regularize para manter tudo em dia:\n"
        "🔗 {link}\n\n"
        "Caso já tenha pago, por favor desconsidere. 💙"
    ),
    "overdueConsolidated2": (
        "Olá, {nome}.\n\n"
        "Você possui {qtd} faturas vencidas, totalizando {total}.\n\n"
        "Pedimos que regularize o quanto antes para evitar interrupção no serviço.\n"
        "🔗 {link}\n\n"
        "Precisa de ajuda? Responda esta mensagem. 🤝"
    ),
    "overdueConsolidated3": (
        "{nome}, atenção! ⚠️\n\n"
        "Você possui {qtd} faturas vencidas, totalizando {total}.\n\n"
        "Última tentativa de contato antes de medidas adicionais.\n"
        "🔗 {link}\n\n"
        "Está com dificuldades? Responda para negociarmos."
    ),
}


def get_overdue_template(days_overdue: int, messages: Dict[str, Any]) -> str:
    """Seleciona template baseado nos dias de atraso."""
    specific_key = f"overdueDia{days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    if days_overdue <= 5:
        return messages.get("overdueTemplate1") or DEFAULT_MESSAGES["overdue1"]
    elif days_overdue <= 10:
        return messages.get("overdueTemplate2") or DEFAULT_MESSAGES["overdue2"]
    else:
        return messages.get("overdueTemplate3") or DEFAULT_MESSAGES["overdue3"]


def get_consolidated_overdue_template(max_days_overdue: int, messages: Dict[str, Any]) -> str:
    """Seleciona template consolidado baseado nos dias de atraso."""
    specific_key = f"overdueConsolidatedDia{max_days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    if max_days_overdue <= 5:
        return messages.get("overdueConsolidatedTemplate1") or DEFAULT_MESSAGES["overdueConsolidated1"]
    elif max_days_overdue <= 10:
        return messages.get("overdueConsolidatedTemplate2") or DEFAULT_MESSAGES["overdueConsolidated2"]
    else:
        return messages.get("overdueConsolidatedTemplate3") or DEFAULT_MESSAGES["overdueConsolidated3"]
```

---

### 1.4 `app/billing/__init__.py`

```python
"""Billing V2 Pipeline - Cobrança automatizada."""
# Vazio para evitar imports circulares
```

---

## FASE 2: Pipeline Core (depende da Fase 1)

### 2.1 Adicionar `count_business_days` em `app/utils/dias_uteis.py`

**Inserir após linha 114** (após `subtract_business_days`):

```python
def count_business_days(start: date, end: date) -> int:
    """
    Conta dias úteis entre duas datas.
    Retorna negativo se end < start.

    Exemplos:
    - start = sexta, end = segunda → retorna 1
    - start = segunda, end = sexta → retorna 4
    """
    if start == end:
        return 0

    direction = 1 if end > start else -1
    count = 0
    current = start

    while current != end:
        current += timedelta(days=direction)
        if is_business_day(current):
            count += direction

    return count
```

**BUG FIX #2:** Corrige dias corridos no pós-vencimento.

---

### 2.2 `app/billing/normalizer.py` (~60L)

```python
"""Normalização de dados da API Asaas para formato interno."""
from datetime import date
from typing import Any, Dict

from app.billing.models import Payment
from app.utils.dias_uteis import parse_date


def normalize_api_payment(payment: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza camelCase da API para snake_case."""
    return {
        **payment,
        "customer_id": payment.get("customer") or payment.get("customer_id", ""),
        "customer_name": payment.get("customerName") or payment.get("customer_name", ""),
        "due_date": payment.get("dueDate") or payment.get("due_date"),
        "billing_type": payment.get("billingType") or payment.get("billing_type", ""),
        "invoice_url": payment.get("invoiceUrl") or payment.get("invoice_url"),
        "bank_slip_url": payment.get("bankSlipUrl") or payment.get("bank_slip_url"),
        "subscription_id": payment.get("subscription") or payment.get("subscription_id"),
    }


def dict_to_payment(data: Dict[str, Any], source: str) -> Payment:
    """Converte dict normalizado para dataclass Payment."""
    due_date_raw = data.get("due_date")
    if isinstance(due_date_raw, str):
        due_date = parse_date(due_date_raw)
    elif isinstance(due_date_raw, date):
        due_date = due_date_raw
    else:
        raise ValueError(f"due_date inválido: {due_date_raw}")

    return Payment(
        id=data["id"],
        customer_id=data.get("customer_id", ""),
        customer_name=data.get("customer_name", ""),
        value=float(data.get("value", 0)),
        due_date=due_date,
        status=data.get("status", ""),
        billing_type=data.get("billing_type", ""),
        invoice_url=data.get("invoice_url"),
        bank_slip_url=data.get("bank_slip_url"),
        subscription_id=data.get("subscription_id"),
        source=source,
    )
```

---

### 2.3 `app/billing/collector.py` (~120L)

**BUG FIX #4:** Se cache > 6h, retorna `degraded=True` e NÃO cobra.

```python
"""Coleta de pagamentos da API Asaas com fallback para cache."""
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Tuple

from app.billing.models import Payment, CollectorResult
from app.billing.normalizer import normalize_api_payment, dict_to_payment
from app.services.gateway_pagamento import create_asaas_service
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

CACHE_MAX_AGE_HOURS = 6.0


async def fetch_from_api(
    asaas_api_key: str,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Busca da API Asaas. Retorna (payments, success)."""
    try:
        asaas = create_asaas_service(api_key=asaas_api_key)
        params = {
            "status": status,
            "dueDate[ge]": due_date_start.strftime("%Y-%m-%d"),
            "dueDate[le]": due_date_end.strftime("%Y-%m-%d"),
            "offset": 0,
            "limit": 100,
        }

        all_payments: List[Dict] = []
        max_pages = 10

        for _ in range(max_pages):
            response = await asaas.list_payments(**params)
            data = response.get("data", [])
            all_payments.extend(data)

            if not response.get("hasMore", False):
                break
            params["offset"] += params["limit"]

        logger.info({
            "event": "api_fetch_success",
            "status": status,
            "count": len(all_payments),
        })
        return all_payments, True

    except Exception as e:
        logger.warning({"event": "api_fetch_failed", "error": str(e)})
        return [], False


async def fetch_from_cache(
    agent_id: str,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], float]:
    """Busca do Supabase (cache). Retorna (payments, cache_age_hours)."""
    supabase = get_supabase_service()

    result = (
        supabase.client.table("asaas_cobrancas")
        .select("*, last_synced_at")
        .eq("agent_id", agent_id)
        .eq("status", status)
        .gte("due_date", due_date_start.strftime("%Y-%m-%d"))
        .lte("due_date", due_date_end.strftime("%Y-%m-%d"))
        .eq("deleted_from_asaas", False)
        .execute()
    )

    payments = result.data or []

    # Calcular idade do cache (mais antigo)
    cache_age = 0.0
    if payments:
        synced_times = [p.get("last_synced_at") for p in payments if p.get("last_synced_at")]
        if synced_times:
            oldest = min(synced_times)
            synced_at = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            cache_age = (now - synced_at).total_seconds() / 3600

    return payments, cache_age


async def collect_payments(
    agent: Dict[str, Any],
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> CollectorResult:
    """
    Busca pagamentos com fallback inteligente.

    - API OK → source="api", degraded=False
    - API falhou + cache < 6h → source="cache", degraded=False
    - API falhou + cache >= 6h → source="cache", degraded=True (NÃO COBRA)
    """
    agent_id = agent["id"]
    asaas_api_key = agent.get("asaas_api_key")

    # 1. Tentar API
    if asaas_api_key:
        api_payments, api_success = await fetch_from_api(
            asaas_api_key, status, due_date_start, due_date_end
        )
        if api_success:
            payments = [
                dict_to_payment(normalize_api_payment(p), "api")
                for p in api_payments
            ]
            return CollectorResult(
                payments=payments,
                source="api",
                cache_age_hours=0.0,
                degraded=False,
            )

    # 2. Fallback para cache
    cache_payments, cache_age = await fetch_from_cache(
        agent_id, status, due_date_start, due_date_end
    )

    degraded = cache_age >= CACHE_MAX_AGE_HOURS
    if degraded:
        logger.warning({
            "event": "collector_degraded",
            "agent_id": agent_id,
            "cache_age_hours": round(cache_age, 2),
            "status": status,
        })

    payments = [dict_to_payment(p, "cache") for p in cache_payments]
    return CollectorResult(
        payments=payments,
        source="cache",
        cache_age_hours=cache_age,
        degraded=degraded,
    )
```

---

### 2.4 `app/billing/eligibility.py` (~130L)

**OTIMIZAÇÃO:** `check_customer_and_phone` combina validação de cliente + busca de telefone numa query só.

**BUG FIXES:** #1 (contrato cancelado), #3 (cliente deletado), #5 (checks explícitos), #6 (opt-out)

```python
"""Funil de elegibilidade - 6 checks em cadeia."""
import logging
from typing import Dict, List, Optional, Tuple

from app.billing.models import Payment, EligiblePayment, RejectedPayment, EligibilityResult
from app.core.utils.phone import normalize_phone, phone_to_remotejid
from app.domain.billing.services.billing_notifier import get_sent_count
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

CARD_BILLING_TYPES = {"CREDIT_CARD", "DEBIT_CARD"}


# ============================================================================
# CHECKS (ordem importa!)
# ============================================================================

def check_card_pending(payment: Payment) -> Tuple[bool, Optional[str]]:
    """Check 1: Cartão PENDING = pula (cobrado automaticamente)."""
    if payment.billing_type in CARD_BILLING_TYPES and payment.status == "PENDING":
        return False, "card_pending"
    return True, None


async def check_active_contract(payment: Payment, agent_id: str) -> Tuple[bool, Optional[str]]:
    """Check 2: Contrato deve estar ACTIVE. BUG FIX #1."""
    if not payment.subscription_id:
        return True, None

    supabase = get_supabase_service()
    result = (
        supabase.client.table("asaas_contratos")
        .select("status")
        .eq("id", payment.subscription_id)
        .eq("agent_id", agent_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return True, None

    if result.data.get("status") != "ACTIVE":
        return False, "contract_cancelled"
    return True, None


async def check_customer_and_phone(
    payment: Payment,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check 3+4: Cliente válido + telefone válido.
    Combina duas validações numa query só.
    BUG FIX #3: Verifica deleted_from_asaas.
    """
    supabase = get_supabase_service()
    result = (
        supabase.client.table("asaas_clientes")
        .select("deleted_from_asaas, mobile_phone, phone")
        .eq("id", payment.customer_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return False, "customer_not_found", None

    if result.data.get("deleted_from_asaas"):
        return False, "customer_deleted", None

    raw_phone = result.data.get("mobile_phone") or result.data.get("phone")
    phone = normalize_phone(raw_phone) if raw_phone else None

    if not phone:
        return False, "invalid_phone", None

    return True, None, phone


async def check_max_attempts(
    payment: Payment, agent_id: str, max_attempts: int
) -> Tuple[bool, Optional[str]]:
    """Check 5: Não exceder máximo de tentativas."""
    sent_count = await get_sent_count(agent_id, payment.id)
    if sent_count >= max_attempts:
        return False, "max_attempts_reached"
    return True, None


async def check_no_exception(
    payment: Payment, agent_id: str, remotejid: str
) -> Tuple[bool, Optional[str]]:
    """Check 6: Não ter exceção ativa (opt-out/pausa). BUG FIX #6."""
    supabase = get_supabase_service()

    result = (
        supabase.client.table("billing_exceptions")
        .select("id, reason")
        .eq("agent_id", agent_id)
        .eq("active", True)
        .or_(f"remotejid.eq.{remotejid},payment_id.eq.{payment.id}")
        .maybe_single()
        .execute()
    )

    if result.data:
        reason = result.data.get("reason", "manual")
        return False, f"exception_{reason}"
    return True, None


# ============================================================================
# ORQUESTRADOR
# ============================================================================

async def run_eligibility_checks(
    payments: List[Payment],
    agent_id: str,
    max_attempts: int = 15,
) -> EligibilityResult:
    """Executa todos os checks em ordem para cada payment."""
    eligible: List[EligiblePayment] = []
    rejected: List[RejectedPayment] = []

    for payment in payments:
        # Check 1: Card pending
        passed, reason = check_card_pending(payment)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "card_pending"))
            continue

        # Check 2: Active contract
        passed, reason = await check_active_contract(payment, agent_id)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "active_contract"))
            continue

        # Check 3+4: Customer valid + phone (query combinada)
        passed, reason, phone = await check_customer_and_phone(payment)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "customer_phone"))
            continue

        # Check 5: Max attempts
        passed, reason = await check_max_attempts(payment, agent_id, max_attempts)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "max_attempts"))
            continue

        # Check 6: No exception
        remotejid = phone_to_remotejid(phone)
        passed, reason = await check_no_exception(payment, agent_id, remotejid)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "no_exception"))
            continue

        # Passou todos os checks
        eligible.append(EligiblePayment(
            payment=payment,
            phone=phone,
            customer_name=payment.customer_name,
        ))

    logger.info({
        "event": "eligibility_complete",
        "agent_id": agent_id,
        "total": len(payments),
        "eligible": len(eligible),
        "rejected": len(rejected),
    })

    return EligibilityResult(eligible=eligible, rejected=rejected)
```

---

### 2.5 `app/billing/ruler.py` (~80L)

**BUG FIX #2:** Usa `count_business_days()` em vez de dias corridos.

```python
"""Régua de cobrança - decide quando e qual template usar."""
from datetime import date
from typing import List, Optional

from app.billing.models import RulerDecision
from app.utils.dias_uteis import count_business_days

DEFAULT_SCHEDULE = [-1, 0, 1, 3, 5, 7, 10, 12, 15]


def calculate_offset(today: date, due_date: date) -> int:
    """
    Calcula offset em dias ÚTEIS (não corridos).

    - Negativo = antes do vencimento (D-1, D-2)
    - Zero = dia do vencimento (D0)
    - Positivo = após vencimento (D+1, D+3...)

    BUG FIX #2: Venceu sexta → D+1 é segunda, não sábado.
    """
    return count_business_days(due_date, today)


def determine_phase(offset: int) -> str:
    """Determina fase: 'pre', 'due', 'post'."""
    if offset < 0:
        return "pre"
    elif offset == 0:
        return "due"
    return "post"


def should_send_today(offset: int, schedule: Optional[List[int]] = None) -> bool:
    """Verifica se deve enviar hoje baseado no schedule."""
    if schedule is None:
        schedule = DEFAULT_SCHEDULE
    return offset in schedule


def select_template_key(offset: int, phase: str) -> str:
    """Seleciona chave do template baseado no offset e fase."""
    if phase == "pre":
        return "reminder"
    elif phase == "due":
        return "dueDate"
    else:
        if offset <= 5:
            return "overdue1"
        elif offset <= 10:
            return "overdue2"
        return "overdue3"


def evaluate(
    today: date,
    due_date: date,
    schedule: Optional[List[int]] = None,
) -> RulerDecision:
    """Avalia se deve enviar e qual template usar."""
    offset = calculate_offset(today, due_date)
    phase = determine_phase(offset)
    should_send = should_send_today(offset, schedule)
    template_key = select_template_key(offset, phase) if should_send else ""

    return RulerDecision(
        should_send=should_send,
        offset=offset,
        template_key=template_key,
        phase=phase,
    )
```

---

## FASE 3: Envio + Orquestração (depende da Fase 2)

### 3.1 `app/billing/dispatcher.py` (~120L)

```python
"""Dispatcher - envio de notificações via WhatsApp."""
import logging
from datetime import datetime
from typing import Any, Dict

from app.billing.models import EligiblePayment, RulerDecision, DispatchResult
from app.billing.templates import get_overdue_template, DEFAULT_MESSAGES
from app.domain.billing.services.billing_formatter import format_message
from app.domain.billing.services.billing_notifier import (
    claim_notification,
    update_notification_status,
)
from app.domain.billing.services.lead_ensurer import save_message_to_conversation_history
from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import leadbox_push_silent, QUEUE_BILLING
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.utils.dias_uteis import format_date

logger = logging.getLogger(__name__)


async def dispatch_single(
    agent: Dict[str, Any],
    eligible: EligiblePayment,
    decision: RulerDecision,
    messages_config: Dict[str, Any],
) -> DispatchResult:
    """Envia notificação para um pagamento."""
    today_str = format_date(datetime.utcnow().date())
    payment = eligible.payment

    # 1. Claim atômico
    claimed = await claim_notification(
        agent_id=agent["id"],
        payment_id=payment.id,
        notification_type=decision.phase,
        scheduled_date=today_str,
        customer_id=payment.customer_id,
        phone=eligible.phone,
        days_from_due=decision.offset,
    )

    if not claimed:
        return DispatchResult(
            status="duplicate",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=None,
        )

    # 2. Formatar mensagem
    template = _get_template(decision, messages_config)
    message = format_message(
        template,
        eligible.customer_name,
        payment.value,
        str(payment.due_date),
        days_overdue=abs(decision.offset) if decision.offset > 0 else None,
        days_until_due=abs(decision.offset) if decision.offset < 0 else None,
        payment_link=payment.invoice_url or payment.bank_slip_url,
    )

    try:
        # 3. Enviar via Leadbox ou UAZAPI
        signed = sign_message(message, agent.get("name", "Ana"))
        push_result = await leadbox_push_silent(
            eligible.phone, QUEUE_BILLING, agent["id"], message=signed
        )

        if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
            uazapi = UazapiService(
                base_url=agent["uazapi_base_url"],
                api_key=agent["uazapi_token"],
            )
            result = await uazapi.send_text_message(eligible.phone, signed)
            if not result.get("success"):
                raise ValueError(result.get("error", "Erro desconhecido"))

        # 4. Salvar histórico
        await save_message_to_conversation_history(
            agent, eligible.phone, message, decision.phase, {"id": payment.id}
        )

        # 5. Log dispatch
        dispatch_logger = get_dispatch_logger()
        await dispatch_logger.log_dispatch(
            job_type="billing_v2",
            agent_id=agent["id"],
            reference_id=payment.id,
            phone=eligible.phone,
            notification_type=decision.phase,
            message_text=message,
            status="sent",
        )

        # 6. Atualizar asaas_cobrancas
        await _update_payment_status(agent["id"], payment.id, decision)

        await update_notification_status(
            agent["id"], payment.id, decision.phase, today_str, "sent"
        )

        logger.info({
            "event": "dispatch_sent",
            "payment_id": payment.id,
            "phase": decision.phase,
            "offset": decision.offset,
        })

        return DispatchResult(
            status="sent",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=None,
        )

    except Exception as e:
        await update_notification_status(
            agent["id"], payment.id, decision.phase, today_str, "failed", str(e)
        )
        logger.error({
            "event": "dispatch_error",
            "payment_id": payment.id,
            "error": str(e),
        })
        return DispatchResult(
            status="error",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=str(e),
        )


def _get_template(decision: RulerDecision, messages_config: Dict) -> str:
    """Obtém template baseado na decisão."""
    if decision.phase == "pre":
        return messages_config.get("reminderTemplate") or DEFAULT_MESSAGES["reminder"]
    elif decision.phase == "due":
        return messages_config.get("dueDateTemplate") or DEFAULT_MESSAGES["dueDate"]
    else:
        return get_overdue_template(decision.offset, messages_config)


async def _update_payment_status(
    agent_id: str, payment_id: str, decision: RulerDecision
) -> None:
    """Atualiza campos ia_* na asaas_cobrancas."""
    supabase = get_supabase_service()
    supabase.client.table("asaas_cobrancas").update({
        "ia_cobrou": True,
        "ia_cobrou_at": datetime.utcnow().isoformat(),
        "ia_ultimo_step": decision.phase,
        "ia_ultimo_days_from_due": decision.offset,
    }).eq("id", payment_id).eq("agent_id", agent_id).execute()
```

---

### 3.2 `app/billing/agent_processor.py` (~100L)

```python
"""Processador de cobrança por agente."""
import logging
from datetime import date
from typing import Any, Dict, List

from app.billing.collector import collect_payments
from app.billing.dispatcher import dispatch_single
from app.billing.eligibility import run_eligibility_checks
from app.billing.models import EligiblePayment
from app.billing.ruler import evaluate
from app.utils.dias_uteis import add_business_days, subtract_business_days

logger = logging.getLogger(__name__)


async def process_agent(agent: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    Processa cobrança para um agente.

    Pipeline:
    1. COLLECT - Busca faturas
    2. ELIGIBILITY - Funil de checks
    3. RULER - Decide se deve enviar
    4. DISPATCH - Envia e registra
    """
    config = (agent.get("asaas_config") or {}).get("autoCollection") or {}
    messages_config = config.get("messages") or {}
    max_attempts = (config.get("afterDue") or {}).get("maxAttempts", 15)

    stats = {"sent": 0, "skipped": 0, "errors": 0, "degraded": False}

    # ========================================================================
    # FASE 1: PENDING (lembretes D-2, D-1 + vencimento D0)
    # ========================================================================
    reminder_days = config.get("reminderDays") or [2, 1]
    on_due_date = config.get("onDueDate", True)

    # Processar lembretes
    for days_ahead in reminder_days:
        target_date = add_business_days(today, days_ahead)
        result = await collect_payments(agent, "PENDING", target_date, target_date)

        if result.degraded:
            stats["degraded"] = True
            continue

        eligibility = await run_eligibility_checks(result.payments, agent["id"], max_attempts)
        stats["skipped"] += len(eligibility.rejected)

        for eligible in eligibility.eligible:
            decision = evaluate(today, eligible.payment.due_date)
            if not decision.should_send:
                stats["skipped"] += 1
                continue

            dispatch_result = await dispatch_single(agent, eligible, decision, messages_config)
            if dispatch_result.status == "sent":
                stats["sent"] += 1
            elif dispatch_result.status == "error":
                stats["errors"] += 1
            else:
                stats["skipped"] += 1

    # Processar dia do vencimento
    if on_due_date:
        result = await collect_payments(agent, "PENDING", today, today)

        if result.degraded:
            stats["degraded"] = True
        else:
            eligibility = await run_eligibility_checks(result.payments, agent["id"], max_attempts)
            stats["skipped"] += len(eligibility.rejected)

            for eligible in eligibility.eligible:
                decision = evaluate(today, eligible.payment.due_date)
                if not decision.should_send:
                    stats["skipped"] += 1
                    continue

                dispatch_result = await dispatch_single(agent, eligible, decision, messages_config)
                if dispatch_result.status == "sent":
                    stats["sent"] += 1
                elif dispatch_result.status == "error":
                    stats["errors"] += 1
                else:
                    stats["skipped"] += 1

    # ========================================================================
    # FASE 2: OVERDUE (D+1 a D+15, agrupado por cliente)
    # ========================================================================
    after_due_config = config.get("afterDue") or {}
    if after_due_config.get("enabled", True):
        thirty_ago = subtract_business_days(today, 30)
        yesterday = subtract_business_days(today, 1)

        result = await collect_payments(agent, "OVERDUE", thirty_ago, yesterday)

        if result.degraded:
            stats["degraded"] = True
        else:
            eligibility = await run_eligibility_checks(result.payments, agent["id"], max_attempts)
            stats["skipped"] += len(eligibility.rejected)

            # Agrupar por customer_id
            grouped: Dict[str, List[EligiblePayment]] = {}
            for eligible in eligibility.eligible:
                cid = eligible.payment.customer_id
                if cid not in grouped:
                    grouped[cid] = []
                grouped[cid].append(eligible)

            # Processar cada cliente
            for customer_id, customer_eligible in grouped.items():
                for eligible in customer_eligible:
                    decision = evaluate(today, eligible.payment.due_date)
                    if not decision.should_send:
                        stats["skipped"] += 1
                        continue

                    dispatch_result = await dispatch_single(
                        agent, eligible, decision, messages_config
                    )
                    if dispatch_result.status == "sent":
                        stats["sent"] += 1
                    elif dispatch_result.status == "error":
                        stats["errors"] += 1
                    else:
                        stats["skipped"] += 1

    logger.info({
        "event": "agent_processed",
        "agent_id": agent["id"],
        "agent_name": agent.get("name"),
        **stats,
    })

    return stats
```

---

### 3.3 `app/jobs/billing_job_v2.py` (~50L)

**Entry point apenas:**

```python
"""Billing Job V2 - Entry point do cron."""
import logging
from typing import Any, Dict

from app.billing.agent_processor import process_agent
from app.domain.billing.models.billing_config import BILLING_JOB_LOCK_KEY, BILLING_JOB_LOCK_TTL
from app.domain.billing.services.billing_rules import get_agents_with_asaas
from app.services.redis import get_redis_service
from app.utils.dias_uteis import get_today_brasilia, is_business_day, is_business_hours

logger = logging.getLogger(__name__)


async def run_billing_v2() -> Dict[str, Any]:
    """Entry point do job v2."""
    redis = await get_redis_service()

    # Lock distribuído
    lock = await redis.client.set(
        BILLING_JOB_LOCK_KEY, "v2", nx=True, ex=BILLING_JOB_LOCK_TTL
    )
    if not lock:
        logger.info({"event": "billing_v2_skipped", "reason": "already_running"})
        return {"status": "skipped", "reason": "already_running"}

    try:
        today = get_today_brasilia()

        if not is_business_day(today):
            logger.info({"event": "billing_v2_skipped", "reason": "not_business_day"})
            return {"status": "skipped", "reason": "not_business_day"}

        if not is_business_hours(8, 20):
            logger.info({"event": "billing_v2_skipped", "reason": "outside_hours"})
            return {"status": "skipped", "reason": "outside_business_hours"}

        agents = await get_agents_with_asaas()
        logger.info({"event": "billing_v2_start", "agents_count": len(agents)})

        stats = {"sent": 0, "skipped": 0, "errors": 0, "degraded": 0, "agents": 0}

        for agent in agents:
            result = await process_agent(agent, today)
            stats["sent"] += result.get("sent", 0)
            stats["skipped"] += result.get("skipped", 0)
            stats["errors"] += result.get("errors", 0)
            if result.get("degraded"):
                stats["degraded"] += 1
            stats["agents"] += 1

        logger.info({"event": "billing_v2_complete", **stats})
        return {"status": "completed", "stats": stats}

    finally:
        await redis.client.delete(BILLING_JOB_LOCK_KEY)
```

---

### 3.4 Migração SQL: `billing_exceptions`

```sql
-- Migration: 20260303_create_billing_exceptions.sql

CREATE TABLE IF NOT EXISTS billing_exceptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id),
    remotejid TEXT,
    payment_id TEXT,
    reason TEXT NOT NULL,
    note TEXT,
    active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_billing_exceptions_active
    ON billing_exceptions(agent_id, active)
    WHERE active = TRUE;

CREATE INDEX idx_billing_exceptions_remotejid
    ON billing_exceptions(agent_id, remotejid)
    WHERE active = TRUE;

CREATE INDEX idx_billing_exceptions_payment
    ON billing_exceptions(agent_id, payment_id)
    WHERE active = TRUE;

ALTER TABLE billing_exceptions ENABLE ROW LEVEL SECURITY;
```

---

## Resumo de Bug Fixes

| # | Bug | Arquivo | Check/Função |
|---|-----|---------|--------------|
| 1 | Cobra contrato cancelado | eligibility.py | `check_active_contract()` |
| 2 | Dias corridos pós-vencimento | ruler.py + dias_uteis.py | `calculate_offset()` usa `count_business_days()` |
| 3 | Busca clientes deletados | eligibility.py | `check_customer_and_phone()` |
| 4 | Fallback silencioso | collector.py | `degraded=True` se cache > 6h |
| 5 | should_skip_payment vazia | eligibility.py | Cadeia de 5 checks com reasons |
| 6 | Sem opt-out/pausa | eligibility.py + SQL | `check_no_exception()` + tabela nova |

---

## Verificação

```bash
cd /var/www/lazaro-v2/apps/ia

# Sintaxe
python3 -m py_compile app/billing/models.py
python3 -m py_compile app/billing/templates.py
python3 -m py_compile app/billing/normalizer.py
python3 -m py_compile app/billing/collector.py
python3 -m py_compile app/billing/eligibility.py
python3 -m py_compile app/billing/ruler.py
python3 -m py_compile app/billing/dispatcher.py
python3 -m py_compile app/billing/agent_processor.py
python3 -m py_compile app/jobs/billing_job_v2.py
```

---

## Commits Sugeridos

```
feat(billing-v2): create app/billing/models.py with dataclasses
feat(billing-v2): add shared/formatters.py with format_brl
feat(billing-v2): add billing/templates.py with humanized messages
feat(billing-v2): add count_business_days to dias_uteis.py
feat(billing-v2): add billing/normalizer.py
feat(billing-v2): add billing/collector.py with degraded fallback
feat(billing-v2): add billing/eligibility.py with combined customer check
feat(billing-v2): add billing/ruler.py with business days calc
feat(billing-v2): add billing/dispatcher.py
feat(billing-v2): add billing/agent_processor.py
feat(billing-v2): add jobs/billing_job_v2.py entry point
feat(billing-v2): create billing_exceptions table (migration)
```

---

## Notas Finais

1. **Templates**: Usando mensagens humanizadas com emojis conforme especificado.

2. **eligibility.py**: `check_customer_and_phone()` combina validação de cliente + busca de telefone numa query só em `asaas_clientes`.

3. **agent_processor.py**: Lógica completa de processamento por agente (~100L).

4. **billing_job_v2.py**: Entry point simples (~50L), apenas orquestra.

5. **shared/phone.py**: NÃO criar. Funções já existem em `app/core/utils/phone.py`:
   - `mask_phone`
   - `mask_customer_name`
   - `get_customer_phone`
   - `phone_to_remotejid`
   - `normalize_phone`

6. **billing/__init__.py**: Mantido vazio para evitar imports circulares.
