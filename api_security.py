"""
Advanced API Security with JWT Authentication, Rate Limiting, and RBAC
Production-grade security for FastAPI endpoints
"""

import os
import json
import logging
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from functools import wraps
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
import redis
# Skip .env loading to avoid OSError: [Errno 22] Invalid argument
# from dotenv import load_dotenv
# load_dotenv()


# Fallback to app configuration defaults if env vars are not set
try:
    from src.configuration.config import (
        API_KEY as CONFIG_API_KEY,
        API_SECRET as CONFIG_API_SECRET,
        REQUIRE_API_KEY as CONFIG_REQUIRE_API_KEY,
    )
except Exception:
    CONFIG_API_KEY = None
    CONFIG_API_SECRET = None
    CONFIG_REQUIRE_API_KEY = True

from src.security.token_manager import get_token_manager

logger = logging.getLogger(__name__)
# Security helpers
def _normalize_secret(value: Optional[str]) -> Optional[str]:
    try:
        return value.strip() if isinstance(value, str) else None
    except Exception:
        return value

# Security configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# API Key configuration with fallbacks to application config
API_KEY = _normalize_secret(os.getenv("API_KEY") or CONFIG_API_KEY)
API_SECRET = _normalize_secret(os.getenv("API_SECRET") or CONFIG_API_SECRET)
REQUIRE_API_KEY = (os.getenv("REQUIRE_API_KEY").lower() == "true") if os.getenv("REQUIRE_API_KEY") is not None else bool(CONFIG_REQUIRE_API_KEY)

# Request signature configuration
SIGNATURE_ALGORITHM = "sha256"
SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
SIGNATURE_TOLERANCE_SECONDS = int(os.getenv("SIGNATURE_TOLERANCE_SECONDS", "300"))  # 5 minutes

# IP Whitelisting configuration
ADMIN_IP_WHITELIST = os.getenv("ADMIN_IP_WHITELIST", "127.0.0.1,::1").split(",")
ENABLE_IP_WHITELIST = os.getenv("ENABLE_IP_WHITELIST", "false").lower() == "true"

# Rate limiting configuration - uses REDIS_URL from config
from ..configuration.config import REDIS_URL
RATE_LIMIT_REDIS_URL = REDIS_URL
DEFAULT_RATE_LIMITS = {
    "default": {"requests": 100, "window": 60},  # 100 requests per minute
    "auth": {"requests": 10, "window": 60},      # 10 auth attempts per minute
    "ai": {"requests": 10, "window": 60},        # 10 AI requests per minute
    "upload": {"requests": 5, "window": 60},     # 5 uploads per minute
    "admin": {"requests": 1000, "window": 60}    # 1000 requests per minute for admin
}

# IP whitelist for admin endpoints
ADMIN_IP_WHITELIST = [
    "127.0.0.1/32",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16"
]

# Security scheme
security = HTTPBearer()

class SecurityError(Exception):
    """Custom security error"""
    pass

class APIKeyValidator:
    """API Key validation and management"""

    @staticmethod
    def validate_api_key(api_key: str, api_secret: str) -> bool:
        """
        Validate API key and secret pair

        Args:
            api_key: API key from request
            api_secret: API secret from request

        Returns:
            True if valid, False otherwise
        """
        try:
            if not REQUIRE_API_KEY:
                return True

            if not API_KEY or not API_SECRET:
                logger.warning("API_KEY or API_SECRET not configured but required")
                return False

            # Constant-time comparison to prevent timing attacks
            key_valid = hmac.compare_digest(str(api_key), str(API_KEY))
            secret_valid = hmac.compare_digest(str(api_secret), str(API_SECRET))

            return key_valid and secret_valid

        except Exception as e:
            logger.error(f"API key validation error: {e}")
            return False

    @staticmethod
    def extract_api_credentials(request: Request) -> tuple[Optional[str], Optional[str]]:
        """
        Extract API key and secret from request headers

        Args:
            request: FastAPI request object

        Returns:
            Tuple of (api_key, api_secret)
        """
        api_key = request.headers.get("PLATFORM_TASK_API_KEY") or request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        api_secret = request.headers.get("PLATFORM_TASK_API_SECRET") or request.headers.get("X-API-Secret") or request.headers.get("x-api-secret")

        return api_key, api_secret

