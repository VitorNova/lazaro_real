"""
Message recovery functions for orphan buffers and failed sends.

This module handles recovery of:
- Orphan buffers after PM2 restart
- Failed message sends that need to be retried
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def recover_orphan_buffers():
    """
    Recupera buffers órfãos após restart do PM2.

    Quando o PM2 reinicia, tasks em memória são perdidas mas os buffers
    permanecem no Redis. Esta função identifica buffers sem lock ativo
    e agenda seu processamento.
    """
    from app.services.redis import get_redis_service
    from app.services.supabase import SupabaseService

    try:
        redis = await get_redis_service()
        orphan_buffers = await redis.list_orphan_buffers()

        if not orphan_buffers:
            logger.info("[STARTUP RECOVERY] Nenhum buffer órfão encontrado")
            return

        logger.warning(
            f"[STARTUP RECOVERY] Encontrados {len(orphan_buffers)} buffers órfãos",
            extra={"count": len(orphan_buffers)},
        )

        supabase = SupabaseService()
        recovered = 0
        failed = 0

        for buffer in orphan_buffers:
            agent_id = buffer["agent_id"]
            phone = buffer["phone"]
            message_count = buffer["message_count"]

            logger.info(
                f"[STARTUP RECOVERY] Processando buffer órfão: agent={agent_id[:8]}... phone={phone} msgs={message_count}"
            )

            try:
                # Buscar agente
                agent = supabase.get_agent_by_id(agent_id)
                if not agent:
                    logger.warning(f"[STARTUP RECOVERY] Agente {agent_id[:8]} não encontrado - limpando buffer")
                    await redis.buffer_clear(agent_id, phone)
                    failed += 1
                    continue

                # Verificar se agente está ativo
                if not agent.get("enabled"):
                    logger.warning(f"[STARTUP RECOVERY] Agente {agent_id[:8]} desativado - limpando buffer")
                    await redis.buffer_clear(agent_id, phone)
                    failed += 1
                    continue

                # Importar handler e processar
                from app.webhooks.mensagens import WhatsAppWebhookHandler

                # Construir contexto mínimo
                handoff_triggers = agent.get("handoff_triggers") or {}
                context = {
                    "agent_id": agent_id,
                    "system_prompt": agent.get("system_prompt", ""),
                    "table_messages": agent.get("table_messages", ""),
                    "table_leads": agent.get("table_leads", ""),
                    "handoff_triggers": handoff_triggers,
                    "uazapi_token": agent.get("uazapi_token", ""),
                    "uazapi_base_url": agent.get("uazapi_base_url", ""),
                    "context_prompts": agent.get("context_prompts"),
                }

                # Construir remotejid
                clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "")
                remotejid = f"{clean_phone}@s.whatsapp.net"

                # Processar em background (não bloqueia startup)
                async def process_orphan():
                    handler = WhatsAppWebhookHandler()
                    try:
                        await handler._process_buffered_messages(
                            agent_id=agent_id,
                            phone=phone,
                            remotejid=remotejid,
                            context=context,
                        )
                        logger.info(f"[STARTUP RECOVERY] Buffer processado: {phone}")
                    except Exception as proc_err:
                        logger.error(f"[STARTUP RECOVERY] Erro ao processar {phone}: {proc_err}")

                # Agendar processamento com pequeno delay para não sobrecarregar
                asyncio.create_task(process_orphan())
                await asyncio.sleep(0.5)  # 500ms entre cada para não sobrecarregar

                recovered += 1

            except Exception as e:
                logger.error(f"[STARTUP RECOVERY] Erro ao recuperar buffer {phone}: {e}")
                failed += 1

        logger.info(
            f"[STARTUP RECOVERY] Concluído: {recovered} agendados, {failed} falhas",
            extra={"recovered": recovered, "failed": failed},
        )

    except Exception as e:
        logger.error(f"[STARTUP RECOVERY] Erro geral: {e}")


async def recover_failed_sends():
    """
    Recupera e reenvia mensagens que falharam ao ser enviadas.

    Quando a UAZAPI falha (timeout, 500, etc), a mensagem é salva na fila
    failed_send:{agent_id}:{phone}. Esta função tenta reenviar essas mensagens.
    """
    from app.services.redis import get_redis_service
    from app.services.whatsapp_api import UazapiService

    try:
        redis = await get_redis_service()

        # Buscar todas as chaves de mensagens pendentes
        failed_keys = []
        async for key in redis.client.scan_iter(match="failed_send:*", count=100):
            failed_keys.append(key)

        if not failed_keys:
            logger.info("[FAILED SEND RECOVERY] Nenhuma mensagem pendente encontrada")
            return

        logger.warning(
            f"[FAILED SEND RECOVERY] Encontradas {len(failed_keys)} mensagens pendentes",
            extra={"count": len(failed_keys)},
        )

        recovered = 0
        failed = 0
        max_attempts = 5  # Máximo de tentativas antes de desistir

        for key in failed_keys:
            try:
                # Extrair agent_id e phone da chave
                # Formato: failed_send:{agent_id}:{phone}
                parts = key.split(":")
                if len(parts) != 3:
                    logger.warning(f"[FAILED SEND RECOVERY] Chave com formato inesperado: {key}")
                    continue

                agent_id = parts[1]
                phone = parts[2]

                # Buscar payload da mensagem
                payload = await redis.cache_get(key)
                if not payload or not isinstance(payload, dict):
                    logger.warning(f"[FAILED SEND RECOVERY] Payload inválido para {key}")
                    await redis.cache_delete(key)
                    continue

                attempts = payload.get("attempts", 0)
                text = payload.get("text", "")

                # Se já tentou demais, desistir
                if attempts >= max_attempts:
                    logger.error(
                        f"[FAILED SEND RECOVERY] Desistindo de {phone} após {attempts} tentativas"
                    )
                    await redis.cache_delete(key)
                    failed += 1
                    continue

                # Buscar agente para pegar credenciais UAZAPI
                from app.services.supabase import SupabaseService
                supabase = SupabaseService()
                agent = supabase.get_agent_by_id(agent_id)

                if not agent:
                    logger.warning(f"[FAILED SEND RECOVERY] Agente {agent_id[:8]} não encontrado")
                    await redis.cache_delete(key)
                    failed += 1
                    continue

                # Criar serviço UAZAPI com credenciais do agente
                uazapi = UazapiService(
                    base_url=agent.get("uazapi_base_url", ""),
                    api_key=agent.get("uazapi_token", ""),
                )

                agent_name = agent.get("name", "Assistente")
                logger.info(
                    f"[FAILED SEND RECOVERY] Tentando reenviar para {phone} "
                    f"(tentativa {attempts + 1}/{max_attempts}, agente={agent_name})"
                )

                # Tentar reenviar com assinatura do agente
                send_result = await uazapi.send_ai_response(phone, text, agent_name, delay=2.0)

                if send_result["all_success"]:
                    # Sucesso! Remover da fila
                    await redis.cache_delete(key)
                    recovered += 1
                    logger.info(f"[FAILED SEND RECOVERY] Mensagem reenviada com sucesso para {phone}")
                else:
                    # Falhou novamente - atualizar contador
                    payload["attempts"] = attempts + 1
                    payload["last_error"] = send_result.get("first_error")
                    await redis.cache_set(key, payload, ttl=86400)
                    logger.warning(
                        f"[FAILED SEND RECOVERY] Falha ao reenviar para {phone}. "
                        f"Tentativas: {attempts + 1}/{max_attempts}"
                    )
                    failed += 1

                # Delay entre tentativas para não sobrecarregar
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"[FAILED SEND RECOVERY] Erro ao processar {key}: {e}")
                failed += 1

        logger.info(
            f"[FAILED SEND RECOVERY] Concluído: {recovered} reenviados, {failed} falhas",
            extra={"recovered": recovered, "failed": failed},
        )

    except Exception as e:
        logger.error(f"[FAILED SEND RECOVERY] Erro geral: {e}")
