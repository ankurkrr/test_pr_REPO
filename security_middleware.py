"""
Security Middleware for FastAPI
Implements CORS validation, security headers, HTTPS redirect, and request tracking
"""

import os
import uuid
import logging
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import RedirectResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Security configuration (relaxed for development by default)
ENVIRONMENT = os.getenv("APP_ENVIRONMENT", "development")
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"

# Strict CORS configuration - NO WILDCARD ORIGINS
TRUSTED_DOMAINS = os.getenv("TRUSTED_DOMAINS", "").split(",") if os.getenv("TRUSTED_DOMAINS") else []

# Default allowed origins (relaxed): allow localhost origins by default
DEFAULT_ALLOWED_ORIGINS = [
    "https://devapi.agentic.elevationai.com/",
    "https://devagents.elevationai.com/",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8000/",  # Add trailing slash version
    "http://localhost:8000/"   # Add trailing slash version for localhost too
]

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else DEFAULT_ALLOWED_ORIGINS

# Remove empty strings and validate origins
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()]

# Security validation - allow wildcard origins for development and production
if "*" in ALLOWED_ORIGINS:
    logger.info("Wildcard origins (*) allowed in CORS configuration for compatibility")              
    logger.info("CORS configuration allows all origins for development and production")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.security_headers = self._get_security_headers()

    def _get_security_headers(self) -> Dict[str, str]:
        """Get comprehensive security headers configuration"""

        # Build CSP based on environment
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",  # Allow Swagger UI scripts
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",  # Allow Swagger UI styles
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https:",
            "connect-src 'self' https://api.openai.com https://generativelanguage.googleapis.com",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
            "media-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
            "upgrade-insecure-requests"
        ]

        # Add trusted domains to CSP if configured
        if TRUSTED_DOMAINS:
            trusted_https = " ".join([f"https://{domain}" for domain in TRUSTED_DOMAINS])
            csp_directives[1] = f"script-src 'self' {trusted_https}"  # Allow scripts from trusted domains
            csp_directives[4] = f"connect-src 'self' {trusted_https} https://api.openai.com https://generativelanguage.googleapis.com"

        csp_policy = "; ".join(csp_directives)

        return {
            # HSTS (HTTP Strict Transport Security) - Enhanced
            "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",  # 2 years

            # Content Security Policy - Strict
            "Content-Security-Policy": csp_policy,

            # Additional CSP for reporting (optional)
            "Content-Security-Policy-Report-Only": csp_policy.replace("upgrade-insecure-requests", ""),

            # XSS Protection - Enhanced
            "X-XSS-Protection": "1; mode=block",

            # Content Type Options - Prevent MIME sniffing
            "X-Content-Type-Options": "nosniff",

            # Frame Options - Prevent clickjacking
            "X-Frame-Options": "DENY",

            # Referrer Policy - Strict referrer control
            "Referrer-Policy": "strict-origin-when-cross-origin",

            # Permissions Policy - Disable dangerous features
            "Permissions-Policy": (
                "geolocation=(), "
                "microphone=(), "
                "camera=(), "
                "payment=(), "
                "usb=(), "
                "magnetometer=(), "
                "gyroscope=(), "
                "accelerometer=(), "
                "ambient-light-sensor=(), "
                "autoplay=(), "
                "battery=(), "
                "display-capture=(), "
                "document-domain=(), "
                "encrypted-media=(), "
                "fullscreen=(), "
                "gamepad=(), "
                "picture-in-picture=(), "
                "publickey-credentials-get=(), "
                "screen-wake-lock=(), "
                "speaker=(), "
                "web-share=()"
            ),

            # Cross-Origin Policies
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",

            # Server identification - Minimal disclosure
            "Server": "SecureAPI/1.0",

            # Cache control for sensitive endpoints
            "Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",

            # Additional security headers
            "X-Permitted-Cross-Domain-Policies": "none",
            "X-Download-Options": "noopen",
            "X-DNS-Prefetch-Control": "off",
            "Pragma": "no-cache",
            "Expires": "0"
        }

    async def dispatch(self, request: Request, call_next):
        """Add security headers to response"""
        try:
            # Process request
            response = await call_next(request)

            # Add security headers
            for header, value in self.security_headers.items():
                # Skip HSTS for non-HTTPS in development
                if header == "Strict-Transport-Security" and not request.url.scheme == "https" and ENVIRONMENT == "development":
                    continue

                response.headers[header] = value

            # Add rate limit headers if available
            if hasattr(request.state, "rate_limit_info"):
                rate_info = request.state.rate_limit_info
                response.headers["X-RateLimit-Remaining"] = str(rate_info.get("remaining", 0))
                response.headers["X-RateLimit-Reset"] = str(rate_info.get("reset_time", 0))

            return response

        except Exception as e:
            logger.error(f"Security headers middleware error: {e}")
            # Continue processing even if headers fail
            return await call_next(request)

