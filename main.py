"""
Meeting Intelligence Agent - Main API Entry Point

Simplified main.py that imports from modular handler components.
"""

import logging
import os
import uuid
from datetime import datetime
import pytz  # For timezone-aware UTC scheduling

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

# Import request models
from .models.request_models import (
    WorkflowRequest, StopRequest, DeleteRequest, LatestAgentRequest
)

# Import handlers
from .handlers.workflow_handlers import start_agent_workflow, stop_agent_workflow, delete_agent, get_latest_agent_details
from .handlers.task_handlers import save_tasks_from_agent

# Import utility functions
from .utils.client_utils import get_client_ip

# Import services
from ..services.database_service_new import get_database_service
from ..services.integration.activity_logger import get_activity_logger

from ..utils.rate_limiting import WORKFLOW_RATE_LIMIT, OAUTH_RATE_LIMIT, GENERAL_RATE_LIMIT

# Initialize logger
logger = logging.getLogger(__name__)

# Load environment early so services pick up credentials in production
try:
    from dotenv import load_dotenv  # type: ignore
    # Load .env file from project root directory (Linux compatible)
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from: {env_path}")
    else:
        # Try loading from current directory
        load_dotenv()
        logger.info("Loaded environment variables from current directory")
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")
    # dotenv is optional; proceed if not available
    pass

# Create FastAPI app
app = FastAPI(
    title="Meeting Intelligence Agent API",
    description="AI-powered meeting analysis and task management system",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ==============================================================================
# SCHEDULER SETUP: This section configures and starts the background tasks.
# ==============================================================================

from apscheduler.schedulers.background import BackgroundScheduler
from ..services.scheduler_service import read_google_calendar_events, refresh_all_users_tokens, sync_user_data_from_platform
from ..configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL

# Configure logging
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.INFO)

# Initialize the background scheduler with the UTC timezone and job defaults to prevent overlaps
# Configured for VM deployment with drift compensation and idle cycle handling
scheduler = BackgroundScheduler(
    timezone=pytz.UTC,  # Explicitly set UTC timezone for consistent scheduling (timezone-aware)
    job_defaults={
        'coalesce': True,  # Combine multiple pending executions into one
        'max_instances': 1,  # Only allow one instance of each job to run at a time
        'misfire_grace_time': 600  # 10 minutes grace period for missed executions (handles VM idle cycles)
    }
)

