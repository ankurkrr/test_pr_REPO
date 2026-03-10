"""
Google API Client using GoogleAuthHandler

Provides Google API services (Calendar, Drive, Sheets) using tokens from GoogleAuthHandler.
"""

import logging
from typing import Optional, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class GoogleAPIClient:
    """
    Google API client that uses GoogleAuthHandler for authentication.
    """

    def __init__(self, auth_handler):
        """
        Initialize Google API client.

        Args:
            auth_handler: GoogleAuthHandler instance with stored tokens
        """
        self.auth_handler = auth_handler
        self._calendar_service = None
        self._drive_service = None
        self._sheets_service = None

    def _get_credentials(self) -> Optional[Credentials]:
        """Get Google credentials from auth handler with automatic refresh."""
        if not self.auth_handler.has_valid_tokens():
            logger.warning("No valid tokens available in auth handler")
            return None

        tokens = self.auth_handler.get_latest_tokens()
        if not tokens:
            logger.warning("Failed to get tokens from auth handler")
            return None

        import os
        from datetime import datetime, timedelta
        
        # Get client credentials from environment
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("Google client credentials not configured")
            return None

        # Get scopes from environment variable
        scopes_str = os.getenv("GOOGLE_OAUTH_SCOPES", "")
        if scopes_str:
            scopes = [scope.strip() for scope in scopes_str.split(",")]
        else:
            # Fallback to default scopes
            scopes = [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile"
            ]
        
        # Check if token is expired or will expire soon (within 5 minutes)
        is_token_expired = self._is_token_expired(tokens)
        
        if is_token_expired:
            logger.info("Access token expired or expiring soon, attempting refresh...")
            try:
                # Try to refresh the token (using sync version)
                refresh_result = self.auth_handler.refresh_access_token()
                if refresh_result:
                    logger.info("Successfully refreshed access token")
                    # Get the updated tokens
                    tokens = self.auth_handler.get_latest_tokens()
                    if not tokens:
                        logger.error("Failed to get refreshed tokens")
                        return None
                else:
                    logger.error("Failed to refresh access token")
                    return None
            except Exception as e:
                logger.error(f"Error during token refresh: {e}")
                return None
        
        # Use full OAuth2 credentials with refresh capability
        return Credentials(
            token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes
        )
    
    def _is_token_expired(self, tokens) -> bool:
        """Check if the token is expired or will expire within 5 minutes."""
        try:
            # Check if we have expiry information
            if hasattr(tokens, 'expires_in') and tokens.expires_in:
                # Calculate expiry time
                from datetime import datetime, timedelta
                expiry_time = datetime.now() + timedelta(seconds=tokens.expires_in)
                # Consider token expired if it expires within 5 minutes
                return expiry_time <= datetime.now() + timedelta(minutes=5)
            
            # If no expiry info, assume token might be expired after 1 hour
            # This is a conservative approach
            return True
            
        except Exception as e:
            logger.warning(f"Error checking token expiry: {e}")
            # If we can't determine expiry, assume it's expired to be safe
            return True

    def get_calendar_service(self):
        """Get Google Calendar service."""
        if not self._calendar_service:
            creds = self._get_credentials()
            if not creds:
                logger.error("No valid credentials available for Calendar service - token refresh may have failed")
                raise ValueError("No valid credentials available for Calendar service")

            self._calendar_service = build('calendar', 'v3', credentials=creds)
        return self._calendar_service

    def get_drive_service(self):
        """Get Google Drive service."""
        if not self._drive_service:
            creds = self._get_credentials()
            if not creds:
                logger.error("No valid credentials available for Drive service - token refresh may have failed")
                raise ValueError("No valid credentials available for Drive service")

            self._drive_service = build('drive', 'v3', credentials=creds)
        return self._drive_service

    def get_sheets_service(self):
        """Get Google Sheets service."""
        if not self._sheets_service:
            creds = self._get_credentials()
            if not creds:
                logger.error("No valid credentials available for Sheets service - token refresh may have failed")
                raise ValueError("No valid credentials available for Sheets service")

            self._sheets_service = build('sheets', 'v4', credentials=creds)
        return self._sheets_service