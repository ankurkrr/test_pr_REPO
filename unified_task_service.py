"""
Unified Task Service
Handles both Google Sheets storage and Platform webhook with the same deduplicated tasks
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import httpx
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..database_service_new import get_database_service
from ...auth.google_auth_handler import GoogleAuthHandler
from ...security.data_encryption import get_audit_logger

logger = logging.getLogger(__name__)


class UnifiedTaskService:
    """
    Unified service that handles task deduplication, Google Sheets storage, and Platform webhook
    with the same payload structure.
    """

    def __init__(self, user_id: str, org_id: str, agent_task_id: str, google_auth: GoogleAuthHandler = None):
        self.user_id = user_id
        self.org_id = org_id
        self.agent_task_id = agent_task_id
        self.google_auth = google_auth or GoogleAuthHandler(user_id, org_id, agent_task_id)

        # Configuration (defaults to dev platform webhook if not provided via env)
        self.platform_webhook_url = (
            os.getenv("TASK_MGMT_WEBHOOK_URL")
            or os.getenv("PLATFORM_TASK_WEBHOOK_URL")
            or "https://devapi.agentic.elevationai.com/task-mgmt/save-from-agent"
        )
        # Prefer dedicated task API credentials, fallback to general platform creds
        self.platform_api_key = os.getenv("PLATFORM_TASK_API_KEY") or os.getenv("PLATFORM_API_KEY") or os.getenv("API_KEY")
        self.platform_api_secret = os.getenv("PLATFORM_TASK_API_SECRET") or os.getenv("PLATFORM_API_SECRET") or os.getenv("API_SECRET")

        # Services
        self.db_service = get_database_service()
        self.audit_logger = get_audit_logger()

        logger.info(f"UnifiedTaskService initialized for {user_id}/{org_id}/{agent_task_id}")

    async def process_and_distribute_tasks(
        self,
        meeting_data: Dict[str, Any],
        raw_tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Main method: Process tasks, deduplicate, and send to both Sheets and Platform

        Args:
            meeting_data: Meeting metadata (title, attendees, etc.)
            raw_tasks: Raw tasks extracted from meeting

        Returns:
            Dict with processing results for both destinations
        """
        try:
            # Step 1: Deduplicate tasks
            deduplicated_tasks = await self._deduplicate_tasks(raw_tasks, meeting_data)

            # Step 2: Prepare unified payload
            unified_payload = self._create_unified_payload(meeting_data, deduplicated_tasks)

            # Step 3: Send to both destinations in parallel
            results = await self._distribute_tasks_parallel(unified_payload, deduplicated_tasks)

            # Step 4: Log results
            await self._log_distribution_results(results)

            return {
                "success": True,
                "message": "Tasks processed and distributed successfully",
                "deduplicated_count": len(deduplicated_tasks),
                "original_count": len(raw_tasks),
                "results": results,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to process and distribute tasks: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    async def _deduplicate_tasks(self, raw_tasks: List[Dict[str, Any]], meeting_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Deduplicate tasks using semantic similarity and existing task hashes
        """
        try:
            # Get existing tasks from database for comparison
            existing_tasks = await self._get_existing_tasks()

            deduplicated = []
            for task in raw_tasks:
                # Create task hash for deduplication
                task_hash = self._generate_task_hash(task)

                # Check if task already exists
                is_duplicate = await self._is_duplicate_task(task, existing_tasks)

                if not is_duplicate:
                    # Use meeting_title from task if available, otherwise use meeting_data
                    task_meeting_title = task.get("meeting_title", meeting_data.get("title", "Unknown Meeting"))
                    if task_meeting_title == "Unknown Meeting" and meeting_data.get("title", "Unknown Meeting") != "Unknown Meeting":
                        task_meeting_title = meeting_data.get("title", "Unknown Meeting")
                    
                    # Extract assignee_name - ensure it's properly extracted
                    assignee_name = task.get("assignee_name", "")
                    if not assignee_name and task.get("assignee"):
                        assignee_name = task.get("assignee")
                    elif not assignee_name and task.get("assignees"):
                        if isinstance(task.get("assignees"), list):
                            assignee_name = ", ".join([str(a) for a in task.get("assignees") if a])
                        else:
                            assignee_name = str(task.get("assignees"))
                    
                    # Add to deduplicated list
                    processed_task = {
                        "id": str(uuid.uuid4()),
                        "task_id": str(uuid.uuid4()),
                        "task_hash": task_hash,
                        "title": task.get("title", ""),
                        "description": task.get("description", task.get("title", "")),
                        "assignee_name": assignee_name,
                        "priority": self._normalize_priority(task.get("priority", "medium")),
                        "status": self._normalize_status(task.get("status", "todo")),
                        "due_date": task.get("due_date", ""),
                        "meeting_title": task_meeting_title,
                        "created_at": datetime.now().isoformat(),
                        "decision": "ADDED"
                    }
                    deduplicated.append(processed_task)
                else:
                    logger.info(f"Duplicate task skipped: {task.get('title', '')[:50]}...")

            logger.info(f"Deduplication complete: {len(deduplicated)} unique tasks from {len(raw_tasks)} raw tasks")
            return deduplicated

        except Exception as e:
            logger.error(f"Failed to deduplicate tasks: {e}")
            return raw_tasks  # Return original if deduplication fails

    def _create_unified_payload(self, meeting_data: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create payload matching the platform schema requested by the client.

        Format:
        {
          "agent_task_id": str,
          "meeting_details": {
            "id": str,
            "event_name": str,
            "video_url": str,
            "transcript_url": str
          },
          "tasks": [
            {
              "title": str,
              "description": str,
              "expected_outcome": str,
              "assignee_name": str,
              "priority": str,
              "task_status": str,
              "end_date": str,
              "sub_tasks": [ ... ]
            }
          ]
        }
        """

        # Map internal task keys to platform-required keys
        mapped_tasks: List[Dict[str, Any]] = []
        for t in tasks:
            # Map main task
            mapped_task = {
                "title": t.get("title") or t.get("task_text") or t.get("description", ""),
                "description": t.get("description") or t.get("task_text", ""),
                "expected_outcome": t.get("expected_outcome", ""),
                "assignee_name": t.get("assignee_name", ""),
                "priority": t.get("priority") or t.get("priority_level", "medium"),
                "task_status": t.get("task_status") or t.get("status", "todo"),
                "end_date": t.get("end_date") or t.get("due_date", ""),
                "sub_tasks": []
            }
            
            # Map subtasks if they exist
            sub_tasks = t.get("sub_tasks", [])
            if sub_tasks:
                for sub_task in sub_tasks:
                    mapped_sub_task = {
                        "title": sub_task.get("title") or sub_task.get("task_text") or sub_task.get("description", ""),
                        "description": sub_task.get("description") or sub_task.get("task_text", ""),
                        "expected_outcome": sub_task.get("expected_outcome", ""),
                        "assignee_name": sub_task.get("assignee_name", ""),
                        "priority": sub_task.get("priority") or sub_task.get("priority_level", "medium"),
                        "task_status": sub_task.get("task_status") or sub_task.get("status", "todo"),
                        "end_date": sub_task.get("end_date") or sub_task.get("due_date", "")
                    }
                    mapped_task["sub_tasks"].append(mapped_sub_task)
            
            mapped_tasks.append(mapped_task)

        return {
            "agent_task_id": self.agent_task_id,
            "meeting_details": {
                "id": meeting_data.get("id", f"M-{datetime.now().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}"),
                "event_name": meeting_data.get("event_name") or meeting_data.get("title", "Weekly Sync"),
                "video_url": meeting_data.get("video_url", ""),
                "transcript_url": meeting_data.get("transcript_url", "")
            },
            "tasks": mapped_tasks
        }

    async def _distribute_tasks_parallel(self, payload: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send tasks to both Google Sheets and Platform webhook in parallel
        """
        import asyncio

        # Create parallel tasks
        sheets_task = asyncio.create_task(self._send_to_google_sheets(payload, tasks))
        platform_task = asyncio.create_task(self._send_to_platform_webhook(payload))

        # Wait for both to complete
        sheets_result, platform_result = await asyncio.gather(
            sheets_task, platform_task, return_exceptions=True
        )

        return {
            "google_sheets": sheets_result if not isinstance(sheets_result, Exception) else {"error": str(sheets_result)},
            "platform_webhook": platform_result if not isinstance(platform_result, Exception) else {"error": str(platform_result)}
        }

    async def _send_to_google_sheets(self, payload: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send tasks to Google Sheets
        """
        try:
            # Get Google Sheets service
            sheets_service = self.google_auth.get_sheets_service()
            if not sheets_service:
                return {"success": False, "error": "Google Sheets service not available"}

            # Get sheet ID
            sheet_id = self._get_sheet_id()
            if not sheet_id:
                return {"success": False, "error": "Google Sheet ID not found"}

            # Prepare rows for Google Sheets (aligned with headers: Task ID, Task Text, Meeting Title, Assignees, Priority Level, Due Date, Status, Created Date)
            rows = []
            for task in tasks:
                row = [
                    task["task_id"],                    # Column A: Task ID
                    task["title"],                     # Column B: Task Text (using title as task text)
                    task["meeting_title"],             # Column C: Meeting Title
                    task["assignee_name"],             # Column D: Assignees
                    task["priority"],                  # Column E: Priority Level
                    task["due_date"],                  # Column F: Due Date
                    task["status"],                    # Column G: Status
                    task["created_at"],                # Column H: Created Date
                ]
                rows.append(row)

            # Append to sheet
            sheets_service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range="A:H",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows}
            ).execute()

            logger.info(f"Successfully sent {len(tasks)} tasks to Google Sheets")
            return {
                "success": True,
                "tasks_sent": len(tasks),
                "sheet_id": sheet_id,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to send tasks to Google Sheets: {e}")
            return {"success": False, "error": str(e)}

    async def _send_to_platform_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send tasks to Platform webhook (optional - doesn't fail workflow if endpoint doesn't exist)
        """
        try:
            if not self.platform_webhook_url:
                return {"success": False, "error": "Platform webhook URL not configured"}

            # Prepare headers: ONLY Content-Type, x-api-key, x-api-secret
            headers = {
                "Content-Type": "application/json",
            }
            if self.platform_api_key:
                headers["x-api-key"] = self.platform_api_key
            if self.platform_api_secret:
                headers["x-api-secret"] = self.platform_api_secret

            # Log the request details for debugging
            logger.info(f"Sending to platform webhook: {self.platform_webhook_url}")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")
            logger.info(f"Headers: {headers}")
            
            # Send webhook
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.platform_webhook_url,
                    json=payload,
                    headers=headers
                )
                logger.info(f"Platform webhook response status: {response.status_code}")
                logger.info(f"Platform webhook response body: {response.text[:500]}")
                
                # Handle 404 gracefully - endpoint might not exist yet
                if response.status_code == 404:
                    logger.warning(f"Platform webhook endpoint not found (404): {self.platform_webhook_url}")
                    return {
                        "success": False,
                        "error": "Platform webhook endpoint not found (404)",
                        "webhook_url": self.platform_webhook_url,
                        "response_status": 404,
                        "timestamp": datetime.now().isoformat()
                    }
                
                response.raise_for_status()

            logger.info(f"Successfully sent tasks to platform webhook: {self.platform_webhook_url}")
            
            # Send friendly audit log to platform
            try:
                from .platform_api_client import PlatformAPIClient
                import asyncio
                
                platform_client = PlatformAPIClient()
                platform_client.send_simple_log_sync(
                    agent_task_id=self.agent_task_id,
                    log_text=f"{len(payload['tasks'])} task(s) added to platform.",
                    activity_type="task",
                    log_for_status="success",
                    action="Create",
                    action_issue_event=f"{len(payload['tasks'])} task(s) have been successfully added to your task management system, making it easy to track progress and follow up on action items.",
                    action_required="None",
                    outcome="All meeting tasks synchronized with platform task management system.",
                    step_str=f"Successfully sent {len(payload['tasks'])} task(s) to the platform. All tasks have been deduplicated and are now available in your task management system.",
                    tool_str="Platform API",
                    log_data={
                        "user_id": self.user_id,
                        "org_id": self.org_id,
                        "tasks_sent": len(payload["tasks"]),
                        "webhook_url": self.platform_webhook_url
                    }
                )
                logger.info(f"Sent friendly audit log: tasks sent to platform for user {self.user_id}")
            except Exception as audit_error:
                logger.warning(f"Failed to send audit log: {audit_error}")
            
            return {
                "success": True,
                "tasks_sent": len(payload["tasks"]),
                "webhook_url": self.platform_webhook_url,
                "response_status": response.status_code,
                "timestamp": datetime.now().isoformat()
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Platform webhook endpoint not found (404): {self.platform_webhook_url}")
                return {
                    "success": False,
                    "error": "Platform webhook endpoint not found (404)",
                    "webhook_url": self.platform_webhook_url,
                    "response_status": 404,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.error(f"Platform webhook HTTP error {e.response.status_code}: {e}")
                return {"success": False, "error": f"HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.error(f"Failed to send tasks to platform webhook: {e}")
            return {"success": False, "error": str(e)}

    def _get_sheet_id(self) -> Optional[str]:
        """Get Google Sheet ID from user_agent_task"""
        try:
            # Query user_agent_task for sheets_id
            query = """
            SELECT sheets_id 
            FROM user_agent_task 
            WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
            AND sheets_id IS NOT NULL AND sheets_id != ''
            ORDER BY updated DESC
            LIMIT 1
            """
            rows = self.db_service.execute_query(query, {
                'user_id': self.user_id,
                'org_id': self.org_id, 
                'agent_task_id': self.agent_task_id
            })
            
            if rows and len(rows) > 0:
                # Handle SQLAlchemy Row objects, tuples, and dict row formats
                row = rows[0]
                if hasattr(row, '_asdict'):  # SQLAlchemy Row object
                    sheet_id = row[0]  # Access by index
                elif isinstance(row, (list, tuple)):
                    sheet_id = row[0]  # First column is sheets_id
                else:
                    sheet_id = row.get('sheets_id')
                logger.info(f"Loaded sheet_id from user_agent_task: {sheet_id}")
                return sheet_id
            else:
                logger.warning("No sheets_id found in user_agent_task")
                return None
        except Exception as e:
            logger.error(f"Failed to get sheet ID from user_agent_task: {e}")
            return None

    def _generate_task_hash(self, task: Dict[str, Any]) -> str:
        """Generate hash for task deduplication"""
        import hashlib

        # Normalize task text for consistent hashing
        task_text = task.get("title", "") + " " + task.get("description", "")
        normalized_text = task_text.lower().strip()
        normalized_text = ' '.join(normalized_text.split())

        return hashlib.sha256(normalized_text.encode()).hexdigest()[:16]

    async def _get_existing_tasks(self) -> List[Dict[str, Any]]:
        """Get existing tasks from database for deduplication"""
        try:
            # This would query the database for existing tasks
            # For now, return empty list (you can implement this based on your DB schema)
            return []
        except Exception as e:
            logger.error(f"Failed to get existing tasks: {e}")
            return []

    async def _is_duplicate_task(self, task: Dict[str, Any], existing_tasks: List[Dict[str, Any]]) -> bool:
        """Check if task is duplicate using semantic similarity"""
        try:
            from difflib import SequenceMatcher

            task_text = task.get("title", "") + " " + task.get("description", "")
            normalized_text = task_text.lower().strip()

            for existing_task in existing_tasks:
                existing_text = existing_task.get("title", "") + " " + existing_task.get("description", "")
                existing_normalized = existing_text.lower().strip()

                # Calculate similarity
                similarity = SequenceMatcher(None, normalized_text, existing_normalized).ratio()

                # Consider duplicate if similarity > 0.8
                if similarity > 0.8:
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to check task duplication: {e}")
            return False

    def _normalize_priority(self, priority: str) -> str:
        """Normalize priority values"""
        priority_map = {
            "high": "high", "urgent": "high", "critical": "high",
            "medium": "medium", "normal": "medium",
            "low": "low"
        }
        return priority_map.get(priority.lower(), "medium")

    def _normalize_status(self, status: str) -> str:
        """Normalize status values"""
        status_map = {
            "todo": "todo", "pending": "todo",
            "in_progress": "in_progress", "active": "in_progress",
            "completed": "completed", "done": "completed", "finished": "completed"
        }
        return status_map.get(status.lower(), "todo")

    async def _log_distribution_results(self, results: Dict[str, Any]):
        """Log the results of task distribution"""
        try:
            sheets_result = results.get("google_sheets", {})
            platform_result = results.get("platform_webhook", {})

            # Log to audit system
            self.audit_logger.log_sensitive_operation(
                operation="TASK_DISTRIBUTION_COMPLETE",
                user_id=self.user_id,
                resource_type="TASK_MANAGEMENT",
                resource_id=self.agent_task_id,
                details={
                    "sheets_success": sheets_result.get("success", False),
                    "platform_success": platform_result.get("success", False),
                    "tasks_sent_sheets": sheets_result.get("tasks_sent", 0),
                    "tasks_sent_platform": platform_result.get("tasks_sent", 0)
                },
                ip_address="internal",
                success=sheets_result.get("success", False) and platform_result.get("success", False),
                risk_level="LOW"
            )

        except Exception as e:
            logger.error(f"Failed to log distribution results: {e}")


def get_unified_task_service(user_id: str, org_id: str, agent_task_id: str, google_auth: GoogleAuthHandler = None) -> UnifiedTaskService:
    """Factory function to get unified task service instance"""
    return UnifiedTaskService(user_id, org_id, agent_task_id, google_auth)