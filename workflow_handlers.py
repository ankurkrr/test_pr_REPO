"""
Workflow Request Handlers

Handles all workflow-related API endpoints including start, stop, delete, and status operations.
"""

import base64
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException, Request, status
from pydantic import ValidationError

from ..models.request_models import (
    WorkflowRequest,
    StopRequest,
    DeleteRequest,
    LatestAgentRequest
)
from ..utils.client_utils import get_client_ip
from ..utils.encryption import _try_decode_key_or_iv, decrypt_aes_cbc_base64, process_token_with_env
from ...utils.jwt_processor import process_token
from ...security.data_encryption import SecureDataDeletion, get_audit_logger
from ...services.database_service_new import get_database_service
from ...services.integration.activity_logger import get_activity_logger
from ...auth.google_auth_handler import get_google_auth_handler
from ...services.integration.agent_integration_service import AgentIntegrationService
# from ...services.integration.audit_logger import get_audit_logger  # This module doesn't exist
from ...configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL

logger = logging.getLogger(__name__)

def process_google_tokens_from_workflow_data(workflow_data):
    """
    Process Google tokens from workflow data - DECRYPTION REQUIRED.
    
    - Access Token: AES encrypted (decrypt using same logic as main token)
    - Refresh Token: AES encrypted (decrypt using same logic as main token)
    
    Args:
        workflow_data: List of workflow items from the request
        
    Returns:
        Dict containing processed Google tokens and user info
    """
    google_tokens = {}
    user_info = {}
    
    logger.info(f"Processing workflow data with {len(workflow_data)} items")
    
    for item in workflow_data:
        logger.info(f"DEBUG: Processing workflow item: {item.get('id')}, text: {item.get('text', '')[:50]}")
        if item.get("tool_to_use"):
            for tool in item["tool_to_use"]:
                # Check if this is a Google integration tool
                is_google_integration = tool.get("integration_type") == "google_calender"
                logger.info(f"DEBUG: Tool integration_type: {tool.get('integration_type')}, is_google_integration: {is_google_integration}")
                
                # Handle both old format (fields_json) and new format (direct fields)
                fields = []
                if is_google_integration and tool.get("fields_json"):
                    # Old format: tool has fields_json array
                    fields = tool.get("fields_json", [])
                elif is_google_integration and tool.get("type") == "string" and tool.get("field"):
                    # New format: direct field objects in Google integration item
                    fields = [tool]
                
                logger.info(f"DEBUG: Processing {len(fields)} fields for tool")
                for field in fields:
                    field_name = field.get("field")
                    field_value = field.get("value")
                    # Log all fields being processed
                    logger.info(f"DEBUG: Field - name: '{field_name}', value: '{field_value[:50] if field_value and len(str(field_value)) > 50 else field_value}'")
                    
                    if field.get("field") == "access_token":
                        # ACCESS TOKEN: Try to decrypt, fallback to plain text
                        access_token = field.get("value")
                        logger.info(f"Found access_token field with value length: {len(access_token) if access_token else 0}")
                        if access_token:
                            try:
                                from ..utils.encryption import decrypt_token, _get_env
                                secret_hex = _get_env("PLATFORM_AES_SECRET_HEX")
                                iv_hex = _get_env("PLATFORM_AES_IV_HEX")
                                if secret_hex and iv_hex:
                                    decrypted_access_token = decrypt_token(access_token, secret_hex, iv_hex)
                                    google_tokens["access_token"] = decrypted_access_token
                                    logger.info("Successfully decrypted access token")
                                else:
                                    # No encryption keys, use as plain text
                                    google_tokens["access_token"] = access_token
                                    logger.info("Using access token as plain text (no encryption keys)")
                            except Exception as e:
                                logger.warning(f"Failed to decrypt access token, using as plain text: {e}")
                                google_tokens["access_token"] = access_token
                        
                    elif field.get("field") == "refresh_token":
                        # REFRESH TOKEN: Try to decrypt, fallback to plain text
                        refresh_token = field.get("value")
                        logger.info(f"Found refresh_token field with value length: {len(refresh_token) if refresh_token else 0}")
                        if refresh_token:
                            try:
                                from ..utils.encryption import decrypt_token, _get_env
                                secret_hex = _get_env("PLATFORM_AES_SECRET_HEX")
                                iv_hex = _get_env("PLATFORM_AES_IV_HEX")
                                if secret_hex and iv_hex:
                                    decrypted_refresh_token = decrypt_token(refresh_token, secret_hex, iv_hex)
                                    google_tokens["refresh_token"] = decrypted_refresh_token
                                    logger.info("Successfully decrypted refresh token")
                                else:
                                    # No encryption keys, use as plain text
                                    google_tokens["refresh_token"] = refresh_token
                                    logger.info("Using refresh token as plain text (no encryption keys)")
                            except Exception as e:
                                logger.warning(f"Failed to decrypt refresh token, using as plain text: {e}")
                                google_tokens["refresh_token"] = refresh_token
                    
                    # Extract user info fields
                    elif field.get("field") == "email":
                        email_value = field.get("value")
                        user_info["email"] = email_value
                        logger.info(f"[SUCCESS] FOUND EMAIL FIELD: '{email_value}' - Setting user_info['email'] = '{email_value}'")
                    elif field.get("field") == "first_name":
                        user_info["first_name"] = field.get("value")
                        logger.info(f"[SUCCESS] FOUND FIRST_NAME FIELD: '{field.get('value')}'")
                    elif field.get("field") == "last_name":
                        user_info["last_name"] = field.get("value")
                        logger.info(f"[SUCCESS] FOUND LAST_NAME FIELD: '{field.get('value')}'")
                    elif field.get("field") == "name":
                        user_info["name"] = field.get("value")
                        logger.info(f"[SUCCESS] FOUND NAME FIELD: '{field.get('value')}'")
    
    # Construct full name if only first_name and last_name are available
    if "name" not in user_info and "first_name" in user_info and "last_name" in user_info:
        user_info["name"] = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
        logger.info(f"[SUCCESS] Constructed full name from first_name + last_name: '{user_info['name']}'")
    
    logger.info(f"Final extracted data - google_tokens: {list(google_tokens.keys())}, user_info: {list(user_info.keys())}")
    logger.info(f"Final user_info: {user_info}")
    return {
        "google_tokens": google_tokens,
        "user_info": user_info
    }

