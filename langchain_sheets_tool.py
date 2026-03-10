"""LangChain Sheets Tool for autonomous meeting intelligence."""

import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

# Import the sheets service
from src.services.google import GoogleSheetsService
# Import tool configs and categories
from src.constants.app import AVAILABLE_TOOLS

logger = logging.getLogger(__name__)


class LangchainSheetsTool(BaseTool):
    """
    LangChain tool for Google Sheets operations.

    This tool allows the agent to:
    - Create and manage Google Sheets
    - Add meeting tasks and data to sheets
    - Update existing sheet data
    - Retrieve sheet information
    - Manage meeting task tracking
    """

    name: str = "sheets_tool"
    description: str = "Manage Google Sheets for meeting tasks and data tracking"
    category: str = "SHEETS"

    # Declare these as proper Pydantic fields
    auth: Optional[Any] = None
    user_id: Optional[str] = None
    sheets_service: Optional[Any] = None

    def __init__(self, auth=None, user_id=None):
        super().__init__(auth=auth, user_id=user_id)
        try:
            self.sheets_service = GoogleSheetsService(auth)
            logger.info("GoogleSheetsService initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize GoogleSheetsService: %s", e)
            self.sheets_service = None

    def _run(
        self,
        query: str,
        *args,
        **kwargs,
    ) -> str:
        """Execute sheets operations."""
        try:
            lower_q = query.lower()

            if "create sheet" in lower_q or "new sheet" in lower_q:
                return self._create_sheet(query)
            elif "add task" in lower_q or "add meeting task" in lower_q:
                return self._add_meeting_task(query)
            elif "get sheet" in lower_q or "sheet info" in lower_q:
                return self._get_sheet_info(query)
            else:
                return self._add_meeting_task(query)  # Default operation

        except Exception as e:
            logger.error("Sheets tool encountered error: %s", e)
            return json.dumps({
                "status": "error",
                "message": f"Error in sheets operation: {str(e)}",
                "timestamp": datetime.now().isoformat()
            })

    def _create_sheet(self, query: str) -> str:
        """Create a new Google Sheet."""
        try:
            if not self.sheets_service:
                return json.dumps({
                    "status": "error",
                    "message": "Sheets service not available",
                    "timestamp": datetime.now().isoformat()
                })

            # Extract sheet title from query
            sheet_title = "Meeting Tasks Sheet"
            if "title:" in query:
                title_part = query.split("title:")[1]
                sheet_title = title_part.split()[0].strip().strip('"\'')

            # Create the sheet
            sheet_id = self.sheets_service.create_meeting_tasks_sheet(sheet_title)

            if sheet_id:
                return json.dumps({
                    "status": "success",
                    "message": f"Sheet '{sheet_title}' created successfully",
                    "sheet_id": sheet_id,
                    "sheet_title": sheet_title,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return json.dumps({
                    "status": "error",
                    "message": "Failed to create sheet",
                    "timestamp": datetime.now().isoformat()
                })

        except Exception as e:
            logger.error("Error creating sheet: %s", e)
            return json.dumps({
                "status": "error",
                "message": f"Error creating sheet: {str(e)}",
                "timestamp": datetime.now().isoformat()
            })

    def _add_meeting_task(self, query: str) -> str:
        """Add a meeting task to the sheet."""
        try:
            if not self.sheets_service:
                return json.dumps({
                    "status": "error",
                    "message": "Sheets service not available",
                    "timestamp": datetime.now().isoformat()
                })

            # Extract task information from query
            task_data = self._parse_task_data(query)

            # Add the task to the sheet
            result = self.sheets_service.append_task(task_data)

            if result:
                return json.dumps({
                    "status": "success",
                    "message": "Meeting task added successfully",
                    "task_data": task_data,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return json.dumps({
                    "status": "error",
                    "message": "Failed to add meeting task",
                    "timestamp": datetime.now().isoformat()
                })

        except Exception as e:
            logger.error("Error adding meeting task: %s", e)
            return json.dumps({
                "status": "error",
                "message": f"Error adding meeting task: {str(e)}",
                "timestamp": datetime.now().isoformat()
            })


    def _get_sheet_info(self, query: str) -> str:
        """Get information about the meeting tasks sheet."""
        try:
            if not self.sheets_service:
                return json.dumps({
                    "status": "error",
                    "message": "Sheets service not available",
                    "timestamp": datetime.now().isoformat()
                })

            # Get sheet information
            sheet_id = self.sheets_service.get_meeting_tasks_sheet_id()
            sheet_url = self.sheets_service.get_sheet_url()
            sheet_info = {
                "sheet_id": sheet_id,
                "sheet_url": sheet_url
            }

            return json.dumps({
                "status": "success",
                "message": "Sheet information retrieved successfully",
                "sheet_info": sheet_info,
                "timestamp": datetime.now().isoformat()
            })

        except Exception as e:
            logger.error("Error getting sheet info: %s", e)
            return json.dumps({
                "status": "error",
                "message": f"Error getting sheet info: {str(e)}",
                "timestamp": datetime.now().isoformat()
            })

    def _parse_task_data(self, query: str) -> Dict[str, Any]:
        """Parse task data from query string."""
        task_data = {
            "task": "Sample meeting task",
            "assignee": "Unknown",
            "due_date": datetime.now().strftime("%Y-%m-%d"),
            "priority": "Medium",
            "status": "Open",
            "meeting_title": "Sample Meeting",
            "meeting_date": datetime.now().strftime("%Y-%m-%d")
        }

        # Extract task information from query
        if "task:" in query:
            task_part = query.split("task:")[1]
            if "assignee:" in task_part:
                task_data["task"] = task_part.split("assignee:")[0].strip().strip('"\'')
            else:
                task_data["task"] = task_part.strip().strip('"\'')

        if "assignee:" in query:
            assignee_part = query.split("assignee:")[1]
            if "due_date:" in assignee_part:
                task_data["assignee"] = assignee_part.split("due_date:")[0].strip().strip('"\'')
            else:
                task_data["assignee"] = assignee_part.strip().strip('"\'')

        if "due_date:" in query:
            due_date_part = query.split("due_date:")[1]
            if "priority:" in due_date_part:
                task_data["due_date"] = due_date_part.split("priority:")[0].strip().strip('"\'')
            else:
                task_data["due_date"] = due_date_part.strip().strip('"\'')

        if "priority:" in query:
            priority_part = query.split("priority:")[1]
            if "status:" in priority_part:
                task_data["priority"] = priority_part.split("status:")[0].strip().strip('"\'')
            else:
                task_data["priority"] = priority_part.strip().strip('"\'')

        if "status:" in query:
            status_part = query.split("status:")[1]
            task_data["status"] = status_part.strip().strip('"\'')

        if "meeting_title:" in query:
            meeting_title_part = query.split("meeting_title:")[1]
            if "meeting_date:" in meeting_title_part:
                task_data["meeting_title"] = meeting_title_part.split("meeting_date:")[0].strip().strip('"\'')
            else:
                task_data["meeting_title"] = meeting_title_part.strip().strip('"\'')

        if "meeting_date:" in query:
            meeting_date_part = query.split("meeting_date:")[1]
            task_data["meeting_date"] = meeting_date_part.strip().strip('"\'')

        return task_data