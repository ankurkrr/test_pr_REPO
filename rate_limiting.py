"""
Rate Limiting Middleware

Provides rate limiting functionality for API endpoints to prevent abuse
and ensure fair resource usage.
"""

import time
import logging
from typing import Dict, Optional
from collections import defaultdict, deque
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Simple in-memory rate limiter using sliding window algorithm.
    
    For production, consider using Redis-based rate limiting.
    """
    
    def __init__(self):
        self.requests: Dict[str, deque] = defaultdict(deque)
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    def is_allowed(
        self, 
        key: str, 
        limit: int, 
        window: int,
        cleanup_threshold: int = 1000
    ) -> bool:
        """
        Check if request is allowed based on rate limit.
        
        Args:
            key: Unique identifier for the rate limit (e.g., IP address, user_id)
            limit: Maximum number of requests allowed
            window: Time window in seconds
            cleanup_threshold: Clean up old entries when this many keys exist
            
        Returns:
            True if request is allowed, False otherwise
        """
        current_time = time.time()
        
        # Cleanup old entries periodically
        if (current_time - self.last_cleanup) > self.cleanup_interval:
            self._cleanup_old_entries(current_time, window)
            self.last_cleanup = current_time
        
        # Cleanup if too many keys
        if len(self.requests) > cleanup_threshold:
            self._cleanup_old_entries(current_time, window)
        
        # Get request history for this key
        request_times = self.requests[key]
        
        # Remove requests outside the window
        cutoff_time = current_time - window
        while request_times and request_times[0] < cutoff_time:
            request_times.popleft()
        
        # Check if under limit
        if len(request_times) < limit:
            request_times.append(current_time)
            return True
        
        return False
    
    def _cleanup_old_entries(self, current_time: float, window: int):
        """Remove old entries to prevent memory leaks"""
        cutoff_time = current_time - window
        keys_to_remove = []
        
        for key, request_times in self.requests.items():
            # Remove old requests
            while request_times and request_times[0] < cutoff_time:
                request_times.popleft()
            
            # Remove empty entries
            if not request_times:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.requests[key]
        
        logger.debug(f"Rate limiter cleanup: removed {len(keys_to_remove)} old entries")


# Global rate limiter instance
rate_limiter = RateLimiter()


def get_client_identifier(request: Request) -> str:
    """
    Get unique identifier for rate limiting.
    
    Uses IP address as primary identifier, with fallback to user agent.
    """
    # Try to get real IP from headers (for reverse proxy setups)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct client IP
    return request.client.host if request.client else "unknown"


def rate_limit(limit: int = 10, window: int = 60):
    """
    Decorator for rate limiting API endpoints.
    
    Args:
        limit: Maximum number of requests allowed
        window: Time window in seconds
        
    Usage:
        @rate_limit(limit=10, window=60)  # 10 requests per minute
        async def my_endpoint(request: Request):
            pass
    """
    def decorator(func):
        import functools
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object in arguments (support both args and kwargs)
            request: Optional[Request] = None
            # Search positional args first
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            # If not found, search keyword args values
            if request is None:
                for value in kwargs.values():
                    if isinstance(value, Request):
                        request = value
                        break

            # If still not found, attempt common kwarg names
            if request is None:
                candidate = kwargs.get("request") or kwargs.get("http_request")
                if isinstance(candidate, Request):
                    request = candidate

            if request is None:
                logger.warning("Rate limiter: No Request object found in function arguments")
                return await func(*args, **kwargs)
            
            # Get client identifier
            client_id = get_client_identifier(request)
            
            # Check rate limit
            if not rate_limiter.is_allowed(client_id, limit, window):
                logger.warning(f"Rate limit exceeded for {client_id}: {limit} requests per {window}s")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {limit} requests per {window} seconds",
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Window": str(window),
                        "Retry-After": str(window)
                    }
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# Predefined rate limits for different endpoint types
WORKFLOW_RATE_LIMIT = rate_limit(limit=5, window=300)  # 5 requests per 5 minutes
OAUTH_RATE_LIMIT = rate_limit(limit=10, window=60)      # 10 requests per minute
WEBHOOK_RATE_LIMIT = rate_limit(limit=20, window=60)    # 20 requests per minute
HEALTH_RATE_LIMIT = rate_limit(limit=100, window=60)     # 100 requests per minute
GENERAL_RATE_LIMIT = rate_limit(limit=30, window=60)    # 30 requests per minute
