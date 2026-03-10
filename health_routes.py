"""
Health and monitoring routes for the Meeting Intelligence Agent API.
"""

import os
import psutil
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status

from ..utils import get_client_ip
from ...security.data_encryption import get_audit_logger
from ...services.database_service_new import get_database_service

logger = logging.getLogger(__name__)

# Import agent functions with fallback
try:
    from ...agents.meeting_agent import get_meeting_agent
    AGENT_AVAILABLE = True
except (ImportError, AttributeError):
    AGENT_AVAILABLE = False
    def get_meeting_agent():
        return None

router = APIRouter()
audit_logger = get_audit_logger()


async def _check_external_services() -> Dict[str, Any]:
    """
    Check health of external services including Google APIs and Platform API.
    
    Returns:
        Dict with service health status
    """
    services = {
        "google_calendar": "unknown",
        "google_drive": "unknown", 
        "google_sheets": "unknown",
        "platform_api": "unknown",
        "redis": "unknown"
    }
    
    # Check Google APIs
    try:
        from ...auth.google_auth_handler import GoogleAuthHandler
        auth_handler = GoogleAuthHandler("health_check", "health_check", "health_check")
        
        # Test Google Calendar API
        try:
            calendar_service = auth_handler.get_calendar_service()
            if calendar_service:
                services["google_calendar"] = "healthy"
            else:
                services["google_calendar"] = "unhealthy"
        except Exception as e:
            services["google_calendar"] = f"error: {str(e)[:50]}"
            
        # Test Google Drive API
        try:
            drive_service = auth_handler.get_drive_service()
            if drive_service:
                services["google_drive"] = "healthy"
            else:
                services["google_drive"] = "unhealthy"
        except Exception as e:
            services["google_drive"] = f"error: {str(e)[:50]}"
            
        # Test Google Sheets API
        try:
            sheets_service = auth_handler.get_sheets_service()
            if sheets_service:
                services["google_sheets"] = "healthy"
            else:
                services["google_sheets"] = "unhealthy"
        except Exception as e:
            services["google_sheets"] = f"error: {str(e)[:50]}"
            
    except Exception as e:
        logger.warning(f"Google API health check failed: {e}")
        services["google_calendar"] = "unavailable"
        services["google_drive"] = "unavailable"
        services["google_sheets"] = "unavailable"
    
    # Check Platform API
    try:
        import httpx
        platform_url = os.getenv("ELEVATION_AI_PLATFORM_URL", "https://devapi.agentic.elevationai.com")
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{platform_url}/health", timeout=5.0)
            if response.status_code == 200:
                services["platform_api"] = "healthy"
            else:
                services["platform_api"] = f"unhealthy: {response.status_code}"
    except Exception as e:
        services["platform_api"] = f"error: {str(e)[:50]}"
    
    # Check Redis
    try:
        import redis
        from ...configuration.config import REDIS_URL
        redis_url = REDIS_URL
        r = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        services["redis"] = "healthy"
    except Exception as e:
        services["redis"] = f"error: {str(e)[:50]}"
    
    return services


