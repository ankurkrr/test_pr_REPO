"""
Constants Configuration for Meeting Intelligence Agent
Defines app metadata, tool configurations, categories, and response formats
"""
import os
from enum import Enum

# =============================================================================
# APP METADATA
# =============================================================================
APP_NAME = "Enhanced Meeting Intelligence Agent"
APP_DESCRIPTION = """
 Advanced LangChain-powered agent with unified 3-table audit system for automated post-meeting intelligence.

 Core Features:
• LangChain integration with Gemini (google.generativeai)
• Google Calendar integration with automatic meeting detection
• Gmail automation for notifications and summaries
• Google Drive management for transcript storage
• Database metadata storage and task tracking
• AI-powered meeting summarization
• Automated task extraction and management
• Smart notifications and follow-ups
• Performance analytics and reporting
• Unified 3-table audit system (agent, user_agent_task, agent_function_log)

 Workflow: Identify → Summarize → Generate → Email → Store → Track → Audit

 Database: 3-table audit system for complete traceability
"""
APP_VERSION = "4.1.0"
APP_ENVIRONMENT = os.getenv("APP_ENVIRONMENT", "development")

# =============================================================================
# API CONFIGURATION
# =============================================================================
API_PREFIX = "/api/v1"
API_TITLE = f"{APP_NAME} API"
API_DOCS_URL = "/docs"
API_REDOC_URL = "/redoc"
API_OPENAPI_URL = "/openapi.json"

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEBUG_MODE = os.getenv("DEBUG", "False").lower() == "true"
RELOAD_ON_CHANGE = DEBUG_MODE

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
class LogLevels(str, Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

LOG_LEVELS = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL"
}


LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_PATH = "logging/api.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# =============================================================================
# HTTP STATUS CODES
# =============================================================================
class HTTPStatus:
    """HTTP status codes"""
    # Success
    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204
    # Client Errors
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    TOO_MANY_REQUESTS = 429

    # Server Errors
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

# =============================================================================
# RESPONSE STATUS
# =============================================================================
class ResponseStatus(str, Enum):
    """Response status"""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

RESPONSE_STATUS = {
    "SUCCESS": ResponseStatus.SUCCESS,
    "ERROR": ResponseStatus.ERROR,
    "WARNING": ResponseStatus.WARNING,
    "INFO": ResponseStatus.INFO,
    "PENDING": ResponseStatus.PENDING,
    "PROCESSING": ResponseStatus.PROCESSING,
    "COMPLETED": ResponseStatus.COMPLETED,
    "FAILED": ResponseStatus.FAILED
}

# =============================================================================
# CORS CONFIGURATION
# =============================================================================
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://localhost:8000/docs",
    "http://localhost:8000/redoc",
    "http://localhost:8000/openapi.json",
    # Deployment/frontends
    "https://devagents.elevationai.com",
    "https://devapi.agentic.elevationai.com"

]

if APP_ENVIRONMENT == "production":
    CORS_ORIGINS.extend([
       "https://elevationai.com",
        "https://www.elevationai.com",
        # Deployed development/staging surfaces
        "https://devagents.elevationai.com",
        "https://devapi.agentic.elevationai.com"

    ])

CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
# SECURITY: NO WILDCARD HEADERS - Explicit allowlist only
CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "PLATFORM_TASK_API_KEY",
    "PLATFORM_TASK_API_SECRET",
    "X-Signature",
    # Common API key header variants used by the platform
    "X-API-Key",
    "X-API-Secret",
    "x-api-key",
    "x-api-secret",
    "X-Timestamp",
    "X-Request-ID",
    "Accept",
    "Accept-Language",
    "Content-Language"
]
CORS_CREDENTIALS = True

# =============================================================================
# MIDDLEWARE CONFIGURATION
# =============================================================================
MIDDLEWARE_CONFIG = {
    "cors": {
        "allow_origins": CORS_ORIGINS,
        "allow_credentials": CORS_CREDENTIALS,
        "allow_methods": CORS_METHODS,
        "allow_headers": CORS_HEADERS,
    },
    "trusted_host": {
        "allowed_hosts": ["*"] if APP_ENVIRONMENT != "production" else ["yourdomain.com", "api.yourdomain.com"]
    }
}

# =============================================================================
# TOOL CONFIGURATIONS
# =============================================================================
TOOL_CATEGORIES = {
    "CALENDAR": "calendar_tools",
    "DRIVE": "drive_tools",
    "AI_SUMMARIZATION": "ai_tools",
    "EMAIL": "email_tools",
    "NOTIFICATION": "notification_tools",

}

AVAILABLE_TOOLS = {
    "calendar_tool": {
        "name": "Google Calendar Tool",
        "description": "Interact with Google Calendar API",
        "category": TOOL_CATEGORIES["CALENDAR"],
        "enabled": True
    },
    "drive_tool": {
        "name": "Google Drive Tool",
        "description": "Manage files in Google Drive",
        "category": TOOL_CATEGORIES["DRIVE"],
        "enabled": True
    },
    "summarizer_tool": {
        "name": "AI Summarization Tool",
        "description": "AI-powered meeting summarization",
        "category": TOOL_CATEGORIES["AI_SUMMARIZATION"],
        "enabled": True
    },
    "email_tool": {
        "name": "Email Notification Tool",
        "description": "Send email notifications",
        "category": TOOL_CATEGORIES["EMAIL"],
        "enabled": True
    },
    "sheets_tool": {
        "name": "Google Sheets Tool",
        "description": "Manage Google Sheets for meeting tasks and data tracking",
        "category": TOOL_CATEGORIES["DRIVE"],
        "enabled": True
    }

}

# =============================================================================
# RESPONSE FORMATS
# =============================================================================
STANDARD_RESPONSE_FORMAT = {
    "status": str,
    "message": str,
    "data": dict,
    "timestamp": str,
    "request_id": str
}

ERROR_RESPONSE_FORMAT = {
    "status": str,
    "error_code": str,
    "message": str,
    "details": dict,
    "timestamp": str,
    "request_id": str
}

# =============================================================================
# HEALTH CHECK CONFIGURATION
# =============================================================================
HEALTH_CHECK_ENDPOINTS = {
    "database": "/health/database",
    "google_services": "/health/google",
    "ai_services": "/health/ai",
    "external_apis": "/health/external"
}

# =============================================================================
# RATE LIMITING
# =============================================================================
RATE_LIMIT_CONFIG = {
    "default": "100/minute",
    "ai_endpoints": "10/minute",
    "file_upload": "5/minute",
    "email_send": "20/hour"
}

# =============================================================================
# FEATURE FLAGS
# =============================================================================
FEATURE_FLAGS = {
    "enable_ai_summarization": True,
    "enable_email_notifications": True,
    "enable_slack_notifications": True,
    "enable_drive_integration": True,
    "enable_calendar_integration": True,
    "enable_cron_scheduling": True,
    "enable_rate_limiting": True,
    "enable_request_logging": True
}