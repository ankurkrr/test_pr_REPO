"""
Error Constants and Definitions for Meeting Intelligence Agent
"""

from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class MeetingIntelligenceError(Exception):
    """Base exception for all Meeting Intelligence Agent errors."""

    def __init__(
        self, message: str, error_code: str = None, details: Dict[str, Any] = None
    ):
        self.message = message
        self.error_code = error_code or "UNKNOWN_ERROR"
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary representation.

        Returns:
            Dictionary containing error details
        """
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# SPECIFIC ERROR CLASSES FOR 3-TABLE AUDIT SYSTEM
# =============================================================================


class AuditSystemError(MeetingIntelligenceError):
    """3-table audit system errors."""


class AgentRegistrationError(AuditSystemError):
    """Agent registration errors in agent table."""


class TaskCreationError(AuditSystemError):
    """User agent task creation errors in user_agent_task table."""


class AuditLogError(AuditSystemError):
    """Audit logging errors in agent_function_log table."""


class WorkflowError(MeetingIntelligenceError):
    """Workflow execution errors."""


class NotificationError(MeetingIntelligenceError):
    """Notification system errors."""


# General Error Categories
GENERAL_ERRORS = {
    "DATABASE_CONNECTION_FAILED": "Failed to connect to the database",
    "INVALID_CONFIGURATION": "Invalid configuration detected",
    "MISSING_CREDENTIALS": "Required credentials are missing",
    "AUTHENTICATION_FAILED": "Authentication failed",
    "PERMISSION_DENIED": "Permission denied for the requested operation",
    "RESOURCE_NOT_FOUND": "Requested resource not found",
    "TIMEOUT_ERROR": "Operation timed out",
    "NETWORK_ERROR": "Network connection error",
    "INVALID_INPUT": "Invalid input provided",
    "PROCESSING_ERROR": "Error occurred during processing",
}

# Database Specific Errors - 3-Table Audit System
DATABASE_ERRORS = {
    "CONNECTION_TIMEOUT": "Database connection timeout",
    "QUERY_FAILED": "Database query execution failed",
    "TRANSACTION_FAILED": "Database transaction failed",
    "TABLE_NOT_FOUND": "Database table not found - check 3-table audit system setup",
    "CONSTRAINT_VIOLATION": "Database constraint violation",
    "DUPLICATE_ENTRY": "Duplicate entry in database",
    "AUDIT_TABLE_MISSING": "Required audit table missing (agent, user_agent_task, or agent_function_log)",
    "FOREIGN_KEY_VIOLATION": "Foreign key constraint violation in 3-table audit system",
    "AUDIT_LOG_FAILED": "Failed to write to agent_function_log table",
    "TASK_CREATION_FAILED": "Failed to create user_agent_task record",
    "AGENT_REGISTRATION_FAILED": "Failed to register agent in agent table",
    "DATA_TRUNCATION": "Data truncation error",
    "LOCK_TIMEOUT": "Database lock timeout",
    "DEADLOCK_DETECTED": "Database deadlock detected",
}

# Google API Errors
GOOGLE_API_ERRORS = {
    "CALENDAR_ACCESS_DENIED": "Access denied to Google Calendar",
    "DRIVE_ACCESS_DENIED": "Access denied to Google Drive",
    "QUOTA_EXCEEDED": "Google API quota exceeded",
    "INVALID_CREDENTIALS": "Invalid Google API credentials",
    "TOKEN_EXPIRED": "Google API token expired",
    "RATE_LIMIT_EXCEEDED": "Google API rate limit exceeded",
    "SERVICE_UNAVAILABLE": "Google API service unavailable",
    "FILE_NOT_FOUND": "File not found in Google Drive",
    "PERMISSION_INSUFFICIENT": "Insufficient permissions for Google API operation",
}

# AI/ML Errors
AI_ERRORS = {
    "MODEL_NOT_AVAILABLE": "AI model not available",
    "GENERATION_FAILED": "Content generation failed",
    "TOKEN_LIMIT_EXCEEDED": "Token limit exceeded",
    "INVALID_PROMPT": "Invalid prompt provided",
    "MODEL_TIMEOUT": "AI model response timeout",
    "CONTENT_FILTERED": "Content filtered by AI safety measures",
    "QUOTA_EXHAUSTED": "AI service quota exhausted",
    "SERVICE_DEGRADED": "AI service performance degraded",
}

# Email Service Errors
EMAIL_ERRORS = {
    "SMTP_CONNECTION_FAILED": "SMTP connection failed",
    "INVALID_EMAIL_ADDRESS": "Invalid email address",
    "EMAIL_SEND_FAILED": "Failed to send email",
    "ATTACHMENT_TOO_LARGE": "Email attachment too large",
    "RECIPIENT_REJECTED": "Email recipient rejected",
    "AUTHENTICATION_FAILED": "Email authentication failed",
    "QUOTA_EXCEEDED": "Email quota exceeded",
    "TEMPLATE_ERROR": "Email template error",
}

# Meeting Processing Errors
MEETING_ERRORS = {
    "TRANSCRIPT_NOT_FOUND": "Meeting transcript not found",
    "INVALID_MEETING_DATA": "Invalid meeting data",
    "MEETING_NOT_FOUND": "Meeting not found",
    "DUPLICATE_PROCESSING": "Meeting already being processed",
    "PROCESSING_TIMEOUT": "Meeting processing timeout",
    "SUMMARY_GENERATION_FAILED": "Failed to generate meeting summary",
    "ATTENDEE_LIST_EMPTY": "Meeting attendee list is empty",
    "INVALID_TIME_RANGE": "Invalid meeting time range",
}

# File System Errors
FILE_ERRORS = {
    "FILE_NOT_FOUND": "File not found",
    "PERMISSION_DENIED": "File permission denied",
    "DISK_SPACE_FULL": "Insufficient disk space",
    "FILE_CORRUPTED": "File is corrupted",
    "INVALID_FILE_FORMAT": "Invalid file format",
    "FILE_TOO_LARGE": "File size exceeds limit",
    "READ_ERROR": "File read error",
    "WRITE_ERROR": "File write error",
}

# Agent Workflow Errors
WORKFLOW_ERRORS = {
    "STEP_FAILED": "Workflow step failed",
    "INVALID_WORKFLOW_STATE": "Invalid workflow state",
    "WORKFLOW_TIMEOUT": "Workflow execution timeout",
    "DEPENDENCY_MISSING": "Required dependency missing",
    "TOOL_UNAVAILABLE": "Required tool unavailable",
    "EXECUTION_INTERRUPTED": "Workflow execution interrupted",
    "RETRY_LIMIT_EXCEEDED": "Maximum retry attempts exceeded",
    "VALIDATION_FAILED": "Workflow validation failed",
}

# Notification Errors
NOTIFICATION_ERRORS = {
    "SMS_SEND_FAILED": "SMS send failed",
    "WEBHOOK_FAILED": "Webhook delivery failed",
    "INVALID_RECIPIENT": "Invalid notification recipient",
    "MESSAGE_TOO_LONG": "Notification message too long",
    "RATE_LIMITED": "Notification rate limited",
    "SERVICE_UNAVAILABLE": "Notification service unavailable",
}

# Configuration Errors
CONFIG_ERRORS = {
    "MISSING_ENV_VAR": "Required environment variable missing",
    "INVALID_CONFIG_VALUE": "Invalid configuration value",
    "CONFIG_FILE_NOT_FOUND": "Configuration file not found",
    "CONFIG_PARSE_ERROR": "Configuration parsing error",
    "INCOMPATIBLE_SETTINGS": "Incompatible configuration settings",
    "VALIDATION_FAILED": "Configuration validation failed",
}

# Security Errors
SECURITY_ERRORS = {
    "UNAUTHORIZED_ACCESS": "Unauthorized access attempt",
    "INVALID_TOKEN": "Invalid security token",
    "ENCRYPTION_FAILED": "Encryption operation failed",
    "DECRYPTION_FAILED": "Decryption operation failed",
    "CERTIFICATE_INVALID": "Invalid security certificate",
    "SIGNATURE_VERIFICATION_FAILED": "Digital signature verification failed",
}

# Error Severity Levels
ERROR_SEVERITY = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "INFO": "info",
}

# Error Categories for Logging
ERROR_CATEGORIES = {
    "SYSTEM": "system",
    "USER": "user",
    "EXTERNAL": "external",
    "CONFIGURATION": "configuration",
    "SECURITY": "security",
    "PERFORMANCE": "performance",
}


def get_error_message(error_code: str, category: str = None) -> str:
    """
    Get error message by code and optional category.

    Args:
        error_code: The error code to look up
        category: Optional category to search in

    Returns:
        Error message string or generic message if not found
    """
    error_maps = {
        "general": GENERAL_ERRORS,
        "database": DATABASE_ERRORS,
        "google_api": GOOGLE_API_ERRORS,
        "ai": AI_ERRORS,
        "email": EMAIL_ERRORS,
        "meeting": MEETING_ERRORS,
        "file": FILE_ERRORS,
        "workflow": WORKFLOW_ERRORS,
        "notification": NOTIFICATION_ERRORS,
        "config": CONFIG_ERRORS,
        "security": SECURITY_ERRORS,
    }

    if category and category in error_maps:
        return error_maps[category].get(error_code, f"Unknown error: {error_code}")

    # Search all categories if no specific category provided
    for error_map in error_maps.values():
        if error_code in error_map:
            return error_map[error_code]

    return f"Unknown error: {error_code}"


def format_error_response(
    error_code: str, details: str = None, category: str = None
) -> dict:
    """
    Format a standardized error response.

    Args:
        error_code: The error code
        details: Additional error details
        category: Error category

    Returns:
        Formatted error dictionary
    """
    return {
        "error": True,
        "error_code": error_code,
        "message": get_error_message(error_code, category),
        "details": details,
        "category": category or "general",
        "timestamp": "2024-01-01T00:00:00Z",  # This would be datetime.utcnow().isoformat() in real usage
    }