@router.get("/health")
async def health_check(
    http_request: Request,
    detailed: bool = False,
    auth_data: Optional[Dict[str, Any]] = Depends(lambda: None),  # Optional auth
):
    """
    Comprehensive health check for API and underlying services.

    This endpoint is designed to be used by load balancers and monitoring tools.

    Args:
        detailed: Return detailed service information (requires authentication)
        auth_data: Optional authentication for detailed info
    """
    client_ip = get_client_ip(http_request)
    start_time = time.time()

    # Test database connectivity with detailed metrics
    db_status = "operational"
    db_error = None
    db_latency_ms = None
    try:
        # Log before database operation
        logger.info(f"ENDPOINT_ACTION: Starting database health check, endpoint=health-check")
        
        db_service = get_database_service()
        db_health = db_service.health_check()
        
        # Log after database operation
        logger.info(f"ENDPOINT_ACTION: Successfully completed database health check, status={db_health.get('status')}")
        
        if db_health.get("status") not in ("ok", "healthy", True):
            db_status = "degraded"
            db_error = db_health.get("error", "Unknown database error")
        else:
            db_latency_ms = db_health.get("latency_ms", 0)
    except Exception as e:
        db_status = "error"
        logger.error(f"ENDPOINT_ACTION: Database health check failed: {e}")
        db_error = str(e)

    # Basic health status (always available)
    health_status = {
        "status": "healthy" if db_status == "operational" else "degraded",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "uptime": time.time() - start_time,
        "database": "connected" if db_status == "operational" else "disconnected",
        "services": {
            "api": "healthy",
            "database": db_status,
            "security": "enabled",
        },
        "system": {
            "platform": os.name,
            "python_version": os.sys.version.split()[0],
        }
    }

    if db_error:
        health_status["database_error"] = db_error
    if db_latency_ms is not None:
        health_status["database_latency_ms"] = db_latency_ms

    # Detailed information requires authentication
    if detailed:
        if not auth_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required for detailed health information",
            )

        # Log access to detailed health info
        audit_logger.log_sensitive_operation(
            operation="HEALTH_CHECK_DETAILED",
            user_id=auth_data.get("user_id", "unknown"),
            resource_type="SYSTEM_INFO",
            ip_address=client_ip,
            success=True,
            risk_level="LOW",
        )

        try:
            # System metrics
            health_status["system_metrics"] = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "percent": psutil.virtual_memory().percent,
                },
                "disk": {
                    "total": psutil.disk_usage('/').total,
                    "free": psutil.disk_usage('/').free,
                    "percent": psutil.disk_usage('/').percent,
                },
                "process_count": len(psutil.pids()),
            }

            # Agent status
            if AGENT_AVAILABLE:
                agent = get_meeting_agent()
                if agent:
                    health_status["services"]["langchain_agent"] = "healthy"
                    health_status["agent_info"] = {
                        "agent_type": "unified_meeting_agent",
                        "tools_available": (
                            len(agent.tools) if getattr(agent, "tools", None) else 0
                        ),
                    }
                else:
                    health_status["status"] = "degraded"
                    health_status["services"]["langchain_agent"] = "agent not initialized"
            else:
                health_status["status"] = "degraded"
                health_status["services"]["langchain_agent"] = "dependency issues - run fix_dependencies.py"

            # Security status
            health_status["security"] = {
                "encryption": "enabled",
                "authentication": "jwt_api_key",
                "rate_limiting": "enabled",
                "cors": "configured",
                "middleware": "active",
            }

            # Environment info
            health_status["environment"] = {
                "app_environment": os.getenv("APP_ENVIRONMENT", "development"),
                "debug_mode": os.getenv("DEBUG", "false").lower() == "true",
                "log_level": os.getenv("LOG_LEVEL", "INFO"),
            }
            
            # External service health checks
            health_status["external_services"] = await _check_external_services()

        except (AttributeError, ImportError) as e:
            health_status["status"] = "degraded"
            health_status["services"]["langchain_agent"] = f"error: {str(e)}"
        except Exception as e:
            health_status["status"] = "degraded"
            health_status["error"] = f"Health check error: {str(e)}"

    return health_status