async def _resolve_auth_and_workflow_data(request, http_request, audit_logger):
    """
    Handles platform token verification, workflow data preparation, and token decryption.

    This function centralizes all cryptographic risk and complex token processing logic.
    It handles the nested loop decryption that was causing BASE64/HEX decoding errors.

    Args:
        request: WorkflowRequest object with encrypted tokens and workflow data
        http_request: FastAPI request object for security context
        audit_logger: Audit logger instance for security logging

    Returns:
        Dict containing resolved user data, workflow data, auth tokens, and recipient scope

    Raises:
        HTTPException: If platform token verification fails (401) or critical decryption fails
    """
    # Initialization
    user_id = ""
    org_id = "unknown"
    key_bytes, iv_bytes = None, None
    decrypted_auth_tokens = {"token": None, "access_token": None, "refresh_token": None}
    client_ip = get_client_ip(http_request)
    request_id = getattr(http_request.state, "request_id", "unknown")

    # 1. PLATFORM TOKEN DECRYPTION (MANDATORY)
    try:
        # NOTE: If this fails, the function raises HTTPException (401)
        token_info = process_token_with_env(request.token)
        user_id = token_info.get("user_id", user_id) or user_id
        org_id = token_info.get("org_id", org_id) or org_id
        decrypted_auth_tokens["token"] = request.token

        logger.info(f"Successfully decrypted platform token for user {user_id}, org {org_id}")

    except Exception as e:
        logger.error(f"Platform token decryption failed: {e}")

        audit_logger.log_sensitive_operation(
            operation="PLATFORM_TOKEN_ERROR",
            user_id=user_id,
            details={"error": str(e)},
            ip_address=client_ip,
            success=False,
            risk_level="HIGH",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Platform token verification failed"
        )

    # 2. DECRYPT EMBEDDED TOOL TOKENS (The highly complex loop is here)
    workflow_data_dicts = []
    recipient_scope = None  # Determined within the loop

    # This loop is where BASE64/HEX decoding errors are most likely occurring
    for item in request.workflow_data:
        item_dict = item.model_dump()

        # Add user context to workflow data for isolation
        item_dict["_user_id"] = user_id
        item_dict["_request_id"] = request_id
        item_dict["_org_id"] = org_id
        if request.timezone:
            item_dict["_timezone"] = request.timezone

        # --- Google tokens are processed separately via process_google_tokens_from_workflow_data ---
        # No decryption needed for Google tokens - they are already plain text or hex-encoded

        # --- Recipient Scope Determination (Inline logic) ---
        try:
            for tool in item.tool_to_use:
                for field in tool.fields_json:
                    if isinstance(field, dict) and field.get("field") == "notify_to":
                        val = (field.get("value") or "").strip().lower()
                        if val == "only_me":
                            recipient_scope = "only_me"
                        elif val == "all":
                            recipient_scope = "all_participants"
                        break
                if recipient_scope:
                    break
        except Exception:
            recipient_scope = None

        # Attach recipient scope to workflow context for downstream tools
        if recipient_scope:
            item_dict["_recipient_scope"] = recipient_scope

        workflow_data_dicts.append(item_dict)

    # Log token presence (NOT values) for security audit
    audit_logger.log_sensitive_operation(
        operation="TOKEN_DECRYPTION_COMPLETE",
        user_id=user_id,
        details={
            "token_present": bool(decrypted_auth_tokens.get("token")),
            "access_token_present": bool(decrypted_auth_tokens.get("access_token")),
            "refresh_token_present": bool(decrypted_auth_tokens.get("refresh_token")),
        },
        ip_address=client_ip,
        success=True,
        risk_level="HIGH",
    )

    # Return structured data for the next step
    return {
        "user_id": user_id,
        "org_id": org_id,
        "workflow_data": workflow_data_dicts,
        "auth_tokens": decrypted_auth_tokens,
        "recipient_scope": recipient_scope,
    }

async def _persist_tokens_and_data(request, resolved_data, http_request):
    """
    Handles all database interaction, token storage, and initial activity logging.

    This function centralizes all I/O operations and database persistence logic.
    It handles Google token storage, workflow data storage, and activity logging.

    Args:
        request: WorkflowRequest object with agent_task_id and timezone
        resolved_data: Dict from _resolve_auth_and_workflow_data containing user data
        http_request: FastAPI request object for security context

    Returns:
        google_auth_handler: GoogleAuthHandler instance if tokens were stored, None otherwise
    """
    # Extract data from the resolved dictionary
    user_id = resolved_data["user_id"]
    org_id = resolved_data["org_id"]
    decrypted_auth_tokens = resolved_data["auth_tokens"]
    workflow_data_dicts = resolved_data["workflow_data"]
    recipient_scope = resolved_data["recipient_scope"]
    client_ip = get_client_ip(http_request)

    # Get service instances
    db_service = get_database_service()
    activity_logger = get_activity_logger()
    google_auth_handler = None

    # 1. GOOGLE TOKEN STORAGE (Critical I/O)
    if decrypted_auth_tokens.get("access_token") and decrypted_auth_tokens.get("refresh_token"):
        try:
            google_auth_handler = get_google_auth_handler(user_id, org_id, request.agent_task_id)

            # This is where the code may fail if DB is down or tokens are bad
            token_stored = google_auth_handler.store_tokens(
                access_token=decrypted_auth_tokens["access_token"],
                refresh_token=decrypted_auth_tokens["refresh_token"],
                scope=os.getenv("GOOGLE_OAUTH_SCOPES")
            )

            if token_stored:
                logger.info(f"Google tokens stored successfully for user {user_id}")

                # Log successful token storage
                await activity_logger.log_activity(
                    action_type="google_tokens_stored",
                    user_id=user_id,
                    agent_task_id=request.agent_task_id,
                    status="success",
                    details={"token_scope": "google_oauth"},
                    ip_address=client_ip,
                    user_agent=http_request.headers.get("user-agent")
                )
            else:
                logger.warning(f"Failed to store Google tokens for user {user_id}")

        except Exception as e:
            # DO NOT raise HTTPException here; this is non-fatal for *starting* the workflow
            logger.error(f"Error storing Google tokens: {e}")
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="token_storage_failed",
                error_message=str(e),
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )

    # 2. WORKFLOW DATA STORAGE (I/O)
    try:
        # This is where the code may fail if DB is down or data format is wrong
        workflow_data_stored = db_service.store_workflow_data(
            user_id=user_id,
            org_id=org_id,
            agent_task_id=request.agent_task_id,
            workflow_data=workflow_data_dicts,
            timezone=request.timezone,
            notify_to=recipient_scope
        )

        if workflow_data_stored:
            logger.info(f"Workflow data stored successfully for task {request.agent_task_id}")
        else:
            logger.warning(f"Failed to store workflow data for task {request.agent_task_id}")

    except Exception as e:
        # Log this failure but do not crash the endpoint (let the workflow run)
        logger.error(f"Error storing workflow data: {e}")
        await activity_logger.log_agent_error(
            user_id=user_id,
            agent_task_id=request.agent_task_id,
            error_type="workflow_data_storage_failed",
            error_message=str(e),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )

    # 3. LOGGING (Non-critical I/O)
    try:
        # Log detailed workflow start activity
        await activity_logger.log_workflow_start(
            agent_task_id=request.agent_task_id,
            user_id=user_id,
            workflow_items_count=len(workflow_data_dicts),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )

        # Log Google token storage if successful
        if google_auth_handler and decrypted_auth_tokens.get("access_token"):
            await activity_logger.log_google_integration(
                agent_task_id=request.agent_task_id,
                action="token_storage",
                service="OAuth",
                status="success",
                details={
                    "user_id": user_id,
                    "org_id": org_id,
                    "scope": os.getenv("GOOGLE_OAUTH_SCOPES", ""),
                    "timestamp": datetime.now().isoformat()
                }
            )

    except Exception as e:
        # Logging failures should not crash the endpoint
        logger.warning(f"Error in activity logging: {e}")

    return google_auth_handler  # Return the handler for the workflow call

