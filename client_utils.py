"""
Client utilities for the Meeting Intelligence Agent API.
Contains helper functions for client handling.
"""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Extract client IP with proper handling of proxy headers"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip

    # Handle cases where request.client might not exist
    try:
        return request.client.host if hasattr(request, 'client') and request.client else "unknown"
    except AttributeError:
        return "unknown"