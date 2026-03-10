"""
Tool Data Flow Service
Handles data passing between tools in the Meeting Intelligence Agent workflow
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class ToolDataFlowService:
    """
    Service to manage data flow between tools in the agent workflow.
    This ensures proper data structure and context passing between tools.
    """

    def __init__(self):
        self.workflow_data = {}
        self.current_step = 0
        self.steps = [
            "calendar_tool",
            "drive_tool", 
            "summarizer_tool",
            "dedup_tool",
            "email_notification_tool"
        ]

    def set_workflow_data(self, data: Dict[str, Any]) -> None:
        """Set the initial workflow data."""
        self.workflow_data = data
        self.current_step = 0
        logger.info(f"Set workflow data with keys: {list(data.keys())}")

    def get_data_for_tool(self, tool_name: str) -> Dict[str, Any]:
        """Get the appropriate data for a specific tool."""
        if tool_name not in self.steps:
            logger.warning(f"Unknown tool: {tool_name}")
            return {}

        # Build data based on the tool and current workflow state
        if tool_name == "calendar_tool":
            return self._get_calendar_data()
        elif tool_name == "drive_tool":
            return self._get_drive_data()
        elif tool_name == "summarizer_tool":
            return self._get_summarizer_data()
        elif tool_name == "dedup_tool":
            return self._get_dedup_data()
        elif tool_name == "email_notification_tool":
            return self._get_email_data()
        
        return {}

    def update_tool_result(self, tool_name: str, result: Any) -> None:
        """Update the workflow data with a tool's result."""
        if tool_name not in self.steps:
            logger.warning(f"Unknown tool: {tool_name}")
            return

        # Parse result if it's a JSON string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON result from {tool_name}")
                result = {"raw_result": result}

        # Store the result with tool-specific key
        tool_key = f"{tool_name}_response"
        self.workflow_data[tool_key] = result
        
        # Update current step
        if tool_name in self.steps:
            self.current_step = self.steps.index(tool_name) + 1
        
        logger.info(f"Updated workflow data with {tool_name} result. Current step: {self.current_step}")

    def _get_calendar_data(self) -> Dict[str, Any]:
        """Get data for calendar tool."""
        return {
            "minutes": self.workflow_data.get("time_window_mins", 480),
            "user_id": self.workflow_data.get("user_id"),
            "org_id": self.workflow_data.get("org_id"),
            "agent_task_id": self.workflow_data.get("agent_task_id")
        }

    def _get_drive_data(self) -> Dict[str, Any]:
        """Get data for drive tool."""
        calendar_result = self.workflow_data.get("calendar_tool_response", {})
        
        return {
            "operation": "find_and_download_transcripts",
            "calendar_events": calendar_result.get("events", []),
            "skip_already_processed": True,
            "user_id": self.workflow_data.get("user_id"),
            "org_id": self.workflow_data.get("org_id"),
            "agent_task_id": self.workflow_data.get("agent_task_id")
        }

    def _get_summarizer_data(self) -> Dict[str, Any]:
        """Get data for summarizer tool."""
        drive_result = self.workflow_data.get("drive_tool_response", {})
        calendar_result = self.workflow_data.get("calendar_tool_response", {})
        
        # Extract transcript content from drive result
        transcript_content = ""
        if isinstance(drive_result, dict):
            transcript_content = drive_result.get("transcript_content", "")
        elif isinstance(drive_result, str):
            try:
                drive_data = json.loads(drive_result)
                transcript_content = drive_data.get("transcript_content", "")
            except json.JSONDecodeError:
                transcript_content = drive_result

        return {
            "transcript_content": transcript_content,
            "meeting_metadata": {
                "events": calendar_result.get("events", []),
                "user_id": self.workflow_data.get("user_id"),
                "org_id": self.workflow_data.get("org_id"),
                "agent_task_id": self.workflow_data.get("agent_task_id")
            }
        }

    def _get_dedup_data(self) -> Dict[str, Any]:
        """Get data for dedup tool."""
        summarizer_result = self.workflow_data.get("summarizer_tool_response", {})
        
        # Convert to JSON string if it's a dictionary (dedup tool expects string)
        if isinstance(summarizer_result, dict):
            summary_data_str = json.dumps(summarizer_result)
        elif isinstance(summarizer_result, str):
            summary_data_str = summarizer_result
        else:
            logger.warning("Unexpected summarizer result type for dedup tool")
            summary_data_str = json.dumps({"raw_result": str(summarizer_result)})

        return {
            "summary_data": summary_data_str,
            "user_id": self.workflow_data.get("user_id"),
            "org_id": self.workflow_data.get("org_id"),
            "agent_task_id": self.workflow_data.get("agent_task_id")
        }

    def _get_email_data(self) -> Dict[str, Any]:
        """Get data for email tool."""
        dedup_result = self.workflow_data.get("dedup_tool_response", {})
        calendar_result = self.workflow_data.get("calendar_tool_response", {})
        summarizer_result = self.workflow_data.get("summarizer_tool_response", {})
        
        # Get recipient scope from database (will be fetched by email tool)
        # We don't set it here since the email tool will fetch from database
        # Get the user's email from calendar events (they are the organizer)
        user_email = None
        events = calendar_result.get("events", [])
        if events:
            # Get the first event's organizer email (this is the user's email)
            first_event = events[0] if events else {}
            organizer_email = first_event.get("organizer") or first_event.get("organizer_email")
            if organizer_email and "@" in organizer_email:
                user_email = organizer_email
                logger.info(f"Extracted user email from calendar events: {user_email}")
            else:
                logger.warning(f"First event does not have organizer email. Event keys: {list(first_event.keys()) if isinstance(first_event, dict) else 'not a dict'}")
        
        email_data = {
            "summary_data": summarizer_result,
            "dedup_data": dedup_result,
            "calendar_metadata": {
                "events": events,
                "user_id": self.workflow_data.get("user_id"),
                "org_id": self.workflow_data.get("org_id"),
                "agent_task_id": self.workflow_data.get("agent_task_id"),
                "organizer_email": user_email,  # Add user's actual email from calendar
                "user_email": user_email
            }
        }

        return email_data

    def get_workflow_summary(self) -> Dict[str, Any]:
        """Get a summary of the current workflow state."""
        return {
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "current_tool": self.steps[self.current_step] if self.current_step < len(self.steps) else "completed",
            "completed_tools": self.steps[:self.current_step],
            "workflow_data_keys": list(self.workflow_data.keys()),
            "timestamp": datetime.now().isoformat()
        }


# Global instance
_data_flow_service = None

def get_tool_data_flow_service() -> ToolDataFlowService:
    """Get the global tool data flow service instance."""
    global _data_flow_service
    if _data_flow_service is None:
        _data_flow_service = ToolDataFlowService()
    return _data_flow_service
