"""
Elevation AI Platform Integration Service
Handles fetching meeting task data from the platform API and creating Google Calendar events
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from src.services.integration.platform_api_client import PlatformAPIClient
from src.services.google import GoogleCalendarService

logger = logging.getLogger(__name__)

@dataclass
class TaskEventData:
    """Data structure for task-based calendar events"""
    task_id: str
    title: str
    description: str
    end_date: datetime
    is_subtask: bool = False
    parent_task_id: Optional[str] = None
    notify_to: str = "only_me"  # 'all' or 'only_me'

class ElevationAIIntegrationService:
    """
    Service for integrating with Elevation AI platform API and Google Calendar
    """

    def __init__(self, platform_token: str, google_auth: Optional[Any] = None):
        """
        Initialize the integration service

        Args:
            platform_token: Decrypted platform token for Elevation AI API authorization
            google_auth: Google authenticator instance (will create if not provided)
        """
        self.platform_token = platform_token
        self.platform_client = PlatformAPIClient()
        self.google_auth = google_auth or GoogleAuthenticator()
        self.calendar_service = GoogleCalendarService(self.google_auth)

    def fetch_meeting_task_data(self, agent_task_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch meeting task data from Elevation AI platform API

        Args:
            agent_task_id: The agent task ID to fetch data for

        Returns:
            Task data with tasks and sub_tasks or None if failed
        """
        try:
            logger.info(f"Fetching meeting task data for agent_task_id: {agent_task_id}")

            # Construct API endpoint for fetching task data
            endpoint = f"/api/agent-tasks/{agent_task_id}"

            headers = {
                'Authorization': f'Bearer {self.platform_token}',
                'Content-Type': 'application/json'
            }

            # Make request to platform API
            result = self.platform_client._make_request(
                method='GET',
                endpoint=endpoint,
                headers=headers
            )

            if result:
                logger.info(f"Successfully fetched task data: {len(result.get('tasks', []))} tasks, {len(result.get('sub_tasks', []))} sub-tasks")
                return result
            else:
                logger.error(f"Failed to fetch task data for agent_task_id: {agent_task_id}")
                return None

        except Exception as e:
            logger.error(f"Error fetching meeting task data: {e}")
            return None

    def parse_task_data_to_events(self, task_data: Dict[str, Any]) -> List[TaskEventData]:
        """
        Parse task data from platform API into calendar event data structures

        Args:
            task_data: Raw task data from platform API

        Returns:
            List of TaskEventData objects ready for calendar creation
        """
        events = []

        try:
            # Extract notify_to preference (default to 'only_me')
            notify_to = task_data.get('notify_to', 'only_me')

            # Process main tasks
            tasks = task_data.get('tasks', [])
            for task in tasks:
                try:
                    # Parse end_date
                    end_date_str = task.get('end_date')
                    if not end_date_str:
                        logger.warning(f"Task {task.get('id', 'unknown')} missing end_date, skipping")
                        continue

                    # Parse datetime (handle various formats)
                    end_date = self._parse_datetime(end_date_str)
                    if not end_date:
                        logger.warning(f"Task {task.get('id', 'unknown')} has invalid end_date format: {end_date_str}")
                        continue

                    event_data = TaskEventData(
                        task_id=task.get('id', ''),
                        title=task.get('title', 'Meeting Task'),
                        description=task.get('description', 'Task created from meeting intelligence'),
                        end_date=end_date,
                        is_subtask=False,
                        notify_to=notify_to
                    )
                    events.append(event_data)

                except Exception as e:
                    logger.error(f"Error parsing task {task.get('id', 'unknown')}: {e}")
                    continue

            # Process sub-tasks
            sub_tasks = task_data.get('sub_tasks', [])
            for sub_task in sub_tasks:
                try:
                    # Parse end_date
                    end_date_str = sub_task.get('end_date')
                    if not end_date_str:
                        logger.warning(f"Sub-task {sub_task.get('id', 'unknown')} missing end_date, skipping")
                        continue

                    end_date = self._parse_datetime(end_date_str)
                    if not end_date:
                        logger.warning(f"Sub-task {sub_task.get('id', 'unknown')} has invalid end_date format: {end_date_str}")
                        continue

                    event_data = TaskEventData(
                        task_id=sub_task.get('id', ''),
                        title=f" {sub_task.get('title', 'Meeting Sub-task')}",  # Add emoji to distinguish
                        description=sub_task.get('description', 'Sub-task created from meeting intelligence'),
                        end_date=end_date,
                        is_subtask=True,
                        parent_task_id=sub_task.get('parent_task_id'),
                        notify_to=notify_to
                    )
                    events.append(event_data)

                except Exception as e:
                    logger.error(f"Error parsing sub-task {sub_task.get('id', 'unknown')}: {e}")
                    continue

            logger.info(f"Parsed {len(events)} events from task data ({len(tasks)} tasks, {len(sub_tasks)} sub-tasks)")
            return events

        except Exception as e:
            logger.error(f"Error parsing task data to events: {e}")
            return []

    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """
        Parse datetime string in various formats

        Args:
            date_str: Date string to parse

        Returns:
            Parsed datetime or None if failed
        """
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%d/%m/%Y'
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Try ISO format parsing
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            pass

        return None

    def create_calendar_events(self, events: List[TaskEventData]) -> Dict[str, Any]:
        """
        Create Google Calendar events for the provided task events

        Args:
            events: List of TaskEventData objects to create calendar events for

        Returns:
            Summary of created events and any errors
        """
        results = {
            'created_events': [],
            'failed_events': [],
            'total_events': len(events),
            'success_count': 0,
            'error_count': 0
        }

        try:
            calendar_service = self.google_auth.get_calendar_service()
            if not calendar_service:
                logger.error("Failed to get Google Calendar service")
                return results

            for event_data in events:
                try:
                    # Create event with deadline as the end time
                    # Set start time 1 hour before deadline for planning
                    start_time = event_data.end_date - timedelta(hours=1)
                    end_time = event_data.end_date

                    # Build event body
                    event_body = {
                        'summary': event_data.title,
                        'description': f"{event_data.description}\n\nTask ID: {event_data.task_id}\nType: {'Sub-task' if event_data.is_subtask else 'Main Task'}\nNotification: {event_data.notify_to}",
                        'start': {
                            'dateTime': start_time.isoformat(),
                            'timeZone': 'UTC'
                        },
                        'end': {
                            'dateTime': end_time.isoformat(),
                            'timeZone': 'UTC'
                        },
                        'reminders': {
                            'useDefault': False,
                            'overrides': [
                                {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                                {'method': 'popup', 'minutes': 60},       # 1 hour before
                            ]
                        }
                    }

                    # Create the event
                    created_event = calendar_service.events().insert(
                        calendarId='primary',
                        body=event_body
                    ).execute()

                    results['created_events'].append({
                        'task_id': event_data.task_id,
                        'event_id': created_event.get('id'),
                        'title': event_data.title,
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'is_subtask': event_data.is_subtask
                    })
                    results['success_count'] += 1

                    logger.info(f"Created calendar event for task {event_data.task_id}: {event_data.title}")

                except Exception as e:
                    logger.error(f"Failed to create calendar event for task {event_data.task_id}: {e}")
                    results['failed_events'].append({
                        'task_id': event_data.task_id,
                        'title': event_data.title,
                        'error': str(e)
                    })
                    results['error_count'] += 1

            logger.info(f"Calendar event creation complete: {results['success_count']} created, {results['error_count']} failed")
            return results

        except Exception as e:
            logger.error(f"Error creating calendar events: {e}")
            results['error_count'] = len(events)
            return results

    def execute_full_workflow(self, agent_task_id: str) -> Dict[str, Any]:
        """
        Execute the complete workflow: fetch task data and create calendar events

        Args:
            agent_task_id: The agent task ID to process

        Returns:
            Complete workflow results
        """
        workflow_results = {
            'agent_task_id': agent_task_id,
            'status': 'started',
            'task_data': None,
            'parsed_events': [],
            'calendar_results': None,
            'error': None,
            'timestamp': datetime.now().isoformat()
        }

        try:
            # Step 1: Fetch task data from platform API
            logger.info(f"Starting workflow for agent_task_id: {agent_task_id}")
            task_data = self.fetch_meeting_task_data(agent_task_id)

            if not task_data:
                workflow_results['status'] = 'failed'
                workflow_results['error'] = 'Failed to fetch task data from platform API'
                return workflow_results

            workflow_results['task_data'] = task_data

            # Step 2: Parse task data into calendar events
            parsed_events = self.parse_task_data_to_events(task_data)

            if not parsed_events:
                workflow_results['status'] = 'completed'
                workflow_results['error'] = 'No valid events found in task data'
                return workflow_results

            workflow_results['parsed_events'] = [
                {
                    'task_id': event.task_id,
                    'title': event.title,
                    'end_date': event.end_date.isoformat(),
                    'is_subtask': event.is_subtask,
                    'notify_to': event.notify_to
                }
                for event in parsed_events
            ]

            # Step 3: Create Google Calendar events
            calendar_results = self.create_calendar_events(parsed_events)
            workflow_results['calendar_results'] = calendar_results

            # Determine final status
            if calendar_results['success_count'] > 0:
                workflow_results['status'] = 'completed'
            else:
                workflow_results['status'] = 'failed'
                workflow_results['error'] = 'No calendar events were created successfully'

            logger.info(f"Workflow completed for agent_task_id: {agent_task_id} - Status: {workflow_results['status']}")
            return workflow_results

        except Exception as e:
            logger.error(f"Workflow failed for agent_task_id: {agent_task_id} - Error: {e}")
            workflow_results['status'] = 'failed'
            workflow_results['error'] = str(e)
            return workflow_results


# ----------------------------------------------------------------------------
# Provider/facade used by API routers (kept lightweight to avoid hard deps)
# ----------------------------------------------------------------------------
class ElevationPlatformIntegrationFacade:
    """Lightweight facade exposing only the operations used by API routers."""

    def __init__(self):
        # Keep lightweight: don't require tokens until needed by callers
        self._healthy = True

    def health_check(self) -> Dict[str, Any]:
        return {"status": "healthy" if self._healthy else "unhealthy"}

    def process_platform_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Basic validation/normalization; real implementation may enrich data
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dict")
        result = {
            "user_id": payload.get("user_id"),
            "workflow_type": payload.get("workflow_type"),
            "google_integration": payload.get("google_integration", {}),
            "notification_preference": payload.get("notification_preference", "only_me"),
            "task_id": payload.get("task_id"),
            "metadata": payload.get("metadata", {}),
        }
        return result

    def save_activity_log(self, activity: Dict[str, Any]) -> bool:
        # In production this would POST to the platform; here we just acknowledge
        try:
            required_keys = ["activity_type", "user_id", "workflow_id"]
            if not all(k in activity for k in required_keys):
                return False
            logging.getLogger(__name__).info(
                "Platform activity: type=%s user=%s workflow=%s",
                activity.get("activity_type"), activity.get("user_id"), activity.get("workflow_id")
            )
            return True
        except Exception:
            return False


def get_elevation_platform_integration() -> ElevationPlatformIntegrationFacade:
    """Provider used by routers; returns a lightweight facade instance."""
    if not hasattr(get_elevation_platform_integration, "_instance"):
        get_elevation_platform_integration._instance = ElevationPlatformIntegrationFacade()
    return get_elevation_platform_integration._instance