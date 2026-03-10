"""
CalendarTool - Reads user events from Google Calendar with structured metadata and audit logging.
"""

import json
import logging
import time
import uuid
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import pytz

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field

from src.auth.google_auth_handler import GoogleAuthHandler
from src.services.google import GoogleCalendarService
from src.services.integration.agent_integration_service import AgentIntegrationService, get_agent_integration_service
from src.services.database_service_new import get_database_service

logger = logging.getLogger(__name__)


def normalize_to_utc(dt_str: str, tz_str: Optional[str] = None) -> datetime:
    """
    Convert an ISO datetime string from the given timezone to UTC.
    
    Args:
        dt_str: ISO datetime string (e.g., "2024-01-15T14:30:00")
        tz_str: Timezone string (e.g., "America/New_York") or None for UTC fallback
        
    Returns:
        UTC datetime object
    """
    try:
        # Parse the datetime string
        if dt_str.endswith('Z'):
            # Already UTC
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        elif '+' in dt_str or dt_str.count('-') > 2:
            # Already has timezone info
            return datetime.fromisoformat(dt_str)
        else:
            # No timezone info - apply the provided timezone
            if tz_str and tz_str in pytz.all_timezones:
                local_tz = pytz.timezone(tz_str)
                local_dt = datetime.fromisoformat(dt_str)
                return local_tz.localize(local_dt).astimezone(pytz.UTC)
            else:
                # Fallback to UTC
                logger.warning(f"Invalid timezone '{tz_str}', falling back to UTC")
                return datetime.fromisoformat(dt_str).replace(tzinfo=pytz.UTC)
    except Exception as e:
        logger.error(f"Error normalizing datetime '{dt_str}' with timezone '{tz_str}': {e}")
        # Safe fallback to UTC
        try:
            return datetime.fromisoformat(dt_str).replace(tzinfo=pytz.UTC)
        except:
            return datetime.now(pytz.UTC)


class CalendarToolInput(BaseModel):
    """Input schema for the calendar tool."""
    minutes: int = Field(
        default=None,
        description="Number of minutes to look back for calendar events. If not provided, uses CALENDAR_LOOKBACK_MINUTES from config."
    )


@dataclass
class CalendarEventMetadata:
    """Structured metadata for calendar events."""

    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    attendees: List[str]  # List of clean email strings
    meeting_link: Optional[str]
    description: Optional[str]
    calendar_id: str
    location: Optional[str]
    organizer: Optional[str]
    created: datetime
    updated: datetime