@app.on_event("startup")
def start_scheduler():
    """
    Starts the background scheduler and adds the core recurring jobs.
    This function is designed to be non-blocking and should not hang the startup.
    """
    import threading
    
    def _start_scheduler_in_thread():
        """Start scheduler in a separate thread to avoid blocking"""
        try:
            print("=" * 80)
            print("Initializing background scheduler...")
            logger.info("Initializing background scheduler...")

            # Check if scheduler is already running
            if scheduler.running:
                print("[WARNING] Scheduler is already running!")
                logger.warning("Scheduler is already running!")
                return

            # Schedule the complete Meeting Intelligence Agent workflow using configurable interval.
            # This includes: Calendar Tool → Drive Tool → Summarizer Tool → Email Tool → Dedup Tool
            # Using SCHEDULER_MEETING_WORKFLOW_INTERVAL from config (default: 30 minutes)
            workflow_interval = SCHEDULER_MEETING_WORKFLOW_INTERVAL
            print(f"Agent auto-run interval set to {workflow_interval} minutes")
            print(f"DEBUG: SCHEDULER_MEETING_WORKFLOW_INTERVAL value = {SCHEDULER_MEETING_WORKFLOW_INTERVAL}")
            print(f"DEBUG: workflow_interval value = {workflow_interval}")
            logger.info(f"Agent auto-run interval set to {workflow_interval} minutes")
            logger.info(f"SCHEDULER_MEETING_WORKFLOW_INTERVAL = {SCHEDULER_MEETING_WORKFLOW_INTERVAL}")
            
            # Add the main workflow job that runs every {workflow_interval} minutes continuously
            # This job will:
            # 1. Query DB for all active users (status=1 AND ready_to_use=1)
            # 2. Process each user through unified_meeting_agent workflow
            # 3. Send audit stream to platform every {workflow_interval} minutes (even if no events)
            # Note: No next_run_time specified - APScheduler will calculate it automatically in UTC
            # This matches how the other jobs (token refresh, platform sync) work correctly
            # Configured for VM deployment with drift compensation:
            # - misfire_grace_time allows recovery from VM idle cycles
            # - max_instances prevents overlapping executions
            # - coalesce combines multiple pending executions
            job = scheduler.add_job(
                read_google_calendar_events,
                'interval',
                minutes=workflow_interval,
                id="run_agent_job",
                name="Meeting Intelligence Agent Workflow",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping executions - strictly run once per interval
                coalesce=True,  # Combine multiple pending executions into one
                misfire_grace_time=600  # 10 minutes grace period - allows recovery from VM idle cycles while maintaining interval
            )
            from ..configuration.config import CALENDAR_LOOKBACK_MINUTES
            print(f"[SUCCESS] Scheduled workflow job: {job.id} (every {workflow_interval} minutes)")
            logger.info(f"Scheduled workflow job: {job.id} (every {workflow_interval} minutes)")
            print(f"   This job will:")
            print(f"   - Query DB for all active users (status=1 AND ready_to_use=1)")
            print(f"   - Run unified_meeting_agent workflow for each user")
            print(f"   - Use {CALENDAR_LOOKBACK_MINUTES} minutes lookback window for calendar events")
            print(f"   - Send audit stream to platform every {workflow_interval} minutes (even if no events)")
            print(f"   - Next run time will be calculated when scheduler starts (in UTC)")
            logger.info(f"   Job configured to process all active users with {CALENDAR_LOOKBACK_MINUTES} min lookback and send audit logs every {workflow_interval} minutes")

            # Schedule the token refresh process to run every {token_refresh_interval} minutes for ALL active users.
            # This refreshes each user's access_token using their refresh_token and updates the database.
            # This is the ONLY place where token refresh happens - NOT inside the {workflow_interval}-minute workflow
            # IMPORTANT: This job runs every {token_refresh_interval} minutes (default: 55 minutes) - it will always execute on schedule
            from ..configuration.config import SCHEDULER_TOKEN_REFRESH_INTERVAL
            token_refresh_interval = SCHEDULER_TOKEN_REFRESH_INTERVAL
            token_job = scheduler.add_job(
                refresh_all_users_tokens,
                'interval',
                minutes=token_refresh_interval,
                id="refresh_tokens_job",
                name="Token Refresh Job",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping token refresh executions
                coalesce=True,  # Combine multiple pending executions into one
                misfire_grace_time=300  # 5 minutes grace period - allows recovery from VM idle cycles
            )
            print(f"[SUCCESS] Scheduled token refresh job: {token_job.id} (every {token_refresh_interval} minutes for ALL active users)")
            logger.info(f"Scheduled token refresh job: {token_job.id} (every {token_refresh_interval} minutes for ALL active users)")
            print(f"   Token refresh updates each user's access_token using their refresh_token every {token_refresh_interval} minutes")
            print(f"   Updates both oauth_tokens and user_agent_task tables with new access tokens")
            logger.info(f"   Token refresh updates each user's access_token using their refresh_token every {token_refresh_interval} minutes")
            logger.info(f"   Updates both oauth_tokens and user_agent_task tables with new access tokens")

            # Schedule the platform user data sync to run every X minutes (configurable via environment).
            platform_sync_interval = int(os.getenv("PLATFORM_SYNC_INTERVAL_MINUTES", "25"))  # Default 25 minutes
            sync_job = scheduler.add_job(
                sync_user_data_from_platform,
                'interval',
                minutes=platform_sync_interval,
                id="platform_sync_job",
                name="Platform Data Sync Job",
                replace_existing=True
            )
            print(f" Scheduled platform sync job: {sync_job.id} (every {platform_sync_interval} minutes)")
            logger.info(f"Scheduled platform sync job: {sync_job.id} (every {platform_sync_interval} minutes)")
            
            # Schedule agent table cleanup job - runs every 2 days
            from ..services.scheduler_service import cleanup_old_agent_records
            cleanup_job = scheduler.add_job(
                cleanup_old_agent_records,
                'interval',
                days=2,
                id="agent_cleanup_job",
                name="Agent Table Cleanup",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            print(f"[SUCCESS] Scheduled agent cleanup job: {cleanup_job.id} (every 2 days)")
            logger.info(f"Scheduled agent cleanup job: {cleanup_job.id} (every 2 days)")
            print(f"   This job will delete agent execution records older than 2 days")
            logger.info(f"   Agent cleanup job will delete records older than 2 days")

            # Start the scheduler
            print("Starting scheduler...")
            logger.info("Starting scheduler...")
            scheduler.start()
            
            # Verify scheduler is running
            import time
            max_wait = 5  # Wait up to 5 seconds for scheduler to start
            wait_time = 0
            while not scheduler.running and wait_time < max_wait:
                time.sleep(0.1)
                wait_time += 0.1
            
            if not scheduler.running:
                raise RuntimeError("Scheduler failed to start within timeout!")
            
            print("[SUCCESS] Scheduler started successfully!")
            logger.info("Scheduler started successfully!")
            
            # Print all scheduled jobs
            print("\nScheduled Jobs:")
            print("-" * 80)
            jobs = scheduler.get_jobs()
            if jobs:
                for job in jobs:
                    next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S UTC") if job.next_run_time else "N/A"
                    print(f"  • {job.name} ({job.id})")
                    print(f"    Next run: {next_run}")
                    print(f"    Trigger: {job.trigger}")
                    logger.info(f"Job scheduled: {job.name} ({job.id}), Next run: {next_run}")
            else:
                print("  [WARNING] No jobs scheduled!")
                logger.warning("No jobs scheduled!")
            
            print("-" * 80)
            print("=" * 80)
            
            # Also call scheduler.print_jobs() for APScheduler's built-in output
            scheduler.print_jobs()
            
        except Exception as e:
            error_msg = f"Failed to start scheduler: {str(e)}"
            print(f"[ERROR] {error_msg}")
            logger.error(error_msg, exc_info=True)
            # Don't raise - allow app to start even if scheduler fails
            # This allows the API to still function for manual triggers
    
    # Start scheduler in a daemon thread to avoid blocking
    scheduler_thread = threading.Thread(target=_start_scheduler_in_thread, daemon=True)
    scheduler_thread.start()
    
    # Don't wait for the thread - let it start in background
    print("Scheduler initialization started in background thread...")
    logger.info("Scheduler initialization started in background thread...")

@app.on_event("shutdown")
def shutdown_scheduler():
    """
    Shuts down the scheduler gracefully when the application is closing.
    """
    try:
        print("Shutting down scheduler...")
        logger.info("Shutting down scheduler...")
        
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=True)
            print("[SUCCESS] Scheduler shut down gracefully.")
            logger.info("Scheduler shut down gracefully.")
        else:
            print("[WARNING] Scheduler was not running.")
            logger.warning("Scheduler was not running.")
            
    except Exception as e:
        error_msg = f"Error shutting down scheduler: {str(e)}"
        print(f"[ERROR] {error_msg}")
        logger.error(error_msg, exc_info=True)

