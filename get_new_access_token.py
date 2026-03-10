"""
Simple Example: How to Get New Access Token
===========================================

This is the simplest possible example showing how to get a new access token
from Google using a refresh token.

No database operations - just the core API call.
"""

import os
import sys
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.database_service_new import get_database_service

# Load environment variables
load_dotenv()


def get_new_access_token(refresh_token: str) -> dict:
    """
    Get a new access token from Google using a refresh token.
    
    This is the core function that does the actual token refresh.
    
    Args:
        refresh_token: The refresh token (from database or user)
    
    Returns:
        Dict with:
            - success: bool
            - access_token: str (if successful)
            - expires_in: int (seconds until expiry)
            - expires_at: datetime (when token expires)
            - error: str (if failed)
    """
    # Step 1: Get OAuth credentials from environment
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return {
            'success': False,
            'error': 'Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in environment'
        }
    
    # Step 2: Prepare the request
    token_url = "https://oauth2.googleapis.com/token"
    
    payload = {
        'grant_type': 'refresh_token',      # Tells Google we want to refresh
        'refresh_token': refresh_token,      # The refresh token (from parameter)
        'client_id': client_id,             # Your OAuth client ID (from env)
        'client_secret': client_secret      # Your OAuth client secret (from env)
    }
    
    print("=" * 60)
    print("STEP 1: Preparing Request")
    print("=" * 60)
    print(f"URL: {token_url}")
    print(f"Grant Type: refresh_token")
    print(f"Client ID: {client_id[:10]}...")
    print(f"Refresh Token: {refresh_token[:20]}...")
    print()
    
    # Step 3: Make the POST request to Google
    print("STEP 2: Calling Google Token Endpoint")
    print("=" * 60)
    try:
        response = requests.post(token_url, data=payload, timeout=30)
        response.raise_for_status()  # Raise error for 4xx/5xx responses
        
        # Step 4: Parse the response
        result = response.json()
        
        print("✅ Success! Google returned new token")
        print()
        
        # Extract the new access token
        new_access_token = result.get('access_token')
        expires_in = result.get('expires_in', 3600)  # Default 1 hour
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        if new_access_token:
            print("STEP 3: Response from Google")
            print("=" * 60)
            print(f"✅ New Access Token: {new_access_token[:30]}...")
            print(f"✅ Expires In: {expires_in} seconds ({expires_in // 60} minutes)")
            print(f"✅ Expires At: {expires_at}")
            print(f"✅ Token Type: {result.get('token_type', 'Bearer')}")
            print(f"✅ Scope: {result.get('scope', 'N/A')}")
            
            # Google may return a new refresh token (optional)
            if result.get('refresh_token'):
                print(f"✅ New Refresh Token: {result.get('refresh_token')[:30]}...")
            
            print()
            print("=" * 60)
            print("✅ SUCCESS! New access token obtained")
            print("=" * 60)
            
            return {
                'success': True,
                'access_token': new_access_token,
                'expires_in': expires_in,
                'expires_at': expires_at,
                'refresh_token': result.get('refresh_token'),  # Optional
                'token_type': result.get('token_type', 'Bearer'),
                'scope': result.get('scope', '')
            }
        else:
            print("❌ Error: No access_token in response")
            print(f"Response: {result}")
            return {
                'success': False,
                'error': 'No access_token in response',
                'response': result
            }
            
    except requests.exceptions.RequestException as e:
        print("❌ HTTP Error occurred")
        print()
        
        if hasattr(e, 'response') and e.response:
            try:
                error_response = e.response.json()
                error_type = error_response.get('error', 'unknown')
                error_description = error_response.get('error_description', 'No description')
                
                print("STEP 3: Error Response from Google")
                print("=" * 60)
                print(f"❌ Error Type: {error_type}")
                print(f"❌ Description: {error_description}")
                print()
                
                if error_type == 'invalid_grant':
                    print("⚠️  This usually means:")
                    print("   - Refresh token has been revoked by user")
                    print("   - Refresh token is expired or invalid")
                    print("   - User needs to re-authenticate")
                elif error_type == 'invalid_client':
                    print("⚠️  This usually means:")
                    print("   - GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET is wrong")
                    print("   - OAuth client credentials don't match the token")
                else:
                    print(f"⚠️  Unknown error type: {error_type}")
                    
            except:
                print(f"Raw Response: {e.response.text}")
        else:
            print(f"Error: {e}")
        
        print()
        print("=" * 60)
        print("❌ FAILED to get new access token")
        print("=" * 60)
        
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def get_refresh_token_from_database(user_id: str = None) -> dict:
    """
    Get refresh token from database tables.
    
    Args:
        user_id: Optional user ID. If None, gets first active user's token.
    
    Returns:
        Dict with 'success', 'refresh_token', 'user_id', 'org_id', 'agent_task_id'
    """
    try:
        db_service = get_database_service()
        
        if user_id:
            # Get refresh token for specific user
            query = """
            SELECT DISTINCT 
                ot.user_id, 
                ot.org_id, 
                ot.agent_task_id,
                COALESCE(ot.refresh_token, uat.google_refresh_token) as refresh_token
            FROM oauth_tokens ot
            INNER JOIN user_agent_task uat ON uat.agent_task_id = ot.agent_task_id
            WHERE ot.provider = 'google'
              AND ot.user_id = :user_id
              AND COALESCE(ot.refresh_token, uat.google_refresh_token) IS NOT NULL 
              AND COALESCE(ot.refresh_token, uat.google_refresh_token) <> ''
              AND uat.status = 1 
              AND uat.ready_to_use = 1
            LIMIT 1
            """
            params = {"user_id": user_id}
        else:
            # Get refresh token for first active user
            query = """
            SELECT DISTINCT 
                ot.user_id, 
                ot.org_id, 
                ot.agent_task_id,
                COALESCE(ot.refresh_token, uat.google_refresh_token) as refresh_token
            FROM oauth_tokens ot
            INNER JOIN user_agent_task uat ON uat.agent_task_id = ot.agent_task_id
            WHERE ot.provider = 'google'
              AND COALESCE(ot.refresh_token, uat.google_refresh_token) IS NOT NULL 
              AND COALESCE(ot.refresh_token, uat.google_refresh_token) <> ''
              AND uat.status = 1 
              AND uat.ready_to_use = 1
            ORDER BY ot.updated_at DESC
            LIMIT 1
            """
            params = {}
        
        rows = db_service.execute_query(query, params)
        
        if not rows:
            return {
                'success': False,
                'error': f'No active user found with refresh token' + (f' for user_id: {user_id}' if user_id else '')
            }
        
        row = rows[0]
        return {
            'success': True,
            'refresh_token': row[3],
            'user_id': row[0],
            'org_id': row[1],
            'agent_task_id': row[2]
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Database error: {str(e)}'
        }


