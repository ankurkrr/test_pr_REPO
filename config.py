# Unified configuration for Meeting Intelligence Agent
import os
import logging
import secrets
from urllib.parse import quote_plus
from pathlib import Path

# Load environment variables early and robustly from a .env file.
# This attempts to load from the project root (three levels up from this file),
# falling back to current working directory. It is safe on Windows and Linux.
try:
    from dotenv import load_dotenv  # type: ignore

    # Determine project root relative to this file: src/configuration/config.py -> project root
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]  # .../Copy/src -> .../Copy
    env_path = project_root / ".env"

    # Load from explicit path if present; otherwise default search
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    else:
        # Fallback to default discovery in CWD and parents
        load_dotenv(override=False)
except Exception:
    # dotenv is optional; continue if unavailable
    pass

# Initialize logger for configuration warnings
logger = logging.getLogger(__name__)



# =============================================================================
# APPLICATION CONFIGURATION
# =============================================================================
APP_NAME = os.getenv("APP_NAME", "Meeting Intelligence Agent")
APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
APP_ENV = os.getenv("APP_ENV", "development")
APP_ENVIRONMENT = os.getenv("APP_ENVIRONMENT", "development")
PORT = int(os.getenv("PORT", 8000))

# Debug & Logging
DEBUG = os.getenv("DEBUG", "False") == "True"
# In production, force INFO level minimum (no DEBUG logging)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
if os.getenv("APP_ENVIRONMENT", "development") == "production" and LOG_LEVEL == "DEBUG":
    logger.warning("DEBUG logging enabled in production - forcing INFO level")
    LOG_LEVEL = "INFO"
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
LOG_DATE_FORMAT = os.getenv("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/app.log")
# Ensure LOG_FILE_PATH is always relative to avoid /app permission issues
if LOG_FILE_PATH.startswith('/'):
    LOG_FILE_PATH = "logs/app.log"

# Docker Configuration
DOCKER_TARGET = os.getenv("DOCKER_TARGET", "development")

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
# MySQL Configuration (Primary) - Google Cloud SQL
# NO DEFAULTS for production - all database credentials must be set via environment variables
DB_HOST = os.getenv("MYSQL_HOST")
DB_PORT = os.getenv("MYSQL_PORT", "3306")  # Port can have default
DB_USER = os.getenv("MYSQL_USERNAME")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_NAME = os.getenv("MYSQL_DATABASE")
DB_ROOT_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
MYSQL_EXTERNAL_PORT = int(os.getenv("MYSQL_EXTERNAL_PORT", 3306))

# Safe password encoding for special characters
safe_password = quote_plus(DB_PASSWORD or "")

# Database URL for SQLAlchemy - Support both MySQL and SQLite for local testing
if DB_HOST and DB_USER and DB_PASSWORD and DB_NAME:
    DB_URL = f"mysql+pymysql://{DB_USER}:{safe_password}@{DB_HOST}:{DB_PORT or 3306}/{DB_NAME}"
elif os.path.exists("local_test.db"):
    # Use SQLite for local testing if the file exists
    DB_URL = "sqlite:///./local_test.db"
else:
    # Fallback to SQLite for local development
    DB_URL = "sqlite:///./local_test.db"

# =============================================================================
# GOOGLE CLOUD CONFIGURATION
# =============================================================================
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Google OAuth2 Credentials (Unified for Gmail, Calendar, Drive)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# Google OAuth2 Client Configuration (alternative names for compatibility)
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", GOOGLE_CLIENT_ID)
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_CLIENT_SECRET)
GOOGLE_OAUTH_SCOPES = os.getenv("GOOGLE_OAUTH_SCOPES", "openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/documents.readonly,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/meetings.space.readonly,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.profile")

# Google OAuth2 Credentials (file paths)
GOOGLE_OAUTH_CREDENTIALS_PATH = os.getenv("GOOGLE_OAUTH_CREDENTIALS_PATH", "./keys/google-oauth-credentials.json")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "./keys/google-token.json")

# Optional Google Sheets ID used by meeting tasks sheet (auto-created if missing)
GOOGLE_SHEETS_MEETING_TASKS_ID = os.getenv("GOOGLE_SHEETS_MEETING_TASKS_ID")

# =============================================================================
# EMAIL CONFIGURATION
# =============================================================================
# SendGrid (preferred)
# NO DEFAULT for API key - must be set via environment variable
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "agent@elevationai.com")
SENDGRID_FROM_NAME = os.getenv("SENDGRID_FROM_NAME", "Meeting Agent")


# =============================================================================
# SECURITY CONFIGURATION
# =============================================================================
# JWT Configuration
# NO DEFAULT for JWT secret - must be set via environment variable
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    if os.getenv("APP_ENVIRONMENT", "development") == "production":
        raise ValueError("JWT_SECRET_KEY is required in production environment")
    else:
        # Generate a random secret for development (NOT for production!)
        JWT_SECRET_KEY = secrets.token_urlsafe(32)
        logger.warning("Generated temporary JWT_SECRET_KEY for development. Set JWT_SECRET_KEY in production!")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", 24))