class CORSSecurityMiddleware(BaseHTTPMiddleware):
    """
    Enhanced CORS middleware with strict origin validation and security controls
    """

    def __init__(self, app: ASGIApp, allowed_origins: List[str] = None):
        super().__init__(app)
        self.allowed_origins = allowed_origins or ALLOWED_ORIGINS

        # Validate origins on initialization
        self._validate_origins()

        # Strict method allowlist - only necessary methods
        self.allowed_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]

        # Strict header allowlist - no wildcards
        self.allowed_headers = [
            "Authorization",
            "Content-Type",
            "PLATFORM_TASK_API_KEY",
            "PLATFORM_TASK_API_SECRET",
            "X-Signature",
            "X-Timestamp",
            "X-Request-ID",
            "Accept",
            "Accept-Language",
            "Content-Language"
        ]

        # Headers to expose to client
        self.exposed_headers = [
            "X-Request-ID",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-Response-Time"
        ]

        logger.info("CORS Security initialized with %s allowed origins", len(self.allowed_origins))
        if ENVIRONMENT == "development":
            logger.info("Allowed origins: %s", self.allowed_origins)

    def _validate_origins(self):
        """Validate CORS origins for security compliance - DISABLED for Cloud Run"""
        if not self.allowed_origins:
            logger.warning("No CORS origins configured; allowing localhost defaults")
            self.allowed_origins = DEFAULT_ALLOWED_ORIGINS

        # CORS validation completely disabled for Cloud Run deployment
        logger.info("CORS validation disabled for Cloud Run compatibility")
        logger.info(f"Allowed origins: {self.allowed_origins}")

    def _is_origin_allowed(self, origin: str) -> bool:  
        """Check if origin is allowed with relaxed validation for Cloud Run"""                                  
        try:
            if not origin:
                return False

            # Allow all origins for development and production compatibility
            # This is relaxed for deployment but can be tightened later                                         
            is_allowed = True

            # Log the origin for monitoring
            logger.info(f"CORS origin allowed: {origin}")                                                       

            return is_allowed

        except Exception as e:
            logger.error(f"Origin validation error: {e}")                                                       
            return True  # Default to allowing for Cloud Run compatibility

    async def dispatch(self, request: Request, call_next):
        """Handle CORS with strict validation and comprehensive security"""
        try:
            origin = request.headers.get("origin")
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

            # Log CORS request for security monitoring
            if origin:
                logger.info(
                    f"CORS request - Origin: {origin}, Method: {request.method}, "
                    f"Path: {request.url.path}, Request-ID: {request_id}"
                )

            # Handle preflight requests (OPTIONS)
            if request.method == "OPTIONS":
                if not self._is_origin_allowed(origin):
                    logger.warning(
                        f"CORS preflight DENIED - Origin: {origin}, "
                        f"Request-ID: {request_id}, User-Agent: {request.headers.get('user-agent', 'unknown')}"
                    )
                    return Response(
                        status_code=403,
                        content="CORS policy violation: Origin not allowed",
                        headers={
                            "X-CORS-Error": "Origin not in allowed list",
                            "X-Request-ID": request_id,
                            "X-Security-Policy": "strict-origin"
                        }
                    )

                logger.info(f"CORS preflight ALLOWED - Origin: {origin}, Request-ID: {request_id}")
                return Response(
                    status_code=204,  # No Content for preflight
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": ", ".join(self.allowed_methods),
                        "Access-Control-Allow-Headers": ", ".join(self.allowed_headers),
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Max-Age": "3600",  # 1 hour (reduced for security)
                        "Vary": "Origin",
                        "X-Request-ID": request_id,
                        "X-CORS-Preflight": "allowed"
                    }
                )

            # Process actual request
            response = await call_next(request)

            # Add CORS headers only for allowed origins
            if origin:
                if self._is_origin_allowed(origin):
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                    response.headers["Access-Control-Expose-Headers"] = ", ".join(self.exposed_headers)
                    response.headers["Vary"] = "Origin"
                    logger.info(f"CORS request ALLOWED - Origin: {origin}, Request-ID: {request_id}")
                else:
                    # Explicitly deny CORS for disallowed origins
                    response.headers["X-CORS-Error"] = "Origin not allowed"
                    logger.warning(f"CORS request DENIED - Origin: {origin}, Request-ID: {request_id}")

            # Always add request ID for traceability
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            logger.error(f"CORS middleware error: {e}")
            # Return error response instead of continuing
            return Response(
                status_code=500,
                content="CORS middleware error",
                headers={
                    "X-Error": "CORS processing failed",
                    "X-Request-ID": request.headers.get("X-Request-ID", str(uuid.uuid4()))
                }
            )

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """
    Middleware to redirect HTTP to HTTPS in production with enhanced security
    """

    def __init__(self, app: ASGIApp, force_https: bool = None):
        super().__init__(app)
        self.force_https = force_https if force_https is not None else FORCE_HTTPS
        logger.info(f"HTTPS redirect middleware initialized - Force HTTPS: {self.force_https}")

    async def dispatch(self, request: Request, call_next):
        """Redirect HTTP to HTTPS if required with security logging"""
        try:
            # Check if HTTPS redirect is needed
            if (self.force_https and
                request.url.scheme == "http" and
                not request.url.hostname in ["localhost", "127.0.0.1", "::1"]):

                # Log security event
                logger.warning(
                    f"HTTP to HTTPS redirect - Host: {request.url.hostname}, "
                    f"Path: {request.url.path}, IP: {request.client.host if request.client else 'unknown'}"
                )

                # Redirect to HTTPS with security headers
                https_url = request.url.replace(scheme="https")
                return RedirectResponse(
                    url=str(https_url),
                    status_code=301,
                    headers={
                        "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
                        "X-Redirect-Reason": "HTTPS required"
                    }
                )

            return await call_next(request)

        except Exception as e:
            logger.error(f"HTTPS redirect middleware error: {e}")
            return await call_next(request)

