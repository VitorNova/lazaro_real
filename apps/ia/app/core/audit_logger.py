"""
Audit Logger Service - Logs tool executions to agent_audit_logs table.

Provides tracing for all tool calls made by the Gemini agent during conversations.
Each execution is logged with input, output, duration, and success status.

Usage:
    from app.core.audit_logger import AuditLogger

    audit = AuditLogger()

    # Log successful tool execution
    await audit.log_tool_execution(
        agent_id="uuid-here",
        lead_id="5566999999999@s.whatsapp.net",
        tool_name="consultar_cliente",
        tool_input={"cpf": "12345678901"},
        tool_output={"sucesso": True, "cliente": "Joao"},
        success=True,
        duration_ms=150,
    )

    # Log error
    await audit.log_tool_execution(
        agent_id="uuid-here",
        lead_id="5566999999999@s.whatsapp.net",
        tool_name="consultar_cliente",
        tool_input={"cpf": "invalid"},
        tool_output={"error": "Timeout"},
        success=False,
        duration_ms=15000,
        error_message="Tool exceeded timeout",
    )
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """Centralized logger for tool executions."""

    TABLE_NAME = "agent_audit_logs"

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        """Lazy load Supabase service."""
        if self._supabase is None:
            from app.services.supabase import get_supabase_service
            self._supabase = get_supabase_service()
        return self._supabase

    async def log_tool_execution(
        self,
        agent_id: str,
        lead_id: Optional[str],
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Dict[str, Any],
        success: bool,
        duration_ms: int,
        error_message: Optional[str] = None,
        action_category: str = "tool_call",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Log a tool execution to agent_audit_logs table.

        Args:
            agent_id: UUID of the agent
            lead_id: Remote JID or phone of the lead (nullable)
            tool_name: Name of the tool executed
            tool_input: Input arguments passed to the tool
            tool_output: Output returned by the tool (summarized)
            success: Whether the tool executed successfully
            duration_ms: Execution time in milliseconds
            error_message: Error message if failed (optional)
            action_category: Category of action (default: "tool_call")
            metadata: Additional metadata (optional)

        Returns:
            ID of the created log entry, or None if failed
        """
        try:
            record = {
                "agent_id": agent_id,
                "lead_id": lead_id,
                "action": f"tool:{tool_name}",
                "action_category": action_category,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
                "success": success,
                "duration_ms": duration_ms,
                "error_message": error_message,
                "metadata": metadata or {},
            }

            result = self.supabase.client.table(self.TABLE_NAME).insert(record).execute()

            if result.data and len(result.data) > 0:
                log_id = result.data[0].get("id")
                logger.debug(
                    f"[AUDIT] Logged tool execution: {tool_name} "
                    f"(success={success}, {duration_ms}ms, id={log_id})"
                )
                return log_id

            return None

        except Exception as e:
            # Fire-and-forget: don't fail the main flow if audit fails
            logger.warning(
                f"[AUDIT] Failed to log tool execution: {e}",
                extra={
                    "tool_name": tool_name,
                    "agent_id": agent_id,
                    "error": str(e),
                },
            )
            return None


# Singleton instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Returns singleton instance of AuditLogger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