# Encryption Keys
# NO DEFAULTS for encryption keys - must be set via environment variables
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ENCRYPTION_IV = os.getenv("ENCRYPTION_IV")
# Legacy IV name used in some paths (kept for compatibility)
ENCRYPT_IV = os.getenv("ENCRYPT_IV", ENCRYPTION_IV)  # Fallback to ENCRYPTION_IV if not set

# API Security
# NO DEFAULTS for API keys - must be set via environment variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
REQUIRE_API_KEY = os.getenv("REQUIRE_API_KEY", "true") == "true"
API_KEY_1 = os.getenv("API_KEY_1")
API_KEY_2 = os.getenv("API_KEY_2")

# Rate Limiting
SIGNATURE_TOLERANCE_SECONDS = int(os.getenv("SIGNATURE_TOLERANCE_SECONDS", 300))
ENABLE_IP_WHITELIST = os.getenv("ENABLE_IP_WHITELIST", "false") == "false"
ADMIN_IP_WHITELIST = os.getenv("ADMIN_IP_WHITELIST", "127.0.0.1,::1")

# Web security / CORS
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false") == "true"
TRUSTED_DOMAINS = os.getenv("TRUSTED_DOMAINS", "localhost,127.0.0.1,https://devapi.agentic.elevationai.com,https://elevationai.com/")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://devapi.agentic.elevationai.com/,https://devagents.elevationai.com/,http://localhost:3000,http://127.0.0.1:3000,http://127.0.0.1:8000")

# =============================================================================
# REDIS CONFIGURATION
# =============================================================================
# Smart Redis URL detection: defaults to localhost for local, redis hostname for Docker/VM
# Set REDIS_URL explicitly in .env for production deployments
# Local development: redis://localhost:6379/0
# Docker/VM deployment: redis://redis:6379/0 or redis://localhost:6379/0 (if Redis is on same host)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")  # Use 'redis' for Docker, 'localhost' for local
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_URL = os.getenv("REDIS_URL") or f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
REDIS_EXTERNAL_PORT = int(os.getenv("REDIS_EXTERNAL_PORT", REDIS_PORT))

# =============================================================================
# FEATURE FLAGS
# =============================================================================
ENABLE_AI_SUMMARIZATION = os.getenv("ENABLE_AI_SUMMARIZATION", "true") == "true"
ENABLE_EMAIL_NOTIFICATIONS = os.getenv("ENABLE_EMAIL_NOTIFICATIONS", "true") == "true"
ENABLE_SLACK_NOTIFICATIONS = os.getenv("ENABLE_SLACK_NOTIFICATIONS", "false") == "true"
ENABLE_DRIVE_INTEGRATION = os.getenv("ENABLE_DRIVE_INTEGRATION", "true") == "true"
ENABLE_CALENDAR_INTEGRATION = os.getenv("ENABLE_CALENDAR_INTEGRATION", "true") == "true"
ENABLE_CRON_SCHEDULING = os.getenv("ENABLE_CRON_SCHEDULING", "true") == "true"
ENABLE_RATE_LIMITING = os.getenv("ENABLE_RATE_LIMITING", "true") == "true"
ENABLE_REQUEST_LOGGING = os.getenv("ENABLE_REQUEST_LOGGING", "true") == "true"

# =============================================================================
# EXTERNAL SERVICE URLS
# =============================================================================
# Used to fetch agent details securely; must be HTTPS in production
AGENT_DETAILS_API_URL = os.getenv("AGENT_DETAILS_API_URL", "https://devapi.agentic.elevationai.com")

# Platform API credentials for external service calls
# NO DEFAULTS for platform API keys - must be set via environment variables
PLATFORM_API_KEY = os.getenv("PLATFORM_API_KEY")
PLATFORM_API_SECRET = os.getenv("PLATFORM_API_SECRET")

# =============================================================================
# SCHEDULING CONFIGURATION
# =============================================================================
# Time window for meeting processing (minutes to look back)
TIME_WINDOW_MINUTES = int(os.getenv("TIME_WINDOW_MINUTES", 35))

# Calendar lookback window (should be larger than TIME_WINDOW_MINUTES to catch meetings)
# Set to 35 minutes for current requirements
CALENDAR_LOOKBACK_MINUTES = int(os.getenv("CALENDAR_LOOKBACK_MINUTES", 35))

# Scheduler intervals (in minutes)
SCHEDULER_MEETING_WORKFLOW_INTERVAL = int(os.getenv("SCHEDULER_MEETING_WORKFLOW_INTERVAL", 30))  # Agent run every 10 minutes
SCHEDULER_TOKEN_REFRESH_INTERVAL = int(os.getenv("SCHEDULER_TOKEN_REFRESH_INTERVAL", 55))  # Refresh tokens every 55 minutes
SCHEDULER_PAYLOAD_PULL_INTERVAL = int(os.getenv("SCHEDULER_PAYLOAD_PULL_INTERVAL", 25))  # Platform sync every 25 minutes
SCHEDULER_HEALTH_CHECK_INTERVAL = int(os.getenv("SCHEDULER_HEALTH_CHECK_INTERVAL", 60))
SCHEDULER_LOG_CLEANUP_INTERVAL = int(os.getenv("SCHEDULER_LOG_CLEANUP_INTERVAL", 1440))  # 24 hours

