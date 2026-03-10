"""
External Payload Processor Service
Handles incoming payloads from external platforms, token decryption, and workflow execution
"""

import logging
import json
import base64
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
from cryptography.fernet import Fernet
import os

# Import services
# from src.services.database_service import DatabaseService  # TODO: Replace with new service structure
from src.services.integration.agent_integration_service import AgentIntegrationService
from src.services.integration.platform_api_client import get_platform_api_client
from src.agents.meeting_agent import run_meeting_workflow

logger = logging.getLogger(__name__)

class ExternalPayloadProcessor:
    """
    Processes external payloads, handles token decryption, and executes workflows
    """

    def __init__(self):
        """Initialize the external payload processor"""
        self.db_service = DatabaseService()
        self.agent_integration = AgentIntegrationService()
        self.platform_api_client = get_platform_api_client()
        self.encryption_key = self._get_or_create_encryption_key()

    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key for token decryption"""
        try:
            # Try to get key from environment
            key_env = os.getenv('ENCRYPTION_KEY')
            if key_env:
                return base64.urlsafe_b64decode(key_env.encode())

            # Try to get key from file
            key_file = 'keys/encryption.key'
            if os.path.exists(key_file):
                with open(key_file, 'rb') as f:
                    return f.read()

            # Generate new key
            key = Fernet.generate_key()

            # Save key to file
            os.makedirs('keys', exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)

            logger.info("Generated new encryption key")
            return key

        except Exception as e:
            logger.error(f"Failed to get/create encryption key: {e}")
            # Fallback to a default key (not recommended for production)
            return Fernet.generate_key()

    def _decrypt_token(self, encrypted_token: str) -> Optional[Dict[str, Any]]:
        """Decrypt the incoming token to extract user credentials and task info"""
        try:
            # Validate token format
            if not encrypted_token or len(encrypted_token) < 10:
                logger.error("Invalid token format: token too short")
                return None

            # Decode base64 token
            try:
                encrypted_data = base64.urlsafe_b64decode(encrypted_token.encode())
            except Exception as e:
                logger.error(f"Failed to decode base64 token: {e}")
                return None

            # Decrypt using Fernet
            fernet = Fernet(self.encryption_key)
            try:
                decrypted_data = fernet.decrypt(encrypted_data)
            except Exception as e:
                logger.error(f"Failed to decrypt token data: {e}")
                return None

            # Parse JSON
            try:
                token_data = json.loads(decrypted_data.decode())
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse token JSON: {e}")
                return None

            # Validate token structure
            required_fields = ['user_id', 'access_token']
            for field in required_fields:
                if field not in token_data:
                    logger.error(f"Missing required field in token: {field}")
                    return None

            # Check token expiration if present
            if 'expires_at' in token_data:
                try:
                    expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
                    if datetime.now(expires_at.tzinfo) > expires_at:
                        logger.error("Token has expired")
                        return None
                except ValueError as e:
                    logger.warning(f"Invalid expires_at format: {e}")

            # Sanitize sensitive data for logging
            safe_token_data = {k: v for k, v in token_data.items() if k not in ['access_token', 'refresh_token']}
            logger.info(f"Successfully decrypted token for user: {safe_token_data.get('user_id', 'unknown')}")

            return token_data

        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}")
            return None

    def _fetch_task_details(self, task_id: str, user_credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetch task details from the platform API"""
        try:
            access_token = user_credentials.get('access_token')
            if not access_token:
                logger.error("No access token available for fetching task details")
                return None

            return self.platform_api_client.get_task_details(task_id, access_token)

        except Exception as e:
            logger.error(f"Error fetching task details: {e}")
            return None

    def _update_task_status(self, task_id: str, status: str, user_credentials: Dict[str, Any],
                           result_data: Optional[Dict[str, Any]] = None) -> bool:
        """Update task status on the platform API"""
        try:
            access_token = user_credentials.get('access_token')
            if not access_token:
                logger.error("No access token available for updating task status")
                return False

            return self.platform_api_client.update_task_status(task_id, status, access_token, result_data)

        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False

    def process_external_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main method to process external payload

        Args:
            payload: Dictionary containing token, agent_task_id, and workflow_data

        Returns:
            Dictionary with processing results
        """
        try:
            logger.info(f"Processing external payload for task: {payload.get('agent_task_id')}")

            # Extract payload components
            encrypted_token = payload.get('token')
            agent_task_id = payload.get('agent_task_id')
            workflow_data = payload.get('workflow_data', [])

            if not encrypted_token or not agent_task_id:
                return {
                    "success": False,
                    "error": "Missing required fields: token or agent_task_id",
                    "workflow_status": "error"
                }

            # Decrypt token to get user credentials
            user_credentials = self._decrypt_token(encrypted_token)
            if not user_credentials:
                return {
                    "success": False,
                    "error": "Failed to decrypt token",
                    "workflow_status": "error"
                }

            # Store workflow data in database
            workflow_id = self._store_workflow_data(agent_task_id, workflow_data, user_credentials)

            # Process workflow data to extract configuration
            config = self._parse_workflow_data(workflow_data)

            # Log successful processing
            self.agent_integration.log_agent_function(
                user_agent_task_id=agent_task_id,
                activity_type="external_payload",
                log_for_status="success",
                tool_name="external_payload_processor",
                log_text=f"Successfully processed external payload",
                outcome="payload_processed",
                scope="external_integration",
                step_str="payload_processing"
            )

            return {
                "success": True,
                "message": "External payload processed successfully",
                "workflow_id": workflow_id,
                "config": config,
                "user_id": user_credentials.get('user_id'),
                "workflow_status": "processed"
            }

        except Exception as e:
            logger.error(f"Failed to process external payload: {e}")

            # Log error
            if payload.get('agent_task_id'):
                self.agent_integration.log_agent_function(
                    user_agent_task_id=payload.get('agent_task_id'),
                    activity_type="external_payload",
                    log_for_status="error",
                    tool_name="external_payload_processor",
                    log_text=f"Failed to process external payload: {str(e)}",
                    outcome="payload_error",
                    scope="external_integration",
                    step_str="payload_processing"
                )

            return {
                "success": False,
                "error": str(e),
                "workflow_status": "error"
            }

    def _store_workflow_data(self, agent_task_id: str, workflow_data: List[Dict[str, Any]],
                           user_credentials: Dict[str, Any]) -> str:
        """Store workflow data in database"""
        try:
            # Create workflow record
            workflow_id = self.db_service.create_workflow(
                agent_id="external_agent",
                user_id=user_credentials.get('user_id', 'unknown'),
                workflow_type="external_payload",
                input_parameters=json.dumps({
                    "agent_task_id": agent_task_id,
                    "workflow_data": workflow_data,
                    "user_credentials": {k: v for k, v in user_credentials.items() if k != 'access_token'}
                })
            )

            logger.info(f"Stored workflow data with ID: {workflow_id}")
            return workflow_id

        except Exception as e:
            logger.error(f"Failed to store workflow data: {e}")
            return agent_task_id  # Fallback to agent_task_id

    def _parse_workflow_data(self, workflow_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse workflow data to extract configuration"""
        config = {
            "google_integration": None,
            "notification_settings": {},
            "tools_to_use": []
        }

        try:
            for item in workflow_data:
                tools = item.get('tool_to_use', [])

                for tool in tools:
                    integration_type = tool.get('integration_type', '')

                    if integration_type == 'google_calender':
                        # Extract Google Calendar integration details
                        fields = tool.get('fields_json', [])
                        google_config = {}

                        for field in fields:
                            field_name = field.get('field')
                            field_value = field.get('value')
                            if field_name and field_value:
                                google_config[field_name] = field_value

                        config['google_integration'] = google_config

                    elif 'notify' in tool.get('title', '').lower():
                        # Extract notification settings
                        fields = tool.get('fields_json', [])
                        for field in fields:
                            if field.get('field') == 'notify_to':
                                config['notification_settings']['notify_to'] = field.get('value')

                    config['tools_to_use'].append({
                        'id': tool.get('id'),
                        'title': tool.get('title'),
                        'integration_type': integration_type,
                        'status': tool.get('integration_status')
                    })

            logger.info("Successfully parsed workflow configuration")
            return config

        except Exception as e:
            logger.error(f"Failed to parse workflow data: {e}")
            return config

    async def execute_agent_workflow(self, agent_task_id: str, workflow_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent workflow based on configuration

        Args:
            agent_task_id: Unique task identifier
            workflow_config: Configuration for workflow execution

        Returns:
            Dictionary with execution results
        """
        try:
            logger.info(f"Executing agent workflow for task: {agent_task_id}")

            # Fetch task details from platform API if needed
            user_credentials = workflow_config.get('user_credentials', {})
            task_details = None

            if user_credentials:
                task_details = self._fetch_task_details(agent_task_id, user_credentials)

            # Update task status to "in_progress"
            if user_credentials:
                self._update_task_status(agent_task_id, "in_progress", user_credentials)

            # Execute the main agentic workflow
            workflow_result = None
            try:
                # Use the main meeting workflow with all 5 steps
                # Note: run_meeting_workflow is not async, so we don't need await
                workflow_result = run_meeting_workflow(
                    agent_task_id=agent_task_id,
                    workflow_data=[],  # Empty workflow data for now
                    auth_tokens=None,  # Use existing auth if available
                    user_id=user_credentials.get('user_id'),
                    use_agent=True  # Use the main agentic LangChain flow
                )

                logger.info(f"Successfully executed workflow for task: {agent_task_id}")

            except Exception as workflow_error:
                logger.error(f"Workflow execution failed: {workflow_error}")
                workflow_result = {
                    "success": False,
                    "error": str(workflow_error),
                    "workflow_type": "meeting_workflow"
                }

            # Create calendar events if Google integration is configured
            calendar_result = None
            google_config = workflow_config.get('google_integration')
            if google_config and task_details:
                calendar_result = self._create_calendar_events(task_details, google_config)

            # Prepare final result
            final_result = {
                "workflow_execution": workflow_result,
                "calendar_integration": calendar_result,
                "task_details": task_details,
                "timestamp": datetime.now().isoformat()
            }

            # Update task status based on results
            if user_credentials:
                status = "completed" if workflow_result and workflow_result.get("success") else "failed"
                self._update_task_status(agent_task_id, status, user_credentials, final_result)

            # Log successful execution
            self.agent_integration.log_agent_function(
                user_agent_task_id=agent_task_id,
                activity_type="workflow_execution",
                log_for_status="success" if workflow_result and workflow_result.get("success") else "error",
                tool_name="external_payload_processor",
                log_text=f"Executed agent workflow",
                outcome="workflow_executed",
                scope="workflow_execution",
                step_str="workflow_execution"
            )

            return {
                "success": True,
                "message": "Agent workflow executed successfully",
                "result": final_result,
                "workflow_status": "completed"
            }

        except Exception as e:
            logger.error(f"Failed to execute agent workflow: {e}")

            # Update task status to failed
            if workflow_config.get('user_credentials'):
                self._update_task_status(agent_task_id, "failed", workflow_config['user_credentials'])

            # Log error
            self.agent_integration.log_agent_function(
                user_agent_task_id=agent_task_id,
                activity_type="workflow_execution",
                log_for_status="error",
                tool_name="external_payload_processor",
                log_text=f"Failed to execute agent workflow: {str(e)}",
                outcome="workflow_error",
                scope="workflow_execution",
                step_str="workflow_execution"
            )

            return {
                "success": False,
                "error": str(e),
                "workflow_status": "error"
            }

    def _create_calendar_events(self, task_details: Dict[str, Any], google_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create Google Calendar events based on task details"""
        try:
            from src.services.utility.google_auth import GoogleAuthenticator
            from src.services.utility.calendar_service import CalendarService
            from datetime import timedelta

            # Initialize Google services
            auth = GoogleAuthenticator()
            calendar_service = CalendarService(auth)

            # Extract event details from task
            events_created = []

            # Parse task details to create meaningful events
            task_type = task_details.get('type', 'general')
            task_title = task_details.get('title', 'Agent Task')
            task_description = task_details.get('description', 'Task created by FastAPI Agent')

            # Determine event timing based on task details
            start_time = datetime.now()
            if task_details.get('scheduled_time'):
                try:
                    start_time = datetime.fromisoformat(task_details['scheduled_time'].replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Invalid scheduled_time format: {task_details['scheduled_time']}")

            # Create different types of events based on task type
            if task_type == 'meeting':
                # Create meeting event
                event_data = self._create_meeting_event(task_details, google_config, start_time)
                created_event = calendar_service.create_event(event_data)
                events_created.append(created_event)

            elif task_type == 'reminder':
                # Create reminder event
                event_data = self._create_reminder_event(task_details, google_config, start_time)
                created_event = calendar_service.create_event(event_data)
                events_created.append(created_event)

            elif task_type == 'workflow':
                # Create workflow tracking events
                workflow_events = self._create_workflow_events(task_details, google_config, start_time)
                for event_data in workflow_events:
                    created_event = calendar_service.create_event(event_data)
                    events_created.append(created_event)

            else:
                # Create general task event
                event_data = {
                    'summary': f"Task: {task_title}",
                    'description': f"{task_description}\n\nCreated by FastAPI Agent\nTask ID: {task_details.get('id', 'unknown')}",
                    'start': {
                        'dateTime': start_time.isoformat(),
                        'timeZone': 'UTC',
                    },
                    'end': {
                        'dateTime': (start_time + timedelta(hours=1)).isoformat(),
                        'timeZone': 'UTC',
                    }
                }

                # Add attendees if available
                if google_config.get('email'):
                    event_data['attendees'] = [{'email': google_config['email']}]

                created_event = calendar_service.create_event(event_data)
                events_created.append(created_event)

            logger.info(f"Created {len(events_created)} calendar events for task type: {task_type}")

            return {
                "success": True,
                "events_created": events_created,
                "count": len(events_created),
                "task_type": task_type
            }

        except Exception as e:
            logger.error(f"Failed to create calendar events: {e}")
            return {
                "success": False,
                "error": str(e),
                "events_created": [],
                "task_type": task_details.get('type', 'unknown')
            }

    def _create_meeting_event(self, task_details: Dict[str, Any], google_config: Dict[str, Any],
                             start_time: datetime) -> Dict[str, Any]:
        """Create a meeting calendar event"""
        from datetime import timedelta

        duration_minutes = task_details.get('duration_minutes', 60)
        end_time = start_time + timedelta(minutes=duration_minutes)

        event_data = {
            'summary': f"Meeting: {task_details.get('title', 'Agent Meeting')}",
            'description': f"{task_details.get('description', '')}\n\n"
                          f"Meeting created by FastAPI Agent\n"
                          f"Task ID: {task_details.get('id', 'unknown')}\n"
                          f"Duration: {duration_minutes} minutes",
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'location': task_details.get('location', ''),
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 15},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        # Add attendees
        attendees = []
        if google_config.get('email'):
            attendees.append({'email': google_config['email']})

        # Add additional attendees from task details
        if task_details.get('attendees'):
            for attendee in task_details['attendees']:
                if isinstance(attendee, str):
                    attendees.append({'email': attendee})
                elif isinstance(attendee, dict) and attendee.get('email'):
                    attendees.append({'email': attendee['email']})

        if attendees:
            event_data['attendees'] = attendees

        # Add conference data if requested
        if task_details.get('create_meeting_link', False):
            event_data['conferenceData'] = {
                'createRequest': {
                    'requestId': f"meeting_{task_details.get('id', 'unknown')}_{int(start_time.timestamp())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }

        return event_data

    def _create_reminder_event(self, task_details: Dict[str, Any], google_config: Dict[str, Any],
                              start_time: datetime) -> Dict[str, Any]:
        """Create a reminder calendar event"""
        from datetime import timedelta

        event_data = {
            'summary': f"Reminder: {task_details.get('title', 'Agent Reminder')}",
            'description': f"{task_details.get('description', '')}\n\n"
                          f"Reminder created by FastAPI Agent\n"
                          f"Task ID: {task_details.get('id', 'unknown')}",
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': (start_time + timedelta(minutes=15)).isoformat(),
                'timeZone': 'UTC',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 0},
                    {'method': 'popup', 'minutes': 0},
                ],
            },
        }

        # Add attendee
        if google_config.get('email'):
            event_data['attendees'] = [{'email': google_config['email']}]

        return event_data

    def _create_workflow_events(self, task_details: Dict[str, Any], google_config: Dict[str, Any],
                               start_time: datetime) -> List[Dict[str, Any]]:
        """Create workflow tracking calendar events"""
        from datetime import timedelta

        events = []
        workflow_steps = task_details.get('workflow_steps', [])

        if not workflow_steps:
            # Create default workflow steps
            workflow_steps = [
                {'name': 'Start Workflow', 'duration_minutes': 5},
                {'name': 'Process Data', 'duration_minutes': 15},
                {'name': 'Generate Results', 'duration_minutes': 10},
                {'name': 'Complete Workflow', 'duration_minutes': 5}
            ]

        current_time = start_time

        for i, step in enumerate(workflow_steps):
            step_duration = step.get('duration_minutes', 10)
            step_end_time = current_time + timedelta(minutes=step_duration)

            event_data = {
                'summary': f"Workflow Step {i+1}: {step.get('name', f'Step {i+1}')}",
                'description': f"Workflow: {task_details.get('title', 'Agent Workflow')}\n"
                              f"Step {i+1} of {len(workflow_steps)}\n"
                              f"{step.get('description', '')}\n\n"
                              f"Created by FastAPI Agent\n"
                              f"Task ID: {task_details.get('id', 'unknown')}",
                'start': {
                    'dateTime': current_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': step_end_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'colorId': str((i % 11) + 1),  # Use different colors for each step
            }

            # Add attendee
            if google_config.get('email'):
                event_data['attendees'] = [{'email': google_config['email']}]

            events.append(event_data)
            current_time = step_end_time

        return events


def get_external_payload_processor() -> ExternalPayloadProcessor:
    """Get singleton instance of external payload processor"""
    if not hasattr(get_external_payload_processor, '_instance'):
        get_external_payload_processor._instance = ExternalPayloadProcessor()
    return get_external_payload_processor._instance