# ==============================================================================
# END OF SCHEDULER SETUP
# ==============================================================================


# -----------------------------------------------------------------------------
# Request ID Middleware for Correlated Logging
# -----------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    """Attach a unique request_id to each request for traceability."""
    request_id = str(uuid.uuid4())
    setattr(request.state, "request_id", request_id)

    try:
        response = await call_next(request)
    except HTTPException as http_exc:
        # Re-raise to be handled by HTTPException handler
        raise http_exc
    except Exception as unhandled_exc:
        # Ensure unexpected errors return a structured response with request_id
        logger.error(
            f"Unhandled error for request_id={request_id}: {unhandled_exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "status_code": 500,
                "message": "Internal server error",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )

    # Propagate request_id in successful responses when possible
    try:
        # Only attach header if not already present
        if "x-request-id" not in response.headers:
            response.headers["x-request-id"] = request_id
    except Exception:
        pass

    return response

# Add CORS middleware - Configure based on environment
# In production, restrict to specific origins for security
allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else ["*"]
# Remove empty strings from list
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]

# For development, allow all origins if explicitly set
if os.getenv("APP_ENV", "development") == "development" and not os.getenv("ALLOWED_ORIGINS"):
    allowed_origins = ["*"]
    logger.warning("CORS: Allowing all origins in development mode. Set ALLOWED_ORIGINS in production!")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()
