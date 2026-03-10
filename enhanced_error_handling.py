"""
Enhanced Error Handling Utilities

This module provides standardized error handling across the application
with proper logging, user-friendly messages, and consistent response formats.
"""

import logging
import traceback
from datetime import datetime
from typing import Any, Dict, Optional, Union
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for better organization."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    DATABASE = "database"
    EXTERNAL_API = "external_api"
    INTERNAL = "internal"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    TIMEOUT = "timeout"


class ApplicationError(Exception):
    """Base application error with enhanced context."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.error_code = error_code
        self.details = details or {}
        self.original_error = original_error
        self.timestamp = datetime.now()
        
        # Log the error
        self._log_error()
    
    def _log_error(self):
        """Log the error with appropriate level based on severity."""
        log_data = {
            "error_code": self.error_code,
            "category": self.category.value,
            "severity": self.severity.value,
            "details": self.details,
            "timestamp": self.timestamp.isoformat()
        }
        
        if self.original_error:
            log_data["original_error"] = str(self.original_error)
        
        if self.severity == ErrorSeverity.CRITICAL:
            logger.critical(f"CRITICAL ERROR: {self.message}", extra=log_data)
        elif self.severity == ErrorSeverity.HIGH:
            logger.error(f"HIGH SEVERITY ERROR: {self.message}", extra=log_data)
        elif self.severity == ErrorSeverity.MEDIUM:
            logger.warning(f"MEDIUM SEVERITY ERROR: {self.message}", extra=log_data)
        else:
            logger.info(f"LOW SEVERITY ERROR: {self.message}", extra=log_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error": True,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "error_code": self.error_code,
            "details": self.details,
            "timestamp": self.timestamp.isoformat()
        }


class AuthenticationError(ApplicationError):
    """Authentication-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            error_code="AUTH_ERROR",
            details=details
        )


class AuthorizationError(ApplicationError):
    """Authorization-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            error_code="AUTHZ_ERROR",
            details=details
        )


class ValidationError(ApplicationError):
    """Input validation errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            error_code="VALIDATION_ERROR",
            details=details
        )


class DatabaseError(ApplicationError):
    """Database-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            error_code="DB_ERROR",
            details=details,
            original_error=original_error
        )


class ExternalAPIError(ApplicationError):
    """External API integration errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.EXTERNAL_API,
            severity=ErrorSeverity.MEDIUM,
            error_code="EXTERNAL_API_ERROR",
            details=details,
            original_error=original_error
        )


class ConfigurationError(ApplicationError):
    """Configuration-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.CRITICAL,
            error_code="CONFIG_ERROR",
            details=details
        )


class NetworkError(ApplicationError):
    """Network-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            error_code="NETWORK_ERROR",
            details=details,
            original_error=original_error
        )


class TimeoutError(ApplicationError):
    """Timeout-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            error_code="TIMEOUT_ERROR",
            details=details
        )


def handle_error(
    error: Exception,
    context: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle any exception and convert it to a standardized error response.
    
    Args:
        error: The exception to handle
        context: Additional context about where the error occurred
        user_id: User ID if available
        request_id: Request ID if available
    
    Returns:
        Dict containing standardized error information
    """
    error_details = {
        "context": context,
        "user_id": user_id,
        "request_id": request_id,
        "traceback": traceback.format_exc() if logger.level <= logging.DEBUG else None
    }
    
    if isinstance(error, ApplicationError):
        # Already a standardized error
        response = error.to_dict()
        response["details"].update(error_details)
        return response
    
    # Convert generic exceptions to ApplicationError
    if isinstance(error, ValueError):
        app_error = ValidationError(str(error), error_details)
    elif isinstance(error, (ConnectionError, TimeoutError)):
        app_error = NetworkError(str(error), error_details, error)
    elif isinstance(error, KeyError):
        app_error = ConfigurationError(f"Missing configuration: {str(error)}", error_details)
    else:
        app_error = ApplicationError(
            message=str(error),
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.HIGH,
            error_code="UNKNOWN_ERROR",
            details=error_details,
            original_error=error
        )
    
    return app_error.to_dict()


def safe_execute(
    func: callable,
    *args,
    context: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        *args: Function arguments
        context: Context for error reporting
        user_id: User ID for error reporting
        request_id: Request ID for error reporting
        **kwargs: Function keyword arguments
    
    Returns:
        Dict with success status and result or error information
    """
    try:
        result = func(*args, **kwargs)
        return {
            "success": True,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        error_response = handle_error(e, context, user_id, request_id)
        return {
            "success": False,
            **error_response
        }


async def safe_execute_async(
    coro,
    context: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Safely execute an async function with error handling.
    
    Args:
        coro: Coroutine to execute
        context: Context for error reporting
        user_id: User ID for error reporting
        request_id: Request ID for error reporting
    
    Returns:
        Dict with success status and result or error information
    """
    try:
        result = await coro
        return {
            "success": True,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        error_response = handle_error(e, context, user_id, request_id)
        return {
            "success": False,
            **error_response
        }


def validate_required_fields(data: Dict[str, Any], required_fields: list) -> None:
    """
    Validate that required fields are present in data.
    
    Args:
        data: Data dictionary to validate
        required_fields: List of required field names
    
    Raises:
        ValidationError: If any required fields are missing
    """
    missing_fields = [field for field in required_fields if field not in data or data[field] is None]
    
    if missing_fields:
        raise ValidationError(
            f"Missing required fields: {', '.join(missing_fields)}",
            details={"missing_fields": missing_fields, "required_fields": required_fields}
        )


def validate_field_types(data: Dict[str, Any], field_types: Dict[str, type]) -> None:
    """
    Validate that fields have correct types.
    
    Args:
        data: Data dictionary to validate
        field_types: Dictionary mapping field names to expected types
    
    Raises:
        ValidationError: If any fields have incorrect types
    """
    type_errors = []
    
    for field, expected_type in field_types.items():
        if field in data and not isinstance(data[field], expected_type):
            type_errors.append({
                "field": field,
                "expected_type": expected_type.__name__,
                "actual_type": type(data[field]).__name__
            })
    
    if type_errors:
        raise ValidationError(
            "Field type validation failed",
            details={"type_errors": type_errors}
        )
