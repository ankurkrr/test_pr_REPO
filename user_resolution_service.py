"""
User Resolution Service
Handles user ID resolution and validation for the meeting agent system
"""

import logging
from typing import Optional, Dict, Any
from src.services.database_service_new import get_database_service

logger = logging.getLogger(__name__)


class UserResolutionService:
    """
    Service for resolving and validating user IDs
    """

    def __init__(self):
        """Initialize the user resolution service"""
        self.db_service = get_database_service()

    def ensure_user_id(self, user_id: Optional[str]) -> str:
        """
        Ensure a valid user ID exists, creating one if necessary

        Args:
            user_id: Optional user ID to validate

        Returns:
            Valid user ID (existing or newly created)
        """
        try:
            # If user_id is provided and valid, return it
            if user_id and self._is_valid_user_id(user_id):
                logger.debug(f"Using existing user ID: {user_id}")
                return user_id

            # If no user_id provided or invalid, create a default one
            default_user_id = self._create_default_user_id()
            logger.info(f"Created default user ID: {default_user_id}")
            return default_user_id

        except Exception as e:
            logger.error(f"Error in user resolution: {e}")
            # Fallback to a simple default
            return f"user_{hash(str(user_id)) % 1000000}"

    def _is_valid_user_id(self, user_id: str) -> bool:
        """
        Check if a user ID is valid

        Args:
            user_id: User ID to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            if not user_id or not isinstance(user_id, str):
                return False

            # Check if user exists in database
            result = self.db_service.execute_query("""
                SELECT COUNT(*) FROM user_agent_task
                WHERE user_id = :user_id
                LIMIT 1
            """, {"user_id": user_id})

            if result and len(result) > 0:
                return result[0][0] > 0

            return False

        except Exception as e:
            logger.error(f"Error validating user ID {user_id}: {e}")
            return False

    def _create_default_user_id(self) -> str:
        """
        Create a default user ID

        Returns:
            Generated user ID
        """
        import uuid
        from datetime import datetime

        # Generate a unique user ID
        user_id = f"user_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"

        # Try to store in database (optional)
        try:
            self.db_service.execute_query("""
                INSERT IGNORE INTO user_agent_task
                (agent_task_id, user_id, org_id, name, status, ready_to_use)
                VALUES (:agent_task_id, :user_id, :org_id, :name, :status, :ready_to_use)
            """, {
                "agent_task_id": str(uuid.uuid4()),
                "user_id": user_id,
                "org_id": "default_org",
                "name": f"Default User Task for {user_id}",
                "status": 1,
                "ready_to_use": 0
            })
            logger.info(f"Created user record for: {user_id}")
        except Exception as e:
            logger.warning(f"Could not create user record for {user_id}: {e}")

        return user_id

    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from database

        Args:
            user_id: User ID to look up

        Returns:
            User information dict or None if not found
        """
        try:
            result = self.db_service.execute_query("""
                SELECT user_id, org_id, name, status, ready_to_use
                FROM user_agent_task
                WHERE user_id = :user_id
                ORDER BY created DESC
                LIMIT 1
            """, {"user_id": user_id})

            if result and len(result) > 0:
                row = result[0]
                return {
                    "user_id": row[0],
                    "org_id": row[1],
                    "name": row[2],
                    "status": row[3],
                    "ready_to_use": row[4]
                }

            return None

        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
            return None


# Factory function for dependency injection
def get_user_resolution_service() -> UserResolutionService:
    """Get a UserResolutionService instance"""
    return UserResolutionService()