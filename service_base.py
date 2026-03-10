"""
Base service class providing common functionality for all services.

This class establishes patterns for:
- Dependency injection
- Error handling
- Logging
- Configuration management
- Health checks
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar, Generic
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """Generic result wrapper for service operations."""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __bool__(self) -> bool:
        """Return True if the operation was successful, False otherwise."""
        return self.success

    @classmethod
    def success_result(cls, data: T, metadata: Optional[Dict[str, Any]] = None) -> 'ServiceResult[T]':
        """Create a successful result."""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def error_result(cls, error: str, metadata: Optional[Dict[str, Any]] = None) -> 'ServiceResult[T]':
        """Create an error result."""
        return cls(success=False, error=error, metadata=metadata)


class BaseService(ABC):
    """
    Base class for all services in the application.

    Provides common functionality including:
    - Dependency injection
    - Error handling
    - Logging
    - Health checks
    - Configuration management
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the base service.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._dependencies: Dict[str, Any] = {}
        self._initialized = False

    def add_dependency(self, name: str, dependency: Any) -> None:
        """
        Add a dependency to the service.

        Args:
            name: Name of the dependency
            dependency: The dependency instance
        """
        self._dependencies[name] = dependency
        self.logger.debug(f"Added dependency: {name}")

    def get_dependency(self, name: str) -> Any:
        """
        Get a dependency by name.

        Args:
            name: Name of the dependency

        Returns:
            The dependency instance

        Raises:
            KeyError: If dependency not found
        """
        if name not in self._dependencies:
            raise KeyError(f"Dependency '{name}' not found")
        return self._dependencies[name]

    def has_dependency(self, name: str) -> bool:
        """
        Check if a dependency exists.

        Args:
            name: Name of the dependency

        Returns:
            True if dependency exists, False otherwise
        """
        return name in self._dependencies

    def initialize(self) -> None:
        """
        Initialize the service.

        This method should be called after all dependencies are added.
        Override in subclasses to perform initialization logic.
        """
        if self._initialized:
            self.logger.warning("Service already initialized")
            return

        self._perform_initialization()
        self._initialized = True
        self.logger.info(f"{self.__class__.__name__} initialized successfully")

    def _perform_initialization(self) -> None:
        """
        Perform service-specific initialization.

        Override in subclasses to add initialization logic.
        """
        pass

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the service.

        Returns:
            Dictionary containing health status information
        """
        try:
            health_status = {
                "service": self.__class__.__name__,
                "status": "healthy",
                "initialized": self._initialized,
                "dependencies": list(self._dependencies.keys()),
                "timestamp": datetime.now().isoformat()
            }

            # Perform service-specific health check
            service_health = self._check_service_health()
            health_status.update(service_health)

            return health_status

        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return {
                "service": self.__class__.__name__,
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def _check_service_health(self) -> Dict[str, Any]:
        """
        Perform service-specific health check.

        Override in subclasses to add service-specific health checks.

        Returns:
            Dictionary containing service-specific health information
        """
        return {}

    def handle_error(self, error: Exception, context: str = "") -> ServiceResult[None]:
        """
        Handle errors consistently across services.

        Args:
            error: The exception that occurred
            context: Additional context about where the error occurred

        Returns:
            ServiceResult indicating the error
        """
        error_msg = f"{context}: {str(error)}" if context else str(error)
        self.logger.error(error_msg, exc_info=True)

        return ServiceResult.error_result(
            error=error_msg,
            metadata={
                "error_type": type(error).__name__,
                "context": context,
                "timestamp": datetime.now().isoformat()
            }
        )

    def log_operation(self, operation: str, **kwargs) -> None:
        """
        Log service operations consistently.

        Args:
            operation: Name of the operation
            **kwargs: Additional context to log
        """
        self.logger.info(f"Operation: {operation}", extra=kwargs)

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def validate_config(self, required_keys: list) -> bool:
        """
        Validate that required configuration keys are present.

        Args:
            required_keys: List of required configuration keys

        Returns:
            True if all required keys are present, False otherwise
        """
        missing_keys = [key for key in required_keys if key not in self.config]

        if missing_keys:
            self.logger.error(f"Missing required configuration keys: {missing_keys}")
            return False

        return True