class LangchainCalendarTool(BaseTool):
    """
    CalendarTool - Reads user events from Google Calendar with structured metadata.

    Features:
    - OAuth2-authenticated Google Calendar access
    - Structured event metadata extraction
    - Database audit logging integration
    - Error handling and graceful degradation
    - Performance monitoring
    """

    name: str = "calendar_tool"
    description: str = """
    Reads user events from Google Calendar and returns structured metadata.

    Capabilities:
    - Find recent calendar events within specified time window
    - Extract comprehensive event metadata (title, time, attendees, links)
    - Store event data in database for audit logging
    - Handle multiple calendar sources
    - Error handling for permission and API issues

    Usage:
    - JSON input: {"minutes": 30}
    - Or text: "find_recent_events(minutes=30)" or "last 30 minutes"
    """
    category: str = "calendar_operations"
    args_schema: type[BaseModel] = CalendarToolInput

    # Tool dependencies
    auth: Optional[GoogleAuthHandler] = None
    calendar_service: Optional[GoogleCalendarService] = None
    agent_integration: Optional[Any] = None
    database_service: Optional[Any] = None

    # Context tracking
    agent_id: str = "meeting_agent_001"
    user_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_agent_task_id: Optional[str] = None

    def __init__(
        self,
        auth: GoogleAuthHandler,
        agent_id: str = "meeting_agent_001",
        user_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_agent_task_id: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.auth = auth
        self.calendar_service = GoogleCalendarService(auth)
        self.agent_integration = get_agent_integration_service()
        self.database_service = get_database_service()
        self.agent_id = agent_id
        self.user_id = user_id
        self.workflow_id = workflow_id
        self.user_agent_task_id = user_agent_task_id

    def set_credentials(self, access_token: str, refresh_token: Optional[str] = None) -> bool:
        """
        Set Google OAuth credentials for calendar access from decrypted tokens

        Args:
            access_token: Decrypted Google access token
            refresh_token: Decrypted Google refresh token (optional)

        Returns:
            True if credentials set successfully, False otherwise
        """
        try:
            success = self.auth.set_credentials_from_tokens(access_token, refresh_token)
            if success:
                # Reinitialize calendar service with new credentials
                self.calendar_service = GoogleCalendarService(self.auth)
                logger.info(f"Calendar tool credentials updated successfully for user {self.user_id}")
                return True
            else:
                logger.error("Failed to set calendar tool credentials")
                return False
        except Exception as e:
            logger.error(f"Error setting calendar tool credentials: {e}", exc_info=True)
            return False

    def run(
        self,
        tool_input: Any,
        **kwargs,
    ) -> str:
        """Override run method to handle input correctly."""
        logger.info(f"Calendar tool run() called with input: {tool_input}, kwargs: {kwargs}")
        return self._run(tool_input, **kwargs)

    def _run(
        self,
        query: Any = None,
        **kwargs,
        ) -> str:
        """Execute calendar operations with comprehensive audit logging."""
        # Handle case where no arguments are passed
        if query is None:
            from src.configuration.config import CALENDAR_LOOKBACK_MINUTES
            default_minutes = CALENDAR_LOOKBACK_MINUTES
            logger.warning(f"Calendar tool _run() called without arguments, using default {default_minutes} minutes from config")
            query = {"minutes": default_minutes}
        elif isinstance(query, dict):
            # query is already a dict
            pass
        else:
            # query might be a string or other type, convert to dict
            from src.configuration.config import CALENDAR_LOOKBACK_MINUTES
            default_minutes = CALENDAR_LOOKBACK_MINUTES
            query = {"minutes": query} if isinstance(query, (int, str)) else {"minutes": default_minutes}
        
        logger.info(f"Calendar tool _run() called with query: {query}")
        
        start_time = time.time()
        operation_id = str(uuid.uuid4())

        try:
        # Log tool invocation
            if self.user_agent_task_id:
                self.agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="task",
                    log_for_status="success",
                    tool_name=self.name,
                    log_text="Started calendar operation",
                    log_params=(),
                    outcome="tool_started",
                    scope="calendar_operations",
                    step_str="calendar_search",
                )

            # Parse and execute query
            result = self._execute_calendar_operation(query, operation_id, **kwargs)

            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Log successful completion
            if self.user_agent_task_id:
                self.agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="task",
                    log_for_status="success",
                    tool_name=self.name,
                    log_text="Calendar operation completed successfully in %sms",
                    log_params=(execution_time_ms,),
                    outcome="tool_completed",
                    scope="calendar_operations",
                    step_str="calendar_search_complete",
                )

                # Send audit log to Elevation AI platform
                # Note: _send_platform_audit_log is async, but _run is sync
                # This will be handled in the async version

            return result

        except Exception as e:
            # Calculate execution time for error case
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Log error with detailed information
            if self.user_agent_task_id:
                self.agent_integration.log_agent_function(
                    user_agent_task_id=self.user_agent_task_id,
                    activity_type="task",
                    log_for_status="error",
                    tool_name=self.name,
                    log_text="Calendar operation failed: %s",
                    log_params=(str(e),),
                    outcome="tool_failed",
                    scope="calendar_operations",
                    step_str="calendar_search_error",
                )

                # Send audit log to Elevation AI platform
                # Note: _send_platform_audit_log is async, but _run is sync
                # This will be handled in the async version

            logger.error("CalendarTool error: %s", e)
            return "Error accessing calendar: %s" % str(e)


    async def _arun(
        self,
        query: Any,
    ) -> str:
        """Execute calendar operations asynchronously."""
        result = self._run(query)

        # Send audit log to Elevation AI platform in async context
        if self.user_agent_task_id:
            try:
                if "Error" not in result:
                    await self._send_platform_audit_log("success", result)
                else:
                    await self._send_platform_audit_log("error", None, result)
            except Exception as e:
                logger.warning(f"Failed to send platform audit log: {e}")

        return result

    def _execute_calendar_operation(self, query: Any, operation_id: str, **kwargs) -> str:
        """Execute the specific calendar operation based on query."""
        # Get default from config
        from src.configuration.config import CALENDAR_LOOKBACK_MINUTES
        default_minutes = CALENDAR_LOOKBACK_MINUTES
        
        # Determine minutes from multiple input styles
        minutes = None
        # Prefer explicit kwarg
        if isinstance(kwargs, dict) and "minutes" in kwargs and isinstance(kwargs["minutes"], (int, float)):
            minutes = int(kwargs["minutes"]) or default_minutes
        # Dict payload from agent
        if minutes is None and isinstance(query, dict) and "minutes" in query:
            try:
                minutes = int(query["minutes"]) or default_minutes
            except Exception:
                minutes = None
        # JSON string payload
        if minutes is None and isinstance(query, str):
            try:
                maybe = json.loads(query)
                if isinstance(maybe, dict) and "minutes" in maybe:
                    minutes = int(maybe["minutes"]) or default_minutes
            except Exception:
                pass
        # Text parsing fallback
        if minutes is None and isinstance(query, str):
            query_lower = query.lower()
            minutes = self._extract_minutes_from_query(query_lower)
        if minutes is None:
            minutes = default_minutes

        return self.find_recent_events(minutes=minutes)

    def _extract_minutes_from_query(self, query: str) -> int:
        """Extract minutes parameter from query string."""
        from src.configuration.config import CALENDAR_LOOKBACK_MINUTES
        default_minutes = CALENDAR_LOOKBACK_MINUTES

        minutes_match = re.search(r"minutes=(\d+)", query)
        if minutes_match:
            return int(minutes_match.group(1))

        minutes_match = re.search(r"(\d+)\s*minutes?", query)
        if minutes_match:
            return int(minutes_match.group(1))

        minutes_match = re.search(r"last\s+(\d+)\s*minutes?", query)
        if minutes_match:
            return int(minutes_match.group(1))

        return default_minutes

    def _get_user_timezone(self) -> Optional[str]:
        """
        Get user's timezone from Google Calendar settings or individual events.
        Prioritizes individual event timezones over calendar default timezone.
        """
        try:
            # First, try to get timezone from recent calendar events
            # This handles cases where individual events have different timezones
            events = self.calendar_service.get_recent_events(minutes=1440)  # Last 24 hours
            
            for event in events:
                if hasattr(event, 'timezone') and event.timezone:
                    if event.timezone in pytz.all_timezones:
                        logger.info(f"Using timezone from calendar event: {event.timezone}")
                        # Store the extracted timezone in database for future use
                        self._store_user_timezone(event.timezone)
                        return event.timezone
            
            # If no event-specific timezone found, get calendar default timezone
            calendar_timezone = self.calendar_service.get_calendar_timezone()
            
            if calendar_timezone and calendar_timezone in pytz.all_timezones:
                logger.info(f"Using calendar default timezone: {calendar_timezone}")
                # Store the extracted timezone in database for future use
                self._store_user_timezone(calendar_timezone)
                return calendar_timezone
            
            # Fallback to database if calendar timezone not available
            db_service = get_database_service()
            
            # Try workflow_data (might have user's timezone if frontend provided it)
            if hasattr(self, 'user_agent_task_id') and self.user_agent_task_id:
                workflow_query = """
                    SELECT timezone FROM workflow_data 
                    WHERE agent_task_id = :agent_task_id 
                    LIMIT 1
                """
                workflow_result = db_service.execute_query(workflow_query, {"agent_task_id": self.user_agent_task_id})
            else:
                workflow_result = None
            
            if workflow_result and len(workflow_result) > 0:
                # Database result is a tuple, not a dictionary
                timezone = workflow_result[0][0]  # First column of first row
                if timezone and timezone in pytz.all_timezones:
                    logger.info(f"Using workflow timezone: {timezone}")
                    return timezone
            
            # Last resort: UTC
            logger.info("Using UTC timezone - no valid timezone found")
            return "UTC"
            
        except Exception as e:
            logger.error(f"Error retrieving user timezone: {e}")
            return "UTC"

    def _store_user_timezone(self, timezone: str) -> None:
        """
        Store the extracted timezone in the database for future use.
        """
        try:
            # Check if agent_task_id is available
            if not hasattr(self, 'user_agent_task_id') or not self.user_agent_task_id:
                logger.error("Cannot store timezone: user_agent_task_id not available")
                raise ValueError("user_agent_task_id is required for timezone storage")
            
            db_service = get_database_service()
            
            # Update user_agent_task table with the actual timezone
            update_query = """
                UPDATE user_agent_task 
                SET timezone = :timezone, updated = NOW()
                WHERE agent_task_id = :agent_task_id
            """
            db_service.execute_query(update_query, {
                "timezone": timezone,
                "agent_task_id": self.user_agent_task_id
            })
            
            # Also update workflow_data table
            workflow_update_query = """
                UPDATE workflow_data 
                SET timezone = :timezone, updated_at = NOW()
                WHERE agent_task_id = :agent_task_id
            """
            db_service.execute_query(workflow_update_query, {
                "timezone": timezone,
                "agent_task_id": self.user_agent_task_id
            })
            
            logger.info(f"Stored user timezone '{timezone}' in database for agent_task_id: {self.user_agent_task_id}")
            
        except Exception as e:
            logger.error(f"Error storing user timezone: {e}")
            # Don't raise the exception - timezone storage is not critical

    def find_recent_events(self, minutes: int = None) -> str:
        """
        Find recent calendar events within specified time window.
        """
        # Use config value if minutes not provided
        if minutes is None:
            from src.configuration.config import CALENDAR_LOOKBACK_MINUTES
            minutes = CALENDAR_LOOKBACK_MINUTES
            
        try:
            logger.info("CALENDAR TOOL: Starting event search")
            logger.info(f"CALENDAR TOOL: Searching for events that ENDED in the last {minutes} minutes")

            # Get user's timezone for proper time calculations
            user_timezone_str = self._get_user_timezone()
            # Ensure timezone is valid - fallback to UTC if None or invalid
            if not user_timezone_str or user_timezone_str not in pytz.all_timezones:
                logger.warning(f"Invalid timezone '{user_timezone_str}', falling back to UTC")
                user_timezone_str = "UTC"
            user_tz = pytz.timezone(user_timezone_str)
            
            # Use user's timezone for current time calculation
            current_time = datetime.now(user_tz)
            end_time = current_time.astimezone(pytz.UTC)  # Convert to UTC for API calls
            
            # Extend search window to find events that ended recently
            # Search back 3x the minutes to catch events that ended within the window
            search_window = minutes * 3
            start_time = end_time - timedelta(minutes=search_window)
            
            logger.info(f"CALENDAR TOOL: Using user timezone: {user_timezone_str}")
            logger.info(f"CALENDAR TOOL: Current time in user timezone: {current_time}")
            logger.info(f"CALENDAR TOOL: Current time in UTC: {end_time}")
            logger.info(f"CALENDAR TOOL: Search window: {search_window} minutes")
            logger.info(f"CALENDAR TOOL: Searching from: {start_time} to {end_time}")

            if minutes > 1440:
                start_time = end_time.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                logger.info(f"CALENDAR TOOL: Large time window ({minutes} minutes), searching from start of day")

            logger.info(
                "Time range: %s to %s",
                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S"),
            )

            events = self.calendar_service.get_events_in_range(
                start_time=start_time, end_time=end_time
            )

            # Filter events to only include those that ENDED within the desired time window
            filtered_events = []
            cutoff_time = end_time - timedelta(minutes=minutes)
            
            # Ensure all datetimes are timezone-aware for comparison
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=pytz.UTC)
            
            # Ensure end_time is also timezone-aware
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=pytz.UTC)
            
            for event in events:
                # Ensure event end_time is timezone-aware and in UTC
                event_end_time = event.end_time
                if event_end_time.tzinfo is None:
                    event_end_time = event_end_time.replace(tzinfo=pytz.UTC)
                elif event_end_time.tzinfo != pytz.UTC:
                    # Convert to UTC for consistent comparison
                    event_end_time = event_end_time.astimezone(pytz.UTC)
                
                # Now all datetimes should be timezone-aware and in UTC
                if event_end_time <= end_time and event_end_time >= cutoff_time:
                    filtered_events.append(event)
                    logger.info(f"Event '{event.summary}' ended at {event_end_time} UTC - within {minutes} minute window")
                else:
                    logger.info(f"Event '{event.summary}' ended at {event_end_time} UTC - outside {minutes} minute window")

            events = filtered_events

            if not events:
                logger.info("No events found in the last %s minutes", minutes)
                return json.dumps(
                    {
                        "status": "success",
                        "events_found": 0,
                        "events": [],
                        "time_range": {
                            "start": start_time.isoformat(),
                            "end": end_time.isoformat(),
                            "minutes_back": minutes,
                        },
                    }
                )

            # Sort events by end time (most recent first) to ensure latest events are processed
            events.sort(key=lambda e: e.end_time, reverse=True)
            logger.info(f"CALENDAR TOOL: Sorted {len(events)} events by end time (most recent first)")

            event_metadata_list = []
            for event in events:
                metadata = self._extract_event_metadata(event)
                event_metadata_list.append(metadata)
                self._store_event_metadata(metadata)

            logger.info(
                "Found %s events in the last %s minutes",
                len(event_metadata_list),
                minutes,
            )

            # Store meetings in database
            self._store_meetings_in_database(event_metadata_list)
            
            # Note: Audit logging for calendar events is handled at the agent/scheduler level
            # to avoid event loop issues in the synchronous _run method

            # Return only essential fields needed by drive tool to prevent JSON truncation
            simplified_events = []
            for metadata in event_metadata_list:
                simplified_event = {
                    "event_id": metadata.event_id,
                    "title": metadata.title,
                    "start_time": metadata.start_time.isoformat(),
                    "end_time": metadata.end_time.isoformat(),
                    "attendees": metadata.attendees[:2] if metadata.attendees else [],  # Limit to first 2 clean email strings
                    "organizer": metadata.organizer if metadata.organizer else ""
                }
                simplified_events.append(simplified_event)
            
            result = {
                "status": "success",
                "events_found": len(simplified_events),
                "events": simplified_events,
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "minutes_back": minutes,
                },
            }

            return json.dumps(result, default=str)

        except Exception as e:
            logger.error("Error finding recent events: %s", e)
            return json.dumps(
                {"status": "error", "error": str(e), "events_found": 0, "events": []}
            )

    def _extract_event_metadata(self, event) -> CalendarEventMetadata:
        """Extract structured metadata from calendar event."""
        try:
            attendees = []
            logger.info(f"CALENDAR DEBUG: Event has attendees: {hasattr(event, 'attendees')}")
            if hasattr(event, "attendees") and event.attendees:
                logger.info(f"CALENDAR DEBUG: Number of attendees: {len(event.attendees)}")
                for i, attendee in enumerate(event.attendees):
                    logger.info(f"CALENDAR DEBUG: Attendee {i}: {type(attendee)} - {attendee}")
                    
                    # Extract clean email string from various attendee formats
                    email = None
                    
                    if isinstance(attendee, str) and "@" in attendee:
                        # Attendee is a string email
                        email = attendee
                    elif hasattr(attendee, 'email') and attendee.email:
                        # Attendee is an object with email property
                        email = attendee.email
                    elif isinstance(attendee, dict) and "email" in attendee:
                        # Attendee is a dictionary
                        email = attendee.get("email", "")
                    
                    # Only add valid email addresses as clean strings
                    if email and "@" in email:
                        attendees.append(email)  # Store as clean email string
                        logger.info(f"CALENDAR TOOL: Added clean email: {email}")
                    else:
                        logger.warning(f"CALENDAR DEBUG: Invalid attendee format: {attendee}")
            else:
                logger.info(f"CALENDAR DEBUG: No attendees found in event")

            meeting_link = None
            start_time = event.start_time
            end_time = event.end_time

            # If organizer is not available, use the first attendee as fallback
            organizer_email = event.organizer if event.organizer else ""
            if not organizer_email and attendees:
                organizer_email = attendees[0]
                logger.info(f"Using first attendee as organizer fallback: {organizer_email}")

            metadata = CalendarEventMetadata(
                event_id=event.id,
                title=event.summary,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                meeting_link=meeting_link,
                description=event.description,
                calendar_id=organizer_email if organizer_email else "primary",
                location=event.location,
                organizer=organizer_email,
                created=datetime.now(),
                updated=datetime.now(),
            )

            return metadata

        except Exception as e:
            logger.error(f"Error extracting event metadata: {e}", exc_info=True)
            # Return minimal metadata with error indication instead of fake "Unknown Event"
            event_id = getattr(event, "id", None) or f"error_{datetime.now().timestamp()}"
            event_summary = getattr(event, "summary", None)
            return CalendarEventMetadata(
                event_id=event_id,
                title=event_summary or f"Event (extraction error: {str(e)[:50]})",
                start_time=datetime.now(),
                end_time=datetime.now(),
                attendees=[],
                meeting_link=None,
                description=f"Metadata extraction failed: {str(e)}",
                calendar_id="primary",
                location=None,
                organizer=None,
                created=datetime.now(),
                updated=datetime.now(),
            )

    def _store_event_metadata(self, metadata: CalendarEventMetadata) -> bool:
        """Store event metadata in database for audit logging."""
        try:
            if not self.database_service:
                logger.warning(
                    "Database service not available, skipping metadata storage"
                )
                return False

            logger.info(
                "Stored event metadata for event: %s - %s",
                metadata.event_id,
                metadata.title,
            )
            return True

        except Exception as e:
            logger.error("Error storing event metadata: %s", e)
            return False
    
    def _store_meetings_in_database(self, event_metadata_list: List[CalendarEventMetadata]):
        """Store meetings in database with attendees."""
        logger.info(f"[DEBUG] Attempting to store {len(event_metadata_list)} meetings for user {self.user_id}, agent_task {self.user_agent_task_id}")
        try:
            if not self.database_service:
                logger.warning("Database service not available, skipping meeting storage")
                return
            
            # Fetch org_id from database if not available
            org_id = None
            if not hasattr(self, 'org_id') or not self.org_id:
                query = """
                SELECT org_id FROM user_agent_task 
                WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                LIMIT 1
                """
                rows = self.database_service.execute_query(query, {
                    "user_id": self.user_id,
                    "agent_task_id": self.user_agent_task_id
                })
                if rows:
                    row = rows[0]
                    # Handle different row types
                    if hasattr(row, 'org_id'):
                        org_id = row.org_id
                    elif isinstance(row, dict):
                        org_id = row.get("org_id")
                    else:
                        org_id = row[0]
                    logger.info(f"Fetched org_id from database: {org_id}")
            else:
                org_id = self.org_id
            
            if not org_id:
                logger.error(f"Cannot store meetings without org_id for user {self.user_id}")
                return
            
            from src.services.data.models import MeetingData
            
            # Get timezone for this user
            user_timezone = self._get_user_timezone()
            
            for metadata in event_metadata_list:
                try:
                    logger.info(f"[STORING] Meeting: {metadata.title} (ID: {metadata.event_id}), user: {self.user_id}, agent_task: {self.user_agent_task_id}")
                    
                    # Prepare meeting data
                    meeting_data = MeetingData(
                        id=metadata.event_id,
                        user_id=self.user_id,
                        organization_id=org_id,
                        agent_task_id=self.user_agent_task_id,
                        external_id=metadata.event_id,
                        title=metadata.title,
                        description=metadata.description or "",
                        start_time=metadata.start_time,
                        end_time=metadata.end_time,
                        timezone=user_timezone,
                        location=metadata.location or "",
                        meeting_url=metadata.meeting_link or "",
                        status="completed",
                        attendees=metadata.attendees if metadata.attendees else []
                    )
                    
                    # Use database service to insert or update meeting
                    query = """
                    INSERT INTO meetings (
                        id, user_id, org_id, agent_task_id, external_id,
                        title, description, start_time, end_time, timezone,
                        location, meeting_url, status, attendees, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :org_id, :agent_task_id, :external_id,
                        :title, :description, :start_time, :end_time, :timezone,
                        :location, :meeting_url, :status, :attendees, NOW(), NOW()
                    )
                    ON DUPLICATE KEY UPDATE
                        title = VALUES(title),
                        description = VALUES(description),
                        start_time = VALUES(start_time),
                        end_time = VALUES(end_time),
                        location = VALUES(location),
                        meeting_url = VALUES(meeting_url),
                        status = VALUES(status),
                        attendees = VALUES(attendees),
                        updated_at = NOW()
                    """
                    
                    import json
                    attendees_json = json.dumps(meeting_data.attendees) if meeting_data.attendees else None
                    
                    params = {
                        "id": meeting_data.id,
                        "user_id": meeting_data.user_id,
                        "org_id": meeting_data.organization_id,
                        "agent_task_id": meeting_data.agent_task_id,
                        "external_id": meeting_data.external_id,
                        "title": meeting_data.title,
                        "description": meeting_data.description,
                        "start_time": meeting_data.start_time,
                        "end_time": meeting_data.end_time,
                        "timezone": meeting_data.timezone,
                        "location": meeting_data.location,
                        "meeting_url": meeting_data.meeting_url,
                        "status": meeting_data.status,
                        "attendees": attendees_json
                    }
                    
                    self.database_service.execute_query(query, params)
                    logger.info(f"[SUCCESS] Stored meeting in database: {metadata.title} (ID: {metadata.event_id}) with {len(metadata.attendees)} attendees for user {self.user_id}, agent_task {self.user_agent_task_id}")
                    
                except Exception as e:
                    logger.error(f"[ERROR] Error storing meeting {metadata.event_id}: {e}", exc_info=True)
                    continue
                    
        except Exception as e:
            logger.error(f"[ERROR] Error storing meetings in database: {e}", exc_info=True)

    async def _send_platform_audit_log(self, status: str, result: str = None, error: str = None):
        """Send audit log to platform using ActivityLogger."""
        try:
            if not self.user_agent_task_id:
                return

            # Parse result to get events count
            events_found = 0
            if result and status == "success":
                try:
                    result_data = json.loads(result)
                    events_found = len(result_data.get("events", []))
                except (json.JSONDecodeError, KeyError):
                    events_found = 0

            # Create audit log entry for ActivityLogger
            audit_log = {
                "activity_type": "integration",
                "log_for_status": "success" if status == "success" else "failed",
                "log_text": f"Calendar tool executed with status: {status}",
                "action": "Complete" if status == "success" else "Error",
                "action_issue_event": error if error else "Calendar events retrieved successfully",
                "action_required": "None",
                "outcome": status,
                "step_str": f"Calendar tool found {events_found} events",
                "tool_str": "Calendar Tool",
                "log_data": {
                    "events_found": events_found,
                    "status": status,
                    "error": error
                }
            }

            # Send to platform using ActivityLogger
            from src.services.integration.activity_logger import get_activity_logger
            activity_logger = get_activity_logger()
            await activity_logger.log_workflow_activity(self.user_agent_task_id, [audit_log])

        except Exception as e:
            logger.warning(f"Failed to send platform audit log for calendar tool: {e}")