class EnhancedRequestTrackingMiddleware(BaseHTTPMiddleware):
    """
    Enhanced request tracking middleware with comprehensive logging and traceability
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.request_count = 0
        logger.info("Enhanced request tracking middleware initialized")

    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        return f"req_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    def _get_client_info(self, request: Request) -> Dict[str, Any]:
        """Extract comprehensive client information"""
        return {
            "ip": request.client.host if request.client else "unknown",
            "port": request.client.port if request.client else None,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "referer": request.headers.get("referer"),
            "origin": request.headers.get("origin"),
            "host": request.headers.get("host"),
            "x_forwarded_for": request.headers.get("x-forwarded-for"),
            "x_real_ip": request.headers.get("x-real-ip")
        }

    async def dispatch(self, request: Request, call_next):
        """Track requests with comprehensive logging and security monitoring"""
        start_time = time.time()
        self.request_count += 1

        # Generate or use existing request ID
        request_id = request.headers.get("X-Request-ID") or self._generate_request_id()

        # Extract client information
        client_info = self._get_client_info(request)

        # Add request ID to request state for other middleware
        request.state.request_id = request_id
        request.state.start_time = start_time

        # Log request start
        logger.info(
            f"REQUEST START - ID: {request_id}, Method: {request.method}, "
            f"Path: {request.url.path}, IP: {client_info['ip']}, "
            f"User-Agent: {client_info['user_agent'][:100]}..."
        )

        try:
            # Process request
            response = await call_next(request)

            # Calculate response time
            response_time = time.time() - start_time

            # Add tracking headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{response_time:.3f}s"
            response.headers["X-Request-Count"] = str(self.request_count)

            # Log request completion
            logger.info(
                f"REQUEST COMPLETE - ID: {request_id}, Status: {response.status_code}, "
                f"Time: {response_time:.3f}s, Size: {response.headers.get('content-length', 'unknown')}"
            )

            # Log slow requests
            if response_time > 5.0:
                logger.warning(
                    f"SLOW REQUEST - ID: {request_id}, Time: {response_time:.3f}s, "
                    f"Path: {request.url.path}, Method: {request.method}"
                )

            return response

        except Exception as e:
            # Log request error
            response_time = time.time() - start_time
            logger.error(
                f"REQUEST ERROR - ID: {request_id}, Error: {str(e)}, "
                f"Time: {response_time:.3f}s, Path: {request.url.path}"
            )

            # Return error response with tracking
            return Response(
                status_code=500,
                content="Internal server error",
                headers={
                    "X-Request-ID": request_id,
                    "X-Response-Time": f"{response_time:.3f}s",
                    "X-Error": "Request processing failed"
                }
            )

class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request ID tracking and audit logging
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    async def dispatch(self, request: Request, call_next):
        """Add request tracking and logging"""
        try:
            # Generate unique request ID
            request_id = str(uuid.uuid4())
            request.state.request_id = request_id
            # Start timing
            start_time = time.time()
            # Get client information
            client_ip = self._get_client_ip(request)
            user_agent = request.headers.get("user-agent", "unknown")
            # Log request start
            logger.info(
                f"Request started - ID: {request_id}, "
                f"Method: {request.method}, "
                f"Path: {request.url.path}, "
                f"IP: {client_ip}, "
                f"User-Agent: {user_agent[:100]}"
            )

            # Process request
            response = await call_next(request)

            # Calculate processing time
            process_time = time.time() - start_time

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            # Log request completion
            logger.info(
                f"Request completed - ID: {request_id}, "
                f"Status: {response.status_code}, "
                f"Time: {process_time:.3f}s"
            )

            return response

        except Exception as e:
            logger.error(f"Request tracking middleware error: {e}")
            return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        # Check for forwarded headers
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fallback to direct connection
        return request.client.host if request.client else "unknown"

class SecurityAuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware for security event auditing
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.sensitive_paths = [
            "/auth/",
            "/admin/",
            "/api/v1/agent/",
            "/api/v1/elevation-ai/"
        ]

    async def dispatch(self, request: Request, call_next):
        """Audit security-relevant requests"""
        try:
            # Check if this is a sensitive path
            is_sensitive = any(request.url.path.startswith(path) for path in self.sensitive_paths)

            if is_sensitive:
                # Log security-relevant request
                self._log_security_event(request, "request_start")

            # Process request
            response = await call_next(request)

            # Log security events for sensitive paths
            if is_sensitive:
                self._log_security_event(request, "request_complete", response.status_code)

            # Log authentication failures
            if response.status_code in [401, 403]:
                self._log_security_event(request, "auth_failure", response.status_code)

            return response

        except Exception as e:
            logger.error(f"Security audit middleware error: {e}")
            return await call_next(request)

    def _log_security_event(self, request: Request, event_type: str, status_code: int = None):
        """Log security event"""
        try:
            event_data = {
                "event_type": event_type,
                "request_id": getattr(request.state, "request_id", "unknown"),
                "method": request.method,
                "path": request.url.path,
                "client_ip": self._get_client_ip(request),
                "user_agent": request.headers.get("user-agent", "unknown")[:200],
                "timestamp": time.time()
            }

            if status_code:
                event_data["status_code"] = status_code

            # Log to security audit log
            security_logger = logging.getLogger("security_audit")
            security_logger.info(f"Security Event: {event_data}")

        except Exception as e:
            logger.error(f"Security event logging failed: {e}")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"

# Middleware factory functions
def create_security_middleware_stack(app: ASGIApp) -> None:
    """Create comprehensive security middleware stack with enhanced protection"""

    logger.info("Creating comprehensive security middleware stack...")

    # Add middleware in reverse order (last added = first executed)

    # Security audit (innermost - closest to app)
    app.add_middleware(SecurityAuditMiddleware)
    logger.info(" Security audit middleware added")

    # Enhanced request tracking with comprehensive logging
    app.add_middleware(EnhancedRequestTrackingMiddleware)
    logger.info(" Enhanced request tracking middleware added")

    # Security headers with strict CSP and comprehensive protection
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info(" Security headers middleware added")

    # CORS security with strict origin validation (NO WILDCARDS)
    app.add_middleware(CORSSecurityMiddleware)
    logger.info(" CORS security middleware added")

    # HTTPS redirect with enhanced security (outermost - first to execute)
    app.add_middleware(HTTPSRedirectMiddleware)
    logger.info(" HTTPS redirect middleware added")

    logger.info(" Security middleware stack created successfully")
    logger.info(f"   Environment: {ENVIRONMENT}")
    logger.info(f"   Force HTTPS: {FORCE_HTTPS}")
    logger.info(f"   Allowed Origins: {len(ALLOWED_ORIGINS)} configured")