class RequestSignatureValidator:
    """Request signature validation for enhanced security"""

    @staticmethod
    def generate_signature(payload: str, secret: str, timestamp: str) -> str:
        """
        Generate HMAC signature for request

        Args:
            payload: Request payload (JSON string)
            secret: Secret key for signing
            timestamp: Request timestamp

        Returns:
            HMAC signature
        """
        try:
            # Create signature string: timestamp + payload
            signature_string = f"{timestamp}.{payload}"

            # Generate HMAC-SHA256 signature
            signature = hmac.new(
                secret.encode(),
                signature_string.encode(),
                hashlib.sha256
            ).hexdigest()

            return f"sha256={signature}"

        except Exception as e:
            logger.error(f"Signature generation error: {e}")
            raise SecurityError(f"Failed to generate signature: {e}")

    @staticmethod
    def verify_signature(request: Request, payload: str) -> bool:
        """
        Verify request signature

        Args:
            request: FastAPI request object
            payload: Request payload (JSON string)

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            # Extract signature and timestamp from headers
            signature = request.headers.get(SIGNATURE_HEADER)
            timestamp = request.headers.get(TIMESTAMP_HEADER)

            if not signature or not timestamp:
                logger.warning("Missing signature or timestamp headers")
                return False

            # Check timestamp tolerance
            try:
                request_time = int(timestamp)
                current_time = int(time.time())

                if abs(current_time - request_time) > SIGNATURE_TOLERANCE_SECONDS:
                    logger.warning(f"Request timestamp outside tolerance: {abs(current_time - request_time)}s")
                    return False

            except ValueError:
                logger.warning("Invalid timestamp format")
                return False

            # Generate expected signature
            if not API_SECRET:
                logger.warning("API_SECRET not configured for signature verification")
                return False

            expected_signature = RequestSignatureValidator.generate_signature(
                payload, API_SECRET, timestamp
            )

            # Constant-time comparison
            return hmac.compare_digest(signature, expected_signature)

        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False

class IPWhitelistValidator:
    """IP address whitelisting for sensitive endpoints"""

    @staticmethod
    def is_ip_whitelisted(client_ip: str, whitelist: List[str] = None) -> bool:
        """
        Check if IP address is whitelisted

        Args:
            client_ip: Client IP address
            whitelist: List of allowed IP addresses/networks

        Returns:
            True if IP is whitelisted, False otherwise
        """
        try:
            if not ENABLE_IP_WHITELIST:
                return True

            if whitelist is None:
                whitelist = ADMIN_IP_WHITELIST

            client_addr = ip_address(client_ip)

            for allowed in whitelist:
                try:
                    # Handle both single IPs and CIDR networks
                    if '/' in allowed:
                        if client_addr in ip_network(allowed, strict=False):
                            return True
                    else:
                        if client_addr == ip_address(allowed):
                            return True
                except ValueError:
                    logger.warning(f"Invalid IP/network in whitelist: {allowed}")
                    continue

            return False

        except Exception as e:
            logger.error(f"IP whitelist validation error: {e}")
            return False

    @staticmethod
    def get_client_ip(request: Request) -> str:
        """
        Extract client IP address from request

        Args:
            request: FastAPI request object

        Returns:
            Client IP address
        """
        # Check for forwarded headers (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        # Fallback to direct connection IP
        return request.client.host if request.client else "unknown"

class RateLimiter:
    """Redis-based rate limiter"""

    def __init__(self):
        self.redis_client = None
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection"""
        try:
            import redis
            self.redis_client = redis.from_url(RATE_LIMIT_REDIS_URL)
            self.redis_client.ping()
            logger.info("Rate limiter Redis connection established")
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory rate limiting: {e}")
            self.redis_client = None
            self._memory_store = {}

    def is_allowed(self, key: str, limit: int, window: int) -> tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed under rate limit

        Args:
            key: Unique identifier for rate limiting
            limit: Maximum requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        try:
            current_time = int(time.time())
            window_start = current_time - window

            if self.redis_client:
                return self._redis_rate_limit(key, limit, window, current_time, window_start)
            else:
                return self._memory_rate_limit(key, limit, window, current_time, window_start)

        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail open - allow request if rate limiter fails
            return True, {"remaining": limit, "reset_time": current_time + window}

    def _redis_rate_limit(self, key: str, limit: int, window: int, current_time: int, window_start: int):
        """Redis-based rate limiting"""
        pipe = self.redis_client.pipeline()

        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current requests
        pipe.zcard(key)

        # Add current request
        pipe.zadd(key, {str(current_time): current_time})

        # Set expiry
        pipe.expire(key, window)

        results = pipe.execute()
        current_requests = results[1]

        is_allowed = current_requests < limit
        remaining = max(0, limit - current_requests - 1)
        reset_time = current_time + window

        return is_allowed, {
            "remaining": remaining,
            "reset_time": reset_time,
            "current_requests": current_requests
        }

    def _memory_rate_limit(self, key: str, limit: int, window: int, current_time: int, window_start: int):
        """In-memory rate limiting fallback"""
        if key not in self._memory_store:
            self._memory_store[key] = []

        # Remove old entries
        self._memory_store[key] = [
            timestamp for timestamp in self._memory_store[key]
            if timestamp > window_start
        ]

        current_requests = len(self._memory_store[key])
        is_allowed = current_requests < limit

        if is_allowed:
            self._memory_store[key].append(current_time)

        remaining = max(0, limit - current_requests - (1 if is_allowed else 0))
        reset_time = current_time + window

        return is_allowed, {
            "remaining": remaining,
            "reset_time": reset_time,
            "current_requests": current_requests
        }

