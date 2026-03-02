# Consulta de Departamento - Código Fonte

## 1. Função get_current_queue() - services/leadbox.py (linhas 604-720)

```python
async def get_current_queue(
    api_url: str,
    api_token: str,
    phone: str,
    ticket_id: Optional[int] = None,
    ia_queue_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Consulta a fila atual de um lead no Leadbox.

    Estratégia:
    1. Se tem ticket_id: faz PUT /tickets/{id} para obter estado atual
    2. Se não tem: busca contato via GET /contacts?searchParam={phone}
       2a. Se encontrar contato, tenta buscar tickets abertos do contato
           via GET /tickets?contactId={id}&status=open (pode falhar por bug da API)
       2b. Se encontrar ticket aberto, retorna queue_id, user_id, ticket_id
       2c. Se API de tickets falhar, retorna contact_found (fail-open)

    Nota sobre a API Leadbox:
        GET /tickets com qualquer filtro retorna erro 500 com "userId undefined"
        quando chamado via token de API externa. Isso é uma limitação conhecida
        da API do Leadbox. Quando ocorre, a função retorna contact_found (sem queue_id)
        e a IA prossegue normalmente (fail-open).

    Returns:
        {"queue_id": int, "user_id": int, "ticket_id": int, "status": str} ou None
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Estratégia 1: Se já tem ticket_id, consulta direto via PUT
        if ticket_id:
            try:
                resp = await client.put(
                    f"{api_url}/tickets/{ticket_id}",
                    headers=headers,
                    json={},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = {
                        "queue_id": data.get("queueId"),
                        "user_id": data.get("userId"),
                        "ticket_id": data.get("id") or ticket_id,
                        "status": data.get("status"),
                    }
                    logger.debug(f"[LEADBOX CHECK] Ticket {ticket_id}: queue={result['queue_id']}, status={result['status']}")
                    return result
            except Exception as e:
                logger.debug(f"[LEADBOX CHECK] Erro ao consultar ticket {ticket_id}: {e}")

        # Estratégia 2: Busca contato pelo telefone, depois tickets abertos
        try:
            clean_phone = "".join(filter(str.isdigit, phone))
            resp = await client.get(
                f"{api_url}/contacts",
                headers=headers,
                params={"searchParam": clean_phone, "pageNumber": 1, "limit": 1},
            )
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get("contacts", [])
                if contacts:
                    contact = contacts[0]
                    contact_id = contact.get("id")
                    logger.info(f"[LEADBOX CHECK] Contato encontrado: id={contact_id}, name={contact.get('name')} - buscando tickets abertos")

                    # Estratégia 2a: Buscar tickets abertos do contato
                    # NOTA: A API Leadbox retorna erro 500 com "userId undefined" para este endpoint
                    # quando chamado via token de API externa. Tentamos mesmo assim para coleta de dados.
                    ticket_found = await _fetch_open_ticket_for_contact(
                        client=client,
                        api_url=api_url,
                        headers=headers,
                        contact_id=contact_id,
                        ia_queue_id=ia_queue_id,
                    )

                    if ticket_found:
                        return ticket_found

                    # Fallback: retorna contact_found sem queue_id (fail-open)
                    logger.debug(f"[LEADBOX CHECK] Contato {contact_id} - sem tickets abertos encontrados via API, retornando contact_found")
                    return {
                        "queue_id": None,
                        "user_id": None,
                        "ticket_id": None,
                        "status": "contact_found",
                        "contact_id": contact_id,
                    }
        except Exception as e:
            logger.debug(f"[LEADBOX CHECK] Erro ao buscar contato {phone}: {e}")

    return None


async def _fetch_open_ticket_for_contact(
    client: httpx.AsyncClient,
    api_url: str,
    headers: dict,
    contact_id: int,
    ia_queue_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Tenta buscar o ticket aberto mais recente de um contato via múltiplas estratégias.

    A API Leadbox tem um bug no endpoint GET /tickets que retorna 500 com
    "userId undefined" quando chamado via token de API externa sem userId explícito.

    Returns:
        {"queue_id": int, "user_id": int, "ticket_id": int, "status": str} ou None
    """
    # Tentativa: GET /tickets?contactId={id}&status=open
    # Pode falhar com erro 500 "userId undefined" - bug conhecido da API Leadbox
```

---

## 2. Onde é chamada - webhooks/mensagens.py (linhas 985-1080)

