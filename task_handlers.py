"""
Task Handlers - Updated to use Unified Task Service
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict

import httpx
from fastapi import Depends, HTTPException, Request, status

# Removed ElevationAIRequest import - tool was deleted
from ..utils.client_utils import get_client_ip
from ...security.api_security import full_authentication_dependency, rate_limit_dependency
from ...security.data_encryption import get_audit_logger
from ...services.database_service_new import get_database_service
from ...services.integration.activity_logger import get_activity_logger

logger = logging.getLogger(__name__)

async def save_tasks_from_agent(
    request: Request
):
    """
    Unified API endpoint for saving tasks from agent using the unified task service.

    This endpoint receives task data from the agent and processes it through the
    unified task service which handles both Google Sheets and Platform webhook.
    """
    # Get request ID from middleware if available, otherwise generate one
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    client_ip = get_client_ip(request)
    audit_logger = get_audit_logger()

    logger.info(f"Processing task save request_id={request_id} from {client_ip}")

    try:
        # Extract tasks data from request body
        try:
            tasks_data = await request.json()
        except Exception as json_error:
            logger.warning(f"JSON parsing failed request_id={request_id}: {json_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON in request body",
                headers={"x-request-id": request_id}
            )

        # Validate input data
        if not tasks_data or not isinstance(tasks_data, dict):
            logger.warning(f"Invalid task data format request_id={request_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid task data format",
                headers={"x-request-id": request_id}
            )

        # Extract user context
        user_id = tasks_data.get("user_id", "unknown")
        org_id = tasks_data.get("org_id", "default_org")
        agent_task_id = tasks_data.get("agent_task_id", "default_task")

        # Log before database operation
        logger.info(f"ENDPOINT_ACTION: Starting task save operation for user_id={user_id}, agent_task_id={agent_task_id}")
        logger.debug(f"ENDPOINT_DATA: Task data keys: {list(tasks_data.keys()) if isinstance(tasks_data, dict) else 'invalid'}")

        # Import unified task service
        from ...services.integration.unified_task_service import get_unified_task_service

        # Create unified task service
        task_service = get_unified_task_service(
            user_id=user_id,
            org_id=org_id,
            agent_task_id=agent_task_id
        )

        # Log after service creation
        logger.info(f"ENDPOINT_ACTION: Successfully created unified task service for user_id={user_id}")

        # Prepare meeting data
        meeting_data = {
            "id": tasks_data.get("meeting_id", f"M-{datetime.now().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}"),
            "title": tasks_data.get("meeting_title", "Unknown Meeting"),
            "attendees": tasks_data.get("attendees", []),
            "executive_summary": tasks_data.get("executive_summary", ""),
            "video_url": tasks_data.get("video_url", ""),
            "transcript_url": tasks_data.get("transcript_url", ""),
            "start_time": tasks_data.get("start_time"),
            "end_time": tasks_data.get("end_time")
        }

        # Prepare raw tasks
        raw_tasks = tasks_data.get("tasks", [])

        if not raw_tasks:
            return {
                "success": True,
                "message": "No tasks to process",
                "tasks_processed": 0,
                "request_id": request_id
            }

        # Initialize ActivityLogger for platform logging
        activity_logger = get_activity_logger()
        
        # Log task processing start to platform
        try:
            await activity_logger.log_workflow_step(
                agent_task_id=agent_task_id,
                step_name="task_processing_start",
                tool_name="Task Management",
                status="success",
                description=f"Starting task processing for {len(raw_tasks)} tasks",
                outcome="Task processing initiated",
                action_type="Execute",
                additional_data={
                    "user_id": user_id,
                    "org_id": org_id,
                    "task_count": len(raw_tasks),
                    "meeting_title": meeting_data.get("title", "Unknown")
                }
            )
        except Exception as e:
            logger.warning(f"Failed to log task processing start to platform: {e}")

        # Process and distribute tasks using unified service
        try:
            logger.info(f"ENDPOINT_ACTION: Starting task processing for {len(raw_tasks)} tasks, user_id={user_id}")
            result = await task_service.process_and_distribute_tasks(meeting_data, raw_tasks)
            logger.info(f"ENDPOINT_ACTION: Successfully completed task processing, user_id={user_id}")
            
            # Log task processing completion to platform
            try:
                await activity_logger.log_workflow_step(
                    agent_task_id=agent_task_id,
                    step_name="task_processing_complete",
                    tool_name="Task Management",
                    status="success",
                    description="Task processing completed successfully",
                    outcome="Tasks processed and distributed",
                    action_type="Execute",
                    additional_data={
                        "user_id": user_id,
                        "org_id": org_id,
                        "deduplicated_count": result.get("deduplicated_count", 0),
                        "original_count": result.get("original_count", 0),
                        "sheets_success": result.get("results", {}).get("google_sheets", {}).get("success", False),
                        "platform_success": result.get("results", {}).get("platform_webhook", {}).get("success", False)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to log task processing completion to platform: {e}")
                
        except Exception as service_error:
            logger.error(f"Task service failed request_id={request_id}: {service_error}")
            
            # Log task processing error to platform
            try:
                await activity_logger.log_workflow_error(
                    agent_task_id=agent_task_id,
                    error_type="TASK_SERVICE_ERROR",
                    error_message=str(service_error),
                    step_name="task_processing",
                    tool_name="Task Management",
                    user_id=user_id
                )
            except Exception as e:
                logger.warning(f"Failed to log task processing error to platform: {e}")
            
            audit_logger.log_sensitive_operation(
                operation="TASK_SERVICE_ERROR",
                user_id=user_id,
                resource_type="TASK_MANAGEMENT",
                resource_id=request_id,
                details={"error": str(service_error)},
                ip_address=client_ip,
                success=False,
                risk_level="HIGH",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Task processing service failed",
                headers={"x-request-id": request_id}
            )

        # Log the operation
        audit_logger.log_sensitive_operation(
            operation="TASK_SAVE_UNIFIED_SERVICE",
            user_id=user_id,
            resource_type="TASK_MANAGEMENT",
            resource_id=request_id,
            details={
                "task_count": result.get("deduplicated_count", 0),
                "original_count": result.get("original_count", 0),
                "sheets_success": result.get("results", {}).get("google_sheets", {}).get("success", False),
                "platform_success": result.get("results", {}).get("platform_webhook", {}).get("success", False)
            },
            ip_address=client_ip,
            success=result.get("success", False),
            risk_level="LOW",
        )

        logger.info(f"Task save completed request_id={request_id} tasks_processed={result.get('deduplicated_count', 0)}")

        return {
            "success": result.get("success", False),
            "message": result.get("message", "Tasks processed"),
            "tasks_processed": result.get("deduplicated_count", 0),
            "original_tasks": result.get("original_count", 0),
            "request_id": request_id,
            "results": result.get("results", {}),
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in save_tasks_from_agent request_id={request_id}: {e}", exc_info=True)
        audit_logger.log_sensitive_operation(
            operation="TASK_SAVE_UNEXPECTED_ERROR",
            user_id=tasks_data.get("user_id", "unknown") if 'tasks_data' in locals() else "unknown",
            resource_type="TASK_MANAGEMENT",
            resource_id=request_id,
            details={
                "error_message": str(e),
                "error_type": type(e).__name__,
                "task_data_keys": list(tasks_data.keys()) if 'tasks_data' in locals() and isinstance(tasks_data, dict) else "invalid"
            },
            ip_address=client_ip,
            success=False,
            risk_level="HIGH",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while processing tasks",
            headers={"x-request-id": request_id}
        )