# Example usage
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("SIMPLE TOKEN REFRESH EXAMPLE")
    print("=" * 60)
    print()
    
    # Get refresh token from command line argument, environment variable, or database
    refresh_token = None
    user_info = {}
    
    if len(sys.argv) > 1:
        # Use refresh token from command line argument
        refresh_token = sys.argv[1]
        print(f"✅ Using refresh token from command line argument")
    else:
        # Try to get from environment variable
        refresh_token = os.getenv("REFRESH_TOKEN") or os.getenv("EXAMPLE_REFRESH_TOKEN", "")
        
        if refresh_token:
            print(f"✅ Using refresh token from environment variable")
        else:
            # Get from database
            print(f"🔄 Getting refresh token from database...")
            user_id_arg = os.getenv("USER_ID")  # Optional: specific user_id from env
            db_result = get_refresh_token_from_database(user_id_arg)
            
            if db_result.get('success'):
                refresh_token = db_result['refresh_token']
                user_info = {
                    'user_id': db_result['user_id'],
                    'org_id': db_result['org_id'],
                    'agent_task_id': db_result['agent_task_id']
                }
                print(f"✅ Found refresh token in database")
                print(f"   User ID: {user_info['user_id']}")
                print(f"   Org ID: {user_info['org_id']}")
                print(f"   Agent Task ID: {user_info['agent_task_id']}")
            else:
                print(f"❌ {db_result.get('error', 'Failed to get refresh token from database')}")
                print()
                print("Usage options:")
                print("  1. Pass as argument:")
                print("     python scripts/get_new_access_token.py <refresh_token>")
                print()
                print("  2. Set environment variable:")
                print("     export REFRESH_TOKEN='your_refresh_token_here'")
                print("     python scripts/get_new_access_token.py")
                print()
                print("  3. Get from database (requires active user with refresh token):")
                print("     python scripts/get_new_access_token.py")
                print("     OR specify user_id:")
                print("     export USER_ID='user_id_here'")
                print("     python scripts/get_new_access_token.py")
                print()
                print("=" * 60)
                sys.exit(1)
    
    print(f"   Refresh token (first 20 chars): {refresh_token[:20]}...")
    print()
    
    # Call the function
    result = get_new_access_token(refresh_token)
    
    # Print summary
    print()
    print("=" * 60)
    if result.get('success'):
        print("✅ SUMMARY: Token refresh successful!")
        print("=" * 60)
        if user_info:
            print(f"   User ID: {user_info.get('user_id', 'N/A')}")
            print(f"   Org ID: {user_info.get('org_id', 'N/A')}")
            print(f"   Agent Task ID: {user_info.get('agent_task_id', 'N/A')}")
            print()
        print(f"   New Access Token: {result['access_token'][:50]}...")
        print(f"   Expires In: {result['expires_in']} seconds ({result['expires_in'] // 60} minutes)")
        print(f"   Valid Until: {result['expires_at']}")
        print(f"   Token Type: {result.get('token_type', 'Bearer')}")
        if result.get('refresh_token'):
            print(f"   New Refresh Token: {result['refresh_token'][:50]}...")
        print()
        print("✅ You can now use this access token for Google API calls!")
        print()
        print("💡 To update the database with this new token, use:")
        print("   python scripts/refresh_token_simple.py")
    else:
        print("❌ SUMMARY: Token refresh failed!")
        print("=" * 60)
        print(f"   Error: {result.get('error', 'Unknown error')}")
        if 'response' in result:
            print(f"   Response: {result.get('response')}")
    print("=" * 60)