# Global rate limiter instance
rate_limiter = RateLimiter()

class JWTManager:
    """Enhanced JWT token management"""

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        try:
            to_encode = data.copy()

            if expires_delta:
                expire = datetime.utcnow() + expires_delta
            else:
                expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)

            to_encode.update({
                "exp": expire,
                "iat": datetime.utcnow(),
                "type": "access"
            })

            encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
            return encoded_jwt

        except Exception as e:
            logger.error(f"JWT creation failed: {e}")
            raise SecurityError(f"Failed to create JWT token: {e}")

    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

            # Validate token type
            if payload.get("type") != "access":
                raise SecurityError("Invalid token type")

            return payload

        except JWTError as e:
            raise SecurityError(f"JWT validation failed: {e}")
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise SecurityError(f"Token verification failed: {e}")

class PasswordManager:
    """Secure password hashing and verification"""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password with bcrypt"""
        try:
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            return hashed.decode('utf-8')
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            raise SecurityError(f"Password hashing failed: {e}")

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False

# Duplicate RequestSignatureValidator class removed - using the one at line 120

def check_ip_whitelist(client_ip: str, whitelist: List[str]) -> bool:
    """Check if IP is in whitelist"""
    try:
        client_addr = ip_address(client_ip)

        for allowed_network in whitelist:
            if client_addr in ip_network(allowed_network):
                return True

        return False

    except Exception as e:
        logger.error(f"IP whitelist check failed: {e}")
        return False

def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    # Check for forwarded headers (load balancer/proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback to direct connection
    return request.client.host if request.client else "unknown"

async def rate_limit_dependency(
    request: Request,
    limit_type: str = "default"
) -> None:
    """Rate limiting dependency"""
    try:
        # Get rate limit configuration
        rate_config = DEFAULT_RATE_LIMITS.get(limit_type, DEFAULT_RATE_LIMITS["default"])

        # Create rate limit key
        client_ip = get_client_ip(request)
        rate_key = f"rate_limit:{limit_type}:{client_ip}"

        # Check rate limit
        is_allowed, rate_info = rate_limiter.is_allowed(
            rate_key,
            rate_config["requests"],
            rate_config["window"]
        )

        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "retry_after": rate_info.get("reset_time", 60),
                    "limit": rate_config["requests"],
                    "window": rate_config["window"]
                }
            )

        # Add rate limit headers to response (handled by middleware)
        request.state.rate_limit_info = rate_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limiting error: {e}")
        # Fail open - allow request if rate limiter fails

async def jwt_auth_dependency(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """JWT authentication dependency"""
    try:
        if not credentials or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Verify JWT token
        token_payload = JWTManager.verify_token(credentials.credentials)

        return token_payload

    except SecurityError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        logger.error(f"JWT authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def admin_auth_dependency(
    request: Request,
    token_payload: Dict[str, Any] = Depends(jwt_auth_dependency)
) -> Dict[str, Any]:
    """Admin authentication with IP whitelisting"""
    try:
        # Check admin role
        user_role = token_payload.get("role", "")
        if user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )

        # Check IP whitelist
        client_ip = get_client_ip(request)
        if not check_ip_whitelist(client_ip, ADMIN_IP_WHITELIST):
            logger.warning(f"Admin access denied for IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied from this IP address"
            )

        return token_payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin authentication failed"
        )

def require_signature(secret_key: str):
    """Decorator for endpoints requiring request signature"""
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            try:
                # Get signature from header
                signature = request.headers.get("X-Signature")
                if not signature:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Missing request signature"
                    )

                # Get request body
                body = await request.body()
                payload = body.decode('utf-8')

                # Verify signature using the correct method
                if not RequestSignatureValidator.verify_signature(request, payload):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid request signature"
                    )

                return await func(request, *args, **kwargs)

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Signature validation failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Signature validation error"
                )

        return wrapper
    return decorator

# Role-based access control
class RoleChecker:
    """Role-based access control"""

    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, token_payload: Dict[str, Any] = Depends(jwt_auth_dependency)) -> Dict[str, Any]:
        user_role = token_payload.get("role", "")

        if user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(self.allowed_roles)}"
            )

        return token_payload

# Convenience functions for common role checks
require_admin = RoleChecker(["admin"])
require_user = RoleChecker(["user", "admin"])
require_agent = RoleChecker(["agent", "admin"])

# Comprehensive Authentication Dependencies

async def api_key_dependency(request: Request) -> Dict[str, Any]:
    """
    API Key authentication dependency
    Validates PLATFORM_TASK_API_KEY and PLATFORM_TASK_API_SECRET headers (with legacy X-API-* fallback)
    """
    try:
        # Fail-fast checks in production for API credentials only. Do not enforce JWT here.
        if os.getenv("APP_ENVIRONMENT", "development") == "production":
            if REQUIRE_API_KEY and (not API_KEY or not API_SECRET):
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API credentials not configured")

        api_key, api_secret = APIKeyValidator.extract_api_credentials(request)

        if not APIKeyValidator.validate_api_key(api_key, api_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key or secret",
                headers={"WWW-Authenticate": "ApiKey"}
            )

        return {
            "api_key": api_key,
            "authenticated_via": "api_key",
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

async def signature_verification_dependency(request: Request) -> Dict[str, Any]:
    """
    Request signature verification dependency
    Validates HMAC signature of request payload
    """
    try:
        # Get request body for signature verification
        body = await request.body()
        payload = body.decode() if body else ""

        if not RequestSignatureValidator.verify_signature(request, payload):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid request signature",
                headers={"WWW-Authenticate": "Signature"}
            )

        return {
            "signature_verified": True,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signature verification service error"
        )

async def ip_whitelist_dependency(request: Request) -> Dict[str, Any]:
    """
    IP whitelist validation dependency
    Validates client IP against whitelist for admin endpoints
    """
    try:
        client_ip = IPWhitelistValidator.get_client_ip(request)

        if not IPWhitelistValidator.is_ip_whitelisted(client_ip):
            logger.warning(f"Access denied for IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: IP not whitelisted"
            )

        return {
            "client_ip": client_ip,
            "ip_whitelisted": True,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"IP whitelist validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IP validation service error"
        )

async def full_authentication_dependency(
    request: Request,
    rate_limit: None = Depends(rate_limit_dependency),
    api_key_data: Dict[str, Any] = Depends(api_key_dependency),
    jwt_data: Dict[str, Any] = Depends(jwt_auth_dependency)
) -> Dict[str, Any]:
    """
    Full authentication dependency combining all security measures
    - Rate limiting
    - API key validation
    - JWT bearer token validation
    """
    return {
        "user_id": jwt_data.get("user_id"),
        "role": jwt_data.get("role"),
        "api_key": api_key_data.get("api_key"),
        "authenticated_via": ["jwt", "api_key"],
        "rate_limited": True,
        "timestamp": datetime.utcnow().isoformat()
    }

async def admin_authentication_dependency(
    request: Request,
    rate_limit: None = Depends(rate_limit_dependency),
    api_key_data: Dict[str, Any] = Depends(api_key_dependency),
    jwt_data: Dict[str, Any] = Depends(jwt_auth_dependency),
    ip_data: Dict[str, Any] = Depends(ip_whitelist_dependency)
) -> Dict[str, Any]:
    """
    Admin authentication dependency with all security measures
    - Rate limiting
    - API key validation
    - JWT bearer token validation
    - IP whitelisting
    """
    # Verify admin role
    if jwt_data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required"
        )

    return {
        "user_id": jwt_data.get("user_id"),
        "role": jwt_data.get("role"),
        "api_key": api_key_data.get("api_key"),
        "client_ip": ip_data.get("client_ip"),
        "authenticated_via": ["jwt", "api_key", "ip_whitelist"],
        "rate_limited": True,
        "timestamp": datetime.utcnow().isoformat()
    }

async def signature_authentication_dependency(
    request: Request,
    rate_limit: None = Depends(rate_limit_dependency),
    api_key_data: Dict[str, Any] = Depends(api_key_dependency),
    jwt_data: Dict[str, Any] = Depends(jwt_auth_dependency),
    signature_data: Dict[str, Any] = Depends(signature_verification_dependency)
) -> Dict[str, Any]:
    """
    Signature authentication dependency for high-security endpoints
    - Rate limiting
    - API key validation
    - JWT bearer token validation
    - Request signature verification
    """
    return {
        "user_id": jwt_data.get("user_id"),
        "role": jwt_data.get("role"),
        "api_key": api_key_data.get("api_key"),
        "signature_verified": signature_data.get("signature_verified"),
        "authenticated_via": ["jwt", "api_key", "signature"],
        "rate_limited": True,
        "timestamp": datetime.utcnow().isoformat()
    }

# Convenience aliases for backward compatibility
authenticate_request = full_authentication_dependency
admin_auth_dependency = admin_authentication_dependency