```python

            table_leads = context.get("table_leads", "")
            if table_leads:
                fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if fresh_lead:
                    # Check 1: current_queue_id (banco local)
                    fresh_queue_raw = fresh_lead.get("current_queue_id")
                    if fresh_queue_raw:
                        try:
                            current_queue = int(fresh_queue_raw)
                        except (ValueError, TypeError):
                            current_queue = None
                        if current_queue is not None and current_queue not in IA_QUEUES_LOCAL:
                            logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} na fila {current_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})")
                            await redis.buffer_clear(agent_id, phone)
                            return
                        else:
                            logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} na fila {current_queue} - OK, processando (filas IA: {IA_QUEUES_LOCAL})")
                    else:
                        logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} sem current_queue_id no banco - prosseguindo para check em tempo real")

                    # ============================================================
                    # CHECK EM TEMPO REAL: consulta API do Leadbox diretamente
                    # Executado quando:
                    #   - current_queue_id está vazio no banco (webhook pode ter falhado)
                    #   - OU sempre que houver ticket_id disponível (confirma estado atual)
                    # Fail-open: se a API falhar, prossegue normalmente
                    # ============================================================
                    handoff_triggers = context.get("handoff_triggers") or {}
                    lb_api_url = handoff_triggers.get("api_url")
                    lb_api_token = handoff_triggers.get("api_token")
                    lb_type = handoff_triggers.get("type", "")

                    # Só consulta se for agente do tipo leadbox com credenciais configuradas
                    if lb_type == "leadbox" and lb_api_url and lb_api_token:
                        ticket_id_raw = fresh_lead.get("ticket_id")
                        ticket_id = int(ticket_id_raw) if ticket_id_raw else None

                        # Consulta quando: sem queue_id no banco (webhook falhou) OU tem ticket_id (confirma estado)
                        should_check = (not fresh_queue_raw) or (ticket_id is not None)
                        if should_check:
                            try:
                                print(f"[LEADBOX REALTIME CHECK] Consultando API para lead {phone} (ticket_id={ticket_id})", flush=True)
                                lb_ia_queue_id = handoff_triggers.get("ia_queue_id")
                                realtime_result = await get_current_queue(
                                    api_url=lb_api_url,
                                    api_token=lb_api_token,
                                    phone=phone,
                                    ticket_id=ticket_id,
                                    ia_queue_id=int(lb_ia_queue_id) if lb_ia_queue_id else None,
                                )
                                if realtime_result:
                                    realtime_queue = realtime_result.get("queue_id")
                                    if realtime_queue is not None:
                                        try:
                                            realtime_queue = int(realtime_queue)
                                        except (ValueError, TypeError):
                                            realtime_queue = None

                                    if realtime_queue is not None and realtime_queue not in IA_QUEUES_LOCAL:
                                        print(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})", flush=True)
                                        logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})")
                                        # Atualizar banco com dado real para próximas verificações
                                        try:
                                            update_fields = {"current_queue_id": str(realtime_queue)}
                                            if realtime_result.get("ticket_id"):
                                                update_fields["ticket_id"] = str(realtime_result["ticket_id"])
                                            if realtime_result.get("user_id"):
                                                update_fields["current_user_id"] = str(realtime_result["user_id"])
                                            supabase.update_lead_by_remotejid(table_leads, remotejid, update_fields)
                                            logger.debug(f"[LEADBOX REALTIME CHECK] Banco atualizado: queue={realtime_queue}")
                                        except Exception as update_err:
                                            logger.warning(f"[LEADBOX REALTIME CHECK] Erro ao atualizar banco: {update_err}")
                                        await redis.buffer_clear(agent_id, phone)
                                        return
                                    else:
                                        print(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - OK (está em filas IA {IA_QUEUES_LOCAL})", flush=True)
                                        logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - OK, processando (filas IA: {IA_QUEUES_LOCAL})")
                                        # Atualizar banco com dado real
                                        if realtime_queue is not None and not fresh_queue_raw:
                                            try:
                                                update_fields = {"current_queue_id": str(realtime_queue)}
                                                if realtime_result.get("ticket_id"):
                                                    update_fields["ticket_id"] = str(realtime_result["ticket_id"])
                                                supabase.update_lead_by_remotejid(table_leads, remotejid, update_fields)
                                                logger.debug(f"[LEADBOX REALTIME CHECK] Banco atualizado com fila IA: queue={realtime_queue}")
                                            except Exception as update_err:
                                                logger.warning(f"[LEADBOX REALTIME CHECK] Erro ao atualizar banco: {update_err}")
                                else:
                                    print(f"[LEADBOX REALTIME CHECK] Lead {phone} - API não retornou dados, prosseguindo (fail-open)", flush=True)
                                    logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} - API sem dados, fail-open")
                            except Exception as lb_err:
                                print(f"[LEADBOX REALTIME CHECK] Lead {phone} - Erro na API ({lb_err}), prosseguindo (fail-open)", flush=True)
                                logger.warning(f"[LEADBOX REALTIME CHECK] Lead {phone} - Erro ao consultar Leadbox: {lb_err} - prosseguindo")

                    # Check 2: Atendimento_Finalizado (defesa extra)
```

---

## Resumo do Fluxo

1. Mensagem chega no webhook (`mensagens.py`)
2. Sistema verifica `current_queue_id` no banco (Supabase)
3. Se não tem no banco, chama `get_current_queue()` (`leadbox.py`)
4. Função consulta API Leadbox: `PUT /tickets/{id}` ou `GET /contacts`
5. Retorna fila atual do lead
6. Se fila NÃO é da IA → ignora mensagem
7. Se fila É da IA → processa mensagem

## Arquivos Originais

- `apps/ia/app/services/leadbox.py` - Função de consulta (linha 604)
- `apps/ia/app/webhooks/mensagens.py` - Lógica de verificação (linha 990)
