"""
Error Handling Utilities

Provides comprehensive error handling patterns including circuit breaker,
retry logic, and graceful degradation for external service calls.
"""

import asyncio
import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Failing, blocking requests
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5
    timeout: int = 60
    expected_exception: Type[Exception] = Exception


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for external service calls.
    
    Prevents cascading failures by temporarily blocking requests to failing services.
    """
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
        
    def __call__(self, func: Callable) -> Callable:
        """Decorator for circuit breaker functionality"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                else:
                    raise Exception(f"Circuit breaker is OPEN for {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result
            except self.config.expected_exception as e:
                self._on_failure()
                raise e
                
        return wrapper
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        return (time.time() - self.last_failure_time) >= self.config.timeout
    
    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED
        
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Retry decorator with exponential backoff and jitter.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff calculation
        jitter: Add random jitter to prevent thundering herd
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"Max retries ({max_retries}) exceeded for {func.__name__}")
                        raise e
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    # Add jitter to prevent thundering herd
                    if jitter:
                        import random
                        delay *= (0.5 + random.random() * 0.5)
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay:.2f}s")
                    await asyncio.sleep(delay)
            
            raise last_exception
            
        return wrapper
    return decorator


class GracefulDegradation:
    """
    Graceful degradation handler for external service failures.
    
    Provides fallback mechanisms when external services are unavailable.
    """
    
    def __init__(self, fallback_func: Optional[Callable] = None):
        self.fallback_func = fallback_func
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for graceful degradation"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Service call failed for {func.__name__}: {e}")
                
                if self.fallback_func:
                    try:
                        logger.info(f"Using fallback for {func.__name__}")
                        return await self.fallback_func(*args, **kwargs)
                    except Exception as fallback_error:
                        logger.error(f"Fallback also failed for {func.__name__}: {fallback_error}")
                
                # Return default response based on function name
                return self._get_default_response(func.__name__)
                
        return wrapper
    
    def _get_default_response(self, func_name: str) -> Dict[str, Any]:
        """Get default response for failed service calls"""
        defaults = {
            "send_webhook": {"success": False, "error": "Service unavailable"},
            "process_tasks": {"success": False, "tasks_processed": 0},
            "get_calendar_events": {"events": [], "status": "service_unavailable"},
            "search_drive_files": {"files": [], "status": "service_unavailable"},
        }
        
        return defaults.get(func_name, {"success": False, "error": "Service unavailable"})


class ErrorHandler:
    """
    Centralized error handling for the application.
    
    Provides consistent error logging, monitoring, and response formatting.
    """
    
    @staticmethod
    def handle_webhook_error(error: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle webhook-specific errors"""
        logger.error(f"Webhook error in {context.get('endpoint', 'unknown')}: {error}")
        
        return {
            "success": False,
            "error": "Webhook delivery failed",
            "error_type": type(error).__name__,
            "context": context,
            "timestamp": time.time()
        }
    
    @staticmethod
    def handle_database_error(error: Exception, operation: str) -> Dict[str, Any]:
        """Handle database-specific errors"""
        logger.error(f"Database error in {operation}: {error}")
        
        return {
            "success": False,
            "error": "Database operation failed",
            "operation": operation,
            "error_type": type(error).__name__,
            "timestamp": time.time()
        }
    
    @staticmethod
    def handle_external_api_error(error: Exception, service: str) -> Dict[str, Any]:
        """Handle external API errors"""
        logger.error(f"External API error for {service}: {error}")
        
        return {
            "success": False,
            "error": f"External service {service} unavailable",
            "service": service,
            "error_type": type(error).__name__,
            "timestamp": time.time()
        }


# Global circuit breaker instances for different services
webhook_circuit_breaker = CircuitBreaker(CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    expected_exception=Exception
))

database_circuit_breaker = CircuitBreaker(CircuitBreakerConfig(
    failure_threshold=5,
    timeout=60,
    expected_exception=Exception
))

external_api_circuit_breaker = CircuitBreaker(CircuitBreakerConfig(
    failure_threshold=3,
    timeout=45,
    expected_exception=Exception
))