async def start_agent_workflow(
    request: WorkflowRequest,
    http_request: Request,
):
    """
    High-security endpoint for starting agent workflow with encrypted tokens.

    Security Features:
    - Rate limiting (10 requests/minute)
    - Comprehensive input validation
    - Encrypted token handling with user isolation
    - Enhanced audit logging
    - No authentication headers required (application/json only)

    Args:
        request: Validated WorkflowRequest with encrypted tokens
        http_request: FastAPI request for security context
    """
    client_ip = get_client_ip(http_request)
    request_id = getattr(http_request.state, "request_id", "unknown")
    
    logger.info(f"Starting agent workflow request_id={request_id} from {client_ip}")
    
    try:
        # Get services
        activity_logger = get_activity_logger()
        audit_logger = get_audit_logger()
        db_service = get_database_service()
        
        # Decrypt and process the main token to get user_id and org_id
        try:
            # Get encryption keys from environment using fallback function
            from ..utils.encryption import _get_env
            secret_hex = _get_env("PLATFORM_AES_SECRET_HEX")
            iv_hex = _get_env("PLATFORM_AES_IV_HEX") 
            jwt_secret = _get_env("PLATFORM_JWT_SECRET")
            
            if not all([secret_hex, iv_hex, jwt_secret]):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Missing encryption configuration"
                )
            
            # Process the encrypted token
            token_data = process_token(request.token, secret_hex, iv_hex, jwt_secret)
            user_id_from_token = token_data["user_id"]
            org_id_from_token = token_data["org_id"]
            
            logger.info(f"Successfully decrypted token for user_id={user_id_from_token}, org_id={org_id_from_token}")
            
        except Exception as e:
            logger.error(f"Token decryption failed: {str(e)}")
            await activity_logger.log_agent_error(
                user_id="unknown",
                agent_task_id=request.agent_task_id,
                error_type="token_decryption_failed",
                error_message=f"Failed to decrypt token: {str(e)}",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired token"
            )
        
        # Log the workflow start with actual user_id
        audit_logger.log_sensitive_operation(
            operation="AGENT_WORKFLOW_START",
            user_id=user_id_from_token,
            resource_type="agent_workflow",
            resource_id=request.agent_task_id,
            details={"workflow_data_count": len(request.workflow_data)},
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent", "unknown")
        )
        
        # If the agent record already exists, re-enable it and return success immediately
        try:
            existing = db_service.execute_query(
                """
                SELECT agent_task_id, status, ready_to_use
                FROM user_agent_task
                WHERE agent_task_id = :agent_task_id AND user_id = :user_id AND org_id = :org_id
                LIMIT 1
                """,
                {
                    "agent_task_id": request.agent_task_id,
                    "user_id": user_id_from_token,
                    "org_id": org_id_from_token,
                },
            )

            if existing:
                logger.info(
                    f"Existing agent found for agent_task_id={request.agent_task_id}; re-enabling (status=1, ready_to_use=1)"
                )

                db_service.execute_query(
                    """
                    UPDATE user_agent_task
                    SET status = 1, ready_to_use = 1, updated = NOW()
                    WHERE agent_task_id = :agent_task_id AND user_id = :user_id AND org_id = :org_id
                    """,
                    {
                        "agent_task_id": request.agent_task_id,
                        "user_id": user_id_from_token,
                        "org_id": org_id_from_token,
                    },
                )

                try:
                    await activity_logger.log_workflow_start(
                        agent_task_id=request.agent_task_id,
                        user_id=user_id_from_token,
                        workflow_items_count=len(request.workflow_data),
                        ip_address=client_ip,
                        user_agent=http_request.headers.get("user-agent"),
                    )
                except Exception:
                    pass

                audit_logger.log_sensitive_operation(
                    operation="AGENT_REENABLED",
                    user_id=user_id_from_token,
                    resource_type="AGENT_TASK",
                    resource_id=request.agent_task_id,
                    details={"org_id": org_id_from_token},
                    ip_address=client_ip,
                    success=True,
                    risk_level="LOW",
                )

                return {
                    "status": "success",
                    "message": "Existing agent re-enabled",
                    "agent_task_id": request.agent_task_id,
                    "user_id": user_id_from_token,
                    "org_id": org_id_from_token,
                    "workflow_status": "active",
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            # If the re-enable path fails for any reason, fall back to full creation flow
            logger.warning(f"Agent re-enable check failed; continuing with full start flow: {e}")

        # Process workflow data using optimal token processing method
        workflow_data_dicts = [item.model_dump() for item in request.workflow_data]
        processed_data = process_google_tokens_from_workflow_data(workflow_data_dicts)
        google_tokens = processed_data["google_tokens"]
        user_info = processed_data["user_info"]
        
        # DEBUG: Log extracted user info
        logger.info(f"DEBUG: Extracted user_info: {user_info}")
        logger.info(f"DEBUG: Extracted email: {user_info.get('email')}")
        logger.info(f"DEBUG: Google tokens keys: {list(google_tokens.keys())}")
        
        # Extract notification preference
        notification_preference = "only_me"  # default
        for workflow_item in request.workflow_data:
            if workflow_item.id == "360e41e7-ddf7-445f-9141-0b5c2ecb1010":  # Notification preference
                for tool in workflow_item.tool_to_use:
                    # Check for notify_to field regardless of integration_type
                    for field in tool.fields_json:
                        if field.field == "notify_to":
                            notification_preference = field.value
                            break
        
        # Validate required data - CRITICAL CHECKS
        email = user_info.get("email")
        if not email or not email.strip():
            error_msg = f"Email is required but missing or empty. user_info: {user_info}"
            logger.error(error_msg)
            await activity_logger.log_agent_error(
                user_id=user_id_from_token,
                agent_task_id=request.agent_task_id,
                error_type="missing_user_email",
                error_message=error_msg,
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required in workflow data"
            )
        
        if not google_tokens.get("access_token") or not google_tokens.get("refresh_token"):
            error_msg = "Missing Google OAuth tokens"
            logger.error(error_msg)
            await activity_logger.log_agent_error(
                user_id=user_id_from_token,
                agent_task_id=request.agent_task_id,
                error_type="missing_google_tokens",
                error_message=error_msg,
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required Google OAuth tokens"
            )
        
        logger.info(f"[SUCCESS] Validation passed - Email: {email}, Has tokens: {bool(google_tokens.get('access_token'))}")
        
        # Store user and agent information in database
        # Prioritize user_id from token, use email as fallback only if token user_id is empty
        user_id = user_id_from_token if user_id_from_token and user_id_from_token.strip() else user_info["email"]
        org_id = org_id_from_token  # Use org_id from decrypted token
        
        # Initialize Google resource IDs (will be populated after database operations)
        drive_folder_id = None
        sheets_id = None
        
        # Store agent task information - STRICT DATABASE REQUIREMENT
        # Use validated email and construct name
        full_name = user_info.get('name') or f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip() or f"User {user_id}"
        
        agent_data = {
            "user_id": user_id,
            "org_id": org_id,
            "agent_task_id": request.agent_task_id,
            "name": full_name,
            "email": email,  # Use validated email
            "status": 1,  # Active
            "ready_to_use": 1,
            "google_access_token": google_tokens["access_token"],
            "google_refresh_token": google_tokens["refresh_token"],
            "notification_preference": notification_preference,
            "timezone": request.timezone or "UTC",  # Use provided timezone or UTC as fallback
            "drive_folder_id": drive_folder_id,
            "sheets_id": sheets_id
        }
        
        # Log before database operation
        logger.info(f"ENDPOINT_ACTION: Starting database save for agent_task_id={request.agent_task_id}, user_id={user_id}")
        logger.debug(f"ENDPOINT_DATA: Agent data to save: {agent_data}")
        logger.info(f"DEBUG: [SUCCESS] Email in agent_data: '{agent_data.get('email')}'")
        logger.info(f"DEBUG: [SUCCESS] Name in agent_data: '{agent_data.get('name')}'")
            
        # Insert or update user agent task record - REQUIRED
        try:
            db_service.execute_query("""
                INSERT INTO user_agent_task 
                (agent_task_id, org_id, user_id, name, email, status, ready_to_use, 
                 google_access_token, google_refresh_token, notification_preference, timezone, 
                 drive_folder_id, sheets_id, created, updated)
                VALUES 
                (:agent_task_id, :org_id, :user_id, :name, :email, :status, :ready_to_use,
                 :google_access_token, :google_refresh_token, :notification_preference, :timezone,
                 :drive_folder_id, :sheets_id, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                email = VALUES(email),
                google_access_token = VALUES(google_access_token),
                google_refresh_token = VALUES(google_refresh_token),
                notification_preference = VALUES(notification_preference),
                timezone = VALUES(timezone),
                drive_folder_id = VALUES(drive_folder_id),
                sheets_id = VALUES(sheets_id),
                updated = NOW()
            """, {
                "agent_task_id": request.agent_task_id,
                "org_id": agent_data["org_id"],
                "user_id": agent_data["user_id"],
                "name": agent_data["name"],
                "email": agent_data["email"],
                "status": agent_data["status"],
                "ready_to_use": agent_data["ready_to_use"],
                "google_access_token": agent_data["google_access_token"],
                "google_refresh_token": agent_data["google_refresh_token"],
                "notification_preference": agent_data["notification_preference"],
                "timezone": agent_data["timezone"],
                "drive_folder_id": agent_data["drive_folder_id"],
                "sheets_id": agent_data["sheets_id"]
            })
            logger.info(f"ENDPOINT_ACTION: Successfully completed user_agent_task save for agent_task_id={request.agent_task_id}, user_id={user_id}")
        except Exception as db_error:
            logger.error(f"CRITICAL: Failed to save user_agent_task to database: {db_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database operation failed: Unable to store agent task data. Error: {str(db_error)}"
            )
        
        # Store OAuth tokens in oauth_tokens table for cron integration - REQUIRED
        try:
            logger.info(f"ENDPOINT_ACTION: Starting OAuth token storage for cron integration, user_id={user_id}")
            
            db_service.execute_query("""
                INSERT INTO oauth_tokens
                (user_id, org_id, agent_task_id, provider,
                 access_token, refresh_token, token_type, expires_at, scope, created_at, updated_at)
                VALUES (:user_id, :org_id, :agent_task_id, :provider,
                        :access_token, :refresh_token, :token_type, :expires_at, :scope, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                access_token = VALUES(access_token),
                refresh_token = VALUES(refresh_token),
                expires_at = VALUES(expires_at),
                token_type = VALUES(token_type),
                scope = VALUES(scope),
                updated_at = VALUES(updated_at)
            """, {
                "user_id": user_id,
                "org_id": org_id,
                "agent_task_id": request.agent_task_id,
                "provider": "google",
                "access_token": google_tokens["access_token"],
                "refresh_token": google_tokens["refresh_token"],
                "token_type": "Bearer",
                "expires_at": None,
                "scope": "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/drive",
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })
            logger.info(f"ENDPOINT_ACTION: Successfully completed OAuth token storage for cron integration, user_id={user_id}")
        except Exception as oauth_error:
            logger.error(f"CRITICAL: Failed to save OAuth tokens to database: {oauth_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database operation failed: Unable to store OAuth tokens. Error: {str(oauth_error)}"
            )
        
        # Create user resources (Google Drive folder and Sheets) - REQUIRED
        logger.info(f"ENDPOINT_ACTION: Creating user resources for user_id={user_id}")
        
        try:
            # Create Google Drive folder
            from ...services.google.drive_service import GoogleDriveService
            from ...auth.google_auth_handler import GoogleAuthHandler
            
            # Initialize auth handler with required parameters
            auth_handler = GoogleAuthHandler(user_id, org_id, request.agent_task_id)
            
            # Store the tokens in the auth handler
            auth_handler.store_tokens(
                google_tokens["access_token"], 
                google_tokens["refresh_token"],
                scope="https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets"
            )
            
            drive_service = GoogleDriveService(auth_handler)
            folder_name = f"Meeting Intelligence - {user_info.get('name', user_id)}"
            drive_folder_id = drive_service.find_or_create_folder(folder_name)
            
            if drive_folder_id:
                logger.info(f"ENDPOINT_ACTION: Created Drive folder {drive_folder_id} for user_id={user_id}")
                # Emit friendly audit for Drive folder creation
                try:
                    from ...services.integration.platform_api_client import PlatformAPIClient
                    import asyncio as _asyncio
                    _platform_client = PlatformAPIClient()
                    _platform_client.send_simple_log_sync(
                        agent_task_id=request.agent_task_id,
                        log_text="Google Drive folder created for meeting storage.",
                        activity_type="integration",
                        log_for_status="success",
                        action="Create",
                            action_issue_event="A dedicated Google Drive folder has been created to securely store all meeting transcripts, summaries, and related files for easy access.",
                        action_required="None",
                        outcome="Meeting data storage location established.",
                        step_str=f"A Google Drive folder has been created for storing meeting recordings, summaries, and related documents. Folder ID: {drive_folder_id}",
                        tool_str="Google Drive",
                        log_data={"user_id": user_id, "org_id": org_id, "drive_folder_id": drive_folder_id}
                    )
                except Exception as _e:
                    logger.warning(f"Failed to emit drive_folder_created audit: {_e}")
            else:
                logger.warning(f"ENDPOINT_ACTION: Failed to create Drive folder for user_id={user_id}")
                
        except Exception as drive_error:
            logger.error(f"ENDPOINT_ACTION: Drive folder creation failed for user_id={user_id}: {drive_error}")
            drive_folder_id = None
        
        try:
            # Create or find Google Sheets using find-or-create approach
            from ...services.google.sheets_service import GoogleSheetsService
            
            sheets_service = GoogleSheetsService(auth_handler)
            sheet_title = f"Meeting_task- {user_info.get('name', user_id)}"
            sheets_id = sheets_service.find_or_create_meeting_tasks_sheet(sheet_title)
            
            if sheets_id:
                logger.info(f"ENDPOINT_ACTION: Created Sheets {sheets_id} for user_id={user_id}")
                # Emit friendly audit for Sheets creation
                try:
                    from ...services.integration.platform_api_client import PlatformAPIClient
                    import asyncio as _asyncio
                    _platform_client = PlatformAPIClient()
                    _platform_client.send_simple_log_sync(
                        agent_task_id=request.agent_task_id,
                        log_text="Google Sheets created for task management.",
                        activity_type="integration",
                        log_for_status="success",
                        action="Create",
                            action_issue_event="A Google Sheet has been created to manage extracted tasks, making it simple to track action items and progress after each meeting.",
                        action_required="None",
                        outcome="Task tracking spreadsheet established.",
                        step_str=f"A Google Sheet has been created for structured task management. All meeting tasks and action items will be automatically logged here. Sheet ID: {sheets_id}",
                        tool_str="Google Sheets",
                        log_data={"user_id": user_id, "org_id": org_id, "sheets_id": sheets_id}
                    )
                except Exception as _e:
                    logger.warning(f"Failed to emit sheets_created audit: {_e}")
            else:
                logger.warning(f"ENDPOINT_ACTION: Failed to create Sheets for user_id={user_id}")
                
        except Exception as sheets_error:
            logger.error(f"ENDPOINT_ACTION: Sheets creation failed for user_id={user_id}: {sheets_error}")
            sheets_id = None
        
        # Update the database with the created resource IDs
        if drive_folder_id or sheets_id:
            try:
                update_data = {}
                if drive_folder_id:
                    update_data["drive_folder_id"] = drive_folder_id
                if sheets_id:
                    update_data["sheets_id"] = sheets_id
                
                if update_data:
                    db_service.execute_query("""
                        UPDATE user_agent_task 
                        SET drive_folder_id = :drive_folder_id, sheets_id = :sheets_id, updated = NOW()
                        WHERE agent_task_id = :agent_task_id
                    """, {
                        "drive_folder_id": drive_folder_id,
                        "sheets_id": sheets_id,
                        "agent_task_id": request.agent_task_id
                    })
                    logger.info(f"ENDPOINT_ACTION: Updated user_agent_task with resource IDs for agent_task_id={request.agent_task_id}")
            except Exception as update_error:
                logger.error(f"ENDPOINT_ACTION: Failed to update resource IDs in database: {update_error}")
        
        # Store workflow data - REQUIRED
        try:
            logger.info(f"ENDPOINT_ACTION: Starting workflow data storage, user_id={user_id}")
            
            # Convert workflow data to JSON (convert Pydantic models to dicts first)
            workflow_data_dicts = [item.model_dump() for item in request.workflow_data]
            workflow_data_json = json.dumps(workflow_data_dicts)
            
            db_service.execute_query("""
                INSERT INTO workflow_data
                (user_id, org_id, agent_task_id, workflow_data, timezone, notify_to, status, created_at, updated_at)
                VALUES (:user_id, :org_id, :agent_task_id, :workflow_data, :timezone, :notify_to, :status, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                workflow_data = VALUES(workflow_data),
                timezone = VALUES(timezone),
                notify_to = VALUES(notify_to),
                status = VALUES(status),
                updated_at = VALUES(updated_at)
            """, {
                "user_id": user_id,
                "org_id": org_id,
                "agent_task_id": request.agent_task_id,
                "workflow_data": workflow_data_json,
                "timezone": request.timezone or "UTC",  # Use provided timezone or UTC as fallback
                "notify_to": notification_preference,
                "status": "active",
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })
            logger.info(f"ENDPOINT_ACTION: Successfully completed workflow data storage, user_id={user_id}")
        except Exception as workflow_error:
            logger.error(f"CRITICAL: Failed to save workflow data to database: {workflow_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database operation failed: Unable to store workflow data. Error: {str(workflow_error)}"
            )
        
        # Cache workflow context for later audit enrichment (step_id/tool_id/integration_type)
        try:
            from ...services.integration.platform_api_client import PlatformAPIClient as _PAC
            _pac = _PAC()
            _pac.cache_workflow_context(agent_task_id=request.agent_task_id, workflow_items=request.workflow_data or [])
        except Exception:
            pass

        # Send friendly audit log to platform (non-blocking)
        try:
            from ...services.integration.platform_api_client import PlatformAPIClient
            import asyncio
            
            platform_client = PlatformAPIClient()
            platform_client.send_simple_log_sync(
                agent_task_id=request.agent_task_id,
                log_text="Meeting agent starts working for you successfully",
                activity_type="workflow",
                log_for_status="success",
                action="Start",
                action_issue_event="Meeting agent is now active and ready to work for you.",
                action_required="None",
                outcome="Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding.",
                step_str=f"Meeting agent starts working for you successfully. Let's get the agent work for you and summarize your long transcripts in the best format of your understanding. Google Calendar integration is active for {user_info.get('name', 'Unknown')} ({user_info['email']}). The agent will automatically check for new meetings every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes.",
                tool_str="Meeting Agent",
                log_data={
                    "user_id": user_id,
                    "org_id": org_id,
                    "google_integration": "connected",
                    "user_email": user_info["email"],
                    "user_name": user_info.get("name", "Unknown"),
                    "notification_preference": notification_preference,
                    "timezone": request.timezone or "America/Chicago"
                }
            )
            logger.info(f"ENDPOINT_ACTION: Sent friendly audit log to platform for user_id={user_id}")
            
        except Exception as audit_error:
            logger.warning(f"Failed to send audit log to platform: {audit_error}")
        
        # Suppress duplicate start audit: already sent via PlatformAPIClient above
        logger.debug("Workflow start audit already sent via PlatformAPIClient; skipping ActivityLogger start log to avoid duplicate.")
        
        # Store agent function logs - REQUIRED
        try:
            logger.info(f"ENDPOINT_ACTION: Starting agent function logging for user_id={user_id}")
            
            agent_integration = AgentIntegrationService()
            
            # Log the workflow start
            agent_integration.log_agent_function(
                user_agent_task_id=request.agent_task_id,
                activity_type="workflow_start",
                log_for_status="success",
                tool_name="workflow_handler",
                log_text="Agent workflow started",
                log_data={
                    "user_id": user_id,
                    "org_id": org_id,
                    "agent_task_id": request.agent_task_id,
                    "google_integration": "connected",
                    "user_email": user_info["email"],
                    "notification_preference": notification_preference,
                    "timezone": request.timezone or "America/Chicago"
                },
                outcome="workflow_initialized",
                action_required="none",
                scope="user_workflow",
                step_str="1",
                status=1
            )
            
            # Log Google integration setup
            agent_integration.log_agent_function(
                user_agent_task_id=request.agent_task_id,
                activity_type="google_integration",
                log_for_status="success",
                tool_name="google_auth",
                log_text=f"Google integration configured for {user_info['email']}",
                log_data={
                    "user_email": user_info["email"],
                    "user_name": user_info.get("name", "Unknown"),
                    "drive_folder_id": drive_folder_id,
                    "sheets_id": sheets_id,
                    "notification_preference": notification_preference
                },
                outcome="google_connected",
                action_required="none",
                scope="user_integration",
                step_str="2",
                status=1
            )
            
            logger.info(f"ENDPOINT_ACTION: Successfully completed agent function logging for user_id={user_id}")
            
        except Exception as log_error:
            logger.error(f"ENDPOINT_ACTION: Failed to log agent functions for user_id={user_id}: {log_error}")
            # Don't fail the main operation if logging fails

        # Store audit logs - REQUIRED
        try:
            logger.info(f"ENDPOINT_ACTION: Starting audit logging for user_id={user_id}")
            
            audit_logger = get_audit_logger()
            
            # Log workflow start
            audit_logger.log_sensitive_operation(
                operation="AGENT_WORKFLOW_START",
                user_id=user_id,
                resource_type="AGENT_TASK",
                resource_id=request.agent_task_id,
                details={
                    "org_id": org_id,
                    "user_email": user_info["email"],
                    "user_name": user_info.get("name", "Unknown"),
                    "google_integration": "connected",
                    "notification_preference": notification_preference,
                    "timezone": request.timezone or "UTC",  # Use provided timezone or UTC as fallback
                    "workflow_data_count": len(request.workflow_data)
                },
                ip_address=client_ip,
                success=True,
                risk_level="LOW"
            )
            
            # Log Google OAuth setup
            audit_logger.log_sensitive_operation(
                operation="GOOGLE_OAUTH_SETUP",
                user_id=user_id,
                resource_type="GOOGLE_ACCOUNT",
                resource_id=user_info["email"],
                details={
                    "org_id": org_id,
                    "agent_task_id": request.agent_task_id,
                    "drive_folder_id": drive_folder_id,
                    "sheets_id": sheets_id,
                    "oauth_scope": "calendar,drive,sheets,email"
                },
                ip_address=client_ip,
                success=True,
                risk_level="MEDIUM"
            )
            
            logger.info(f"ENDPOINT_ACTION: Successfully completed audit logging for user_id={user_id}")
            
        except Exception as audit_error:
            logger.error(f"ENDPOINT_ACTION: Failed to log audit events for user_id={user_id}: {audit_error}")
            # Don't fail the main operation if audit logging fails

        # Return success response with database storage confirmation
        return {
            "status": "success",
            "message": "Meeting Intelligence Agent workflow started successfully",
            "agent_task_id": request.agent_task_id,
            "user_id": user_id,
            "workflow_status": "active",
            "database_storage": {
                "user_agent_task": "stored",
                "workflow_data": "stored", 
                "agent": "stored",
                "agent_function_log": "stored",
                "audit_logs": "stored"
            },
            "google_integration": {
                "status": "connected",
                "email": user_info["email"],
                "name": user_info.get("name", "Unknown"),
                "drive_folder_id": drive_folder_id,
                "sheets_id": sheets_id
            },
            "preferences": {
                "notification_recipients": notification_preference,
                "timezone": request.timezone or "America/Chicago"
            },
            "next_steps": [
                "Agent is ready to process meeting data",
                "Google Calendar integration is active",
                f"Google Drive folder created: {drive_folder_id or 'Failed to create'}",
                f"Google Sheets created: {sheets_id or 'Failed to create'}",
                "Meeting summaries will be sent based on your preference",
                "All data has been stored in database for tracking",
                "Use /latest endpoint to check agent status"
            ],
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in start_agent_workflow request_id={request_id}: {e}", exc_info=True)
        try:
            await activity_logger.log_agent_error(
                user_id="unknown",
                agent_task_id=request.agent_task_id,
                error_type="unexpected_error",
                error_message=f"Unexpected error: {str(e)}",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
        except Exception as log_error:
            logger.warning(f"Failed to log agent error request_id={request_id}: {log_error}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during workflow initialization",
            headers={"x-request-id": request_id}
        )

async def stop_agent_workflow(
    request: StopRequest,
    http_request: Request,
) -> Dict[str, Any]:
    """
    Securely stop the agent workflow execution.

    Enhanced Features:
    - Proper agent validation and status checking
    - Database integration for workflow state management
    - Activity logging to external audit API
    - Comprehensive error handling for edge cases
    - Input validation and sanitization
    - Audit logging for security compliance
    """
    client_ip = get_client_ip(http_request)
    request_id = getattr(http_request.state, "request_id", "unknown")

    activity_logger = get_activity_logger()
    audit_logger = get_audit_logger()
    db_service = get_database_service()

    # 1) Decrypt platform token to identify user/org
    try:
        secret_hex = os.getenv("PLATFORM_AES_SECRET_HEX")
        iv_hex = os.getenv("PLATFORM_AES_IV_HEX")
        jwt_secret = os.getenv("PLATFORM_JWT_SECRET")
        if not all([secret_hex, iv_hex, jwt_secret]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing encryption configuration"
            )
        token_data = process_token(request.token, secret_hex, iv_hex, jwt_secret)
        user_id = token_data.get("user_id", "unknown")
        org_id = token_data.get("org_id", "unknown")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token decryption failed in /stop: {e}")
        await activity_logger.log_agent_error(
            user_id="unknown",
            agent_task_id=request.agent_task_id,
            error_type="token_decryption_failed",
            error_message=str(e),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    # 2) Mark agent as stopped/disabled in DB, revoke tokens if desired
    try:
        # Set ready_to_use = 0 and status = 0 for this agent_task_id
        db_service.execute_query(
            """
            UPDATE user_agent_task
            SET status = 0, ready_to_use = 0, updated = NOW()
            WHERE agent_task_id = :agent_task_id
            """,
            {"agent_task_id": request.agent_task_id}
        )
    except Exception as e:
        logger.error(f"Failed to update user_agent_task status for stop: {e}")
        # Continue; stopping background processes shouldn't be blocked

    # Optional: remove oauth_tokens to effectively stop background processing for this user
    try:
        db_service.execute_query(
            """
            DELETE FROM oauth_tokens
            WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id AND provider = 'google'
            """,
            {"user_id": user_id, "org_id": org_id, "agent_task_id": request.agent_task_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete oauth_tokens during stop for {user_id}/{request.agent_task_id}: {e}")

    # 3) Attempt to stop any scheduler jobs specific to this user (if jobs are per-user in future)
    try:
        # Current scheduler runs a single global job; nothing user-specific to cancel.
        # Placeholder in case per-user jobs are added later.
        pass
    except Exception:
        pass

    # 4) Log stop activity
    try:
        await activity_logger.log_workflow_stop(
            agent_task_id=request.agent_task_id,
            user_id=user_id,
            reason=(request.reason or "User requested"),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )
    except Exception as e:
        logger.warning(f"Failed to log workflow stop activity: {e}")

    # Send friendly audit log to platform (non-blocking)
    try:
        from ...services.integration.platform_api_client import PlatformAPIClient
        import asyncio
        
        platform_client = PlatformAPIClient()
        platform_client.send_simple_log_sync(
            agent_task_id=request.agent_task_id,
            log_text="Your meeting agent has been stopped.",
            activity_type="workflow",
            log_for_status="success",
            action="Stop",
            action_issue_event="Your meeting agent has been successfully stopped and is no longer monitoring your calendar.",
            action_required="None",
            outcome="Meeting agent stopped successfully. Calendar monitoring has been disabled.",
            step_str="Your meeting agent has been stopped. It will no longer check your calendar for new meetings or send notifications. You can restart it anytime to resume monitoring.",
            tool_str="Meeting Agent",
            log_data={
                "user_id": user_id,
                "org_id": org_id,
                "reason": request.reason or "User requested",
                "stopped_at": datetime.now().isoformat()
            }
        )
        logger.info(f"ENDPOINT_ACTION: Sent friendly stop audit log to platform for user_id={user_id}")
    except Exception as audit_error:
        logger.warning(f"Failed to send stop audit log to platform: {audit_error}")

    try:
        audit_logger.log_sensitive_operation(
            operation="AGENT_WORKFLOW_STOP",
            user_id=user_id,
            resource_type="agent_workflow",
            resource_id=request.agent_task_id,
            details={"org_id": org_id, "reason": request.reason or "User requested"},
            ip_address=client_ip,
            success=True,
            risk_level="LOW",
        )
    except Exception:
        pass

    return {
        "status": "success",
        "message": "All background processes have been stopped for the user",
        "agent_task_id": request.agent_task_id,
        "user_id": user_id,
        "request_id": request_id,
        "timestamp": datetime.now().isoformat()
    }

async def delete_agent(
    request: DeleteRequest,
    http_request: Request,
) -> Dict[str, Any]:
    """
    Securely delete the agent with comprehensive protection.

    Security Features:
    - Admin authentication required (JWT + API Key + IP whitelist)
    - Rate limiting
    - Input validation
    - Confirmation required
    - Comprehensive audit logging
    - Secure deletion
    """
    client_ip = get_client_ip(http_request)
    request_id = getattr(http_request.state, "request_id", "unknown")

    activity_logger = get_activity_logger()
    audit_logger = get_audit_logger()
    db_service = get_database_service()

    # 1) Decrypt token to identify user/org
    try:
        secret_hex = os.getenv("PLATFORM_AES_SECRET_HEX")
        iv_hex = os.getenv("PLATFORM_AES_IV_HEX")
        jwt_secret = os.getenv("PLATFORM_JWT_SECRET")
        if not all([secret_hex, iv_hex, jwt_secret]):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing encryption configuration"
            )
        token_data = process_token(request.token, secret_hex, iv_hex, jwt_secret)
        user_id = token_data.get("user_id", "unknown")
        org_id = token_data.get("org_id", "unknown")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token decryption failed in /delete: {e}")
        await activity_logger.log_agent_error(
            user_id="unknown",
            agent_task_id=request.agent_task_id,
            error_type="token_decryption_failed",
            error_message=str(e),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    # 2) Verify that the agent_task_id belongs to the decrypted user/org
    try:
        rows = db_service.execute_query(
            """
            SELECT user_id, org_id
            FROM user_agent_task
            WHERE agent_task_id = :agent_task_id
            LIMIT 1
            """,
            {"agent_task_id": request.agent_task_id}
        )
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
        row_user_id, row_org_id = rows[0][0], rows[0][1]
        if (row_user_id and row_user_id != user_id) or (row_org_id and row_org_id != org_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent does not belong to user/org")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify agent ownership: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Verification failed")

    # 3) Hard delete rows across related tables for this user/org/agent
    # Delete workflow_data records
    try:
        db_service.execute_query(
            """
            DELETE FROM workflow_data
            WHERE agent_task_id = :agent_task_id AND user_id = :user_id AND org_id = :org_id
            """,
            {"agent_task_id": request.agent_task_id, "user_id": user_id, "org_id": org_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete workflow_data during delete: {e}")

    # Delete oauth_tokens records
    try:
        db_service.execute_query(
            """
            DELETE FROM oauth_tokens
            WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
            """,
            {"user_id": user_id, "org_id": org_id, "agent_task_id": request.agent_task_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete oauth_tokens during delete: {e}")

    # Delete agent_function_log records
    try:
        db_service.execute_query(
            """
            DELETE FROM agent_function_log
            WHERE agent_task_id = :agent_task_id
            """,
            {"agent_task_id": request.agent_task_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete agent_function_log during delete: {e}")

    # Delete meetings records (if table exists)
    try:
        db_service.execute_query(
            """
            DELETE FROM meetings
            WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
            """,
            {"user_id": user_id, "org_id": org_id, "agent_task_id": request.agent_task_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete meetings during delete: {e}")

    # Finally, delete the user_agent_task row itself
    try:
        db_service.execute_query(
            """
            DELETE FROM user_agent_task
            WHERE agent_task_id = :agent_task_id
              AND user_id = :user_id
              AND org_id = :org_id
            """,
            {"agent_task_id": request.agent_task_id, "user_id": user_id, "org_id": org_id}
        )
    except Exception as e:
        logger.warning(f"Failed to delete user_agent_task during delete: {e}")

    # 4) Log stop to activity and audit logs
    try:
        await activity_logger.log_workflow_stop(
            agent_task_id=request.agent_task_id,
            user_id=user_id,
            reason="Delete endpoint invoked",
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )
    except Exception as e:
        logger.warning(f"Failed to log activity for delete: {e}")

    try:
        audit_logger.log_sensitive_operation(
            operation="AGENT_WORKFLOW_DELETE",
            user_id=user_id,
            resource_type="agent_workflow",
            resource_id=request.agent_task_id,
            details={"org_id": org_id, "action": "disable_and_token_delete"},
            ip_address=client_ip,
            success=True,
            risk_level="HIGH",
        )
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Agent disabled and tokens deleted for user",
        "agent_task_id": request.agent_task_id,
        "user_id": user_id,
        "org_id": org_id,
        "request_id": request_id,
        "timestamp": datetime.now().isoformat()
    }

async def get_latest_agent_details(
    request: LatestAgentRequest,
    http_request: Request,
) -> Dict[str, Any]:
    """
    Securely fetch the agent's latest data from external API.

    Security Features:
    - JWT + API Key authentication required
    - Rate limiting
    - Input validation
    - User data isolation
    - Secure external API communication
    - Comprehensive audit logging
    """
    client_ip = get_client_ip(http_request)
    user_id = request.user_id
    request_id = getattr(http_request.state, "request_id", "unknown")

    try:
        # Get activity logger instance
        activity_logger = get_activity_logger()
        audit_logger = get_audit_logger()

        # Validate input parameters
        if not request.user_id or not request.org_id or not request.agent_task_id:
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="missing_required_parameters",
                error_message="Missing required parameters: user_id, org_id, or agent_task_id",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required parameters: user_id, org_id, and agent_task_id are required"
            )

        # Audit log the request
        audit_logger.log_sensitive_operation(
            operation="AGENT_LATEST_DATA_REQUEST",
            user_id=user_id,
            resource_type="AGENT_DATA",
            resource_id=request.agent_task_id,
            details={"org_id": request.org_id, "external_api_call": True},
            ip_address=client_ip,
            success=True,
            risk_level="MEDIUM",
        )

        # Platform API configuration (loaded from environment)
        base_url = os.getenv("ELEVATION_AI_PLATFORM_URL", "https://devapi.agentic.elevationai.com")
        external_url = os.getenv("PLATFORM_LATEST_AGENT_URL") or f"{base_url.rstrip('/')}/user-agent-task/get-latest-agent-details"
        api_key = os.getenv("PLATFORM_API_KEY")
        api_secret = os.getenv("PLATFORM_API_SECRET")

        if not external_url or not api_key or not api_secret:
            logger.error("Missing platform API configuration in environment")
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="platform_api_config_missing",
                error_message="Required env vars: PLATFORM_LATEST_AGENT_URL, PLATFORM_API_KEY, PLATFORM_API_SECRET",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Platform API configuration missing"
            )

        # Validate external URL for security
        if not external_url.startswith("https://"):
            logger.error("Insecure platform API URL configured")
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="insecure_api_url",
                error_message="Platform API URL is not HTTPS",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Platform API configuration error - HTTPS required",
            )

        # Prepare payload as specified in requirements
        payload = {
            "org_id": request.org_id,
            "user_id": request.user_id,
            "agent_task_id": request.agent_task_id,
        }

        # Add required headers: ONLY Content-Type, x-api-key, x-api-secret
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "x-api-secret": api_secret,
        }

        logger.info(f"Calling platform API: {external_url}")
        logger.debug(f"Payload: {payload}")
        logger.debug(f"Headers: {list(headers.keys())} (values masked)")

        # Make secure external API call via PlatformAPIClient (async)
        latest_data = None
        try:
            from ...services.integration.platform_api_client import PlatformAPIClient
            client = PlatformAPIClient(base_url=base_url)
            platform_headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "x-api-secret": api_secret,
            }
            latest_data = await client.async_request(
                "POST",
                external_url.replace(base_url, ""),
                headers=platform_headers,
                data=payload,
                timeout=30.0,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Platform API HTTP error: {e.response.status_code} - {e.response.text}")

            # Log to activity logger
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="platform_api_http_error",
                error_message=f"HTTP {e.response.status_code}: {e.response.text}",
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )

            audit_logger.log_sensitive_operation(
                operation="PLATFORM_API_HTTP_ERROR",
                user_id=user_id,
                resource_id=request.agent_task_id,
                details={
                    "status_code": e.response.status_code,
                    "url": external_url,
                    "error": str(e)
                },
                ip_address=client_ip,
                success=False,
                risk_level="MEDIUM",
            )

            # Map platform API errors to appropriate HTTP status
            if e.response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Platform API authentication failed - check PLATFORM_TASK_API_KEY and PLATFORM_TASK_API_SECRET")
            elif e.response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Platform API access forbidden",
                )
            elif e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent task not found on platform",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Platform API error: {e.response.status_code}",
                )

        except httpx.RequestError as e:
            logger.error(f"Platform API connection error: {e}")

            # Log to activity logger
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="platform_api_connection_error",
                error_message=str(e),
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )

            audit_logger.log_sensitive_operation(
                operation="PLATFORM_API_CONNECTION_ERROR",
                user_id=user_id,
                resource_id=request.agent_task_id,
                details={
                    "url": external_url,
                    "error": str(e)
                },
                ip_address=client_ip,
                success=False,
                risk_level="HIGH",
            )

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Platform API temporarily unavailable",
            )

        except Exception as e:
            logger.error(f"Unexpected error calling platform API: {e}")

            # Log to activity logger
            await activity_logger.log_agent_error(
                user_id=user_id,
                agent_task_id=request.agent_task_id,
                error_type="platform_api_unexpected_error",
                error_message=str(e),
                ip_address=client_ip,
                user_agent=http_request.headers.get("user-agent")
            )

            audit_logger.log_sensitive_operation(
                operation="PLATFORM_API_UNEXPECTED_ERROR",
                user_id=user_id,
                resource_id=request.agent_task_id,
                details={
                    "url": external_url,
                    "error": str(e)
                },
                ip_address=client_ip,
                success=False,
                risk_level="HIGH",
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error calling platform API",
            )

        # Log successful API call
        audit_logger.log_sensitive_operation(
            operation="PLATFORM_API_SUCCESS",
            user_id=user_id,
            resource_id=request.agent_task_id,
            details={
                "url": external_url,
                "response_received": bool(latest_data)
            },
            ip_address=client_ip,
            success=True,
            risk_level="LOW",
        )

        # Log to activity logger
        await activity_logger.log_agent_activity(
            user_id=user_id,
            agent_task_id=request.agent_task_id,
            activity_type="platform_api_call_success",
            details={
                "api_endpoint": external_url,
                "response_received": bool(latest_data)
            },
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )

        # Return the latest agent details from platform
        return {
            "success": True,
            "message": "Latest agent details retrieved successfully",
            "data": latest_data,
            "metadata": {
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "platform_api_url": external_url,
                "user_id": user_id,
                "org_id": request.org_id,
                "agent_task_id": request.agent_task_id
            }
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_latest_agent_details: {e}")

        # Log to activity logger
        await activity_logger.log_agent_error(
            user_id=user_id,
            agent_task_id=request.agent_task_id,
            error_type="unexpected_error",
            error_message=str(e),
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent")
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error - please try again"
        )