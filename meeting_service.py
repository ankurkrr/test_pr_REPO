"""
Meeting Service - Core business logic for meeting operations.

This service handles:
- Meeting creation and management
- Transcript processing
- Summary generation
- Meeting data validation
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

from ..base.service_base import BaseService, ServiceResult
from ..base.interfaces import IMeetingService, IRepository, IEmailService, ICalendarService
from ..data.repositories.meeting_repository import MeetingRepository

logger = logging.getLogger(__name__)


@dataclass
class MeetingData:
    """Data structure for meeting information."""
    id: str
    title: str
    start_time: datetime
    end_time: datetime
    organizer_email: str
    attendees: List[str]
    description: Optional[str] = None
    location: Optional[str] = None
    calendar_event_id: Optional[str] = None


@dataclass
class TranscriptData:
    """Data structure for meeting transcript."""
    meeting_id: str
    content: str
    file_path: Optional[str] = None
    word_count: Optional[int] = None
    duration_minutes: Optional[int] = None


class MeetingService(BaseService, IMeetingService):
    """
    Service for managing meeting operations.

    This service coordinates between repositories and external services
    to provide comprehensive meeting management functionality.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the meeting service."""
        super().__init__(config)
        self._meeting_repository: Optional[MeetingRepository] = None
        self._email_service: Optional[IEmailService] = None
        self._calendar_service: Optional[ICalendarService] = None

    def _perform_initialization(self) -> None:
        """Initialize service dependencies."""
        if not self.has_dependency("meeting_repository"):
            raise ValueError("MeetingRepository dependency not found")
        if not self.has_dependency("email_service"):
            raise ValueError("EmailService dependency not found")
        if not self.has_dependency("calendar_service"):
            raise ValueError("CalendarService dependency not found")

        self._meeting_repository = self.get_dependency("meeting_repository")
        self._email_service = self.get_dependency("email_service")
        self._calendar_service = self.get_dependency("calendar_service")

    async def create_meeting(self, meeting_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """
        Create a new meeting.

        Args:
            meeting_data: Meeting data dictionary

        Returns:
            ServiceResult containing the created meeting data
        """
        try:
            self.log_operation("create_meeting", meeting_id=meeting_data.get("id"))

            # Validate meeting data
            validation_result = self._validate_meeting_data(meeting_data)
            if not validation_result.success:
                return validation_result

            # Create meeting in database
            db_result = await self._meeting_repository.create_meeting(meeting_data)
            if not db_result.success:
                return ServiceResult.error_result(f"Failed to create meeting in database: {db_result.error}")

            # Create calendar event if calendar_event_id is provided
            if meeting_data.get("calendar_event_id"):
                calendar_result = await self._calendar_service.create_event({
                    "id": meeting_data["calendar_event_id"],
                    "title": meeting_data["title"],
                    "start_time": meeting_data["start_time"],
                    "end_time": meeting_data["end_time"],
                    "attendees": meeting_data.get("attendees", []),
                    "description": meeting_data.get("description", ""),
                    "location": meeting_data.get("location", "")
                })

                if not calendar_result.success:
                    self.logger.warning(f"Failed to create calendar event: {calendar_result.error}")

            return ServiceResult.success_result(
                data=db_result.data,
                metadata={"created_at": datetime.now().isoformat()}
            )

        except Exception as e:
            return self.handle_error(e, "create_meeting")

    async def get_meeting(self, meeting_id: str) -> ServiceResult[Dict[str, Any]]:
        """
        Get a meeting by ID.

        Args:
            meeting_id: Meeting ID

        Returns:
            ServiceResult containing the meeting data
        """
        try:
            self.log_operation("get_meeting", meeting_id=meeting_id)

            result = await self._meeting_repository.get_meeting(meeting_id)
            if not result.success:
                return ServiceResult.error_result(f"Meeting not found: {result.error}")

            return ServiceResult.success_result(data=result.data)

        except Exception as e:
            return self.handle_error(e, "get_meeting")

    async def update_meeting(self, meeting_id: str, updates: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """
        Update a meeting.

        Args:
            meeting_id: Meeting ID
            updates: Update data

        Returns:
            ServiceResult containing the updated meeting data
        """
        try:
            self.log_operation("update_meeting", meeting_id=meeting_id)

            # Validate updates
            validation_result = self._validate_meeting_updates(updates)
            if not validation_result.success:
                return validation_result

            # Update meeting in database
            result = await self._meeting_repository.update_meeting(meeting_id, updates)
            if not result.success:
                return ServiceResult.error_result(f"Failed to update meeting: {result.error}")

            return ServiceResult.success_result(data=result.data)

        except Exception as e:
            return self.handle_error(e, "update_meeting")

    async def get_user_meetings(self, user_id: str, limit: int = 50) -> ServiceResult[List[Dict[str, Any]]]:
        """
        Get meetings for a user.

        Args:
            user_id: User ID
            limit: Maximum number of meetings to return

        Returns:
            ServiceResult containing list of meetings
        """
        try:
            self.log_operation("get_user_meetings", user_id=user_id, limit=limit)

            result = await self._meeting_repository.get_user_meetings(user_id, limit)
            if not result.success:
                return ServiceResult.error_result(f"Failed to get user meetings: {result.error}")

            return ServiceResult.success_result(data=result.data)

        except Exception as e:
            return self.handle_error(e, "get_user_meetings")

    async def process_meeting_transcript(self, transcript_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """
        Process a meeting transcript.

        Args:
            transcript_data: Transcript data including content and metadata

        Returns:
            ServiceResult containing processing results
        """
        try:
            self.log_operation("process_meeting_transcript", meeting_id=transcript_data.get("meeting_id"))

            # Validate transcript data
            validation_result = self._validate_transcript_data(transcript_data)
            if not validation_result.success:
                return validation_result

            # Store transcript in database
            store_result = await self._meeting_repository.store_transcript(transcript_data)
            if not store_result.success:
                return ServiceResult.error_result(f"Failed to store transcript: {store_result.error}")

            # Generate AI summary (this would integrate with AI service)
            summary_result = await self._generate_meeting_summary(transcript_data)
            if not summary_result.success:
                self.logger.warning(f"Failed to generate summary: {summary_result.error}")

            # Send email notification if configured
            if self.get_config_value("send_email_notifications", False):
                email_result = await self._send_meeting_notification(transcript_data, summary_result.data)
                if not email_result.success:
                    self.logger.warning(f"Failed to send email notification: {email_result.error}")

            return ServiceResult.success_result(
                data={
                    "transcript_id": store_result.data.get("id"),
                    "summary_generated": summary_result.success,
                    "email_sent": email_result.success if 'email_result' in locals() else False
                },
                metadata={"processed_at": datetime.now().isoformat()}
            )

        except Exception as e:
            return self.handle_error(e, "process_meeting_transcript")

    def _validate_meeting_data(self, meeting_data: Dict[str, Any]) -> ServiceResult[bool]:
        """Validate meeting data."""
        required_fields = ["id", "title", "start_time", "end_time", "organizer_email"]
        missing_fields = [field for field in required_fields if field not in meeting_data]

        if missing_fields:
            return ServiceResult.error_result(f"Missing required fields: {missing_fields}")

        # Validate time range
        try:
            start_time = datetime.fromisoformat(meeting_data["start_time"])
            end_time = datetime.fromisoformat(meeting_data["end_time"])

            if start_time >= end_time:
                return ServiceResult.error_result("Start time must be before end time")

        except ValueError as e:
            return ServiceResult.error_result(f"Invalid datetime format: {e}")

        return ServiceResult.success_result(True)

    def _validate_meeting_updates(self, updates: Dict[str, Any]) -> ServiceResult[bool]:
        """Validate meeting updates."""
        # Check for invalid field updates
        invalid_fields = ["id", "created_at"]  # Fields that cannot be updated
        invalid_updates = [field for field in invalid_fields if field in updates]

        if invalid_updates:
            return ServiceResult.error_result(f"Cannot update fields: {invalid_updates}")

        return ServiceResult.success_result(True)

    def _validate_transcript_data(self, transcript_data: Dict[str, Any]) -> ServiceResult[bool]:
        """Validate transcript data."""
        required_fields = ["meeting_id", "content"]
        missing_fields = [field for field in required_fields if field not in transcript_data]

        if missing_fields:
            return ServiceResult.error_result(f"Missing required fields: {missing_fields}")

        if not transcript_data["content"].strip():
            return ServiceResult.error_result("Transcript content cannot be empty")

        return ServiceResult.success_result(True)

    async def _generate_meeting_summary(self, transcript_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Generate AI summary for meeting transcript."""
        # This would integrate with the AI summarizer service
        # For now, return a placeholder
        return ServiceResult.success_result({
            "summary": "AI-generated meeting summary placeholder",
            "key_points": ["Point 1", "Point 2", "Point 3"],
            "action_items": ["Action 1", "Action 2"]
        })

    async def _send_meeting_notification(self, transcript_data: Dict[str, Any],
                                       summary_data: Optional[Dict[str, Any]]) -> ServiceResult[bool]:
        """Send meeting notification email."""
        try:
            # Get meeting data
            meeting_result = await self.get_meeting(transcript_data["meeting_id"])
            if not meeting_result.success:
                return ServiceResult.error_result("Meeting not found for notification")

            meeting = meeting_result.data

            # Prepare email content
            subject = f"Meeting Summary: {meeting['title']}"
            body = f"Meeting: {meeting['title']}\n\n"
            body += f"Date: {meeting['start_time']}\n"
            body += f"Attendees: {', '.join(meeting.get('attendees', []))}\n\n"

            if summary_data:
                body += f"Summary: {summary_data.get('summary', 'No summary available')}\n\n"
                body += "Key Points:\n"
                for point in summary_data.get('key_points', []):
                    body += f"- {point}\n"

            # Send email to attendees
            email_result = await self._email_service.send_bulk_email(
                recipients=meeting.get('attendees', []),
                subject=subject,
                body=body
            )

            return ServiceResult.success_result(email_result.success)

        except Exception as e:
            return ServiceResult.error_result(str(e))

    def _check_service_health(self) -> Dict[str, Any]:
        """Check service-specific health."""
        health = {
            "dependencies_available": all([
                self._meeting_repository is not None,
                self._email_service is not None,
                self._calendar_service is not None
            ])
        }

        # Check repository health
        if self._meeting_repository:
            try:
                repo_health = self._meeting_repository.health_check()
                health["repository_health"] = repo_health.get("status", "unknown")
            except Exception as e:
                health["repository_health"] = f"error: {e}"

        return health