"""
Token Repository

Handles all token-related database operations including Google OAuth tokens.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

class TokenRepository:
    """Repository for token data operations"""

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def store_google_tokens(
        self,
        user_id: str,
        org_id: str,
        agent_task_id: str,
        access_token: str,
        refresh_token: str,
        scope: str,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """Store Google OAuth tokens"""
        try:
            self.db_session.execute(
                text("""
                    INSERT INTO oauth_tokens (
                        user_id, org_id, agent_task_id, provider,
                        access_token, refresh_token, token_type, expires_at, scope,
                        created_at, updated_at
                    ) VALUES (
                        :user_id, :org_id, :agent_task_id, :provider,
                        :access_token, :refresh_token, :token_type, :expires_at, :scope,
                        :created_at, :updated_at
                    )
                    ON DUPLICATE KEY UPDATE
                        access_token = VALUES(access_token),
                        refresh_token = VALUES(refresh_token),
                        token_type = VALUES(token_type),
                        expires_at = VALUES(expires_at),
                        scope = VALUES(scope),
                        updated_at = VALUES(updated_at)
                """),
                {
                    "user_id": user_id,
                    "org_id": org_id,
                    "agent_task_id": agent_task_id,
                    "provider": "google",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "Bearer",
                    "expires_at": expires_at,
                    "scope": scope,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
            )
            self.db_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error storing Google tokens for user {user_id}: {e}")
            self.db_session.rollback()
            return False

    def get_google_tokens(self, user_id: str, agent_task_id: str) -> Optional[Dict[str, Any]]:
        """Get Google OAuth tokens for a user and agent task"""
        try:
            result = self.db_session.execute(
                text("""
                    SELECT access_token, refresh_token, token_type, expires_at, scope,
                           created_at, updated_at
                    FROM oauth_tokens
                    WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                    AND provider = 'google'
                """),
                {"user_id": user_id, "agent_task_id": agent_task_id}
            ).fetchone()

            if result:
                return {
                    "access_token": result.access_token,
                    "refresh_token": result.refresh_token,
                    "token_type": result.token_type,
                    "expires_at": result.expires_at,
                    "scope": result.scope,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at
                }
            return None
        except Exception as e:
            logger.error(f"Error getting Google tokens for user {user_id}: {e}")
            return None

    def update_google_tokens(
        self,
        user_id: str,
        agent_task_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """Update Google OAuth tokens"""
        try:
            update_fields = ["access_token = :access_token", "updated_at = NOW()"]
            params = {
                "user_id": user_id,
                "agent_task_id": agent_task_id,
                "access_token": access_token
            }

            if refresh_token is not None:
                update_fields.append("refresh_token = :refresh_token")
                params["refresh_token"] = refresh_token

            if expires_at is not None:
                update_fields.append("expires_at = :expires_at")
                params["expires_at"] = expires_at

            result = self.db_session.execute(
                text(f"""
                    UPDATE oauth_tokens
                    SET {', '.join(update_fields)}
                    WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                    AND provider = 'google'
                """),
                params
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating Google tokens for user {user_id}: {e}")
            self.db_session.rollback()
            return False

    def delete_google_tokens(self, user_id: str, agent_task_id: str) -> bool:
        """Delete Google OAuth tokens"""
        try:
            result = self.db_session.execute(
                text("""
                    DELETE FROM oauth_tokens
                    WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                    AND provider = 'google'
                """),
                {"user_id": user_id, "agent_task_id": agent_task_id}
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting Google tokens for user {user_id}: {e}")
            self.db_session.rollback()
            return False

    def cleanup_expired_tokens(self, days_old: int = 30) -> int:
        """Clean up expired tokens"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)
            result = self.db_session.execute(
                text("""
                    DELETE FROM oauth_tokens
                    WHERE expires_at < :cutoff_date AND expires_at IS NOT NULL
                """),
                {"cutoff_date": cutoff_date}
            )
            self.db_session.commit()
            return result.rowcount
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}")
            self.db_session.rollback()
            return 0