# Retry configuration
MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", 3))
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", 30))
BACKOFF_MULTIPLIER = float(os.getenv("BACKOFF_MULTIPLIER", 2.0))

# Concurrency limits
MAX_CONCURRENT_WORKFLOWS = int(os.getenv("MAX_CONCURRENT_WORKFLOWS", 50))
MAX_CONCURRENT_TOKEN_REFRESHES = int(os.getenv("MAX_CONCURRENT_TOKEN_REFRESHES", 30))  

# Intelligent scheduling
ENABLE_INTELLIGENT_SCHEDULING = os.getenv("ENABLE_INTELLIGENT_SCHEDULING", "true") == "true"
MEETING_PATTERN_ANALYSIS_DAYS = int(os.getenv("MEETING_PATTERN_ANALYSIS_DAYS", 7))
QUIET_HOURS_START = os.getenv("QUIET_HOURS_START", "22:00")  # 10 PM
QUIET_HOURS_END = os.getenv("QUIET_HOURS_END", "06:00")     # 6 AM
QUIET_HOURS_TIMEZONE = os.getenv("QUIET_HOURS_TIMEZONE", "UTC")

# Performance monitoring
ENABLE_SCHEDULER_METRICS = os.getenv("ENABLE_SCHEDULER_METRICS", "true") == "true"
METRICS_RETENTION_DAYS = int(os.getenv("METRICS_RETENTION_DAYS", 30))

# =============================================================================
# ORGANIZATIONAL CONFIGURATION
# =============================================================================
ORG_ID = os.getenv("ORG_ID", "default_org")
AGENT_ID = os.getenv("AGENT_ID", "meeting_agent_001")
AGENT_NAME = os.getenv("AGENT_NAME", "Unified Meeting Agent")

# =============================================================================
# MISC OPTIONALS
# =============================================================================
DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "system")
EMAIL_TEMPLATE_PATH = os.getenv("EMAIL_TEMPLATE_PATH", "./client/meeting_agent_email.html")
UPLOAD_SUMMARIES_TO_DRIVE = os.getenv("UPLOAD_SUMMARIES_TO_DRIVE", "false") == "true"
PLATFORM_JWT_ALG = os.getenv("PLATFORM_JWT_ALG", "HS256")


# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================

def validate_production_config():
    """
    Validate that all required configuration is present in production environment.
    Raises ValueError if any required configuration is missing.
    
    This function should be called on application startup in production.
    """
    app_environment = os.getenv("APP_ENVIRONMENT", "development")
    
    if app_environment != "production":
        # Skip validation in non-production environments
        return
    
    missing_vars = []
    
    # Required database configuration
    if not DB_HOST:
        missing_vars.append("MYSQL_HOST")
    if not DB_USER:
        missing_vars.append("MYSQL_USERNAME")
    if not DB_PASSWORD:
        missing_vars.append("MYSQL_PASSWORD")
    if not DB_NAME:
        missing_vars.append("MYSQL_DATABASE")
    
    # Required security configuration
    if not JWT_SECRET_KEY:
        missing_vars.append("JWT_SECRET_KEY")
    if not ENCRYPTION_KEY:
        missing_vars.append("ENCRYPTION_KEY")
    if not ENCRYPTION_IV:
        missing_vars.append("ENCRYPTION_IV")
    
    # Validate encryption key length
    if ENCRYPTION_KEY and len(ENCRYPTION_KEY) < 32:
        raise ValueError("ENCRYPTION_KEY must be at least 32 characters long")
    if ENCRYPTION_IV and len(ENCRYPTION_IV) < 16:
        raise ValueError("ENCRYPTION_IV must be at least 16 characters long")
    
    # Required API keys if API key requirement is enabled
    if REQUIRE_API_KEY:
        if not API_KEY:
            missing_vars.append("API_KEY")
        if not API_SECRET:
            missing_vars.append("API_SECRET")
    
    # Required SendGrid API key if email notifications are enabled
    if os.getenv("ENABLE_EMAIL_NOTIFICATIONS", "true") == "true":
        if not SENDGRID_API_KEY:
            missing_vars.append("SENDGRID_API_KEY")
    
    # Raise error if any required variables are missing
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables in production: {', '.join(missing_vars)}. "
            f"Please set these variables in your .env file or environment."
        )
    
    logger.info("Production configuration validation passed")


# Auto-validate configuration on import in production
if os.getenv("APP_ENVIRONMENT", "development") == "production":
    try:
        validate_production_config()
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        # Re-raise to prevent application from starting with invalid configuration
        raise