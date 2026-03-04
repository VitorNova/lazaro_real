"""
Dispatch Logger Service - Unified logging for all notification jobs.

Provides a centralized way to log dispatches (sent notifications) and failures
across all job types (billing, maintenance, calendar, follow_up).

Usage:
    from app.services.dispatch_logger import DispatchLogger

    logger = DispatchLogger()

    # Log successful dispatch
    await logger.log_dispatch(
        job_type="billing",
        agent_id="uuid-here",
        reference_id="pay_abc123",
        phone="5566999999999",
        notification_type="overdue",
        message_text="Your bill...",
        status="sent",
        metadata={"valor": 150.00, "due_date": "2026-03-01"},
    )

    # Log failure
    await logger.log_failure(
        job_type="billing",
        agent_id="uuid-here",
        reference_id="pay_abc123",
        phone="5566999999999",
        notification_type="overdue",
        error_message="Connection timeout",
    )
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


class DispatchLogger:
    """Centralized logger for notification dispatches."""

    TABLE_NAME = "dispatch_log"

    # Failure reason classification based on error message
    FAILURE_PATTERNS = {
        "timeout": ["timeout", "timed out", "deadline exceeded"],
        "rate_limit": ["429", "rate limit", "too many requests"],
        "not_found": ["404", "not found"],
        "auth_error": ["401", "403", "unauthorized", "forbidden"],
        "network_error": ["network", "connection", "socket", "dns"],
        "invalid_data": ["invalid", "validation", "malformed"],
        "api_error": [],  # Default fallback
    }

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        """Lazy load Supabase service."""
        if self._supabase is None:
            self._supabase = get_supabase_service()
        return self._supabase

    def _classify_failure(self, error_message: str) -> str:
        """
        Classify failure reason based on error message patterns.

        Args:
            error_message: The error message to classify

        Returns:
            Classified failure reason (timeout, rate_limit, etc.)
        """
        if not error_message:
            return "unknown"

        error_lower = error_message.lower()

        for reason, patterns in self.FAILURE_PATTERNS.items():
            for pattern in patterns:
                if pattern in error_lower:
                    return reason

        return "api_error"

    async def log_dispatch(
        self,
        job_type: str,
        agent_id: str,
        reference_id: str,
        phone: str,
        notification_type: str,
        message_text: Optional[str] = None,
        status: str = "sent",
        *,
        reference_table: Optional[str] = None,
        customer_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        days_from_due: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        dispatch_method: str = "whatsapp",
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Log a dispatch (notification sent or attempted).

        Args:
            job_type: Type of job ('billing', 'maintenance', 'follow_up', 'calendar')
            agent_id: UUID of the agent
            reference_id: ID of related record (payment_id, contract_id, etc.)
            phone: Recipient phone number
            notification_type: Type of notification ('reminder', 'due_date', 'overdue', etc.)
            message_text: The message content sent
            status: Dispatch status ('pending', 'sent', 'failed', 'skipped')
            reference_table: Source table name (optional)
            customer_id: Customer ID (optional)
            customer_name: Customer name (optional)
            days_from_due: Days from due date (negative=before, positive=after)
            metadata: Additional job-specific data as dict
            dispatch_method: How it was sent ('whatsapp', 'sms', 'email')
            scheduled_at: When the dispatch was scheduled

        Returns:
            ID of created record or None if failed
        """
        now = datetime.utcnow()
        schedule_time = scheduled_at or now

        record = {
            "job_type": job_type,
            "agent_id": agent_id,
            "reference_id": reference_id,
            "phone": phone,
            "notification_type": notification_type,
            "message_text": message_text,
            "status": status,
            "reference_table": reference_table,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "days_from_due": days_from_due,
            "metadata": metadata or {},
            "dispatch_method": dispatch_method,
            "scheduled_date": schedule_time.strftime("%Y-%m-%d"),  # DATE for unique index
            "scheduled_at": schedule_time.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "attempts_count": 1,
            "last_attempt_at": now.isoformat(),
        }

        # Set sent_at if status is sent
        if status == "sent":
            record["sent_at"] = now.isoformat()

        try:
            result = self.supabase.client.table(self.TABLE_NAME).insert(record).execute()

            if result.data and len(result.data) > 0:
                record_id = result.data[0].get("id")
                logger.info(
                    f"[DISPATCH_LOG] {job_type}/{notification_type} logged: "
                    f"{reference_id} -> {phone[:8]}*** (status={status})"
                )
                return record_id
            return None

        except Exception as e:
            # Check if it's a duplicate violation (unique index)
            error_str = str(e)
            if "unique" in error_str.lower() or "duplicate" in error_str.lower():
                logger.debug(
                    f"[DISPATCH_LOG] Duplicate dispatch skipped: "
                    f"{job_type}/{notification_type} for {reference_id}"
                )
                return None

            logger.error(f"[DISPATCH_LOG] Error logging dispatch: {e}")
            return None

    async def log_failure(
        self,
        job_type: str,
        agent_id: str,
        reference_id: str,
        phone: str,
        notification_type: str,
        error_message: str,
        *,
        message_text: Optional[str] = None,
        reference_table: Optional[str] = None,
        customer_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        days_from_due: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        dispatch_method: str = "whatsapp",
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Log a failed dispatch attempt.

        Args:
            job_type: Type of job ('billing', 'maintenance', 'follow_up', 'calendar')
            agent_id: UUID of the agent
            reference_id: ID of related record
            phone: Recipient phone number
            notification_type: Type of notification
            error_message: Error description
            message_text: The message that failed to send
            reference_table: Source table name (optional)
            customer_id: Customer ID (optional)
            customer_name: Customer name (optional)
            days_from_due: Days from due date
            metadata: Additional job-specific data
            dispatch_method: How it was attempted ('whatsapp', 'sms', 'email')
            scheduled_at: When the dispatch was scheduled

        Returns:
            ID of created record or None if failed
        """
        failure_reason = self._classify_failure(error_message)
        now = datetime.utcnow()
        schedule_time = scheduled_at or now

        record = {
            "job_type": job_type,
            "agent_id": agent_id,
            "reference_id": reference_id,
            "phone": phone,
            "notification_type": notification_type,
            "message_text": message_text,
            "status": "failed",
            "error_message": error_message[:1000] if error_message else None,  # Limit size
            "failure_reason": failure_reason,
            "reference_table": reference_table,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "days_from_due": days_from_due,
            "metadata": metadata or {},
            "dispatch_method": dispatch_method,
            "scheduled_date": schedule_time.strftime("%Y-%m-%d"),  # DATE for unique index
            "scheduled_at": schedule_time.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "attempts_count": 1,
            "last_attempt_at": now.isoformat(),
        }

        try:
            result = self.supabase.client.table(self.TABLE_NAME).insert(record).execute()

            if result.data and len(result.data) > 0:
                record_id = result.data[0].get("id")
                logger.warning(
                    f"[DISPATCH_LOG] {job_type}/{notification_type} FAILED: "
                    f"{reference_id} -> {phone[:8]}*** (reason={failure_reason})"
                )
                return record_id
            return None

        except Exception as e:
            logger.error(f"[DISPATCH_LOG] Error logging failure: {e}")
            return None

    async def check_already_dispatched(
        self,
        agent_id: str,
        job_type: str,
        reference_id: str,
        notification_type: str,
        scheduled_date: Optional[str] = None,
    ) -> bool:
        """
        Check if a dispatch was already sent today (prevents duplicates).

        Uses the unique index to check for existing non-failed dispatches.

        Args:
            agent_id: UUID of the agent
            job_type: Type of job
            reference_id: ID of related record
            notification_type: Type of notification
            scheduled_date: Date to check (defaults to today)

        Returns:
            True if already dispatched today, False otherwise
        """
        if scheduled_date is None:
            scheduled_date = datetime.utcnow().strftime("%Y-%m-%d")

        try:
            result = (
                self.supabase.client.table(self.TABLE_NAME)
                .select("id")
                .eq("agent_id", agent_id)
                .eq("job_type", job_type)
                .eq("reference_id", reference_id)
                .eq("notification_type", notification_type)
                .eq("scheduled_date", scheduled_date)
                .neq("status", "failed")
                .limit(1)
                .execute()
            )

            return bool(result.data and len(result.data) > 0)

        except Exception as e:
            logger.error(f"[DISPATCH_LOG] Error checking duplicate: {e}")
            return False

    async def update_status(
        self,
        dispatch_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Update the status of an existing dispatch record.

        Args:
            dispatch_id: UUID of the dispatch record
            status: New status ('pending', 'sent', 'failed', 'skipped')
            error_message: Error message if status is 'failed'

        Returns:
            True if updated successfully, False otherwise
        """
        now = datetime.utcnow()

        update_data = {
            "status": status,
            "updated_at": now.isoformat(),
            "last_attempt_at": now.isoformat(),
        }

        if status == "sent":
            update_data["sent_at"] = now.isoformat()

        if status == "failed" and error_message:
            update_data["error_message"] = error_message[:1000]
            update_data["failure_reason"] = self._classify_failure(error_message)

        try:
            self.supabase.client.table(self.TABLE_NAME).update(update_data).eq(
                "id", dispatch_id
            ).execute()

            logger.info(f"[DISPATCH_LOG] Updated {dispatch_id} -> status={status}")
            return True

        except Exception as e:
            logger.error(f"[DISPATCH_LOG] Error updating status: {e}")
            return False


# Singleton instance for easy import
_dispatch_logger: Optional[DispatchLogger] = None


def get_dispatch_logger() -> DispatchLogger:
    """Get the singleton DispatchLogger instance."""
    global _dispatch_logger
    if _dispatch_logger is None:
        _dispatch_logger = DispatchLogger()
    return _dispatch_logger
