"""
Platform API Client Service
Handles communication with the external platform API at https://devapi.agentic.elevationai.com
Adds async audit-log sender for activity logs.
"""

import logging
import os
import json
import requests
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class PlatformAPIClient:
    """
    Client for interacting with the external platform API
    """

    def __init__(self, base_url: str = "https://devapi.agentic.elevationai.com"):
        """Initialize the platform API client"""
        # Ensure .env is loaded early if keys are not already present
        try:
            if not (os.getenv("PLATFORM_API_KEY") and os.getenv("PLATFORM_API_SECRET")):
                from dotenv import load_dotenv  # type: ignore
                # Attempt to load from project root
                env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '..', '.env')
                env_path = os.path.abspath(env_path)
                if os.path.exists(env_path):
                    load_dotenv(env_path)
                else:
                    load_dotenv()
        except Exception:
            # .env loading is best-effort
            pass
        self.base_url = base_url.rstrip('/')
        self.timeout = 30
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'FastAPI-Agent/1.0'
        })
        # Cache of workflow tool context per agent_task_id
        # Format: { agent_task_id: [ { 'step_id': str, 'tool_id': str, 'tool_str': str, 'integration_type': str } ] }
        if not hasattr(self, "_tool_context_cache"):
            self._tool_context_cache: Dict[str, List[Dict[str, Any]]] = {}

        # Activity log endpoint & credentials (for async log sender)
        self.activity_log_url = os.getenv(
            "ACTIVITY_LOG_API_URL",
            f"{self.base_url}/activity-log/agent/save-log"
        )
        # Require platform keys only (no fallback)
        self.platform_api_key = os.getenv("PLATFORM_API_KEY")
        self.platform_api_secret = os.getenv("PLATFORM_API_SECRET")

        if not self.platform_api_key or not self.platform_api_secret:
            logger.warning("Platform API credentials are not set in environment (PLATFORM_API_KEY/PLATFORM_API_SECRET)")

    # ---------------------------------------------------------------------
    # Tool context resolution helpers
    # ---------------------------------------------------------------------
    def _platform_headers(self) -> Dict[str, str]:
        return {
            'Content-Type': 'application/json',
            'x-api-key': self.platform_api_key or '',
            'x-api-secret': self.platform_api_secret or ''
        }

    # Public: store mapping from start-agent payload
    def cache_workflow_context(self, *, agent_task_id: str, workflow_items: List[Dict[str, Any]]) -> None:
        try:
            mapped: List[Dict[str, Any]] = []
            for item in workflow_items or []:
                step_id = item.get("id") or item.get("step_id")
                for tool in item.get("tool_to_use", []) or []:
                    mapped.append({
                        "step_id": step_id,
                        "tool_id": tool.get("id") or tool.get("tool_id"),
                        "tool_str": tool.get("title") or tool.get("tool_name") or tool.get("name"),
                        "integration_type": tool.get("integration_type"),
                    })
            if mapped:
                self._tool_context_cache[agent_task_id] = mapped
        except Exception:
            return

    def _get_latest_agent_details_sync(self, *, user_id: str, org_id: str, agent_task_id: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/user-agent-task/get-latest-agent-details"
            payload = {"org_id": org_id, "user_id": user_id, "agent_task_id": agent_task_id}
            resp = self.session.post(url, json=payload, headers=self._platform_headers(), timeout=self.timeout)
            if resp.status_code in (200, 201):
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return None
        except Exception as e:
            logger.debug("_get_latest_agent_details_sync error: %s", e)
        return None

    async def _get_latest_agent_details_async(self, *, user_id: str, org_id: str, agent_task_id: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/user-agent-task/get-latest-agent-details"
            payload = {"org_id": org_id, "user_id": user_id, "agent_task_id": agent_task_id}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=self._platform_headers())
                if resp.status_code in (200, 201):
                    try:
                        return resp.json()
                    except json.JSONDecodeError:
                        return None
        except Exception as e:
            logger.debug("_get_latest_agent_details_async error: %s", e)
        return None

    @staticmethod
    def _find_tool_context(agent_details: Dict[str, Any], *, tool_hint: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            data = agent_details.get("data")
            if isinstance(data, dict):
                # Some responses may wrap in dict → normalize to list
                data = [data]
            if not isinstance(data, list):
                return None
            normalized_hint = (tool_hint or "").strip().lower()
            for workflow_item in data:
                step_id = workflow_item.get("id") or workflow_item.get("step_id")
                for tool in workflow_item.get("tool_to_use", []) or []:
                    tool_name = (tool.get("tool_name") or tool.get("name") or tool.get("integration_type") or "").lower()
                    integration_type = tool.get("integration_type") or tool_name
                    tool_id = tool.get("id") or tool.get("tool_id") or tool_name
                    if not normalized_hint or normalized_hint in tool_name or normalized_hint == integration_type.lower():
                        return {
                            "step_id": step_id,
                            "tool_id": tool_id,
                            "integration_type": integration_type,
                        }
        except Exception:
            return None
        return None

    def _find_tool_context_from_cache(self, *, agent_task_id: str, tool_hint: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            if not agent_task_id:
                return None
            entries = self._tool_context_cache.get(agent_task_id) or []
            if not entries:
                return None
            hint = (tool_hint or "").strip().lower()
            for e in entries:
                name = (e.get("tool_str") or "").lower()
                integ = (e.get("integration_type") or "").lower()
                if not hint or hint in name or hint == integ:
                    return {
                        "step_id": e.get("step_id"),
                        "tool_id": e.get("tool_id"),
                        "integration_type": e.get("integration_type"),
                    }
        except Exception:
            return None
        return None

    # Lightweight resolver for user/org from local DB by agent_task_id
    def _resolve_user_org_from_db(self, agent_task_id: str) -> Optional[Dict[str, str]]:
        try:
            if not agent_task_id:
                return None
            try:
                from ..database_service_new import get_database_service  # type: ignore
            except Exception:
                return None
            db = get_database_service()
            rows = db.execute_query(
                """
                SELECT user_id, org_id
                FROM user_agent_task
                WHERE agent_task_id = :agent_task_id
                ORDER BY updated DESC
                LIMIT 1
                """,
                {"agent_task_id": agent_task_id}
            )
            if rows and len(rows) > 0:
                row = rows[0]
                # Support row as tuple or mapping
                user_id = row[0] if isinstance(row, (list, tuple)) else row.get("user_id")
                org_id = row[1] if isinstance(row, (list, tuple)) else row.get("org_id")
                if user_id and org_id:
                    return {"user_id": user_id, "org_id": org_id}
        except Exception:
            return None
        return None

    def _enrich_entry_with_tool_context_sync(self, *, entry: Dict[str, Any], agent_task_id: str) -> None:
        try:
            # Skip if already present
            if all(k in entry for k in ("step_id", "tool_id", "integration_type")):
                return
            ld = entry.get("log_data") or {}
            user_id = ld.get("user_id")
            org_id = ld.get("org_id")
            if not (user_id and org_id):
                resolved = self._resolve_user_org_from_db(agent_task_id)
                if resolved:
                    user_id = user_id or resolved.get("user_id")
                    org_id = org_id or resolved.get("org_id")
            tool_hint = entry.get("tool_str") or ld.get("tool_hint") or ld.get("integration_type")
            # Try cache first
            ctx = self._find_tool_context_from_cache(agent_task_id=agent_task_id, tool_hint=tool_hint)
            if ctx:
                for k, v in ctx.items():
                    if k not in entry and v is not None:
                        entry[k] = v
                # ensure log_data carries these too
                ld.setdefault("step_id", entry.get("step_id"))
                ld.setdefault("tool_id", entry.get("tool_id"))
                ld.setdefault("integration_type", entry.get("integration_type"))
                entry["log_data"] = ld
                return
            if not (user_id and org_id and agent_task_id and tool_hint):
                return
            details = self._get_latest_agent_details_sync(user_id=user_id, org_id=org_id, agent_task_id=agent_task_id)
            if not details:
                return
            ctx = self._find_tool_context(details, tool_hint=tool_hint)
            if ctx:
                for k, v in ctx.items():
                    if k not in entry and v is not None:
                        entry[k] = v
                ld.setdefault("step_id", entry.get("step_id"))
                ld.setdefault("tool_id", entry.get("tool_id"))
                ld.setdefault("integration_type", entry.get("integration_type"))
                entry["log_data"] = ld
        except Exception:
            return

    async def _enrich_entry_with_tool_context_async(self, *, entry: Dict[str, Any], agent_task_id: str) -> None:
        try:
            if all(k in entry for k in ("step_id", "tool_id", "integration_type")):
                return
            ld = entry.get("log_data") or {}
            user_id = ld.get("user_id")
            org_id = ld.get("org_id")
            if not (user_id and org_id):
                resolved = self._resolve_user_org_from_db(agent_task_id)
                if resolved:
                    user_id = user_id or resolved.get("user_id")
                    org_id = org_id or resolved.get("org_id")
            tool_hint = entry.get("tool_str") or ld.get("tool_hint") or ld.get("integration_type")
            # Try cache first
            ctx = self._find_tool_context_from_cache(agent_task_id=agent_task_id, tool_hint=tool_hint)
            if ctx:
                for k, v in ctx.items():
                    if k not in entry and v is not None:
                        entry[k] = v
                ld.setdefault("step_id", entry.get("step_id"))
                ld.setdefault("tool_id", entry.get("tool_id"))
                ld.setdefault("integration_type", entry.get("integration_type"))
                entry["log_data"] = ld
                return
            if not (user_id and org_id and agent_task_id and tool_hint):
                return
            details = await self._get_latest_agent_details_async(user_id=user_id, org_id=org_id, agent_task_id=agent_task_id)
            if not details:
                return
            ctx = self._find_tool_context(details, tool_hint=tool_hint)
            if ctx:
                for k, v in ctx.items():
                    if k not in entry and v is not None:
                        entry[k] = v
                ld.setdefault("step_id", entry.get("step_id"))
                ld.setdefault("tool_id", entry.get("tool_id"))
                ld.setdefault("integration_type", entry.get("integration_type"))
                entry["log_data"] = ld
        except Exception:
            return

    def _make_request(self, method: str, endpoint: str, headers: Optional[Dict[str, str]] = None,
                     data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Make HTTP request to the platform API"""
        try:
            url = f"{self.base_url}{endpoint}"

            # Merge headers
            request_headers = self.session.headers.copy()
            if headers:
                request_headers.update(headers)

            # Make request
            response = self.session.request(
                method=method,
                url=url,
                headers=request_headers,
                json=data,
                timeout=self.timeout
            )

            response.raise_for_status()

            # Try to parse JSON response
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw_response": response.text}

        except requests.exceptions.RequestException as e:
            logger.error(f"Platform API request failed: {method} {endpoint} - {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in platform API request: {e}")
            return None

    def make_request(self, method: str, endpoint: str, headers: Optional[Dict[str, str]] = None,
                    data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Public method to make HTTP request to the platform API
        This is the method called by the Elevation AI LangChain tool
        """
        return self._make_request(method, endpoint, headers, data)

    async def _post_to_platform(self, *, url: str, payload: Dict[str, Any], request_id: str, error_msg: str) -> Dict[str, Any]:
        """Async helper to POST JSON to platform with API key/secret headers."""
        headers = {
            'Content-Type': 'application/json',
        }
        if self.platform_api_key:
            headers['x-api-key'] = self.platform_api_key
        if self.platform_api_secret:
            headers['x-api-secret'] = self.platform_api_secret

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code in (200, 201, 202):
                    try:
                        return {'status': 'success', 'response': resp.json(), 'status_code': resp.status_code}
                    except json.JSONDecodeError:
                        return {'status': 'success', 'response': resp.text, 'status_code': resp.status_code}
                return {
                    'status': 'error',
                    'status_code': resp.status_code,
                    'message': f"{error_msg}: HTTP {resp.status_code}",
                    'response': resp.text,
                }
        except Exception as e:
            logger.error("%s: %s", error_msg, str(e))
            return {'status': 'error', 'message': f"{error_msg}: {str(e)}"}

    async def send_audit_log_to_platform(self, log_payload: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        Sends a prepared audit log payload to the external platform's save-log endpoint.
        Non-blocking use: await by caller or schedule as a task.
        """
        url = self.activity_log_url
        if not url:
            return {'status': 'error', 'message': 'ACTIVITY_LOG_API_URL not configured'}
        # Swap log_text and step_str for each log entry prior to send
        try:
            logs = (log_payload or {}).get("logs", [])
            for entry in logs:
                if isinstance(entry, dict):
                    # Enrich with tool context if available
                    await self._enrich_entry_with_tool_context_async(entry=entry, agent_task_id=log_payload.get("agent_task_id", ""))
                    lt = entry.get("log_text", "")
                    ss = entry.get("step_str", "")
                    entry["log_text"], entry["step_str"] = ss, lt
                    # Promote contextual fields from log_data if present
                    ld = entry.get("log_data") or {}
                    for k in ("step_id", "tool_id", "integration_type"):
                        if k in ld and k not in entry:
                            entry[k] = ld.get(k)
        except Exception:
            pass
        return await self._post_to_platform(
            url=url,
            payload=log_payload,
            request_id=request_id,
            error_msg="External Log Post Failed"
        )
    
    async def send_audit_log(self, audit_data: Dict[str, Any]) -> bool:
        """
        Simple method to send audit log to platform using the correct format.
        
        Args:
            audit_data: The audit log data to send (will be converted to correct format)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            import uuid
            request_id = str(uuid.uuid4())
            
            # Convert audit_data to the correct platform API format
            platform_payload = self._convert_audit_data_to_platform_format(audit_data)
            
            result = await self.send_audit_log_to_platform(platform_payload, request_id)
            
            if result.get('status') == 'success':
                logger.info(f"Audit log sent successfully: {request_id}")
                return True
            else:
                logger.warning(f"Failed to send audit log: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending audit log: {e}")
            return False
    
    def send_simple_log_sync(
        self,
        *,
        agent_task_id: str,
        log_text: str,
        activity_type: str = "task",
        log_for_status: str = "success",
        action: str = "Read",
        action_issue_event: str = "",
        action_required: str = "None",
        outcome: str = "",
        step_str: str = "",
        tool_str: str = "N/A",
        log_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a user-friendly audit log using the platform's exact payload shape (synchronous)."""
        try:
            import uuid
            from datetime import datetime as _dt
            import requests
            request_id = str(uuid.uuid4())
            payload = {
                "agent_task_id": agent_task_id,
                "logs": [
                    {
                        "activity_type": activity_type,
                        "log_for_status": log_for_status,
                        "log_text": log_text,
                        "action": action,
                        "action_issue_event": action_issue_event or "",
                        "action_required": action_required,
                        "outcome": outcome or "",
                        "step_str": step_str or "",
                        "tool_str": tool_str or "N/A",
                        "description": step_str or action_issue_event or "",  # Add description field
                        "log_data": log_data or {},
                    }
                ],
            }
            # Swap log_text and step_str prior to send
            try:
                first = payload.get("logs", [{}])[0]
                # Enrich with tool context (sync)
                self._enrich_entry_with_tool_context_sync(entry=first, agent_task_id=agent_task_id)
                lt = first.get("log_text", "")
                ss = first.get("step_str", "")
                first["log_text"], first["step_str"] = ss, lt
                # Promote contextual fields from log_data if present
                ld = first.get("log_data") or {}
                for k in ("step_id", "tool_id", "integration_type"):
                    if k in ld and k not in first:
                        first[k] = ld.get(k)
            except Exception:
                pass
            headers = {
                'Content-Type': 'application/json',
                'x-api-key': self.platform_api_key or '',
                'x-api-secret': self.platform_api_secret or ''
            }
            response = requests.post(self.activity_log_url, json=payload, headers=headers, timeout=5)
            if response.status_code in (200, 201, 202):
                logger.info(f"Sent simple audit log: {log_text[:120]}")
                return True
            logger.warning(f"Failed to send simple audit log: {response.status_code} - {response.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"send_simple_log_sync error: {e}")
            return False
    
    def _convert_audit_data_to_platform_format(self, audit_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert audit data to the platform API format.
        
        Args:
            audit_data: Original audit data with user_id, org_id, agent_task_id, action, etc.
            
        Returns:
            Dict in the correct platform API format
        """
        # Extract basic info
        agent_task_id = audit_data.get("agent_task_id", "unknown")
        action = audit_data.get("action", "unknown_action")
        details = audit_data.get("details", {})
        
        # Determine message and action based on the scenario
        if action == "no_events_found":
            # User-friendly, concise title and clear follow-up context
            log_text = details.get(
                "headline",
                "No meetings found this cycle"
            )
            activity_type = "task"
            action_type = "Read"
            action_issue_event = "No calendar events found."
            action_required = "None"
            outcome = details.get(
                "message",
                "No active calendar events were found in the selected window. I'll check again on schedule."
            )
            step_str = "I checked your recent calendar events — nothing new right now. I'll look again soon."
            tool_str = "Calendar API"
        elif action == "workflow_started":
            log_text = "Meeting agent starts working for you successfully"
            activity_type = "workflow"
            action_type = "Start"
            action_issue_event = "Meeting agent is now active and ready to work for you."
            action_required = "None"
            outcome = "Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding."
            step_str = "Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding."
            tool_str = "Meeting Agent"
        elif action == "sheets_created":
            log_text = "Google Sheet created for tasks"
            activity_type = "integration"
            action_type = "Complete"
            action_issue_event = "Sheets created for task tracking."
            action_required = "None"
            outcome = "Sheets created successfully."
            step_str = "A spreadsheet was created and linked to your agent to track action items."
            tool_str = "Sheets Service"
        elif action == "drive_folder_created":
            log_text = "Drive folder created for meeting files"
            activity_type = "integration"
            action_type = "Complete"
            action_issue_event = "Drive folder created for meeting storage."
            action_required = "None"
            outcome = "Drive folder created successfully."
            step_str = "A dedicated folder was created to store transcripts, summaries, and related files."
            tool_str = "Drive Service"
        elif action == "email_sent":
            log_text = details.get("message", "Meeting summary email sent")
            activity_type = "task"
            action_type = "Complete"
            action_issue_event = "Email notification sent to recipients."
            action_required = "None"
            outcome = "Email sent successfully; summary and tasks delivered."
            step_str = "Summary and action items were emailed to the selected recipients."
            tool_str = "Email Service"
        elif action == "agent_completed":
            log_text = details.get("message", "Workflow finished successfully")
            activity_type = "workflow"
            action_type = "Complete"
            action_issue_event = "Agent workflow completed successfully."
            action_required = "None"
            outcome = "Agent completed successfully."
            step_str = "All meeting insights and files are available in your connected tools."
            tool_str = "Meeting Agent"
        else:
            # For other agent workflow events
            log_text = details.get("message", f"Agent workflow: {action}")
            activity_type = "workflow"
            action_type = "Complete"
            action_issue_event = f"Workflow {action} completed successfully"
            action_required = "None"
            outcome = "success"
            step_str = f"Agent workflow step '{action}' completed."
            tool_str = "Meeting Agent"
        
        # Create the log entry in the correct format
        log_entry = {
            "activity_type": activity_type,
            "log_for_status": "success",
            "log_text": log_text,
            "action": action_type,
            "action_issue_event": action_issue_event,
            "action_required": action_required,
            "outcome": outcome,
            "step_str": step_str,
            "tool_str": tool_str,
            "timestamp": audit_data.get("timestamp"),
            "log_data": {
                "user_id": audit_data.get("user_id"),
                "org_id": audit_data.get("org_id"),
                "agent_task_id": agent_task_id,
                "action": action,
                "timestamp": audit_data.get("timestamp"),
                "details": details
            }
        }
        
        # Return in the correct platform format
        return {
            "agent_task_id": agent_task_id,
            "logs": [log_entry]
        }

    async def async_request(self, method: str, endpoint: str, headers: Optional[Dict[str, str]] = None,
                            data: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async HTTP request using httpx against base_url + endpoint."""
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        req_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'FastAPI-Agent/1.0'
        }
        if headers:
            req_headers.update(headers)
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.request(method=method.upper(), url=url, json=data, headers=req_headers)
                resp.raise_for_status()
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return {"raw_response": resp.text}
        except Exception as e:
            logger.error("Async platform request failed: %s %s - %s", method, url, str(e))
            raise

    def get_task_details(self, task_id: str, access_token: str) -> Optional[Dict[str, Any]]:
        """
        Fetch task details from the platform API

        Args:
            task_id: Unique task identifier
            access_token: User's access token for authentication

        Returns:
            Task details dictionary or None if failed
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            endpoint = f'/api/tasks/{task_id}'
            result = self._make_request('GET', endpoint, headers=headers)

            if result:
                logger.info(f"Successfully fetched task details for task: {task_id}")
                return result
            else:
                logger.error(f"Failed to fetch task details for task: {task_id}")
                return None

        except Exception as e:
            logger.error(f"Error fetching task details: {e}")
            return None

    def update_task_status(self, task_id: str, status: str, access_token: str,
                          result_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update task status on the platform API

        Args:
            task_id: Unique task identifier
            status: New status for the task
            access_token: User's access token for authentication
            result_data: Optional result data to include

        Returns:
            True if successful, False otherwise
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            payload = {
                'status': status,
                'updated_at': datetime.now().isoformat(),
                'agent_result': result_data
            }

            endpoint = f'/api/tasks/{task_id}/status'
            result = self._make_request('PUT', endpoint, headers=headers, data=payload)

            if result:
                logger.info(f"Successfully updated task status to {status} for task: {task_id}")
                return True
            else:
                logger.error(f"Failed to update task status for task: {task_id}")
                return False

        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False

    def get_task_list(self, access_token: str, status: Optional[str] = None,
                     limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """
        Get list of tasks from the platform API

        Args:
            access_token: User's access token for authentication
            status: Optional status filter
            limit: Maximum number of tasks to return

        Returns:
            List of tasks or None if failed
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            # Build query parameters
            params = {'limit': limit}
            if status:
                params['status'] = status

            # Convert params to query string
            query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
            endpoint = f'/api/tasks?{query_string}'

            result = self._make_request('GET', endpoint, headers=headers)

            if result:
                logger.info(f"Successfully fetched task list (limit: {limit})")
                return result.get('tasks', [])
            else:
                logger.error("Failed to fetch task list")
                return None

        except Exception as e:
            logger.error(f"Error fetching task list: {e}")
            return None

    def create_task(self, task_data: Dict[str, Any], access_token: str) -> Optional[Dict[str, Any]]:
        """
        Create a new task on the platform API

        Args:
            task_data: Task data to create
            access_token: User's access token for authentication

        Returns:
            Created task data or None if failed
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            endpoint = '/api/tasks'
            result = self._make_request('POST', endpoint, headers=headers, data=task_data)

            if result:
                logger.info(f"Successfully created task: {result.get('id', 'unknown')}")
                return result
            else:
                logger.error("Failed to create task")
                return None

        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return None

    def delete_task(self, task_id: str, access_token: str) -> bool:
        """
        Delete a task on the platform API

        Args:
            task_id: Unique task identifier
            access_token: User's access token for authentication

        Returns:
            True if successful, False otherwise
        """
        try:
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            endpoint = f'/api/tasks/{task_id}'
            result = self._make_request('DELETE', endpoint, headers=headers)

            if result is not None:  # DELETE might return empty response
                logger.info(f"Successfully deleted task: {task_id}")
                return True
            else:
                logger.error(f"Failed to delete task: {task_id}")
                return False

        except Exception as e:
            logger.error(f"Error deleting task: {e}")
            return False


def get_platform_api_client() -> PlatformAPIClient:
    """Get singleton instance of platform API client"""
    if not hasattr(get_platform_api_client, '_instance'):
        get_platform_api_client._instance = PlatformAPIClient()
    return get_platform_api_client._instance