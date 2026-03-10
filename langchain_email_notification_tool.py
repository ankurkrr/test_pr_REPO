import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
import re
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field
from src.auth.google_auth_handler import GoogleAuthHandler
from src.services.google import GoogleDriveService
from src.services.external.email.sendgrid_service import SendGridEmailService
from pybars import Compiler

logger = logging.getLogger(__name__)


class EmailNotificationToolInput(BaseModel):
    """Input schema for the email notification tool."""
    summary_data: str = Field(
        description="JSON string containing meeting summary data to send via email"
    )
    calendar_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Calendar metadata containing user preferences and notification settings"
    )
    recipient_email: Optional[str] = Field(
        default=None,
        description="Email address to send the notification to (if not provided, uses user's email)"
    )
    subject: Optional[str] = Field(
        default=None,
        description="Email subject line (if not provided, uses default)"
    )


class LangchainEmailNotificationTool(BaseTool):
    name: str = "email_notification_tool"
    description: str = "sends_email"
    args_schema: type[BaseModel] = EmailNotificationToolInput

    # SendGrid configuration
    sendgrid_api_key: Optional[str] = None
    from_email: Optional[str] = None
    from_name: str = "Meeting Intelligence Agent"
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    auth_handler: Optional[GoogleAuthHandler] = None
    drive_service: Optional[GoogleDriveService] = None
    email_service: Optional[SendGridEmailService] = None
    database_service: Optional[Any] = None  # Add database_service as a proper field

    def __init__(
        self, 
        user_id: str, 
        org_id: str, 
        agent_task_id: str, 
        auth_handler: GoogleAuthHandler,
        **kwargs
    ):
        super().__init__(**kwargs)
        # Initialize user ID, org ID, and agent task ID
        self.user_id = user_id
        self.org_id = org_id
        self.agent_task_id = agent_task_id
        self.auth_handler = auth_handler
        # Initialize SendGrid configuration from config file
        from src.configuration.config import SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, SENDGRID_FROM_NAME
        self.sendgrid_api_key = SENDGRID_API_KEY
        self.from_email = SENDGRID_FROM_EMAIL
        self.from_name = SENDGRID_FROM_NAME

        # Validate SendGrid configuration at startup (fail fast)
        if not self.sendgrid_api_key or not self.from_email:
            raise RuntimeError("SendGrid configuration missing: SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are required")

        # Initialize SendGrid email service
        try:
            self.email_service = SendGridEmailService()
            logger.info("[OK] SendGrid Email Service initialized successfully")
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize SendGrid service: {e}")
            raise

        # Initialize Google Drive service for summary persistence
        try:
            self.drive_service = GoogleDriveService(self.auth_handler)
            logger.info("[OK] Google Drive service initialized for summary persistence")
        except Exception as e:
            logger.warning(f"[WARN] Could not initialize Drive service: {e}")
            self.drive_service = None

        # Initialize database service for workflow_data lookups
        try:
            from src.services.database_service_new import get_database_service
            self.database_service = get_database_service()
            logger.info("[OK] Database service initialized for email notify preferences")
        except Exception as e:
            logger.warning(f"[WARN] Could not initialize database service in email tool: {e}")
            self.database_service = None

        logger.info(f"EmailNotificationTool initialized with SendGrid API")

    def run(
        self,
        tool_input: Any,
        **kwargs,
    ) -> str:
        """Override run method to handle input correctly."""
        logger.info(f"Email tool run() called with input: {tool_input}, kwargs: {kwargs}")
        return self._run(tool_input, **kwargs)

    def _log_audit_event(self, event_type: str, status: str, message: str, data: Dict[str, Any] = None):
        """Log audit events for email operations."""
        try:
            logger.info(f"[AUDIT] {event_type}: {status} - {message}")
            if data:
                logger.info(f"[AUDIT] Data: {data}")
            
            # Send audit log to platform when email is sent successfully
            if event_type == "email_sent" and status == "success" and self.agent_task_id:
                try:
                    from src.services.integration.platform_api_client import PlatformAPIClient
                    
                    # Get recipients count from data
                    recipients_count = len(data.get("recipients", [])) if data else 0
                    
                    # Send to platform using PlatformAPIClient (synchronous method)
                    platform_client = PlatformAPIClient()
                    
                    # Create friendly message based on recipient count
                    if recipients_count == 1:
                        friendly_message = "All set! I've just sent the meeting summary to your inbox!!!"
                        description = "It includes a quick recap of the discussion, key takeaways, and action items. Take a look whenever you're ready!"
                    else:
                        friendly_message = f"All set! I've just sent the meeting summary to {recipients_count} inboxes!!!"
                        description = "It includes a quick recap of the discussion, key takeaways, and action items. All recipients can take a look whenever they're ready!"
                    
                    platform_client.send_simple_log_sync(
                        agent_task_id=self.agent_task_id,
                        log_text=friendly_message,
                        activity_type="task",
                        log_for_status="success",
                        action="Send",
                        action_issue_event=description,
                        action_required="None",
                        outcome="Email sent successfully - Summary sent",
                        step_str=f"{friendly_message} {description}",
                        tool_str="SendGrid",
                        log_data={
                            "user_id": self.user_id,
                            "org_id": self.org_id,
                            "agent_task_id": self.agent_task_id,
                            "recipients_count": recipients_count,
                            "recipients": data.get("recipients", []) if data else []
                        }
                    )
                    logger.info(f"[AUDIT] Sent platform audit log for email sent (agent_task_id: {self.agent_task_id}, recipients: {recipients_count})")
                except Exception as e:
                    logger.warning(f"Failed to send platform audit log for email sent: {e}")
        except Exception as e:
            logger.error(f"Error logging audit event: {e}")

    def _parse_json_safely(self, json_string: str, context: str = "JSON") -> Dict[str, Any]:
        """Safely parse JSON with multiple fallback strategies."""
        try:
            # Strategy 1: Direct parsing
            return json.loads(json_string)
        except json.JSONDecodeError as e:
            logger.warning(f"Direct JSON parsing failed for {context}: {e}")
            
            try:
                # Strategy 2: Fix common escape issues
                cleaned_json = json_string
                # Fix common escape issues step by step
                cleaned_json = cleaned_json.replace('\\\\', '\\')  # Fix double backslashes
                cleaned_json = cleaned_json.replace('\\"', '"')    # Fix escaped quotes
                cleaned_json = cleaned_json.replace("\\'", "'")    # Fix escaped single quotes
                # Fix the specific issue: \\' -> '
                cleaned_json = re.sub(r"\\\\'", "'", cleaned_json)
                return json.loads(cleaned_json)
            except json.JSONDecodeError as e2:
                logger.warning(f"Escape fixing failed for {context}: {e2}")
                
                try:
                    # Strategy 3: More comprehensive escape fixing
                    fixed_json = json_string
                    # Fix all problematic escape sequences
                    fixed_json = re.sub(r'\\\\', r'\\', fixed_json)  # \\ -> \
                    fixed_json = re.sub(r"\\'", "'", fixed_json)   # \' -> '
                    fixed_json = re.sub(r'\\"', '"', fixed_json)   # \" -> "
                    fixed_json = re.sub(r'\\(?![\\"/bfnrt])', r'\\\\', fixed_json)  # Fix other escapes
                    return json.loads(fixed_json)
                except json.JSONDecodeError as e3:
                    logger.warning(f"Comprehensive escape fixing failed for {context}: {e3}")
                    
                    try:
                        # Strategy 4: Use ast.literal_eval for safer parsing
                        import ast
                        # Convert to Python dict and back to JSON
                        python_dict = ast.literal_eval(json_string.replace('\\\'', "'"))
                        return python_dict
                    except Exception as e4:
                        logger.error(f"All JSON parsing strategies failed for {context}: {e4}")
                        # Return empty dict as fallback
                        return {}

    def _extract_meeting_title(self, calendar_metadata: Optional[Dict[str, Any]] = None, summary_data: Optional[Dict[str, Any]] = None) -> str:
        """
        Extract meeting title with priority order:
        1. Calendar event title (from calendar_metadata)
        2. Meetings table (database)
        3. Summarizer data
        4. Fallback to "Meeting Summary"
        
        Args:
            calendar_metadata: Calendar metadata with events
            summary_data: Summary data from summarizer
            
        Returns:
            Meeting title string
        """
        meeting_title = None
        
        # Priority 1: Extract from calendar_metadata events
        if calendar_metadata and isinstance(calendar_metadata, dict):
            # Check if calendar_metadata has events array
            events = calendar_metadata.get("events", [])
            if events and isinstance(events, list) and len(events) > 0:
                # Get title from first event
                first_event = events[0]
                if isinstance(first_event, dict):
                    meeting_title = first_event.get("title")
                    if meeting_title and meeting_title != "Meeting Summary":
                        logger.info(f"Extracted meeting title from calendar event: '{meeting_title}'")
                        return meeting_title
            
            # Also check if calendar_metadata has calendar_tool_response structure
            calendar_tool_response = calendar_metadata.get("calendar_tool_response", {})
            if calendar_tool_response:
                events = calendar_tool_response.get("events", [])
                if events and isinstance(events, list) and len(events) > 0:
                    first_event = events[0]
                    if isinstance(first_event, dict):
                        meeting_title = first_event.get("title")
                        if meeting_title and meeting_title != "Meeting Summary":
                            logger.info(f"Extracted meeting title from calendar_tool_response: '{meeting_title}'")
                            return meeting_title
        
        # Priority 2: Fetch from meetings table
        if not meeting_title or meeting_title == "Meeting Summary":
            try:
                if self.database_service and self.user_id and self.agent_task_id:
                    meetings_query = """
                    SELECT title
                    FROM meetings
                    WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                      AND start_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                    ORDER BY start_time DESC
                    LIMIT 1
                    """
                    meetings = self.database_service.execute_query(meetings_query, {
                        "user_id": self.user_id,
                        "agent_task_id": self.agent_task_id
                    })
                    
                    if meetings and len(meetings) > 0:
                        meeting_row = meetings[0]
                        # Handle different row types
                        if hasattr(meeting_row, '_mapping'):
                            db_title = meeting_row.title
                        elif isinstance(meeting_row, dict):
                            db_title = meeting_row.get("title")
                        else:
                            db_title = meeting_row[0] if len(meeting_row) > 0 else None
                        
                        if db_title and db_title != "Meeting Summary":
                            meeting_title = db_title
                            logger.info(f"Extracted meeting title from meetings table: '{meeting_title}'")
                            return meeting_title
            except Exception as e:
                logger.warning(f"Error fetching meeting title from database: {e}")
        
        # Priority 3: Extract from summary_data
        if not meeting_title or meeting_title == "Meeting Summary":
            if summary_data and isinstance(summary_data, dict):
                if "summarizer_tool_response" in summary_data:
                    summarizer_data = summary_data["summarizer_tool_response"]
                    meeting_metadata = summarizer_data.get("meeting_metadata", {})
                    meeting_title = meeting_metadata.get("title") or summarizer_data.get("event_title")
                elif "meeting_metadata" in summary_data:
                    meeting_metadata = summary_data["meeting_metadata"]
                    meeting_title = meeting_metadata.get("title") or summary_data.get("event_title")
                elif "event_title" in summary_data:
                    meeting_title = summary_data.get("event_title")
                
                if meeting_title and meeting_title != "Meeting Summary":
                    logger.info(f"Extracted meeting title from summary_data: '{meeting_title}'")
                    return meeting_title
        
        # Priority 4: Fallback to "Meeting Summary"
        if not meeting_title:
            meeting_title = "Meeting Summary"
            logger.warning("No meeting title found, using fallback: 'Meeting Summary'")
        
        return meeting_title

    def _fetch_calendar_metadata_from_workflow(self) -> Dict[str, Any]:
        """Fetch calendar metadata from workflow data if not provided directly."""
        try:
            if not hasattr(self, "database_service") or not self.database_service:
                logger.warning("No database service available for fetching calendar metadata")
                return self._create_fallback_calendar_metadata()
            
            # Fetch the latest workflow data for this user/agent_task
            query = """
            SELECT workflow_data 
            FROM workflow_data 
            WHERE user_id = :user_id AND agent_task_id = :agent_task_id
            ORDER BY updated_at DESC 
            LIMIT 1
            """
            rows = self.database_service.execute_query(query, {
                "user_id": self.user_id, 
                "agent_task_id": self.agent_task_id
            })
            
            if rows:
                workflow_data_str = rows[0][0] if isinstance(rows[0], (list, tuple)) else rows[0].get("workflow_data")
                if workflow_data_str:
                    workflow_data = self._parse_json_safely(workflow_data_str, "workflow_data")
                    calendar_result = workflow_data.get("calendar_tool_response", {})
                    
                    # Extract events and create calendar_metadata
                    events = calendar_result.get("events", [])
                    logger.info(f"Fetched {len(events)} events from workflow data")
                    
                    return {
                        "events": events,
                        "user_id": self.user_id,
                        "org_id": self.org_id,
                        "agent_task_id": self.agent_task_id
                    }
            
            logger.warning("No workflow data found, creating fallback calendar metadata")
            return self._create_fallback_calendar_metadata()
            
        except Exception as e:
            logger.error(f"Error fetching calendar metadata from workflow: {e}")
            return self._create_fallback_calendar_metadata()
    
    def _create_fallback_calendar_metadata(self) -> Dict[str, Any]:
        """Create a fallback calendar metadata structure."""
        return {
            "events": [],
            "user_id": self.user_id,
            "org_id": self.org_id,
            "agent_task_id": self.agent_task_id
        }

    def _fetch_attendees_from_meetings_table(self, recipient_scope: str) -> List[Dict[str, Any]]:
        """
        Fetch attendees from meetings table based on notification preference.
        
        Args:
            recipient_scope: "only_me" or "all_participants" or "all"
        
        Returns:
            List of normalized attendees
        """
        try:
            if not self.database_service:
                logger.warning("Database service not available for fetching attendees")
                return []
            
            # Fetch meetings for this user first to get the user's email from organizer
            # The user's email is the meeting organizer
            meetings_query = """
            SELECT id, title, attendees, start_time, end_time
            FROM meetings
            WHERE user_id = :user_id AND agent_task_id = :agent_task_id
              AND start_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            ORDER BY start_time DESC
            LIMIT 1
            """
            meetings = self.database_service.execute_query(meetings_query, {
                "user_id": self.user_id,
                "agent_task_id": self.agent_task_id
            })
            
            if not meetings:
                logger.warning(f"No meetings found for user {self.user_id}, agent_task {self.agent_task_id}")
                return []
            
            # Get attendees from the most recent meeting
            meeting_row = meetings[0]
            
            # Try dict access first (SQLAlchemy Row object), then fallback to tuple access
            if hasattr(meeting_row, '_mapping'):
                # SQLAlchemy Row object with named access
                meeting_id = meeting_row.id
                meeting_title = meeting_row.title
                attendees_json = meeting_row.attendees
            elif isinstance(meeting_row, dict):
                # Dictionary access
                meeting_id = meeting_row.get("id")
                meeting_title = meeting_row.get("title")
                attendees_json = meeting_row.get("attendees")
            else:
                # Tuple/list access (fallback)
                meeting_id = meeting_row[0]
                meeting_title = meeting_row[1]
                attendees_json = meeting_row[2]
            
            logger.info(f"Fetched meeting {meeting_id}: {meeting_title}")
            
            # Parse attendees from JSON
            import json
            all_attendees = []
            if attendees_json:
                try:
                    all_attendees = json.loads(attendees_json) if isinstance(attendees_json, str) else attendees_json
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"Failed to parse attendees JSON: {attendees_json}")
                    all_attendees = []
            
            logger.info(f"Found {len(all_attendees)} attendees in meeting: {all_attendees}")
            
            # Get user_email from user_agent_task table (this is the actual user's email)
            user_email_query = """
            SELECT email 
            FROM user_agent_task 
            WHERE user_id = :user_id AND agent_task_id = :agent_task_id
            LIMIT 1
            """
            user_email_rows = self.database_service.execute_query(user_email_query, {
                "user_id": self.user_id,
                "agent_task_id": self.agent_task_id
            })
            
            user_email = None
            if user_email_rows and user_email_rows[0]:
                row = user_email_rows[0]
                # Handle different row types
                if hasattr(row, '_mapping'):
                    # SQLAlchemy Row object
                    user_email = row.email
                elif isinstance(row, tuple):
                    # Tuple
                    user_email = row[0]
                elif isinstance(row, dict):
                    # Dictionary
                    user_email = row.get("email")
                else:
                    user_email = None
                logger.info(f"Found user email from user_agent_task: {user_email}")
            else:
                # Fallback to first attendee if email not in user_agent_task
                user_email = all_attendees[0] if all_attendees else None
                logger.warning(f"User email not found in user_agent_task, falling back to first attendee: {user_email}")
            
            # Filter based on recipient_scope
            if recipient_scope == "only_me":
                if user_email:
                    # Send to the user's actual email
                    normalized_attendees = [{"email": user_email, "name": user_email.split("@")[0].replace(".", " ").title()}]
                    logger.info(f"Only_me mode: sending to user {user_email}")
                    return normalized_attendees
                else:
                    logger.warning("No user email available for only_me mode")
                    return []
            else:  # recipient_scope == "all_participants"
                # Send to all attendees
                normalized_attendees = []
                for attendee in all_attendees:
                    if isinstance(attendee, str) and "@" in attendee:
                        normalized_attendees.append({
                            "email": attendee,
                            "name": attendee.split("@")[0].replace(".", " ").title()
                        })
                logger.info(f"All mode: sending to {len(normalized_attendees)} attendees")
                return normalized_attendees
                
        except Exception as e:
            logger.error(f"Error fetching attendees from meetings table: {e}")
            return []

    def _get_notify_preference_and_user_email(self) -> tuple[str, Optional[str]]:
        """Fetch notify_to and user email from user_agent_task for current user/agent_task.

        Returns:
            (notify_pref, user_email)
        """
        try:
            if not hasattr(self, "database_service") or not self.database_service:
                return "everyone", None

            rows = self.database_service.execute_query(
                """
                SELECT notification_preference
                FROM user_agent_task
                WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                ORDER BY updated DESC
                LIMIT 1
                """,
                {"user_id": self.user_id, "agent_task_id": self.agent_task_id},
            )
            notify_pref = None
            if rows:
                row0 = rows[0]
                try:
                    notify_pref = row0.get("notification_preference") if isinstance(row0, dict) else row0[0]
                except Exception:
                    notify_pref = None

            # Get user email from calendar metadata (organizer_email or user_email)
            user_email = None
            if hasattr(self, 'calendar_metadata') and self.calendar_metadata:
                user_email = self.calendar_metadata.get("organizer_email") or self.calendar_metadata.get("user_email")
            
            # If still no email, try to get from Google Calendar API (the user's own email from calendar metadata)
            # The user's email comes from Google Calendar when they are the organizer
            if not user_email and self.auth_handler:
                try:
                    # Get the user's own email from their calendar profile
                    # When they create calendar events, their email is stored as organizer_email
                    user_email = self.user_id  # Use user_id as fallback only
                except Exception as e:
                    logger.warning(f"Could not get user email from calendar: {e}")

            normalized = (notify_pref or "everyone").strip().lower()
            return normalized, user_email
        except Exception as e:
            logger.warning(f"Failed to fetch notify preference/user email: {e}")
            return "everyone", None

    def _run(
        self,
        summary_data,
        recipient_email: Optional[str] = None,
        subject: Optional[str] = None,
        recipient_scope: str = "all_participants",
        notify_to: Optional[List[str]] = None,
        calendar_metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Send meeting summary emails to attendees.

        Args:
            summary_data: JSON string containing meeting summary data
            run_manager: LangChain callback manager
            recipient_scope: Who to send the summary to
                - "all_participants": Send to all meeting attendees (default)
                - "only_me": Send only to the current user
        """
        try:
            # Handle both dict and string inputs properly
            if isinstance(summary_data, dict):
                logger.info(f"Email tool received dict input with keys: {list(summary_data.keys())}")
                # Extract calendar_metadata if present
                if 'calendar_metadata' in summary_data:
                    calendar_metadata = summary_data['calendar_metadata']
                    logger.info(f"Found calendar_metadata in input: {calendar_metadata}")
                # Extract summary_data if nested
                if 'summary_data' in summary_data:
                    data = summary_data['summary_data']
                    # If summary_data is a string, parse it as JSON
                    if isinstance(data, str):
                        data = self._parse_json_safely(data, "nested summary_data")
                else:
                    data = summary_data
            else:
                # Parse the summary data as JSON string
                logger.info(f"Email tool received string input (first 200 chars): {summary_data[:200]}")
                data = self._parse_json_safely(summary_data, "string input")
            
            # Ensure data is a dict
            if not isinstance(data, dict):
                logger.error(f"Data is not a dict: {type(data)}")
                return json.dumps({
                    "status": "error",
                    "error": "Invalid data format",
                    "timestamp": datetime.now().isoformat(),
                })
            
            # Parse calendar_metadata if it's a JSON string
            if isinstance(calendar_metadata, str):
                logger.info(f"Parsing calendar_metadata from JSON string: {calendar_metadata[:100]}...")
                calendar_metadata = self._parse_json_safely(calendar_metadata, "calendar_metadata")
                logger.info(f"Parsed calendar_metadata type: {type(calendar_metadata)}, keys: {list(calendar_metadata.keys()) if isinstance(calendar_metadata, dict) else 'Not a dict'}")
            
            # Handle missing calendar_metadata gracefully
            if not isinstance(calendar_metadata, dict):
                logger.warning(f"calendar_metadata not provided or invalid format: {type(calendar_metadata)}, fetching from workflow data")
                # Try to fetch calendar metadata from workflow data
                calendar_metadata = self._fetch_calendar_metadata_from_workflow()
                logger.info(f"Fetched calendar_metadata from workflow: {type(calendar_metadata)}, keys: {list(calendar_metadata.keys()) if isinstance(calendar_metadata, dict) else 'Not a dict'}")

            # Validate required fields
            if not self._validate_sendgrid_config():
                return json.dumps(
                    {
                        "status": "error",
                        "error": "SendGrid configuration missing. Check SENDGRID_API_KEY, SENDGRID_FROM_EMAIL environment variables.",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Extract meeting information from new JSON format
            # Handle both summarizer_tool_response and dedup_tool_response formats
            summary_content = ""
            raw_attendees = []
            
            if "summarizer_tool_response" in data:
                # Get data from summarizer tool response
                summarizer_data = data["summarizer_tool_response"]
                meeting_metadata = summarizer_data.get("meeting_metadata", {})
                summary_content = summarizer_data.get("executive_summary", "")
                raw_attendees = meeting_metadata.get("attendees", [])
            elif "dedup_tool_response" in data:
                # Get data from dedup tool response - need to extract from original summarizer data
                dedup_data = data["dedup_tool_response"]
                summary_content = "Meeting summary with extracted tasks"
                raw_attendees = []
            else:
                # Direct format (fallback)
                meeting_metadata = data.get("meeting_metadata", {})
                summary_content = data.get("executive_summary", "")
                raw_attendees = meeting_metadata.get("attendees", [])
            
            # Extract meeting title using priority order: calendar events -> meetings table -> summary data -> fallback
            meeting_title = self._extract_meeting_title(calendar_metadata=calendar_metadata, summary_data=data)
            
            # Handle missing calendar_metadata gracefully
            if not isinstance(calendar_metadata, dict):
                logger.warning("calendar_metadata not provided, using fallback attendee extraction")
                # Try to get attendees from calendar tool as fallback
                calendar_attendees = self._get_calendar_attendees()
                # Get user's actual email from Google Calendar (should be retrieved from calendar API)
                user_actual_email = None  # Will be set from calendar events
                calendar_metadata = {
                    "attendees": calendar_attendees,
                    "user_email": user_actual_email,  # Will be set from calendar metadata
                    "start_time": "Unknown",
                    "end_time": "Unknown"
                }

            # Get notification preference from database
            notify_pref, user_email_from_db = self._get_notify_preference_and_user_email()
            
            # Map database values to recipient scope
            # Check for "only_me" variations first
            if notify_pref in ("only_me", "me", "self", "user_only", "user_only", "self_only"):
                recipient_scope = "only_me"
            # Check for "all" variations (including "all_participants")
            elif notify_pref in ("all", "all_participants"):
                recipient_scope = "all_participants"
            else:
                # Default to "all_participants" for any other value
                recipient_scope = "all_participants"
            
            logger.info(f"Database notify_pref: {notify_pref} -> recipient_scope: {recipient_scope}")
            
            # Fetch attendees from meetings table based on user_id and agent_task_id
            attendees = self._fetch_attendees_from_meetings_table(recipient_scope)
            
            if not attendees:
                    return json.dumps({
                    "status": "no_attendees",
                    "message": "No attendees found in meetings table",
                        "timestamp": datetime.now().isoformat(),
                    })
            
            # Extract meeting date based on data format
            if "summarizer_tool_response" in data:
                meeting_date = meeting_metadata.get("start_time") or "Unknown"
            elif "dedup_tool_response" in data:
                meeting_date = "Unknown"  # Dedup tool doesn't have meeting date
            else:
                meeting_date = meeting_metadata.get("start_time") or (
                    (calendar_metadata or {}).get("start_time") if isinstance(calendar_metadata, dict) else None
                ) or "Unknown"

            # Create email content based on data format
            if "dedup_tool_response" in data:
                # For dedup tool response, create content with task information
                dedup_data = data["dedup_tool_response"]
                processed_tasks = dedup_data.get("processed_tasks", [])
                tasks_added = dedup_data.get("tasks_added", 0)
                
                # Create summary content with task information
                task_summary = f"Meeting: {meeting_title}\n\n"
                task_summary += f"Tasks Processed: {len(processed_tasks)}\n"
                task_summary += f"New Tasks Added: {tasks_added}\n\n"
                
                if processed_tasks:
                    task_summary += "Action Items:\n"
                    for i, task in enumerate(processed_tasks, 1):
                        if task.get("decision") == "ADDED":
                            task_summary += f"{i}. {task.get('task_text', 'N/A')}\n"
                            task_summary += f"   Assignee: {', '.join(task.get('assignees', []))}\n"
                            task_summary += f"   Priority: {task.get('priority_level', 'medium')}\n\n"
                
                summary_content = task_summary
            else:
                # Use existing summary content for summarizer tool response
                pass

            if not attendees:
                return json.dumps(
                    {
                        "status": "no_attendees",
                        "message": "No attendees found in meeting data",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Build explicit recipients from notify_to, if provided
            explicit_recipients: List[Dict[str, Any]] = []
            if notify_to and isinstance(notify_to, list):
                for e in notify_to:
                    if isinstance(e, str) and "@" in e:
                        explicit_recipients.append({
                            "email": e,
                            "name": e.split("@")[0].replace(".", " ").title()
                        })

            # Attendees are already filtered by _fetch_attendees_from_meetings_table based on recipient_scope
            # No need to filter again since the data flow already handled it
            scoped_attendees = attendees
            logger.info(f"Using pre-filtered attendees from meetings table: {len(scoped_attendees)} recipients")

            # Merge and de-duplicate (notify_to must always be included)
            merged: Dict[str, Dict[str, Any]] = {}
            for r in scoped_attendees + explicit_recipients:
                email = (r.get("email") or "").lower()
                if email:
                    merged[email] = {"email": email, "name": r.get("name") or email.split("@")[0].replace(".", " ").title()}
            target_attendees = list(merged.values())

            if not target_attendees:
                return json.dumps(
                    {
                        "status": "no_target_recipients",
                        "message": f"No valid recipients found for scope: {recipient_scope}",
                        "recipient_scope": recipient_scope,
                        "total_attendees": len(attendees),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Persist summaries to Google Drive first
            drive_results = self._persist_summaries_to_drive(
                meeting_title=meeting_title,
                summary_content=summary_content,
                meeting_date=meeting_date,
                attendees=attendees,
            )

            # Send emails to target recipients using SendGrid
            if not self.email_service:
                return json.dumps(
                    {
                        "status": "error",
                        "error": "SendGrid email service not available",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            # Prepare recipients for bulk send
            recipients = []
            for attendee in target_attendees:
                email = attendee.get("email")
                name = attendee.get("name", email)

                if email:
                    recipients.append({"email": email, "name": name})

            if not recipients:
                return json.dumps(
                    {
                        "status": "no_valid_recipients",
                        "message": "No valid email addresses found in target recipients",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            logger.info(
                f" Sending emails to {len(recipients)} recipients via SendGrid (scope: {recipient_scope})"
            )

            # Create email content
            subject = f"Meeting Summary: {meeting_title}"
            plain_text = self._create_plain_text_email(
                "Team", meeting_title, summary_content, meeting_date, recipient_scope
            )
            # Pass the full data object to the HTML email creator for Handlebars rendering
            html_content = self._create_html_email_from_json(
                data,
                meeting_title,
                meeting_date,
                calendar_metadata=calendar_metadata,
            )

            # Send email via SendGrid using direct HTTP request
            import requests
            import json as json_lib
            
            if recipients:
                # Prepare SendGrid API request
                sendgrid_url = "https://api.sendgrid.com/v3/mail/send"
                headers = {
                    "Authorization": f"Bearer {self.email_service.api_key}",
                    "Content-Type": "application/json"
                }
                
                # Create email payload
                email_data = {
                    "personalizations": [
                        {
                            "to": [{"email": r["email"], "name": r["name"]} for r in recipients],
                            "subject": subject
                        }
                    ],
                    "from": {
                        "email": self.email_service.from_email,
                        "name": self.email_service.from_name
                    },
                    "content": [
                        {
                            "type": "text/plain",
                            "value": plain_text
                        },
                        {
                            "type": "text/html",
                            "value": html_content
                        }
                    ]
                }
                
                try:
                    logger.info(f"[SENDGRID] Sending email to: {[r['email'] for r in recipients]}")
                    logger.info(f"[SENDGRID] Subject: {subject}")
                    logger.info(f"[SENDGRID] From: {self.email_service.from_email}")
                    response = requests.post(sendgrid_url, headers=headers, json=email_data)
                    email_sent = response.status_code == 202
                    if not email_sent:
                        logger.error(f"SendGrid API error: {response.status_code} - {response.text}")
                    else:
                        logger.info(f"[SENDGRID] Email sent successfully with status code: {response.status_code}")
                except Exception as e:
                    logger.error(f"Error sending email via SendGrid: {e}", exc_info=True)
                    email_sent = False
            else:
                email_sent = False

            # Process email result
            if email_sent:
                successful_sends = len(recipients)
                failed_sends = 0
                logger.info(f"[OK] Email sent successfully to {len(recipients)} recipients for meeting: {meeting_title}")
                self._log_audit_event(
                    "email_sent",
                    "success",
                    f"Email sent for meeting: {meeting_title}",
                    {"recipients": [r["email"] for r in recipients]},
                )
                return json.dumps(
                    {
                        "status": "success",
                        "message": "Email sent successfully",
                        "recipients": [r["email"] for r in recipients],
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            else:
                failed_sends = len(recipients)
                successful_sends = 0
                logger.error(f"[ERROR] Failed to send email for meeting: {meeting_title}")
                self._log_audit_event(
                    "email_sent", "failure", f"Failed to send email for meeting: {meeting_title}", {}
                )
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Failed to send email",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        except Exception as e:
            logger.error(f"EmailNotificationTool error: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
            )

    async def _arun(
        self,
        summary_data: str,
    ) -> str:
        """Execute email notifications asynchronously."""
        return self._run(summary_data)

    def _validate_sendgrid_config(self) -> bool:
        """Validate SendGrid configuration."""
        return self.email_service is not None and self.sendgrid_api_key is not None

    def _filter_recipients(
        self,
        attendees: List[Dict[str, Any]],
        recipient_scope: str,
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Filter attendees based on recipient scope.
        
        NOTE: This method is no longer actively used since attendees are already
        filtered in _fetch_attendees_from_meetings_table. Kept for backward compatibility.

        Args:
            attendees: List of meeting attendees
            recipient_scope: "all_participants" or "only_me"
            user_id: Current user ID for filtering (deprecated - not used)

        Returns:
            Filtered list of recipients
        """
        # Attendees are already filtered by recipient_scope in _fetch_attendees_from_meetings_table
        # Just return them as-is
        logger.info(f"Returning {len(attendees)} attendees (already filtered by recipient_scope: {recipient_scope})")
        return attendees

    def _create_plain_text_email(
        self,
        to_name: str,
        meeting_title: str,
        summary_content: str,
        meeting_date: str,
        recipient_scope: str = "all_participants",
    ) -> str:
        """Create plain text email content using system prompts."""
        # System prompt for email generation
        system_prompt = """You are an AI assistant that creates professional meeting summary emails.
        Generate a concise, well-formatted plain text email that includes:
        1. A professional greeting
        2. Meeting title and date
        3. The summary content
        4. A professional closing
        5. Appropriate context based on recipient scope

        Keep the tone professional but friendly. Use proper email formatting with line breaks."""

        # Create email content using system prompt approach
        email_content = f"""Meeting Summary: {meeting_title}

Dear {to_name},

Here is the summary of the meeting that took place on {meeting_date}:

{summary_content}

If you have any questions about this meeting, please contact the meeting organizer.

Best regards,
Meeting Intelligence Agent
"""

        # Add recipient context based on scope
        if recipient_scope == "only_me":
            email_content += "\n\nNote: This summary was sent only to you."
        elif recipient_scope == "all_participants":
            email_content += (
                "\n\nNote: This summary was sent to all meeting participants."
            )

        return email_content

    def _load_email_template(self) -> str:
        """Load email template with Elevation AI design as primary, fallback to original.

        Tries the new Elevation AI template first, then falls back to the original template.
        """
        template_paths = [
            Path("client/meeting_agent_email.html").resolve(),
            Path("client/meeting-agent-email (1).html").resolve(),
        ]

        # Add environment path if set
        template_env_path = os.getenv("EMAIL_TEMPLATE_PATH")
        if template_env_path:
            template_paths.insert(0, Path(template_env_path).resolve())

        for template_path in template_paths:
            if template_path.exists():
                with open(template_path, "r", encoding="utf-8") as f:
                    template = f.read()
                logger.info(f"[OK] Email template loaded from {template_path}")
                return template

        raise FileNotFoundError(
            f"No email template found. Checked: {[str(p) for p in template_paths]}"
        )

    # Fallback template removed per requirement to use only the external HTML template

    def _create_html_email_from_json(
        self,
        summary_data: Dict[str, Any],
        meeting_title: str,
        meeting_date: str,
        calendar_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create HTML email content using Handlebars template and JSON data from summarizer.

        This method properly processes the JSON output from the summarizer tool and
        renders it using the Handlebars template at client/email_template.html.

        Args:
            summary_data: Full JSON data from summarizer tool
            meeting_title: Meeting title for fallback
            meeting_date: Meeting date for fallback

        Returns:
            Rendered HTML email content
        """
        try:
            # Load the Handlebars template
            template_str = self._load_email_template()
            compiler = Compiler()
            template = compiler.compile(template_str)

            # Transform the summarizer JSON to match the template's expected structure
            template_data = self._transform_summarizer_json_for_template(
                summary_data, meeting_title, meeting_date, calendar_metadata
            )

            # Render the template with the data
            html_content = template(template_data)

            logger.info("[OK] HTML email created using Handlebars template")
            return html_content

        except Exception as e:
            logger.error(f"[ERROR] Failed to render Handlebars template: {e}")
            # Fallback to the old method if Handlebars rendering fails
            return self._create_html_email(
                "Team", meeting_title, "", meeting_date, "all_participants"
            )

    def _transform_summarizer_json_for_template(
        self,
        summary_data: Dict[str, Any],
        meeting_title: str,
        meeting_date: str,
        calendar_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transform summarizer JSON output to match email template structure.

        The email template expects:
        - meeting_metadata: Meeting metadata with title, attendees
        - executive_summary: Executive summary text
        - tasks: List of task objects with assignee_name, title, description, etc.
        - decisions: List of decision objects
        - unresolved_questions: List of question objects
        - follow_up_needs: List of follow-up objects
        - year: Current year

        Args:
            summary_data: JSON from summarizer tool
            meeting_title: Meeting title
            meeting_date: Meeting date

        Returns:
            Dictionary matching template structure
        """
        # Extract data from summarizer output
        # Handle nested structure from summarizer tool
        if "summarizer_tool_response" in summary_data:
            summarizer_data = summary_data["summarizer_tool_response"]
            executive_summary = summarizer_data.get("executive_summary", "")
            tasks = summarizer_data.get("tasks", [])
            decisions = summarizer_data.get("decisions", [])
            unresolved_questions = summarizer_data.get("unresolved_questions", [])
            follow_up_needs = summarizer_data.get("follow_up_needs", [])
            meeting_metadata = summarizer_data.get("meeting_metadata", {})
        else:
            executive_summary = summary_data.get("executive_summary", "")
            tasks = summary_data.get("tasks", [])
            decisions = summary_data.get("decisions", [])
            unresolved_questions = summary_data.get("unresolved_questions", [])
            follow_up_needs = summary_data.get("follow_up_needs", [])
            meeting_metadata = summary_data.get("meeting_metadata", {})
        attendees = meeting_metadata.get("attendees", [])
        # Merge calendar attendees if provided
        if isinstance(calendar_metadata, dict):
            cal_attendees = calendar_metadata.get("attendees") or calendar_metadata.get("participants") or []
            if cal_attendees:
                attendees = list(attendees) + list(cal_attendees)

        # Normalize attendees to strings for the template
        def _attendee_to_string(a: Any) -> Optional[str]:
            try:
                if isinstance(a, str):
                    return a
                if isinstance(a, dict):
                    email = a.get("email")
                    name = a.get("name")
                    if email and name:
                        return f"{name} <{email}>"
                    if email:
                        return email
                    if name:
                        return name
                return None
            except Exception:
                return None

        attendees_strings: List[str] = []
        seen_attendees: set[str] = set()
        for a in attendees:
            s = _attendee_to_string(a)
            if s and s.lower() not in seen_attendees:
                attendees_strings.append(s)
                seen_attendees.add(s.lower())

        # Prefer summarizer links, else fallback to calendar metadata
        video_url = meeting_metadata.get("video_url")
        transcript_url = meeting_metadata.get("transcript_url")
        if not video_url and isinstance(calendar_metadata, dict):
            video_url = calendar_metadata.get("video_url") or calendar_metadata.get("meeting_link")
        if not transcript_url and isinstance(calendar_metadata, dict):
            transcript_url = calendar_metadata.get("transcript_url")

        # Friendly meeting date formatting
        pretty_meeting_date = meeting_date
        try:
            if isinstance(meeting_date, str) and ("T" in meeting_date or "-" in meeting_date):
                dt = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
                pretty_meeting_date = dt.strftime("%B %d, %Y %I:%M %p")
        except Exception:
            pass

        # Group tasks by assignee for the new template structure and enrich with priority color
        def _priority_color(priority: str) -> str:
            p = (priority or "").lower()
            if p == "high":
                return "#ed4341"
            if p == "medium":
                return "#fa8c16"
            return "#52c41a"  # low or default

        tasks_by_assignee = {}
        for task in tasks:
            assignee = task.get("assignee_name", "Unassigned")
            task["priority_color"] = _priority_color(task.get("priority", ""))
            # Enrich subtasks
            if isinstance(task.get("sub_tasks"), list):
                for st in task["sub_tasks"]:
                    st["priority_color"] = _priority_color(st.get("priority", ""))
            if assignee not in tasks_by_assignee:
                tasks_by_assignee[assignee] = {
                    "assignee_name": assignee,
                    "tasks": []
                }
            tasks_by_assignee[assignee]["tasks"].append(task)

        # Convert to list for template iteration
        tasks_by_assignee_list = list(tasks_by_assignee.values())

        # Return the transformed data for the template
        return {
            "meeting_metadata": {
                "title": meeting_title,
                "attendees": attendees_strings,
                "video_url": video_url or "",
                "transcript_url": transcript_url or "",
            },
            "executive_summary": executive_summary or "No executive summary available.",
            "tasks": tasks,
            "tasksByAssignee": tasks_by_assignee_list,
            "decisions": decisions,
            "unresolved_questions": unresolved_questions,
            "follow_up_needs": follow_up_needs,
            "meeting_date": pretty_meeting_date,
            "year": datetime.now().year
        }

    def _create_html_email(
        self,
        to_name: str,
        meeting_title: str,
        summary_content: str,
        meeting_date: str,
        recipient_scope: str = "all_participants",
    ) -> str:
        """Create HTML email content using external template."""
        # Load template from external file (strict)
        template = self._load_email_template()

        # Convert plain text summary to basic HTML formatting
        html_summary = summary_content.replace("\n", "<br>")

        # Calculate meeting duration (placeholder for now)
        meeting_duration = (
            "1 hour"  # This could be calculated from actual meeting data
        )

        # Create attendee list HTML
        attendee_list = f'<li class="attendee-item">{to_name}</li>'

        # Format meeting date
        try:
            if isinstance(meeting_date, str) and "T" in meeting_date:
                dt = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
                formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")
            else:
                formatted_date = str(meeting_date)
        except:
            formatted_date = str(meeting_date)

        # Replace template placeholders
        html_content = template.format(
            meeting_title=meeting_title,
            meeting_date=formatted_date,
            meeting_duration=meeting_duration,
            attendee_count=1,
            summary_content=html_summary,
            attendee_list=attendee_list,
            generated_date=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        )

        logger.info("[OK] HTML email created using external template")
        return html_content

        # No fallback: any exception will be raised to caller and handled as an error

    def _persist_summaries_to_drive(
        self,
        meeting_title: str,
        summary_content: str,
        meeting_date: str,
        attendees: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Persist meeting summaries to Google Drive with deterministic folder/file naming.

        Args:
            meeting_title: Title of the meeting
            summary_content: Summary content (JSON or text)
            meeting_date: Meeting date string
            attendees: List of attendee information

        Returns:
            Dictionary with persistence results including file IDs and links
        """
        if not self.drive_service:
            return {
                "status": "skipped",
                "message": "Google Drive service not available",
                "files": [],
            }

        try:
            # Create deterministic folder structure: Meeting Summaries/YYYY/MM/
            current_date = datetime.now()
            year_folder = f"Meeting Summaries"
            month_folder = f"{current_date.strftime('%Y-%m')}"

            # Find or create folder structure
            year_folder_id = self.drive_service.find_or_create_folder(year_folder)
            if not year_folder_id:
                return {
                    "status": "error",
                    "message": "Could not create year folder",
                    "files": [],
                }

            month_folder_id = self.drive_service.find_or_create_folder(
                month_folder, year_folder_id
            )
            if not month_folder_id:
                return {
                    "status": "error",
                    "message": "Could not create month folder",
                    "files": [],
                }

            # Create deterministic file names
            safe_title = re.sub(r"[^\w\s-]", "", meeting_title).strip()
            safe_title = re.sub(r"[-\s]+", "-", safe_title)
            timestamp = current_date.strftime("%Y%m%d_%H%M%S")

            base_filename = f"{timestamp}_{safe_title}"

            # Prepare summary data for JSON format
            summary_data = {
                "meeting_title": meeting_title,
                "meeting_date": meeting_date,
                "summary_content": summary_content,
                "attendees": attendees,
                "generated_at": current_date.isoformat(),
                "generated_by": "Meeting Intelligence Agent",
            }

            # Create HTML content for the summary
            html_content = self._create_drive_html_summary(
                meeting_title, summary_content, meeting_date, attendees
            )

            uploaded_files = []

            # Upload JSON summary
            try:
                json_content = json.dumps(summary_data, indent=2, ensure_ascii=False)
                json_file = self.drive_service.upload_file(
                    file_name=f"{base_filename}_summary.json",
                    content=json_content.encode("utf-8"),
                    mime_type="application/json",
                    parent_folder_id=month_folder_id,
                )

                if json_file and isinstance(json_file, dict):
                    uploaded_files.append(
                        {
                            "type": "json",
                            "file_id": json_file.get("id"),
                            "file_name": json_file.get("name"),
                            "web_link": json_file.get("webViewLink"),
                        }
                    )
                    logger.info(f"[OK] JSON summary saved: {json_file.get('name')}")
                else:
                    logger.warning(
                        f"[WARN] JSON upload returned unexpected format: {type(json_file)}"
                    )

            except Exception as e:
                logger.error(f"[ERROR] Error uploading JSON summary: {e}")

            # Upload HTML summary
            try:
                html_file = self.drive_service.upload_file(
                    file_name=f"{base_filename}_summary.html",
                    content=html_content.encode("utf-8"),
                    mime_type="text/html",
                    parent_folder_id=month_folder_id,
                )

                if html_file and isinstance(html_file, dict):
                    uploaded_files.append(
                        {
                            "type": "html",
                            "file_id": html_file.get("id"),
                            "file_name": html_file.get("name"),
                            "web_link": html_file.get("webViewLink"),
                        }
                    )
                    logger.info(f"[OK] HTML summary saved: {html_file.get('name')}")
                else:
                    logger.warning(
                        f"[WARN] HTML upload returned unexpected format: {type(html_file)}"
                    )

            except Exception as e:
                logger.error(f"[ERROR] Error uploading HTML summary: {e}")

            return {
                "status": "success",
                "message": f"Summaries saved to Google Drive",
                "folder_path": f"{year_folder}/{month_folder}",
                "files": uploaded_files,
                "total_files": len(uploaded_files),
            }

        except Exception as e:
            logger.error(f"[ERROR] Error persisting summaries to Drive: {e}")
            return {
                "status": "error",
                "message": f"Failed to persist summaries: {str(e)}",
                "files": [],
            }

    def _get_calendar_attendees(self) -> List[Dict[str, Any]]:
        """
        Get attendee emails directly from calendar events within the last 2 hours.
        
        Returns:
            List of attendee dictionaries with email and name
        """
        try:
            from src.tools.langchain_calendar_tool import LangchainCalendarTool
            
            # Initialize calendar tool with same auth handler
            calendar_tool = LangchainCalendarTool(
                user_id=self.user_id,
                org_id=self.org_id,
                agent_task_id=self.agent_task_id,
                auth=self.auth_handler
            )
            
            # Get recent events (use same time window as workflow - 30 minutes)
            events_result = calendar_tool.find_recent_events(minutes=30)
            
            if isinstance(events_result, str):
                events_data = json.loads(events_result)
            else:
                events_data = events_result
            
            if events_data.get("status") == "success" and events_data.get("events"):
                events = events_data.get("events", [])
                logger.info(f"EMAIL DEBUG: Found {len(events)} events from calendar tool")
                if events:
                    # Use the first event's attendees
                    first_event = events[0]
                    logger.info(f"EMAIL DEBUG: First event: {first_event}")
                    attendees = first_event.get("attendees", [])
                    logger.info(f"EMAIL DEBUG: Attendees from first event: {attendees}")
                    logger.info(f"Found {len(attendees)} calendar attendees from recent events")
                    return attendees
                else:
                    logger.info("EMAIL DEBUG: No events in events list")
            else:
                logger.info(f"EMAIL DEBUG: Calendar tool returned status: {events_data.get('status')}, events: {events_data.get('events')}")
            
            logger.info("No calendar events found in last 10 hours")
            return []
            
        except Exception as e:
            logger.error(f"Error getting calendar attendees: {e}")
            return []

    def _extract_attendees_from_transcript(self, summary_data: Any) -> List[str]:
        """
        Extract attendees from transcript content when not available in metadata.
        
        Args:
            summary_data: Summary data containing transcript information (can be dict or string)
            
        Returns:
            List of attendee names/emails extracted from transcript
        """
        try:
            attendees = []
            
            # Parse JSON string if needed
            if isinstance(summary_data, str):
                try:
                    import json
                    data = json.loads(summary_data)
                except json.JSONDecodeError:
                    logger.error("Failed to parse summary_data as JSON")
                    return []
            else:
                data = summary_data
            
            # Look for attendees in the summarizer tool response
            if "summarizer_tool_response" in data:
                summarizer_data = data["summarizer_tool_response"]
                meeting_metadata = summarizer_data.get("meeting_metadata", {})
                attendees = meeting_metadata.get("attendees", [])
            
            # If still no attendees, try to extract from the original transcript content
            if not attendees:
                # Look for "Invited" pattern in the data
                data_str = str(data)
                if "Invited" in data_str:
                    # Extract names after "Invited"
                    invited_match = re.search(r'Invited\s+([^\\r\\n]+)', data_str)
                    if invited_match:
                        invited_text = invited_match.group(1)
                        # Split by common separators and clean up
                        names = re.split(r'[,\s]+', invited_text)
                        attendees = [name.strip() for name in names if name.strip() and len(name.strip()) > 2]
            
            logger.info(f"Extracted attendees from transcript: {attendees}")
            return attendees
            
        except Exception as e:
            logger.error(f"Error extracting attendees from transcript: {e}")
            return []

    def _normalize_attendees(self, raw_attendees: List[Any], calendar_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Normalize attendee data to handle both string and dict formats.

        Args:
            raw_attendees: List of attendees (can be strings or dicts)

        Returns:
            List of normalized attendee dictionaries
        """
        normalized = []

        for attendee in raw_attendees:
            if isinstance(attendee, str):
                # Handle string format: "email@example.com" or "Name <email@example.com>"
                if "<" in attendee and ">" in attendee:
                    # Format: "Name <email@example.com>"
                    name, email = attendee.split("<", 1)
                    name = name.strip()
                    email = email.rstrip(">").strip()
                else:
                    attendee_str = attendee.strip()
                    # If it's a plain name without email, try to get email from calendar metadata
                    if "@" not in attendee_str:
                        logger.warning(f"Attendee '{attendee_str}' has no email - trying to get from calendar metadata")
                        # Try to get email from calendar metadata if available
                        if calendar_metadata and isinstance(calendar_metadata, dict):
                            events = calendar_metadata.get('events', [])
                            for event in events:
                                event_attendees = event.get('attendees', [])
                                for event_attendee in event_attendees:
                                    if isinstance(event_attendee, str) and "@" in event_attendee:
                                        email = event_attendee
                                        name = email.split("@")[0].replace(".", " ").title()
                                        normalized.append({"email": email, "name": name})
                                        logger.info(f"Found email for attendee '{attendee_str}': {email}")
                                        break
                        # If no email found in calendar metadata, create a fallback
                        logger.warning(f"No email found for attendee '{attendee_str}', skipping")
                        continue
                    else:
                        email = attendee_str
                        name = email.split("@")[0].replace(".", " ").title()

                if email:
                    normalized.append({"email": email, "name": name})
            elif isinstance(attendee, dict):
                # Handle dict format: {"email": "...", "name": "..."}
                email = attendee.get("email", "")
                name = attendee.get("name", "")

                if email:
                    if not name:
                        name = email.split("@")[0].replace(".", " ").title()

                    normalized.append({"email": email, "name": name})

        return normalized

    def _create_drive_html_summary(
        self,
        meeting_title: str,
        summary_content: str,
        meeting_date: str,
        attendees: List[Dict[str, Any]],
    ) -> str:
        """Create a comprehensive HTML summary for Drive storage."""

        # Parse summary content if it's JSON
        parsed_summary = summary_content
        if summary_content.strip().startswith("{"):
            try:
                summary_json = json.loads(summary_content)
                parsed_summary = json.dumps(summary_json, indent=2)
            except:
                pass

        # Convert to HTML with better formatting
        html_summary = parsed_summary.replace("\n", "<br>")

        # Create attendee list
        attendee_list = ""
        for attendee in attendees:
            name = attendee.get("name", "Unknown")
            email = attendee.get("email", "")
            attendee_list += f"<li><strong>{name}</strong> ({email})</li>"

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Meeting Summary: {meeting_title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px; background-color: #f8f9fa; }}
        .container {{ max-width: 900px; margin: 0 auto; background-color: white; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 32px; font-weight: 300; }}
        .meeting-info {{ background-color: rgba(255,255,255,0.1); padding: 20px; border-radius: 8px; margin-top: 20px; }}
        .content {{ padding: 30px; }}
        .section {{ background-color: #f8f9fa; padding: 25px; border-radius: 8px; border-left: 4px solid #667eea; margin: 25px 0; }}
        .attendees {{ background-color: #e8f5e8; border-left-color: #28a745; }}
        .summary {{ background-color: #fff3cd; border-left-color: #ffc107; }}
        .footer {{ background-color: #f1f3f4; padding: 20px; text-align: center; font-size: 14px; color: #666; }}
        h2 {{ color: #2c3e50; border-bottom: 2px solid #ecf0f1; padding-bottom: 10px; margin-top: 0; }}
        ul {{ list-style-type: none; padding-left: 0; }}
        li {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
        .metadata {{ font-size: 12px; color: #666; margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>[LIST] Meeting Summary</h1>
            <div class="meeting-info">
                <h2 style="margin: 0; color: white; border: none;">{meeting_title}</h2>
                <p style="margin: 10px 0 0 0; font-size: 18px;">Date: {meeting_date}</p>
            </div>
        </div>

        <div class="content">
            <div class="section attendees">
                <h2>Attendees ({len(attendees)})</h2>
                <ul>
                    {attendee_list}
                </ul>
            </div>

            <div class="section summary">
                <h2>[NOTE] Meeting Summary</h2>
                <div>{html_summary}</div>
            </div>

            <div class="metadata">
                <strong>[DATA] Document Metadata:</strong><br>
                Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                Source: Meeting Intelligence Agent<br>
                Format: HTML Summary Report
            </div>
        </div>

        <div class="footer">
            <p> This summary was automatically generated and saved by the Meeting Intelligence Agent.</p>
            <p>For questions about this meeting, please contact the meeting organizer.</p>
        </div>
    </div>
</body>
</html>
"""


"""
    Sends meeting summaries to attendees via SendGrid API with recipient selection.

    Capabilities:
    - Send formatted meeting summaries via email (HTML and plain text)
    - Choose recipient scope: all participants or only current user
    - Handle email delivery failures gracefully
    - Track email delivery status with SendGrid analytics
    - Store summaries in Google Drive for persistence
    - Comprehensive audit logging integration
    - Better deliverability and bounce handling

    Usage:
    - "send_email_summary(summary_data, recipient_scope='all_participants')" - Send to all attendees
    - "send_email_summary(summary_data, recipient_scope='only_me')" - Send only to current user

    Recipient Scope Options:
    - "all_participants": Send to all meeting attendees (default)
    - "only_me": Send only to the current user

    Input should be a JSON string containing summary data with attendee information.
    """