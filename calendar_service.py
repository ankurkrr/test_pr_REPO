"""
Google Calendar Service for Meeting Intelligence Workflow
"""

import logging
import pytz
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    """Calendar event data structure."""

    id: str
    summary: str
    start_time: datetime
    end_time: datetime
    attendees: List[str]
    organizer: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None  # Add timezone field for individual events


class GoogleCalendarService:
    """
    Google Calendar service for reading calendar events.
    """

    def __init__(self, auth_handler):
        """
        Initialize Calendar service.

        Args:
            auth_handler: GoogleAuthHandler instance
        """
        self.auth_handler = auth_handler
        self.service = None

    def _get_service(self):
        """Get Google Calendar service."""
        if not self.service:
            from src.auth.google_api_client import GoogleAPIClient
            api_client = GoogleAPIClient(self.auth_handler)
            self.service = api_client.get_calendar_service()
        return self.service

    def get_calendar_timezone(self, calendar_id: str = "primary") -> Optional[str]:
        """
        Get the timezone setting from the user's calendar.
        
        Args:
            calendar_id: Calendar ID (default: 'primary')
            
        Returns:
            Timezone string (e.g., 'America/New_York') or None if not found
        """
        try:
            service = self._get_service()
            if not service:
                logger.error("Calendar service not available")
                return None
            
            # Get calendar metadata which includes timezone
            calendar = service.calendars().get(calendarId=calendar_id).execute()
            timezone = calendar.get('timeZone')
            
            if timezone:
                logger.info(f"Retrieved calendar timezone: {timezone}")
                return timezone
            else:
                logger.warning("No timezone found in calendar settings")
                return None
                
        except HttpError as e:
            logger.error("Calendar API error getting timezone: %s", e)
            # Check if it's a token/scope issue
            if e.resp.status == 401 or 'invalid_scope' in str(e):
                logger.error("Authentication/scope error - token may be expired or invalid")
            return None
        except Exception as e:
            logger.error("Error getting calendar timezone: %s", e)
            return None

    def get_events_in_range(
        self, start_time: datetime, end_time: datetime, calendar_id: str = "primary"
    ) -> List[CalendarEvent]:
        """
        Get calendar events within a time range.

        Args:
            start_time: Start of time range
            end_time: End of time range
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            List of CalendarEvent objects
        """
        try:
            service = self._get_service()
            if not service:
                logger.error("Calendar service not available")
                return []

            # Format time for API - convert to UTC and format properly
            if start_time.tzinfo is not None:
                start_time = start_time.astimezone(pytz.UTC)
            if end_time.tzinfo is not None:
                end_time = end_time.astimezone(pytz.UTC)
            
            # Format as UTC without timezone info (API expects this format)
            time_min = start_time.replace(tzinfo=None).isoformat() + "Z"
            time_max = end_time.replace(tzinfo=None).isoformat() + "Z"

            logger.info("Fetching events from %s to %s", time_min, time_max)

            # Call the Calendar API
            events_result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            logger.info("Found %s events in time range", len(events))

            # Convert to CalendarEvent objects
            calendar_events = []
            for event in events:
                try:
                    calendar_event = self._parse_event(event)
                    if calendar_event:
                        calendar_events.append(calendar_event)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        "Failed to parse event %s: %s",
                        event.get("id", "unknown"),
                        e,
                    )
                    continue

            return calendar_events

        except HttpError as e:
            logger.error("Calendar API error: %s", e)
            # Check if it's a token/scope issue
            if e.resp.status == 401 or 'invalid_scope' in str(e):
                logger.error("Authentication/scope error - token may be expired or invalid")
            return []
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error fetching calendar events: %s", e)
            return []

    def _parse_event(self, event: Dict[str, Any]) -> Optional[CalendarEvent]:
        """
        Parse Google Calendar event into CalendarEvent object.

        Args:
            event: Raw event data from Google Calendar API

        Returns:
            CalendarEvent object or None if parsing fails
        """
        try:
            # Extract basic info
            event_id = event.get("id", "")
            summary = event.get("summary", "No Title")

            # Parse start and end times
            start_time = self._parse_datetime(event.get("start", {}))
            end_time = self._parse_datetime(event.get("end", {}))

            if not start_time or not end_time:
                logger.warning("Invalid datetime for event %s", event_id)
                return None

            # Extract timezone from event metadata
            event_timezone = self._extract_event_timezone(event)

            # Extract attendees
            attendees = []
            for attendee in event.get("attendees", []):
                email = attendee.get("email", "")
                if email:
                    attendees.append(email)

            # Extract organizer
            organizer = None
            if "organizer" in event:
                organizer = event["organizer"].get("email", "")

            return CalendarEvent(
                id=event_id,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                organizer=organizer,
                description=event.get("description", ""),
                location=event.get("location", ""),
                timezone=event_timezone,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error parsing event: %s", e)
            return None

    def _parse_datetime(self, datetime_obj: Dict[str, Any]) -> Optional[datetime]:
        """
        Parse Google Calendar datetime object.

        Args:
            datetime_obj: Datetime object from Google Calendar API

        Returns:
            Python datetime object or None if parsing fails
        """
        try:
            # Try 'dateTime' first (for specific times)
            if "dateTime" in datetime_obj:
                dt = datetime.fromisoformat(
                    datetime_obj["dateTime"].replace("Z", "+00:00")
                )
                # Ensure timezone-aware datetime
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                return dt

            # Fall back to 'date' (for all-day events)
            if "date" in datetime_obj:
                dt = datetime.fromisoformat(datetime_obj["date"])
                # For all-day events, set to UTC timezone
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                return dt

            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error parsing datetime %s: %s", datetime_obj, e)
            return None

    def _extract_event_timezone(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Extract timezone information from individual event metadata.
        
        Args:
            event: Raw event data from Google Calendar API
            
        Returns:
            Timezone string if found, None otherwise
        """
        try:
            # Method 1: Check if event has explicit timezone in start/end times
            start_data = event.get("start", {})
            end_data = event.get("end", {})
            
            # Look for timezone in start time
            if "timeZone" in start_data:
                timezone = start_data["timeZone"]
                logger.info(f"Found event timezone in start time: {timezone}")
                return timezone
            
            # Look for timezone in end time
            if "timeZone" in end_data:
                timezone = end_data["timeZone"]
                logger.info(f"Found event timezone in end time: {timezone}")
                return timezone
            
            # Method 2: Check if datetime strings contain timezone info
            start_datetime = start_data.get("dateTime", "")
            if start_datetime and ("+" in start_datetime or start_datetime.endswith("Z")):
                # Extract timezone from datetime string
                if "+" in start_datetime:
                    # Format: "2024-01-15T14:30:00+05:00"
                    timezone_part = start_datetime.split("+")[1]
                    if ":" in timezone_part:
                        offset_hours = int(timezone_part.split(":")[0])
                        offset_mins = int(timezone_part.split(":")[1])
                        # Convert offset to timezone name (simplified)
                        if offset_hours == 0 and offset_mins == 0:
                            return "UTC"
                        elif offset_hours == -5 and offset_mins == 0:
                            return "America/New_York"  # EST
                        elif offset_hours == -8 and offset_mins == 0:
                            return "America/Los_Angeles"  # PST
                        elif offset_hours == 9 and offset_mins == 0:
                            return "Asia/Tokyo"  # JST
                        # Add more timezone mappings as needed
                        else:
                            logger.info(f"Found timezone offset +{offset_hours}:{offset_mins:02d}, using UTC")
                            return "UTC"
                elif start_datetime.endswith("Z"):
                    return "UTC"
            
            # Method 3: Check event-level timezone metadata
            if "timeZone" in event:
                timezone = event["timeZone"]
                logger.info(f"Found event-level timezone: {timezone}")
                return timezone
            
            logger.debug(f"No timezone found for event {event.get('id', 'unknown')}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting event timezone: {e}")
            return None

    def get_recent_events(
        self, minutes: int = 30, calendar_id: str = "primary"
    ) -> List[CalendarEvent]:
        """
        Get recent events from the last N minutes.

        Args:
            minutes: Number of minutes to look back
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            List of recent CalendarEvent objects
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=minutes)

        return self.get_events_in_range(start_time, end_time, calendar_id)

    def search_events(
        self, query: str, max_results: int = 10, calendar_id: str = "primary"
    ) -> List[CalendarEvent]:
        """
        Search for events by query string.

        Args:
            query: Search query
            max_results: Maximum number of results
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            List of matching CalendarEvent objects
        """
        try:
            service = self._get_service()
            if not service:
                return []

            # Search events
            events_result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    q=query,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            logger.info("Found %s events matching query: %s", len(events), query)

            # Convert to CalendarEvent objects
            calendar_events = []
            for event in events:
                try:
                    calendar_event = self._parse_event(event)
                    if calendar_event:
                        calendar_events.append(calendar_event)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to parse search result event: %s", e)
                    continue

            return calendar_events

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error searching events: %s", e)
            return []