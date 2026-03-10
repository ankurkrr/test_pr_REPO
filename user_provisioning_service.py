"""
User Provisioning Service

Handles user onboarding by creating Drive folders and Sheets for new users.
This service is called during OAuth callback to set up user resources.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..google.drive_service import GoogleDriveService
from ..google.sheets_service import GoogleSheetsService
from ..data.repositories.workflow_repository import WorkflowRepository
from ..database_service_new import get_database_service
from ...auth.google_auth_handler import GoogleAuthHandler

logger = logging.getLogger(__name__)

def onboard_user_with_tokens(
    user_id: str,
    access_token: str,
    refresh_token: str
) -> Dict[str, Any]:
    """
    Onboard a new user by creating Drive folder and Sheets.
    
    Args:
        user_id: User ID for the new user
        access_token: Google access token
        refresh_token: Google refresh token
        
    Returns:
        Dict containing drive_folder_id and sheets_id, or error details
    """
    try:
        logger.info(f"Starting user onboarding for user_id={user_id}")
        
        # First, check if we have a valid agent_task_id in the database
        db_service = get_database_service()
        
        # Try to find an existing agent task for this user
        result = db_service.execute_query("""
            SELECT agent_task_id FROM user_agent_task 
            WHERE user_id = :user_id AND org_id = :org_id 
            ORDER BY created DESC LIMIT 1
        """, {"user_id": user_id, "org_id": "elevationai"})
        
        if result and len(result) > 0:
            # Handle both tuple and dict results
            if isinstance(result[0], dict):
                agent_task_id = result[0]["agent_task_id"]
            else:
                agent_task_id = result[0][0]  # First column of tuple
            logger.info(f"Found existing agent_task_id: {agent_task_id}")
        else:
            # Create a temporary agent task entry first to satisfy foreign key constraint
            import uuid
            agent_task_id = f"temp_{uuid.uuid4().hex[:8]}"
            logger.warning(f"No existing agent task found, creating temporary entry: {agent_task_id}")
            
            # Insert temporary agent task entry
            db_service.execute_query("""
                INSERT INTO user_agent_task (agent_task_id, org_id, user_id, name, 
                                           ready_to_use, created, updated, status)
                VALUES (:id, :org_id, :user_id, :name, 
                        :ready_to_use, NOW(), NOW(), :status)
            """, {
                "id": agent_task_id,
                "org_id": "elevationai",
                "user_id": user_id,
                "name": f"Temporary task for {user_id}",
                "ready_to_use": 0,
                "status": 1
            })
        
        # Initialize Google auth handler with user tokens
        auth_handler = GoogleAuthHandler(user_id, "elevationai", agent_task_id)
        
        # Store tokens in auth handler
        auth_handler.store_tokens(access_token, refresh_token)
        
        # Initialize Google services with auth handler
        drive_service = GoogleDriveService(auth=auth_handler)
        sheets_service = GoogleSheetsService(auth=auth_handler)
        
        # Create Drive folder for the user
        folder_name = f"Meeting Intelligence - {user_id}"
        drive_folder_id = drive_service.find_or_create_folder(folder_name)
        
        if not drive_folder_id:
            logger.error(f"Failed to create Drive folder for user {user_id}")
            return {
                "success": False,
                "error": "Failed to create Drive folder",
                "drive_folder_id": None,
                "sheets_id": None
            }
        
        logger.info(f"Created Drive folder {drive_folder_id} for user {user_id}")
        
        # Resolve user name if available for nicer sheet title
        try:
            from .user_resolution_service import get_user_resolution_service
            _urs = get_user_resolution_service()
            _uinfo = _urs.get_user_info(user_id)
            _username = _uinfo.get("name") if _uinfo else None
        except Exception:
            _username = None

        # Create or find Sheets document for the user using find-or-create approach
        sheet_title = f"Meeting_task- {_username or user_id}"
        sheets_id = sheets_service.find_or_create_meeting_tasks_sheet(sheet_title)
        
        if not sheets_id:
            logger.error(f"Failed to create Sheets document for user {user_id}")
            return {
                "success": False,
                "error": "Failed to create Sheets document",
                "drive_folder_id": drive_folder_id,
                "sheets_id": None
            }
        
        logger.info(f"Created Sheets document {sheets_id} for user {user_id}")
        
        # Store user resources in database and upsert workflow_data
        db_service = get_database_service()
        
        try:
            # Update user_agent_task table with resource IDs for this specific agent_task_id
            db_service.execute_query("""
                UPDATE user_agent_task 
                SET drive_folder_id = :drive_folder_id, sheets_id = :sheets_id, updated = NOW()
                WHERE agent_task_id = :agent_task_id
            """, {
                "drive_folder_id": drive_folder_id,
                "sheets_id": sheets_id,
                "agent_task_id": agent_task_id
            })
            
            logger.info(f"Updated database with resources for user {user_id}")

            # Upsert workflow_data for this agent_task
            try:
                from datetime import datetime
                with db_service.get_session() as session:  # type: ignore[attr-defined]
                    repo = WorkflowRepository(session)
                    workflow_payload = [
                        {
                            "type": "provisioning",
                            "created_at": datetime.now().isoformat(),
                            "drive_folder_id": drive_folder_id,
                            "sheets_id": sheets_id,
                            "status": "ready"
                        }
                    ]
                    repo.store_workflow_data(
                        user_id=user_id,
                        org_id="elevationai",
                        agent_task_id=agent_task_id,
                        workflow_data=workflow_payload,
                        timezone=None,
                        notify_to=None
                    )
            except Exception as wf_err:
                logger.warning(f"Failed to upsert workflow_data for {user_id}/{agent_task_id}: {wf_err}")
            
        except Exception as db_error:
            logger.warning(f"Failed to update database with resources: {db_error}")
            # Don't fail the onboarding if database update fails
        
        # Return success with resource IDs
        return {
            "success": True,
            "drive_folder_id": drive_folder_id,
            "sheets_id": sheets_id,
            "message": "User successfully onboarded with Drive folder and Sheets"
        }
        
    except Exception as e:
        logger.error(f"User onboarding failed for {user_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "drive_folder_id": None,
            "sheets_id": None
        }

def create_user_resources_if_missing(
    user_id: str,
    access_token: str,
    refresh_token: str
) -> Dict[str, Any]:
    """
    Create user resources if they don't exist.
    This is a fallback function for existing users who might not have resources.
    
    Args:
        user_id: User ID
        access_token: Google access token
        refresh_token: Google refresh token
        
    Returns:
        Dict with resource creation results
    """
    try:
        # Check if user already has resources
        db_service = get_database_service()
        existing_resources = db_service.get_user_resource_ids(user_id)
        
        if existing_resources.get("drive_folder_id") and existing_resources.get("sheets_id"):
            logger.info(f"User {user_id} already has resources, skipping creation")
            return {
                "success": True,
                "drive_folder_id": existing_resources["drive_folder_id"],
                "sheets_id": existing_resources["sheets_id"],
                "message": "Resources already exist"
            }
        
        # Create resources if missing
        return onboard_user_with_tokens(user_id, access_token, refresh_token)
        
    except Exception as e:
        logger.error(f"Failed to create user resources for {user_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "drive_folder_id": None,
            "sheets_id": None
        }