@router.get("/health/detailed")
async def detailed_health_check(
    http_request: Request,
    auth_data: Optional[Dict[str, Any]] = Depends(lambda: None),
):
    """
    Comprehensive detailed health check for all services and dependencies.
    
    Requires authentication and provides extensive system diagnostics.
    """
    if not auth_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for detailed health information",
        )
    
    client_ip = get_client_ip(http_request)
    start_time = time.time()
    
    # Log access to detailed health info
    audit_logger.log_sensitive_operation(
        operation="DETAILED_HEALTH_CHECK",
        user_id=auth_data.get("user_id", "unknown"),
        resource_type="SYSTEM_INFO",
        ip_address=client_ip,
        success=True,
        risk_level="LOW",
    )
    
    try:
        # Comprehensive health status
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "check_duration_ms": round((time.time() - start_time) * 1000, 2),
            "services": {},
            "external_services": {},
            "system_metrics": {},
            "database_metrics": {},
            "agent_metrics": {},
            "security_status": {}
        }
        
        # Database metrics
        try:
            db_service = get_database_service()
            db_health = db_service.health_check()
            health_status["database_metrics"] = {
                "status": db_health.get("status", "unknown"),
                "latency_ms": db_health.get("latency_ms", 0),
                "connection_pool_size": getattr(db_service.engine.pool, 'size', 'unknown'),
                "active_connections": getattr(db_service.engine.pool, 'checkedout', 'unknown')
            }
        except Exception as e:
            health_status["database_metrics"] = {"error": str(e)}
        
        # System metrics
        try:
            health_status["system_metrics"] = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "percent": psutil.virtual_memory().percent,
                },
                "disk": {
                    "total": psutil.disk_usage('/').total,
                    "free": psutil.disk_usage('/').free,
                    "percent": psutil.disk_usage('/').percent,
                },
                "process_count": len(psutil.pids()),
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None
            }
        except Exception as e:
            health_status["system_metrics"] = {"error": str(e)}
        
        # Agent metrics
        if AGENT_AVAILABLE:
            try:
                agent = get_meeting_agent()
                if agent:
                    health_status["agent_metrics"] = {
                        "status": "healthy",
                        "tools_available": len(agent.tools) if getattr(agent, "tools", None) else 0,
                        "agent_type": "unified_meeting_agent",
                        "llm_configured": agent.agent_executor is not None
                    }
                else:
                    health_status["agent_metrics"] = {"status": "not_initialized"}
            except Exception as e:
                health_status["agent_metrics"] = {"error": str(e)}
        else:
            health_status["agent_metrics"] = {"status": "dependency_issues"}
        
        # External services
        health_status["external_services"] = await _check_external_services()
        
        # Security status
        health_status["security_status"] = {
            "encryption": "enabled",
            "authentication": "jwt_api_key",
            "rate_limiting": "enabled",
            "cors": "configured",
            "middleware": "active",
            "audit_logging": "enabled"
        }
        
        # Determine overall health
        all_healthy = all(
            service_status in ["healthy", "operational"] 
            for service_status in [
                health_status["database_metrics"].get("status"),
                health_status["agent_metrics"].get("status")
            ]
        )
        
        health_status["status"] = "healthy" if all_healthy else "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {str(e)}"
        )


@router.get("/ping")
async def ping():
    """
    Simple ping endpoint for load balancers and basic health checks.
    Returns a simple OK response without any processing.
    """
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/health-simple")
async def simple_health():
    """
    Simple health check endpoint for load balancers and monitoring.
    Returns basic API health status without authentication.
    """
    return {
        "status": "healthy",
        "api": "running",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "message": "API is operational",
        "endpoint": "/api/v1/health-simple"
    }


@router.get("/scheduler/status")
async def scheduler_status():
    """
    Check the status of the background scheduler and its jobs.
    Returns information about scheduled jobs and their next run times.
    """
    try:
        # Import scheduler using importlib to avoid circular imports
        import importlib
        main_module = importlib.import_module('src.api.main')
        scheduler = getattr(main_module, 'scheduler', None)
        
        scheduler_info = {
            "running": scheduler.running if scheduler else False,
            "jobs": [],
            "job_count": 0,
            "timestamp": datetime.now().isoformat()
        }
        
        if scheduler and scheduler.running:
            jobs = scheduler.get_jobs()
            scheduler_info["job_count"] = len(jobs)
            
            for job in jobs:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S UTC") if job.next_run_time else "N/A"
                scheduler_info["jobs"].append({
                    "id": job.id,
                    "name": getattr(job, 'name', job.id),
                    "next_run": next_run,
                    "trigger": str(job.trigger),
                    "func": job.func.__name__ if job.func else "unknown"
                })
        else:
            scheduler_info["error"] = "Scheduler is not running"
        
        return scheduler_info
        
    except Exception as e:
        logger.error(f"Error checking scheduler status: {e}", exc_info=True)
        return {
            "running": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@router.post("/scheduler/trigger")
async def trigger_scheduler_job(job_id: str = "run_agent_job"):
    """
    Manually trigger a scheduled job by ID.
    Useful for testing and immediate execution.
    
    Args:
        job_id: The ID of the job to trigger (default: "run_agent_job")
    """
    try:
        # Import scheduler using importlib to avoid circular imports
        import importlib
        main_module = importlib.import_module('src.api.main')
        scheduler = getattr(main_module, 'scheduler', None)
        
        if not scheduler or not scheduler.running:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduler is not running"
            )
        
        # Find the job
        job = scheduler.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{job_id}' not found"
            )
        
        # Trigger the job by running it immediately
        scheduler.add_job(
            job.func,
            'date',
            run_date=datetime.now(),
            id=f"{job_id}_manual_{int(time.time())}",
            replace_existing=True
        )
        
        return {
            "status": "success",
            "message": f"Job '{job_id}' triggered successfully",
            "job_id": job_id,
            "triggered_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering scheduler job: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger job: {str(e)}"
        )