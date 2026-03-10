"""
Google Authentication Handler

Simplified authentication handler that stores and retrieves Google tokens from database.
Used by LangChain tools and other services that need Google API access.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Lazy import to avoid circular dependency
# from src.services.database_service import get_database_service

logger = logging.getLogger(__name__)


@dataclass
class GoogleTokens:
    """Container for Google OAuth tokens."""
    access_token: str
    refresh_token: str
    user_id: str
    org_id: str
    agent_task_id: str
    created_at: datetime
    expires_in: Optional[int] = None
    token_type: str = "Bearer"
    scope: Optional[str] = None


class GoogleAuthHandler:
    """
    Simplified Google authentication handler.

    Stores and retrieves Google tokens from database.
    Provides latest tokens to LangChain tools and services.
    """

    def __init__(self, user_id: str, org_id: str, agent_task_id: str):
        self.user_id = user_id
        self.org_id = org_id
        self.agent_task_id = agent_task_id
        self._db = None  # Lazy initialization
        self._tokens: Optional[GoogleTokens] = None

    @property
    def db(self):
        """Lazy initialization of database service to avoid circular imports."""
        if self._db is None:
            from src.services.database_service_new import get_database_service
            self._db = get_database_service()
        return self._db

    def store_tokens(self, access_token: str, refresh_token: str,
                    expires_in: Optional[int] = None, scope: Optional[str] = None) -> bool:
        """
        Store Google tokens in both oauth_tokens and user_agent_task tables.

        Args:
            access_token: Google access token
            refresh_token: Google refresh token
            expires_in: Token expiry time in seconds
            scope: Token scopes

        Returns:
            True if stored successfully, False otherwise
        """
        try:
            # Compute expires_at if expires_in provided
            from datetime import timedelta, timezone
            expires_at = None
            if expires_in is not None:
                try:
                    # Use UTC for consistency with database storage
                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
                except Exception:
                    expires_at = None

            # Log before database operation
            logger.info(f"ENDPOINT_ACTION: Starting database upsert for OAuth tokens, user_id={self.user_id}, agent_task_id={self.agent_task_id}")
            logger.debug(f"ENDPOINT_DATA: OAuth token data to save: provider=google, token_type=Bearer, has_refresh={bool(refresh_token)}")
            
            # Upsert tokens into oauth_tokens table (provider scoped)
            self.db.execute_query("""
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
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id,
                "provider": "google",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_at": expires_at,
                "scope": scope,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })
            
            # Log after database operation
            logger.info(f"ENDPOINT_ACTION: Successfully completed database upsert for OAuth tokens, user_id={self.user_id}, agent_task_id={self.agent_task_id}")

            # Also update user_agent_task table with tokens
            self.db.execute_query("""
                UPDATE user_agent_task 
                SET google_access_token = :access_token, 
                    google_refresh_token = :refresh_token,
                    updated = NOW()
                WHERE user_id = :user_id AND org_id = :org_id 
                AND agent_task_id = :agent_task_id
            """, {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id
            })

            # Update local cache
            self._tokens = GoogleTokens(
                access_token=access_token,
                refresh_token=refresh_token,
                user_id=self.user_id,
                org_id=self.org_id,
                agent_task_id=self.agent_task_id,
                created_at=datetime.now(),
                expires_in=expires_in,
                token_type="Bearer",
                scope=scope
            )

            logger.info("Stored Google tokens for user %s, task %s", self.user_id, self.agent_task_id)
            return True

        except Exception as e:
            logger.error("Failed to store Google tokens: %s", e, exc_info=True)
            return False

    def get_latest_tokens(self) -> Optional[GoogleTokens]:
        """
        Get the latest Google tokens from database.

        Returns:
            GoogleTokens object if found, None otherwise
        """
        try:
            # First check local cache
            if self._tokens:
                return self._tokens

            # Log before database operation
            logger.info(f"ENDPOINT_ACTION: Starting database query for OAuth tokens, user_id={self.user_id}, agent_task_id={self.agent_task_id}")
            
            # Query database for latest tokens
            result = self.db.execute_query("""
                SELECT access_token, refresh_token, expires_at, token_type, scope, created_at
                FROM oauth_tokens
                WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id AND provider = 'google'
                ORDER BY updated_at DESC
                LIMIT 1
            """, {"user_id": self.user_id, "org_id": self.org_id, "agent_task_id": self.agent_task_id})
            
            # Log after database operation
            logger.info(f"ENDPOINT_ACTION: Successfully completed database query for OAuth tokens, found {len(result) if result else 0} records")

            if result and len(result) > 0:
                row = result[0]
                access_token, refresh_token, expires_at, token_type, scope, created_at = row
                
                # Calculate expires_in if we have expires_at
                expires_in = None
                if expires_at:
                    from datetime import datetime, timezone
                    # Use UTC for consistency with database storage
                    now = datetime.now(timezone.utc)
                    if isinstance(expires_at, str):
                        # Parse string datetime - handle both with and without timezone
                        try:
                            expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                        except ValueError:
                            # Try parsing without timezone (assume UTC)
                            expires_at = datetime.fromisoformat(expires_at.replace('Z', ''))
                            expires_at = expires_at.replace(tzinfo=timezone.utc)
                    # Ensure expires_at is timezone-aware (assume UTC if naive)
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        except ValueError:
                            created_at = datetime.fromisoformat(created_at.replace('Z', ''))
                            created_at = created_at.replace(tzinfo=timezone.utc)
                    if created_at and created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    
                    # Calculate seconds until expiry
                    if expires_at > now:
                        expires_in = int((expires_at - now).total_seconds())
                        # Log for debugging
                        logger.debug(f"Token expires in {expires_in} seconds for user {self.user_id}")
                    else:
                        expires_in = 0  # Already expired
                        logger.warning(f"Token already expired for user {self.user_id}. expires_at={expires_at}, now={now}")
                
                self._tokens = GoogleTokens(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    user_id=self.user_id,
                    org_id=self.org_id,
                    agent_task_id=self.agent_task_id,
                    created_at=created_at or datetime.now(),
                    expires_in=expires_in,
                    token_type=token_type or "Bearer",
                    scope=scope
                )
                logger.info("Retrieved Google tokens from database for user %s", self.user_id)
                return self._tokens
            else:
                logger.warning("No Google tokens found for user %s, task %s", self.user_id, self.agent_task_id)
                return None

        except Exception as e:
            logger.error("Failed to get Google tokens: %s", e, exc_info=True)
            return None

    def get_access_token(self) -> Optional[str]:
        """Get current access token."""
        tokens = self.get_latest_tokens()
        return tokens.access_token if tokens else None

    def get_refresh_token(self) -> Optional[str]:
        """Get current refresh token."""
        tokens = self.get_latest_tokens()
        return tokens.refresh_token if tokens else None

    def has_valid_tokens(self) -> bool:
        """
        Check if we have valid tokens that are not expired.

        Returns:
            True if we have valid, non-expired tokens, False otherwise
        """
        tokens = self.get_latest_tokens()
        if not tokens or not tokens.access_token:
            logger.debug(f"No tokens found for user {self.user_id}")
            return False
        
        # Check if token is expired
        if tokens.expires_in is not None:
            # Token expires within 5 minutes, consider it invalid
            is_valid = tokens.expires_in > 300
            logger.debug(f"Token validation for user {self.user_id}: expires_in={tokens.expires_in}, valid={is_valid}")
            return is_valid
        else:
            # If no expiry info, assume it might be valid for now
            # The API client will handle refresh if needed
            logger.debug(f"No expiry info for user {self.user_id}, assuming valid")
            return True

    def get_drive_service(self):
        """Build and return an authenticated Google Drive service.

        Uses stored tokens to construct OAuth2 credentials and returns a
        googleapiclient Drive v3 service instance. This method is used by
        `GoogleDriveService` and similar utilities that expect an auth
        object exposing `get_drive_service()`.
        """
        try:
            tokens = self.get_latest_tokens()
            if not tokens:
                logger.error("No tokens available to build Drive service")
                return None

            import os
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            client_id = os.getenv("GOOGLE_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            token_uri = "https://oauth2.googleapis.com/token"

            # Create credentials with proper refresh mechanism using client credentials
            # This allows automatic token refresh every 30 minutes
            from datetime import datetime, timedelta
            
            if client_id and client_secret:
                # Use full OAuth2 credentials with refresh capability
                creds = Credentials(
                    token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    token_uri=token_uri,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            else:
                # Fallback: Use access token only without refresh capability
                # Set expiry to far future to prevent refresh attempts
                future_expiry = datetime.utcnow() + timedelta(hours=24)
                creds = Credentials(
                    token=tokens.access_token,
                    expiry=future_expiry,
                    # Don't set refresh_token, token_uri, client_id, client_secret
                    # This prevents automatic refresh attempts
                )

            # Build service with credentials only (http parameter conflicts with credentials)
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return service
        except Exception as e:
            logger.error("Failed to build Drive service: %s", e, exc_info=True)
            return None

    def get_sheets_service(self):
        """Build and return an authenticated Google Sheets service.

        Uses stored tokens to construct OAuth2 credentials and returns a
        googleapiclient Sheets v4 service instance. This method is used by
        `GoogleSheetsService` and similar utilities that expect an auth
        object exposing `get_sheets_service()`.
        """
        try:
            tokens = self.get_latest_tokens()
            if not tokens:
                logger.error("No tokens available to build Sheets service")
                return None

            import os
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            client_id = os.getenv("GOOGLE_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            token_uri = "https://oauth2.googleapis.com/token"

            # Create credentials with proper refresh mechanism using client credentials
            # This allows automatic token refresh every 30 minutes
            from datetime import datetime, timedelta
            
            if client_id and client_secret:
                # Use full OAuth2 credentials with refresh capability
                creds = Credentials(
                    token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    token_uri=token_uri,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            else:
                # Fallback: Use access token only without refresh capability
                # Set expiry to far future to prevent refresh attempts
                future_expiry = datetime.utcnow() + timedelta(hours=24)
                creds = Credentials(
                    token=tokens.access_token,
                    expiry=future_expiry,
                    # Don't set refresh_token, token_uri, client_id, client_secret
                    # This prevents automatic refresh attempts
                )

            # Build service with credentials only (http parameter conflicts with credentials)
            service = build("sheets", "v4", credentials=creds, cache_discovery=False)
            return service
        except Exception as e:
            logger.error("Failed to build Sheets service: %s", e, exc_info=True)
            return None

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token and update both oauth_tokens and user_agent_task tables."""
        try:
            tokens = self.get_latest_tokens()
            if not tokens or not tokens.refresh_token:
                logger.error("No refresh token available for token refresh")
                return False

            import os
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google.auth.exceptions import RefreshError

            client_id = os.getenv("GOOGLE_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            token_uri = "https://oauth2.googleapis.com/token"

            if not client_id or not client_secret:
                logger.error("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET for token refresh")
                return False

            # Validate refresh token format
            if not self._is_valid_token_format(tokens.refresh_token):
                logger.error(f"Invalid refresh token format for user {self.user_id}")
                self._clear_invalid_tokens()
                return False

            # Create credentials with refresh capability
            creds = Credentials(
                token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_uri=token_uri,
                client_id=client_id,
                client_secret=client_secret,
            )

            # Refresh the token
            logger.info(f"Refreshing access token for user {self.user_id}")
            try:
                creds.refresh(Request())
            except RefreshError as e:
                error_msg = str(e)
                logger.error(f"Token refresh failed for user {self.user_id}: {error_msg}")
                
                # Handle specific error cases
                if "invalid_grant" in error_msg.lower():
                    logger.warning(f"Refresh token is invalid/expired for user {self.user_id}. Clearing tokens.")
                    self._clear_invalid_tokens()
                    return False
                elif "invalid_client" in error_msg.lower():
                    logger.error(f"Invalid Google OAuth client credentials. Check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
                    return False
                else:
                    logger.error(f"Unexpected refresh error for user {self.user_id}: {error_msg}")
                    return False

            # Get expires_in if available from credentials
            expires_in = getattr(creds, 'expires_in', 3600) if hasattr(creds, 'expires_in') else None
            from datetime import datetime, timedelta, timezone
            expires_at = None
            if expires_in:
                # Use UTC for consistency with database storage
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
            # Update oauth_tokens table with new access token AND expires_at
            self.db.execute_query("""
                UPDATE oauth_tokens 
                SET access_token = :access_token,
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id AND org_id = :org_id 
                AND agent_task_id = :agent_task_id AND provider = 'google'
            """, {
                "access_token": creds.token,
                "expires_at": expires_at,
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id
            })

            # Update user_agent_task table with new access token (both tables must stay in sync)
            self.db.execute_query("""
                UPDATE user_agent_task 
                SET google_access_token = :access_token, updated = NOW()
                WHERE user_id = :user_id AND org_id = :org_id 
                AND agent_task_id = :agent_task_id
            """, {
                "access_token": creds.token,
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id
            })

            # Clear cached tokens to force reload
            self._tokens = None
            
            logger.info(f"Successfully refreshed access token for user {self.user_id} in both oauth_tokens and user_agent_task tables")
            logger.info(f"   New token expires_at: {expires_at} (UTC), expires_in: {expires_in} seconds")
            return True

        except Exception as e:
            logger.error(f"Failed to refresh access token for user {self.user_id}: {e}", exc_info=True)
            return False

    def _is_valid_token_format(self, token: str) -> bool:
        """Validate token format to catch obviously invalid tokens."""
        if not token or not isinstance(token, str):
            return False
        
        # Basic validation - tokens should be reasonably long and contain valid characters
        if len(token) < 20:
            return False
        
        # Check for common invalid patterns
        invalid_patterns = [
            "undefined", "null", "none", "invalid", "test", "dummy"
        ]
        
        token_lower = token.lower()
        for pattern in invalid_patterns:
            if pattern in token_lower:
                return False
        
        return True

    def _clear_invalid_tokens(self) -> bool:
        """Clear invalid tokens from database and cache."""
        try:
            logger.warning(f"Clearing invalid tokens for user {self.user_id}")
            
            # Clear from oauth_tokens table
            self.db.execute_query("""
                DELETE FROM oauth_tokens
                WHERE user_id = :user_id AND org_id = :org_id 
                AND agent_task_id = :agent_task_id AND provider = 'google'
            """, {
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id
            })

            # Clear from user_agent_task table
            self.db.execute_query("""
                UPDATE user_agent_task 
                SET google_access_token = NULL, 
                    google_refresh_token = NULL,
                    updated = NOW()
                WHERE user_id = :user_id AND org_id = :org_id 
                AND agent_task_id = :agent_task_id
            """, {
                "user_id": self.user_id,
                "org_id": self.org_id,
                "agent_task_id": self.agent_task_id
            })

            # Clear local cache
            self._tokens = None
            
            logger.info(f"Successfully cleared invalid tokens for user {self.user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to clear invalid tokens for user {self.user_id}: {e}")
            return False

    def clear_tokens(self) -> bool:
        """Clear tokens from database and cache."""
        try:
            # Log before database operation
            logger.info(f"ENDPOINT_ACTION: Starting database delete for OAuth tokens, user_id={self.user_id}, agent_task_id={self.agent_task_id}")
            
            self.db.execute_query("""
                DELETE FROM oauth_tokens
                WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id AND provider = 'google'
            """, {"user_id": self.user_id, "org_id": self.org_id, "agent_task_id": self.agent_task_id})
            
            # Log after database operation
            logger.info(f"ENDPOINT_ACTION: Successfully completed database delete for OAuth tokens, user_id={self.user_id}, agent_task_id={self.agent_task_id}")

            self._tokens = None
            logger.info("Cleared Google tokens for user %s, task %s", self.user_id, self.agent_task_id)
            return True

        except Exception as e:
            logger.error("Failed to clear Google tokens: %s", e, exc_info=True)
            return False


def get_google_auth_handler(user_id: str, org_id: str, agent_task_id: str) -> GoogleAuthHandler:
    """Factory function to create GoogleAuthHandler instance."""
    return GoogleAuthHandler(user_id, org_id, agent_task_id)


def cleanup_invalid_tokens_for_user(user_id: str, org_id: str, agent_task_id: str) -> bool:
    """
    Utility function to clean up invalid tokens for a specific user.
    This can be called when tokens are known to be invalid.
    """
    try:
        auth_handler = GoogleAuthHandler(user_id, org_id, agent_task_id)
        return auth_handler._clear_invalid_tokens()
    except Exception as e:
        logger.error(f"Failed to cleanup invalid tokens for user {user_id}: {e}")
        return False


def get_auth_status_for_user(user_id: str, org_id: str, agent_task_id: str) -> dict:
    """
    Get authentication status for a user.
    Returns information about token validity and any issues.
    """
    try:
        auth_handler = GoogleAuthHandler(user_id, org_id, agent_task_id)
        # Clear cache to ensure fresh data from database
        auth_handler._tokens = None
        tokens = auth_handler.get_latest_tokens()
        
        if not tokens:
            logger.debug(f"No tokens found for user {user_id}, agent_task_id {agent_task_id}")
            return {
                "has_tokens": False,
                "has_valid_tokens": False,
                "status": "no_tokens",
                "message": "No tokens found for user"
            }
        
        has_valid = auth_handler.has_valid_tokens()
        
        logger.debug(f"Auth status for user {user_id}: has_tokens=True, has_valid={has_valid}, expires_in={tokens.expires_in}")
        
        return {
            "has_tokens": True,
            "has_valid_tokens": has_valid,
            "has_access_token": bool(tokens.access_token),
            "has_refresh_token": bool(tokens.refresh_token),
            "expires_in": tokens.expires_in,
            "status": "valid" if has_valid else "invalid",
            "message": "Tokens are valid" if has_valid else "Tokens are invalid or expired"
        }
        
    except Exception as e:
        logger.error(f"Failed to get auth status for user {user_id}: {e}", exc_info=True)
        return {
            "has_tokens": False,
            "has_valid_tokens": False,
            "status": "error",
            "message": f"Error checking auth status: {str(e)}"
        }