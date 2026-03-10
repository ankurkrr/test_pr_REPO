"""
Simple Token Refresh Script
============================

This script demonstrates how to get a new access token using a refresh token.

Usage:
    python scripts/refresh_token_simple.py [user_id]

If user_id is not provided, it will refresh tokens for all active users.
"""

import os
import sys
import requests
from datetime import datetime, timedelta

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.database_service_new import get_database_service


def get_new_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """
    Get a new access token from Google using a refresh token.
    
    Args:
        refresh_token: The refresh token from database
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
    
    Returns:
        Dict with 'success', 'access_token', 'expires_in', and 'error' (if failed)
    """
    token_url = "https://oauth2.googleapis.com/token"
    
    # Prepare the request payload
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret
    }
    
    print(f"🔄 Calling Google token endpoint...")
    print(f"   URL: {token_url}")
    print(f"   Refresh token (first 20 chars): {refresh_token[:20]}...")
    
    try:
        # Make POST request to Google
        response = requests.post(token_url, data=payload, timeout=30)
        response.raise_for_status()  # Raise error for 4xx/5xx responses
        
        # Parse response
        result = response.json()
        new_access_token = result.get('access_token')
        expires_in = result.get('expires_in', 3600)  # Default 1 hour
        
        if new_access_token:
            print(f"✅ Success! New access token obtained")
            print(f"   Access token (first 20 chars): {new_access_token[:20]}...")
            print(f"   Expires in: {expires_in} seconds ({expires_in // 60} minutes)")
            print(f"   Expires at: {datetime.now() + timedelta(seconds=expires_in)}")
            
            return {
                'success': True,
                'access_token': new_access_token,
                'expires_in': expires_in,
                'expires_at': datetime.now() + timedelta(seconds=expires_in),
                'refresh_token': result.get('refresh_token'),  # Google may return new one
                'token_type': result.get('token_type', 'Bearer'),
                'scope': result.get('scope', '')
            }
        else:
            print(f"❌ Error: No access_token in response")
            print(f"   Response: {result}")
            return {'success': False, 'error': 'No access_token in response', 'response': result}
            
    except requests.exceptions.RequestException as e:
        print(f"❌ HTTP Error: {e}")
        if hasattr(e, 'response') and e.response:
            try:
                error_response = e.response.json()
                error_type = error_response.get('error', 'unknown')
                error_description = error_response.get('error_description', 'No description')
                print(f"   Google Error: {error_type}")
                print(f"   Description: {error_description}")
                
                if error_type == 'invalid_grant':
                    print(f"   ⚠️  This means the refresh token is invalid/revoked")
                    print(f"   Solution: User needs to re-authenticate")
                elif error_type == 'invalid_client':
                    print(f"   ⚠️  This means client_id/client_secret are wrong")
                    print(f"   Solution: Check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
            except:
                print(f"   Raw Response: {e.response.text}")
        
        return {'success': False, 'error': str(e)}
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return {'success': False, 'error': str(e)}


def refresh_user_token(user_id: str = None):
    """
    Refresh access token for a specific user or all active users.
    
    Args:
        user_id: Optional user ID. If None, refreshes all active users.
    """
    # Get OAuth credentials from environment
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Error: Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET")
        print("   Please set these in your .env file")
        return
    
    print(f"✅ OAuth credentials loaded")
    print(f"   Client ID (first 10 chars): {client_id[:10]}...")
    
    # Get database service
    db_service = get_database_service()
    
    # Build query to get refresh tokens
    if user_id:
        query = """
        SELECT DISTINCT 
            ot.user_id, 
            ot.org_id, 
            ot.agent_task_id,
            COALESCE(ot.refresh_token, uat.google_refresh_token) as refresh_token,
            ot.access_token
        FROM oauth_tokens ot
        INNER JOIN user_agent_task uat ON uat.agent_task_id = ot.agent_task_id
        WHERE ot.provider = 'google'
          AND ot.user_id = :user_id
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) IS NOT NULL 
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) <> ''
          AND uat.status = 1 
          AND uat.ready_to_use = 1
        """
        params = {"user_id": user_id}
    else:
        query = """
        SELECT DISTINCT 
            ot.user_id, 
            ot.org_id, 
            ot.agent_task_id,
            COALESCE(ot.refresh_token, uat.google_refresh_token) as refresh_token,
            ot.access_token
        FROM oauth_tokens ot
        INNER JOIN user_agent_task uat ON uat.agent_task_id = ot.agent_task_id
        WHERE ot.provider = 'google'
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) IS NOT NULL 
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) <> ''
          AND uat.status = 1 
          AND uat.ready_to_use = 1
        """
        params = {}
    
    rows = db_service.execute_query(query, params)
    
    if not rows:
        print(f"⚠️  No active users found with refresh tokens")
        if user_id:
            print(f"   User ID: {user_id}")
        return
    
    print(f"\n📋 Found {len(rows)} user(s) to refresh tokens for\n")
    print("=" * 80)
    
    # Process each user
    for row in rows:
        user_id = row[0]
        org_id = row[1]
        agent_task_id = row[2]
        refresh_token = row[3]
        current_access_token = row[4]
        
        print(f"\n👤 User: {user_id}")
        print(f"   Org: {org_id}")
        print(f"   Agent Task: {agent_task_id}")
        print(f"   Current token (first 20 chars): {current_access_token[:20] if current_access_token else 'None'}...")
        
        # Get new access token
        result = get_new_access_token(refresh_token, client_id, client_secret)
        
        if result.get('success'):
            new_access_token = result['access_token']
            new_expires_at = result['expires_at']
            new_refresh_token = result.get('refresh_token')
            
            # Update oauth_tokens table
            print(f"\n📝 Updating database...")
            oauth_params = {
                "access_token": new_access_token,
                "expires_at": new_expires_at,
                "user_id": user_id,
                "agent_task_id": agent_task_id
            }
            
            if new_refresh_token:
                oauth_query = """
                UPDATE oauth_tokens 
                SET access_token = :access_token,
                    refresh_token = :refresh_token,
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id AND agent_task_id = :agent_task_id AND provider = 'google'
                """
                oauth_params["refresh_token"] = new_refresh_token
            else:
                oauth_query = """
                UPDATE oauth_tokens 
                SET access_token = :access_token,
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id AND agent_task_id = :agent_task_id AND provider = 'google'
                """
            
            db_service.execute_query(oauth_query, oauth_params)
            print(f"   ✅ Updated oauth_tokens table")
            
            # Update user_agent_task table
            uat_params = {
                "access_token": new_access_token,
                "user_id": user_id,
                "org_id": org_id,
                "agent_task_id": agent_task_id
            }
            
            if new_refresh_token:
                uat_query = """
                UPDATE user_agent_task 
                SET google_access_token = :access_token,
                    google_refresh_token = :refresh_token,
                    updated = NOW()
                WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
                """
                uat_params["refresh_token"] = new_refresh_token
            else:
                uat_query = """
                UPDATE user_agent_task 
                SET google_access_token = :access_token,
                    updated = NOW()
                WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
                """
            
            db_service.execute_query(uat_query, uat_params)
            print(f"   ✅ Updated user_agent_task table")
            print(f"\n✅ Token refresh completed successfully for user {user_id}")
        else:
            print(f"\n❌ Token refresh failed for user {user_id}")
            print(f"   Error: {result.get('error', 'Unknown error')}")
        
        print("=" * 80)
    
    print(f"\n✅ Token refresh process completed")


if __name__ == "__main__":
    # Load environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv()
    
    # Get user_id from command line argument (optional)
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    if user_id:
        print(f"🔄 Refreshing token for user: {user_id}\n")
    else:
        print(f"🔄 Refreshing tokens for all active users\n")
    
    try:
        refresh_user_token(user_id)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

