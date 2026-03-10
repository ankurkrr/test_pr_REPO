"""
Service interfaces defining contracts for all services.

These interfaces establish clear contracts between services and enable
dependency injection, testing, and loose coupling.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Generic, TypeVar
from dataclasses import dataclass
from datetime import datetime

T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """Generic result wrapper for service operations."""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class IRepository(ABC):
    """Interface for repository implementations."""

    @abstractmethod
    def find_by_id(self, id_value: Any) -> ServiceResult[T]:
        """Find a record by ID."""
        pass

    @abstractmethod
    def find_by_criteria(self, criteria: Dict[str, Any],
                        limit: Optional[int] = None,
                        offset: Optional[int] = None) -> ServiceResult[List[T]]:
        """Find records by criteria."""
        pass

    @abstractmethod
    def create(self, data: Dict[str, Any]) -> ServiceResult[T]:
        """Create a new record."""
        pass

    @abstractmethod
    def update(self, id_value: Any, data: Dict[str, Any]) -> ServiceResult[T]:
        """Update a record."""
        pass

    @abstractmethod
    def delete(self, id_value: Any) -> ServiceResult[bool]:
        """Delete a record."""
        pass


class IMeetingService(ABC):
    """Interface for meeting-related operations."""

    @abstractmethod
    async def create_meeting(self, meeting_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Create a new meeting."""
        pass

    @abstractmethod
    async def get_meeting(self, meeting_id: str) -> ServiceResult[Dict[str, Any]]:
        """Get a meeting by ID."""
        pass

    @abstractmethod
    async def update_meeting(self, meeting_id: str, updates: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Update a meeting."""
        pass

    @abstractmethod
    async def get_user_meetings(self, user_id: str, limit: int = 50) -> ServiceResult[List[Dict[str, Any]]]:
        """Get meetings for a user."""
        pass

    @abstractmethod
    async def process_meeting_transcript(self, transcript_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Process a meeting transcript."""
        pass


class IWorkflowService(ABC):
    """Interface for workflow operations."""

    @abstractmethod
    async def start_workflow(self, workflow_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Start a new workflow."""
        pass

    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> ServiceResult[Dict[str, Any]]:
        """Get a workflow by ID."""
        pass

    @abstractmethod
    async def update_workflow_status(self, workflow_id: str, status: str) -> ServiceResult[bool]:
        """Update workflow status."""
        pass

    @abstractmethod
    async def execute_scheduled_workflow(self) -> ServiceResult[Dict[str, Any]]:
        """Execute scheduled workflow for all active users."""
        pass


class ITaskService(ABC):
    """Interface for task operations."""

    @abstractmethod
    async def create_tasks(self, tasks: List[Dict[str, Any]]) -> ServiceResult[List[Dict[str, Any]]]:
        """Create multiple tasks."""
        pass

    @abstractmethod
    async def get_tasks_for_meeting(self, meeting_id: str) -> ServiceResult[List[Dict[str, Any]]]:
        """Get tasks for a meeting."""
        pass

    @abstractmethod
    async def update_task_status(self, task_id: str, status: str) -> ServiceResult[bool]:
        """Update task status."""
        pass

    @abstractmethod
    async def sync_tasks_to_platform(self, tasks: List[Dict[str, Any]]) -> ServiceResult[Dict[str, Any]]:
        """Sync tasks to external platform."""
        pass


class IEmailService(ABC):
    """Interface for email operations."""

    @abstractmethod
    async def send_email(self, to_email: str, subject: str, body: str,
                        html_body: Optional[str] = None) -> ServiceResult[Dict[str, Any]]:
        """Send a single email."""
        pass

    @abstractmethod
    async def send_bulk_email(self, recipients: List[str], subject: str, body: str,
                             html_body: Optional[str] = None) -> ServiceResult[Dict[str, Any]]:
        """Send bulk email."""
        pass

    @abstractmethod
    async def send_meeting_summary(self, meeting_data: Dict[str, Any],
                                  recipients: List[str]) -> ServiceResult[Dict[str, Any]]:
        """Send meeting summary email."""
        pass


class ICalendarService(ABC):
    """Interface for calendar operations."""

    @abstractmethod
    async def get_events(self, start_time: datetime, end_time: datetime) -> ServiceResult[List[Dict[str, Any]]]:
        """Get calendar events in time range."""
        pass

    @abstractmethod
    async def create_event(self, event_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Create a calendar event."""
        pass

    @abstractmethod
    async def update_event(self, event_id: str, event_data: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Update a calendar event."""
        pass

    @abstractmethod
    async def delete_event(self, event_id: str) -> ServiceResult[bool]:
        """Delete a calendar event."""
        pass


class IAuthService(ABC):
    """Interface for authentication operations."""

    @abstractmethod
    async def validate_token(self, token: str) -> ServiceResult[Dict[str, Any]]:
        """Validate an authentication token."""
        pass

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> ServiceResult[Dict[str, Any]]:
        """Refresh an authentication token."""
        pass

    @abstractmethod
    async def get_user_credentials(self, user_id: str) -> ServiceResult[Dict[str, Any]]:
        """Get user credentials."""
        pass


class INotificationService(ABC):
    """Interface for notification operations."""

    @abstractmethod
    async def send_notification(self, user_id: str, message: str,
                               notification_type: str = "info") -> ServiceResult[bool]:
        """Send a notification to a user."""
        pass

    @abstractmethod
    async def send_bulk_notification(self, user_ids: List[str], message: str,
                                    notification_type: str = "info") -> ServiceResult[Dict[str, Any]]:
        """Send notifications to multiple users."""
        pass