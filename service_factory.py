"""
Service Factory for Dependency Injection

This factory provides a centralized way to create and configure services
with proper dependency injection, making the codebase more maintainable
and testable.
"""

import logging
from typing import Any, Dict, Optional, Type, TypeVar
from functools import lru_cache

from .base.service_base import BaseService
from .data.repositories.meeting_repository import MeetingRepository
from .core.meeting_service import MeetingService
from .external.email.sendgrid_service import SendGridEmailService

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseService)


class ServiceFactory:
    """
    Factory for creating and configuring services with dependency injection.

    This factory ensures that all services are properly configured with their
    dependencies and follow the established patterns.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the service factory.

        Args:
            config: Global configuration dictionary
        """
        self.config = config or {}
        self._services: Dict[str, Any] = {}
        self._repositories: Dict[str, Any] = {}

    def get_meeting_service(self) -> MeetingService:
        """Get or create the meeting service."""
        if "meeting_service" not in self._services:
            # Create a simple meeting service without complex dependencies for now
            self._services["meeting_service"] = MeetingService()
        return self._services["meeting_service"]

    def get_meeting_repository(self) -> MeetingRepository:
        """Get or create the meeting repository."""
        if "meeting_repository" not in self._repositories:
            # For now, we'll create a mock session factory
            # In a real implementation, this would come from the database config
            self._repositories["meeting_repository"] = MeetingRepository(None)
        return self._repositories["meeting_repository"]

    def get_email_service(self) -> SendGridEmailService:
        """Get or create the email service."""
        if "email_service" not in self._services:
            self._services["email_service"] = SendGridEmailService()
        return self._services["email_service"]

    def get_service(self, service_name: str) -> Any:
        """
        Get a service by name.

        Args:
            service_name: Name of the service to get

        Returns:
            Service instance
        """
        if service_name == "meeting_service":
            return self.get_meeting_service()
        elif service_name == "email_service":
            return self.get_email_service()
        elif service_name == "meeting_repository":
            return self.get_meeting_repository()
        else:
            raise ValueError(f"Unknown service: {service_name}")

    def get_repository(self, repository_name: str) -> Any:
        """
        Get a repository by name.

        Args:
            repository_name: Name of the repository to get

        Returns:
            Repository instance
        """
        if repository_name == "meeting_repository":
            return self.get_meeting_repository()
        else:
            raise ValueError(f"Unknown repository: {repository_name}")

    def health_check(self) -> Dict[str, Any]:
        """Check the health of all services."""
        health_status = {
            "factory_initialized": True,
            "services": {},
            "repositories": {}
        }

        # Check services
        for name, service in self._services.items():
            try:
                if hasattr(service, 'health_check'):
                    health_status["services"][name] = service.health_check()
                else:
                    health_status["services"][name] = {"status": "healthy", "message": "No health check implemented"}
            except Exception as e:
                health_status["services"][name] = {"status": "unhealthy", "error": str(e)}

        # Check repositories
        for name, repo in self._repositories.items():
            try:
                if hasattr(repo, 'health_check'):
                    health_status["repositories"][name] = repo.health_check()
                else:
                    health_status["repositories"][name] = {"status": "healthy", "message": "No health check implemented"}
            except Exception as e:
                health_status["repositories"][name] = {"status": "unhealthy", "error": str(e)}

        return health_status


# Global factory instance
_factory: Optional[ServiceFactory] = None


def get_service_factory() -> ServiceFactory:
    """Get the global service factory instance."""
    global _factory
    if _factory is None:
        _factory = ServiceFactory()
    return _factory