"""
Migration Helper for Service Layer Refactoring

This module provides utilities to help migrate from the old service structure
to the new refactored service layer. It includes compatibility layers and
migration utilities.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, List
from functools import wraps

from .service_factory import get_service_factory

logger = logging.getLogger(__name__)


class ServiceMigrationHelper:
    """
    Helper class for migrating from old service structure to new one.

    This class provides compatibility layers and migration utilities
    to ensure smooth transition from the old service architecture.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the migration helper."""
        self.config = config or {}
        self.factory = get_service_factory(config)
        self._compatibility_map = self._build_compatibility_map()

    def _build_compatibility_map(self) -> Dict[str, str]:
        """Build mapping from old service names to new service names."""
        return {
            # Old service names -> New service names
            "SendGridEmailService": "SendGridEmailService",
            "GoogleCalendarService": "GoogleCalendarService",
            "GoogleDriveService": "GoogleDriveService",
            "GoogleSheetsService": "GoogleSheetsService",
            "DatabaseService": "DatabaseService",
            "MeetingService": "MeetingService",
            "WorkflowOrchestrator": "WorkflowService",
            "ElevationAIIntegrationService": "ElevationAIService",
        }

    def get_legacy_service(self, service_name: str) -> Any:
        """
        Get a service using the old naming convention.

        Args:
            service_name: Old service name

        Returns:
            Service instance
        """
        new_name = self._compatibility_map.get(service_name, service_name)

        if new_name == "SendGridEmailService":
            return self.factory.get_email_service()
        elif new_name == "GoogleCalendarService":
            return self.factory.get_calendar_service()
        elif new_name == "GoogleDriveService":
            return self.factory.get_drive_service()
        elif new_name == "GoogleSheetsService":
            return self.factory.get_sheets_service()
        elif new_name == "DatabaseService":
            return self.factory.get_database_service()
        elif new_name == "MeetingService":
            return self.factory.get_meeting_service()
        elif new_name == "WorkflowService":
            return self.factory.get_workflow_service()
        elif new_name == "ElevationAIService":
            return self.factory.get_platform_service()
        else:
            raise ValueError(f"Unknown service: {service_name}")

    def create_compatibility_wrapper(self, old_service_class, new_service_class):
        """
        Create a compatibility wrapper for old service classes.

        Args:
            old_service_class: The old service class
            new_service_class: The new service class

        Returns:
            Wrapped class that maintains old interface
        """
        class CompatibilityWrapper(old_service_class):
            def __init__(self, *args, **kwargs):
                # Initialize the new service
                self._new_service = self.factory.get_service(new_service_class)
                # Call old init for compatibility
                super().__init__(*args, **kwargs)

            def __getattr__(self, name):
                # Delegate to new service if method not found in old service
                if hasattr(self._new_service, name):
                    return getattr(self._new_service, name)
                raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

        return CompatibilityWrapper


def migrate_imports():
    """
    Migration guide for updating imports.

    This function provides guidance on how to update imports from the old
    service structure to the new one.
    """
    migration_guide = {
        "Old Imports": {
            "from src.service.sendgrid_email_service import SendGridEmailService":
                "from src.services import SendGridEmailService",
            "from src.service.calendar_service import GoogleCalendarService":
                "from src.services.google import GoogleCalendarService",
            "from src.service.drive_service import GoogleDriveService":
                "from src.services.google import GoogleDriveService",
            "from src.service.sheets_service import GoogleSheetsService":
                "from src.services.google import GoogleSheetsService",
            "from src.services.database_service import DatabaseService":
                "from src.services import DatabaseService",
            "from src.services.workflow_orchestrator import WorkflowOrchestrator":
                "from src.services import WorkflowService",
        },
        "New Imports": {
            "Core Services": "from src.services import MeetingService, WorkflowService, TaskService",
            "External Services": "from src.services import SendGridEmailService, GoogleCalendarService",
            "Data Layer": "from src.services import DatabaseService, MeetingRepository",
            "Service Factory": "from src.services import ServiceFactory, get_service_factory",
        },
        "Usage Patterns": {
            "Old Pattern": "service = SomeService()",
            "New Pattern": "factory = get_service_factory()\nservice = factory.get_meeting_service()",
            "Dependency Injection": "service.add_dependency('email_service', email_service)",
        }
    }

    return migration_guide


def create_migration_script():
    """
    Create a migration script to help update existing code.

    Returns:
        String containing migration script
    """
    script = '''
# Service Layer Migration Script
# Run this script to help migrate from old service structure to new one

import os
import re
from pathlib import Path

def update_imports_in_file(file_path: str) -> bool:
    """Update imports in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # Update service imports
        import_mappings = {
            r'from src\.service\.sendgrid_email_service import SendGridEmailService':
                'from src.services import SendGridEmailService',
            r'from src\.service\.calendar_service import GoogleCalendarService':
                'from src.services.google import GoogleCalendarService',
            r'from src\.service\.drive_service import GoogleDriveService':
                'from src.services.google import GoogleDriveService',
            r'from src\.service\.sheets_service import GoogleSheetsService':
                'from src.services.google import GoogleSheetsService',
            r'from src\.services\.database_service import DatabaseService':
                'from src.services import DatabaseService',
            r'from src\.services\.workflow_orchestrator import WorkflowOrchestrator':
                'from src.services import WorkflowService',
        }

        for old_pattern, new_import in import_mappings.items():
            content = re.sub(old_pattern, new_import, content)

        # Update service instantiation patterns
        service_instantiations = {
            r'SendGridEmailService\(\)': 'get_service_factory().get_email_service()',
            r'GoogleCalendarService\([^)]*\)': 'get_service_factory().get_calendar_service()',
            r'DatabaseService\(\)': 'get_service_factory().get_database_service()',
        }

        for old_pattern, new_pattern in service_instantiations.items():
            content = re.sub(old_pattern, new_pattern, content)

        # Add factory import if needed
        if 'get_service_factory' in content and 'from src.services import get_service_factory' not in content:
            content = 'from src.services import get_service_factory\\n' + content

        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return False

