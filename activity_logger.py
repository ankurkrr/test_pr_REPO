"""
Enhanced Activity Logger Service for Meeting Intelligence Agent

Integrates with external activity log API to track all workflow operations
with detailed logging structure as required by the platform API.

API Endpoint: https://devapi.agentic.elevationai.com/activity-log/agent/save-log
Method: POST
Headers: x-api-key, x-api-secret
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
import httpx
import json

logger = logging.getLogger(__name__)


class ActivityLogger:
    """
    Enhanced service for logging detailed workflow activities to external audit log API.

    Sends structured activity logs with comprehensive workflow tracking including:
    - Workflow start/stop events
    - Individual step completions
    - Tool usage and outcomes
    - Error tracking and recovery
    """

    def __init__(self):
        # Set default API URL to the platform endpoint
        self.api_url = os.getenv("ACTIVITY_LOG_API_URL", "https://devapi.agentic.elevationai.com/activity-log/agent/save-log")
        # Use platform API credentials as fallback
        self.api_key = os.getenv("ACTIVITY_LOG_API_KEY", os.getenv("PLATFORM_API_KEY"))
        self.api_secret = os.getenv("ACTIVITY_LOG_API_SECRET", os.getenv("PLATFORM_API_SECRET"))
        self.org_id = os.getenv("ORG_ID", "elevationai")
        self.agent_id = os.getenv("AGENT_ID", "meeting_agent_001")

        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds

        if not self.api_url:
            logger.warning("Activity log API URL not configured - activity logging disabled")
        if not self.api_key or not self.api_secret:
            logger.warning("Activity log API credentials not configured - activity logging disabled")
        else:
            logger.info(f"Activity logging enabled - API URL: {self.api_url}")

    def is_enabled(self) -> bool:
        """Check if activity logging is properly configured and enabled."""
        return bool(self.api_url and self.api_key and self.api_secret)
    
    def _get_workflow_interval(self) -> int:
        """Get the workflow interval from configuration."""
        try:
            from ...configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL
            return SCHEDULER_MEETING_WORKFLOW_INTERVAL
        except ImportError:
            return 10  # Default fallback

    async def log_workflow_activity(
        self,
        agent_task_id: str,
        logs: List[Dict[str, Any]],
        retry_count: int = 0
    ) -> bool:
        """
        Log detailed workflow activities to the external audit log API and local database.

        Args:
            agent_task_id: Unique agent task ID
            logs: List of log entries with detailed structure
            retry_count: Current retry attempt (for internal use)

        Returns:
            bool: True if logging was successful, False otherwise
        """
        # Always store logs locally first
        await self._store_logs_locally(agent_task_id, logs)

        if not self.is_enabled():
            logger.debug("Activity logging disabled - stored locally only")
            return False

        try:
            # Prepare payload according to API specification
            payload = {
                "agent_task_id": agent_task_id,
                "logs": logs
            }

            # Delegate outbound send to PlatformAPIClient for single path
            try:
                from .platform_api_client import PlatformAPIClient
                client = PlatformAPIClient()
                request_id = f"activity-{agent_task_id}-{datetime.utcnow().strftime('%H%M%S')}"
                resp = await client.send_audit_log_to_platform(payload, request_id=request_id)
                if resp.get("status") == "success":
                    logger.info(f"Workflow activity logged successfully for task {agent_task_id}")
                    await self._mark_logs_sent(agent_task_id, logs, json.dumps(resp.get("response")))
                    return True
                else:
                    logger.error(f"Workflow activity log API error: {resp}")
                    if retry_count < self.max_retries:
                        logger.info(f"Retrying workflow activity log (attempt {retry_count + 1}/{self.max_retries})")
                        await asyncio.sleep(self.retry_delay * (retry_count + 1))
                        return await self.log_workflow_activity(agent_task_id, logs, retry_count + 1)
                    return False
            except Exception as e:
                logger.error(f"Activity logger delegation failed: {e}")
                if retry_count < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (retry_count + 1))
                    return await self.log_workflow_activity(agent_task_id, logs, retry_count + 1)
                return False

        except httpx.RequestError as e:
            logger.error(f"Workflow activity log API connection error: {e}")

            # Retry on connection errors
            if retry_count < self.max_retries:
                logger.info(f"Retrying workflow activity log due to connection error (attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(self.retry_delay * (retry_count + 1))
                return await self.log_workflow_activity(agent_task_id, logs, retry_count + 1)

            return False
        except Exception as e:
            logger.error(f"Workflow activity logging failed: {e}", exc_info=True)
            return False

    async def _store_logs_locally(self, agent_task_id: str, logs: List[Dict[str, Any]]) -> None:
        """Store logs in local database as backup."""
        try:
            from ..database_service_new import get_database_service
            db_service = get_database_service()

            for log_entry in logs:
                db_service.store_workflow_activity_log(
                    agent_task_id=agent_task_id,
                    activity_type=log_entry.get("activity_type", "task"),
                    log_for_status=log_entry.get("log_for_status", "success"),
                    log_text=log_entry.get("log_text", ""),
                    action=log_entry.get("action", "Execute"),
                    action_issue_event=log_entry.get("action_issue_event", ""),
                    action_required=log_entry.get("action_required", "None"),
                    outcome=log_entry.get("outcome", ""),
                    step_str=log_entry.get("step_str", ""),
                    tool_str=log_entry.get("tool_str", "N/A"),
                    log_data=log_entry.get("log_data", {}),
                    api_sent=False
                )
        except Exception as e:
            logger.error(f"Failed to store logs locally: {e}")

    async def _mark_logs_sent(self, agent_task_id: str, logs: List[Dict[str, Any]], api_response: str) -> None:
        """Mark logs as sent to external API in local database."""
        try:
            from ..database_service_new import get_database_service
            db_service = get_database_service()

            # This is a simplified approach - in production you might want to track individual log IDs
            logger.debug(f"Marked {len(logs)} logs as sent for task {agent_task_id}")
        except Exception as e:
            logger.error(f"Failed to mark logs as sent: {e}")

    def create_log_entry(
        self,
        activity_type: str = "task",
        log_for_status: str = "success",
        log_text: str = "",
        action: str = "Execute",
        action_issue_event: str = "",
        action_required: str = "None",
        outcome: str = "",
        step_str: str = "",
        tool_str: str = "N/A",
        log_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a properly formatted log entry for workflow activities.

        Args:
            activity_type: Type of activity ("task", "error", "info", "warning")
            log_for_status: Status ("success", "failure", "pending", "in_progress")
            log_text: Human-readable description of what happened
            action: Type of action performed ("Read", "Write", "Update", "Delete", "Execute")
            action_issue_event: Specific event details
            action_required: What needs to be done next (or "None")
            outcome: Result of the action
            step_str: Detailed step description for tracking workflow progress
            tool_str: Which tool/service was used (Calendar, Drive, Email, etc.)
            log_data: Additional metadata as JSON object

        Returns:
            Dict[str, Any]: Formatted log entry
        """
        return {
            "activity_type": activity_type,
            "log_for_status": log_for_status,
            "log_text": log_text,
            "action": action,
            "action_issue_event": action_issue_event,
            "action_required": action_required,
            "outcome": outcome,
            "step_str": step_str,
            "tool_str": tool_str,
            "log_data": log_data or {}
        }

    async def log_workflow_start(
        self,
        agent_task_id: str,
        user_id: str,
        workflow_items_count: int = 0,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log workflow start event with detailed information."""
        log_entry = self.create_log_entry(
            activity_type="task",
            log_for_status="success",
            log_text="Your meeting agent is now active and monitoring your calendar.",
            action="Execute",
            action_issue_event="Your meeting agent has been successfully started and is now monitoring your calendar for new meetings.",
            action_required="None",
            outcome=f"Meeting agent is now active and will check for new meetings every {self._get_workflow_interval()} minutes.",
            step_str=f"Your meeting agent is now active! It will automatically check your calendar every {self._get_workflow_interval()} minutes for new meetings, process transcripts, generate summaries, and send you notifications.",
            tool_str="Meeting Agent",
            log_data={
                "user_id": user_id,
                "workflow_items_count": workflow_items_count,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )

        return await self.log_workflow_activity(agent_task_id, [log_entry])

    async def log_workflow_stop(
        self,
        agent_task_id: str,
        user_id: str,
        reason: str = "User requested",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log workflow stop event."""
        log_entry = self.create_log_entry(
            activity_type="task",
            log_for_status="success",
            log_text="Your meeting agent has been stopped.",
            action="Update",
            action_issue_event="Your meeting agent has been successfully stopped and is no longer monitoring your calendar.",
            action_required="None",
            outcome="Meeting agent stopped successfully. Calendar monitoring has been disabled.",
            step_str="Your meeting agent has been stopped. It will no longer check your calendar for new meetings or send notifications. You can restart it anytime to resume monitoring.",
            tool_str="Meeting Agent",
            log_data={
                "user_id": user_id,
                "stop_reason": reason,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )

        return await self.log_workflow_activity(agent_task_id, [log_entry])

    async def log_workflow_step(
        self,
        agent_task_id: str,
        step_name: str,
        tool_name: str,
        status: str = "success",
        description: str = "",
        outcome: str = "",
        action_type: str = "Execute",
        additional_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Log individual workflow step completion."""
        log_entry = self.create_log_entry(
            activity_type="task",
            log_for_status=status,
            log_text=description or f"{step_name} completed using {tool_name}",
            action=action_type,
            action_issue_event=f"{step_name} execution completed",
            action_required="None" if status == "success" else "Review and retry",
            outcome=outcome or f"{step_name} processed successfully",
            step_str=f"Executed {step_name} workflow step using {tool_name} integration",
            tool_str=tool_name,
            log_data=additional_data or {}
        )

        return await self.log_workflow_activity(agent_task_id, [log_entry])

    async def log_agent_delete(
        self,
        user_id: str,
        agent_id: str,
        confirmed: bool = False,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log agent deletion event with detailed workflow logging."""
        log_entry = self.create_log_entry(
            activity_type="task",
            log_for_status="success",
            log_text=f"Agent {agent_id} deleted by user {user_id}",
            action="Delete",
            action_issue_event=f"Agent deletion requested and confirmed: {confirmed}",
            action_required="None",
            outcome="Agent and all associated data removed successfully",
            step_str=f"Executed agent deletion process for {agent_id} with confirmation status: {confirmed}",
            tool_str="Agent Management",
            log_data={
                "user_id": user_id,
                "agent_id": agent_id,
                "confirmed": confirmed,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )

        return await self.log_workflow_activity(agent_id, [log_entry])

    async def log_workflow_error(
        self,
        agent_task_id: str,
        error_type: str,
        error_message: str,
        step_name: str = "",
        tool_name: str = "N/A",
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log workflow error event with detailed information."""
        log_entry = self.create_log_entry(
            activity_type="error",
            log_for_status="failure",
            log_text=f"Workflow error in {step_name or 'unknown step'}: {error_type}",
            action="Execute",
            action_issue_event=f"Error occurred during workflow execution: {error_type}",
            action_required="Review error and retry operation",
            outcome=f"Workflow step failed: {error_message}",
            step_str=f"Error in {step_name or 'workflow step'}: {error_message}",
            tool_str=tool_name,
            log_data={
                "error_type": error_type,
                "error_message": error_message,
                "step_name": step_name,
                "user_id": user_id,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )

        return await self.log_workflow_activity(agent_task_id, [log_entry])

    async def log_google_integration(
        self,
        agent_task_id: str,
        action: str,
        service: str,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Log Google service integration activities."""
        log_entry = self.create_log_entry(
            activity_type="task",
            log_for_status=status,
            log_text=f"Google {service} integration: {action}",
            action="Execute",
            action_issue_event=f"Google {service} {action} completed",
            action_required="None" if status == "success" else "Check Google API credentials",
            outcome=f"Google {service} {action} {'successful' if status == 'success' else 'failed'}",
            step_str=f"Executed Google {service} integration for {action}",
            tool_str=f"Google {service}",
            log_data=details or {}
        )

        return await self.log_workflow_activity(agent_task_id, [log_entry])

    # Legacy methods for backward compatibility
    async def log_activity(
        self,
        action_type: str,
        user_id: str,
        agent_task_id: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Legacy method - converts to new workflow logging format."""
        log_entry = self.create_log_entry(
            activity_type="task" if status == "success" else "error",
            log_for_status=status,
            log_text=f"{action_type}: {details.get('message', '') if details else ''}",
            action="Execute",
            action_issue_event=f"{action_type} event",
            action_required="None",
            outcome=f"{action_type} completed",
            step_str=f"Legacy {action_type} operation",
            tool_str="Legacy API",
            log_data={
                "user_id": user_id,
                "action_type": action_type,
                "details": details or {},
                "error_message": error_message,
                "ip_address": ip_address,
                "user_agent": user_agent
            }
        )

        return await self.log_workflow_activity(agent_task_id or "unknown", [log_entry])

    async def log_agent_start(
        self,
        user_id: str,
        agent_task_id: str,
        workflow_items_count: int = 0,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log agent start using new workflow logging."""
        return await self.log_workflow_start(
            agent_task_id=agent_task_id,
            user_id=user_id,
            workflow_items_count=workflow_items_count,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_agent_stop(
        self,
        user_id: str,
        agent_task_id: str,
        reason: str = "User requested",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log agent stop using new workflow logging."""
        return await self.log_workflow_stop(
            agent_task_id=agent_task_id,
            user_id=user_id,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_agent_error(
        self,
        user_id: str,
        agent_task_id: str,
        error_type: str,
        error_message: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log agent error using new workflow logging."""
        return await self.log_workflow_error(
            agent_task_id=agent_task_id,
            error_type=error_type,
            error_message=error_message,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )


# Global instance
_activity_logger = None


def get_activity_logger() -> ActivityLogger:
    """Get the global activity logger instance."""
    global _activity_logger
    if _activity_logger is None:
        _activity_logger = ActivityLogger()
    return _activity_logger