# Include routers (health, webhook) with versioned prefixes - cron routes removed

try:
    from .routes.health_routes import router as health_router
    app.include_router(health_router, prefix="/api/v1", tags=["health"])  # adds /api/v1/health etc.
except Exception as e:
    logger.warning(f"Failed to include health routes: {e}")

# Webhook and cron routes are not implemented yet
# They will be added when needed
logger.info("Webhook and cron routes are not implemented yet")

# =============================================================================
# CORE ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint - API information and available endpoints"""
    return {
        "message": "Meeting Intelligence Agent API",
        "version": "2.0.0",
        "status": "active",
        "endpoints": {
            "health": "/health",
            "start_workflow": "/start",
            "stop_workflow": "/stop",
            "delete_agent": "POST /delete",
            "latest_agent": "/latest",
            "save_tasks": "/task-mgmt/save-from-agent",
            "note": f"Scheduler runs automatically every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes in background"
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check(request: Request = None):
    """Health check endpoint for load balancers and monitoring"""
    try:
        # Basic health checks
        db_service = get_database_service()
        # Touch the connection and/or run health
        db_error = None
        try:
            db_health = db_service.health_check()
            ok = db_health.get("status") in ("ok", "healthy", True)
            db_status = "connected" if ok else "unavailable"
            if not ok:
                db_error = db_health.get("error")
        except Exception as _e:
            db_status = "unavailable"
            db_error = str(_e)

        base = {
            "status": "healthy" if db_status != "unavailable" else "degraded",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "database": db_status,
            "services": {
                "database": "operational" if db_status != "unavailable" else "unavailable",
                "auth": "operational",
                "logging": "operational"
            }
        }
        # Attach request_id if available
        if request:
            request_id = getattr(request.state, "request_id", None)
            if request_id:
                base["request_id"] = request_id
        return base
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )

# WORKFLOW ENDPOINTS

@app.post("/start")
@WORKFLOW_RATE_LIMIT
async def start_workflow_endpoint(
    request: WorkflowRequest,
    http_request: Request
):
    """Start the Meeting Intelligence Agent workflow"""
    return await start_agent_workflow(request, http_request)

@app.post("/stop")
@WORKFLOW_RATE_LIMIT
async def stop_workflow_endpoint(
    request: StopRequest,
    http_request: Request
):
    """Stop the Meeting Intelligence Agent workflow"""
    # Log before database operation
    logger.info(f"ENDPOINT_ACTION: Starting stop workflow for agent_task_id={request.agent_task_id}")
    logger.debug(f"ENDPOINT_DATA: Stop request data: {request.dict()}")
    
    result = await stop_agent_workflow(request, http_request)
    
    # Log after operation
    logger.info(f"ENDPOINT_ACTION: Successfully completed stop workflow for agent_task_id={request.agent_task_id}")
    
    return result

@app.post("/delete")
@WORKFLOW_RATE_LIMIT
async def delete_agent_endpoint(
    request: DeleteRequest,
    http_request: Request
):
    """Delete the Meeting Intelligence Agent and all associated data"""
    # Log before database operation
    logger.info(f"ENDPOINT_ACTION: Starting delete agent for agent_task_id={request.agent_task_id}")
    logger.debug(f"ENDPOINT_DATA: Delete request data: {request.dict()}")
    
    result = await delete_agent(request, http_request)
    
    # Log after operation
    logger.info(f"ENDPOINT_ACTION: Successfully completed delete agent for agent_task_id={request.agent_task_id}")
    
    return result

@app.post("/latest")
@GENERAL_RATE_LIMIT
async def get_latest_agent_endpoint(
    request: WorkflowRequest,
    http_request: Request
):
    """Get the latest agent details for a user"""
    # Log before database operation
    logger.info(f"ENDPOINT_ACTION: Starting get latest agent for agent_task_id={request.agent_task_id}")
    logger.debug(f"ENDPOINT_DATA: Latest request data: {request.dict()}")
    
    result = await get_latest_agent_details(request, http_request)
    
    # Log after operation
    logger.info(f"ENDPOINT_ACTION: Successfully completed get latest agent for agent_task_id={request.agent_task_id}")
    
    return result

# TASK MANAGEMENT ENDPOINTS


@app.post("/task-mgmt/save-from-agent")
@GENERAL_RATE_LIMIT
async def save_tasks_endpoint(
    request: Request
):
    """Save tasks extracted by the agent"""
    # Log before database operation
    logger.info(f"ENDPOINT_ACTION: Starting save tasks from agent")
    logger.debug(f"ENDPOINT_DATA: Save tasks request received")
    
    result = await save_tasks_from_agent(request)
    
    # Log after operation
    logger.info(f"ENDPOINT_ACTION: Successfully completed save tasks from agent")
    
    return result


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with correlated request_id and structured body."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        f"HTTPException request_id={request_id} status={exc.status_code} detail={exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions with correlated request_id and stack trace logging."""
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        f"Unhandled Exception request_id={request_id}: {str(exc)}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "message": "Internal server error",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
        },
    )

# =============================================================================
# STARTUP AND SHUTDOWN
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup with timeout handling"""
    print("[STARTUP] Meeting Intelligence Agent API starting up...")
    logger.info("Meeting Intelligence Agent API starting up...")
    try:
        # Initialize database connection with timeout
        import asyncio
        import concurrent.futures
        
        def _init_database_sync():
            """Initialize database synchronously"""
            try:
                db_service = get_database_service()
                # Try a lightweight health check to verify connection
                try:
                    health = db_service.health_check()
                    if health.get("status") not in ("ok", "healthy", True):
                        logger.warning(f"Database health check returned: {health}")
                except Exception as health_err:
                    logger.warning(f"Database health check failed (non-critical): {health_err}")
                
                return db_service
            except Exception as e:
                logger.error(f"Database initialization error: {e}")
                raise
        
        # Run database initialization with timeout in a thread pool
        try:
            loop = asyncio.get_event_loop()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            db_service = await asyncio.wait_for(
                loop.run_in_executor(executor, _init_database_sync),
                timeout=15.0
            )
            print("[SUCCESS] Database service initialized")
            logger.info("Database service initialized")
        except asyncio.TimeoutError:
            error_msg = "Database initialization timed out after 15 seconds"
            print(f"[WARNING] {error_msg}")
            logger.warning(error_msg)
            # Don't raise - allow app to start even if database is slow
            # The database connection will be retried on first use
        except Exception as e:
            error_msg = f"Database initialization failed: {e}"
            print(f"[WARNING] {error_msg}")
            logger.warning(error_msg)
            # Don't raise - allow app to start even if database fails
            # The database connection will be retried on first use

        # Initialize other services
        print("[SUCCESS] All services initialized successfully")
        logger.info("All services initialized successfully")
    except Exception as e:
        print(f"[ERROR] Startup failed: {e}")
        logger.error(f"Startup failed: {e}", exc_info=True)
        # Don't raise - allow app to start even if some services fail
        # This allows the API to still function for manual triggers

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Meeting Intelligence Agent API shutting down...")
    # Background scheduler shutdown is handled by the shutdown_scheduler function above

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000)