def migrate_project():
    """Migrate entire project."""
    project_root = Path('.')
    python_files = list(project_root.rglob('*.py'))

    updated_files = []

    for file_path in python_files:
        # Skip migration script itself
        if 'migration' in str(file_path):
            continue

        if update_imports_in_file(str(file_path)):
            updated_files.append(str(file_path))

    print(f"Updated {len(updated_files)} files:")
    for file_path in updated_files:
        print(f"  - {file_path}")

if __name__ == "__main__":
    migrate_project()
'''
    return script


def validate_migration() -> Dict[str, Any]:
    """
    Validate that the migration was successful.

    Returns:
        Dictionary containing validation results
    """
    validation_results = {
        "status": "success",
        "checks": [],
        "errors": [],
        "warnings": []
    }

    try:
        # Test service factory
        factory = get_service_factory()
        health_check = factory.health_check_all()

        if health_check["factory_status"] != "healthy":
            validation_results["errors"].append("Service factory health check failed")
            validation_results["status"] = "failed"
        else:
            validation_results["checks"].append("Service factory is healthy")

        # Test core services
        try:
            meeting_service = factory.get_meeting_service()
            if meeting_service.health_check()["status"] != "healthy":
                validation_results["warnings"].append("Meeting service health check failed")
        except Exception as e:
            validation_results["errors"].append(f"Meeting service creation failed: {e}")

        try:
            email_service = factory.get_email_service()
            if email_service.health_check()["status"] != "healthy":
                validation_results["warnings"].append("Email service health check failed")
        except Exception as e:
            validation_results["errors"].append(f"Email service creation failed: {e}")

        # Check for old service directory
        old_service_dir = Path("src/service")
        if old_service_dir.exists():
            validation_results["warnings"].append("Old service directory still exists - consider removing after migration")

    except Exception as e:
        validation_results["status"] = "failed"
        validation_results["errors"].append(f"Validation failed: {e}")

    return validation_results


# Convenience functions for easy migration
def get_legacy_service(service_name: str, config: Optional[Dict[str, Any]] = None):
    """Get a service using legacy naming for backward compatibility."""
    helper = ServiceMigrationHelper(config)
    return helper.get_legacy_service(service_name)


def create_service_factory(config: Optional[Dict[str, Any]] = None):
    """Create a service factory with the given configuration."""
    return get_service_factory(config)