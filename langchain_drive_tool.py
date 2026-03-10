"""
LangchainDriveTool - Advanced transcript matching and downloading with calendar event integration.
Consolidated canonical implementation with Redis caching and parallel processing optimizations.
"""

import json
import logging
import re
import redis
from datetime import datetime, timedelta
import uuid
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field

from src.auth.google_auth_handler import GoogleAuthHandler
from src.services.google import GoogleDriveService
from src.services.integration.agent_integration_service import AgentIntegrationService, get_agent_integration_service
from src.services.database_service_new import get_database_service

logger = logging.getLogger(__name__)


class DriveToolInput(BaseModel):
    """Input schema for the drive tool."""
    operation: str = Field(
        default="find_and_download_transcripts",
        description="Operation to perform: find_and_download_transcripts, search_recent_documents, match_transcript_to_event, download_transcript_content"
    )
    skip_already_processed: Optional[bool] = Field(
        default=True,
        description="If true, skip files that were already summarized/processed before"
    )
    calendar_events: Optional[Any] = Field(
        default=None,
        description="Calendar events data - can be a list of events or calendar tool response object"
    )
    query: Optional[str] = Field(
        default="",
        description="Search query for recent documents"
    )
    time_window_mins: Optional[int] = Field(
        default=60,
        description="Time window in minutes for searching recent documents"
    )
    event_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Event data for transcript matching"
    )
    file_id: Optional[str] = Field(
        default=None,
        description="File ID for downloading transcript content"
    )


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    attendees: List[Dict[str, str]]
    organizer: Optional[str]
    description: Optional[str]
    location: Optional[str]
    meeting_link: Optional[str]


@dataclass
class TranscriptMatch:
    file_id: str
    file_name: str
    file_path: str
    mime_type: str
    size: int
    last_modified: datetime
    content: Optional[str]
    match_score: float
    match_reason: str
    matched_event_id: str
    matched_event_title: str
    confidence: str  # high, medium, low


class LangchainDriveTool(BaseTool):
    name: str = "drive_tool"
    description: str = """
    Advanced Google Drive tool for finding and downloading meeting transcripts.
    """
    category: str = "file_operations"
    args_schema: type[BaseModel] = DriveToolInput

    # Dependencies
    auth: Optional[GoogleAuthHandler] = None
    drive_service: Optional[GoogleDriveService] = None
    agent_integration: Optional[Any] = None
    database_service: Optional[Any] = None
    redis_client: Optional[redis.Redis] = None

    # Context
    agent_id: str = "enhanced_meeting_agent"
    user_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_agent_task_id: Optional[str] = None

    def __init__(self, auth: GoogleAuthHandler, agent_id: str = "enhanced_meeting_agent",
                 user_id: Optional[str] = None, workflow_id: Optional[str] = None,
                 user_agent_task_id: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.auth = auth
        self.drive_service = GoogleDriveService(auth)
        self.agent_integration = get_agent_integration_service()
        self.database_service = get_database_service()
        
        # Set user and task identifiers for processed file tracking
        self.user_id = user_id
        self.user_agent_task_id = user_agent_task_id
        self.agent_id = agent_id
        self.workflow_id = workflow_id
        
        # Initialize Redis client with environment configuration
        try:
            import os
            from ..configuration.config import REDIS_URL
            redis_url = REDIS_URL
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established successfully")
        except Exception as e:
            # Fail fast if REDIS_URL was explicitly set but connection fails; otherwise fallback to memory
            explicit_url = os.getenv("REDIS_URL")
            if explicit_url:
                raise RuntimeError(f"Redis connection failed for REDIS_URL={explicit_url}: {e}")
            logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
            self.redis_client = None
            self._memory_cache = {}
            self._memory_processed: set[str] = set()

    def _get_processed_set_key(self) -> str:
        """Key for the Redis set tracking processed transcript file IDs."""

        # Use both user_id and agent_task_id to ensure proper isolation
        if self.user_id and self.user_agent_task_id:
            return f"processed_transcripts:{self.user_id}:{self.user_agent_task_id}"
        elif self.user_id:
            return f"processed_transcripts:{self.user_id}"
        elif self.user_agent_task_id:
            return f"processed_transcripts:{self.user_agent_task_id}"
        else:
            return "processed_transcripts:global"

    def _is_file_processed(self, file_id: str) -> bool:
        try:
            if self.redis_client:
                return bool(self.redis_client.sismember(self._get_processed_set_key(), file_id))
            return file_id in getattr(self, "_memory_processed", set())
        except Exception as e:
            logger.warning(f"Error checking if file {file_id} is processed in cache: {e}")
            return False  # Assume not processed if check fails

    def _mark_file_processed(self, file_id: str) -> None:
        try:
            if self.redis_client:
                self.redis_client.sadd(self._get_processed_set_key(), file_id)
            else:
                if not hasattr(self, "_memory_processed"):
                    self._memory_processed = set()
                self._memory_processed.add(file_id)
        except Exception as e:
            logger.warning(f"Failed to mark file {file_id} as processed in cache: {e}")
            # Continue execution - cache failure is not critical

    # -----------------------------
    # Database processed tracking
    # -----------------------------
    def _db_table_names_for_processed(self) -> List[str]:
        """Preferred table names in order of use for processed tracking."""
        return [
            "processed_document_history"
        ]

    def _is_file_processed_db(self, file_id: str) -> bool:
        try:
            if not self.database_service or not file_id:
                return False

            user_id = getattr(self, "user_id", None)
            agent_task_id = getattr(self, "user_agent_task_id", None)
            if not user_id or not agent_task_id:
                # agent_task_id is mandatory for processed checks
                return False

            for table in self._db_table_names_for_processed():
                try:
                    # Try existence check by file id (and user if available)
                    rows = self.database_service.execute_query(
                        f"""
                        SELECT 1 FROM {table}
                        WHERE drive_file_id = :file_id AND user_id = :user_id AND agent_task_id = :agent_task_id
                        LIMIT 1
                        """,
                        {"file_id": file_id, "user_id": user_id, "agent_task_id": agent_task_id},
                    )
                    if rows:
                        return True
                except Exception as table_error:
                    logger.warning(f"Error checking processed status in {table} for file {file_id}: {table_error}")
                    # Try next candidate table
                    continue
            return False
        except Exception as e:
            logger.error(f"Error in _is_file_processed_db for file {file_id}: {e}")
            return False

    def _mark_file_processed_db(self, file_id: str) -> None:
        try:
            if not self.database_service or not file_id:
                return

            import uuid as _uuid
            from datetime import datetime as _dt

            user_id = getattr(self, "user_id", None)
            agent_task_id = getattr(self, "user_agent_task_id", None)
            if not user_id or not agent_task_id:
                # agent_task_id is mandatory to mark processed
                return
            
            # Validate that agent_task_id exists in user_agent_task table
            try:
                validation_query = """
                SELECT 1 FROM user_agent_task 
                WHERE agent_task_id = :agent_task_id 
                LIMIT 1
                """
                validation_result = self.database_service.execute_query(validation_query, {"agent_task_id": agent_task_id})
                if not validation_result:
                    logger.warning(f"Agent task ID {agent_task_id} does not exist in user_agent_task table. Attempting to create it...")
                    
                    # Try to create the missing user_agent_task record
                    try:
                        from src.services.integration.agent_integration_service import get_agent_integration_service
                        agent_service = get_agent_integration_service()
                        created_task_id = agent_service.create_user_agent_task(
                            user_id=user_id,
                            task_name=f"Meeting Intelligence Task - {agent_task_id}",
                            description=f"Auto-created task for file processing: {file_id}"
                        )
                        if created_task_id == agent_task_id:
                            logger.info(f"Successfully created missing user_agent_task record for {agent_task_id}")
                        else:
                            logger.error(f"Created task ID {created_task_id} doesn't match expected {agent_task_id}")
                            return
                    except Exception as create_error:
                        logger.error(f"Failed to create missing user_agent_task record: {create_error}")
                        return
            except Exception as validation_error:
                logger.error(f"Failed to validate agent_task_id {agent_task_id}: {validation_error}")
                return
            
            now = _dt.now()

            for table in self._db_table_names_for_processed():
                try:
                    # Attempt an upsert-like behavior: insert ignore if exists
                    # Works across engines by selecting first, then inserting if not present
                    exists = self._is_file_processed_db(file_id)
                    if exists:
                        logger.info(f"File {file_id} already marked as processed in {table}, skipping")
                        return

                    # Insert row
                    self.database_service.execute_query(
                        f"""
                        INSERT INTO {table}
                        (user_id, drive_file_id, agent_task_id, last_processed_at)
                        VALUES (:user_id, :drive_file_id, :agent_task_id, :last_processed_at)
                        """,
                        {
                            "user_id": user_id,
                            "drive_file_id": file_id,
                            "agent_task_id": agent_task_id,
                            "last_processed_at": now,
                        },
                    )
                    logger.info(f"[SUCCESS] Successfully marked file {file_id} as processed in {table} for user {user_id}, agent_task {agent_task_id}")
                    return
                except Exception as table_error:
                    logger.error(f"[ERROR] Failed to insert into {table} for file {file_id}: {table_error}")
                    # Try next table name
                    continue
        except Exception as e:
            logger.error(f"[ERROR] Error in _mark_file_processed_db for file {file_id}: {e}")
            return

    def set_credentials(self, access_token: str, refresh_token: Optional[str] = None) -> bool:
        """
        Set Google OAuth credentials for drive access from decrypted tokens

        Args:
            access_token: Decrypted Google access token
            refresh_token: Decrypted Google refresh token (optional)

        Returns:
            True if credentials set successfully, False otherwise
        """
        try:
            # Update the auth handler with new credentials
            if hasattr(self.auth, 'set_credentials'):
                return self.auth.set_credentials(access_token, refresh_token)
            else:
                # If auth handler doesn't have set_credentials, update the drive service directly
                self.drive_service = GoogleDriveService(self.auth)
                return True
        except Exception as e:
            logger.error(f"Failed to set drive credentials: {e}")
            return False

    def _get_cache_key(self, file_id: str) -> str:
        """Generate cache key for transcript content."""
        # Use both user_id and agent_task_id for proper isolation
        if self.user_id and self.user_agent_task_id:
            return f"transcript:{self.user_id}:{self.user_agent_task_id}:{file_id}"
        elif self.user_agent_task_id:
            return f"transcript:{self.user_agent_task_id}:{file_id}"
        else:
            return f"transcript:global:{file_id}"

    def _get_full_transcript_cache_key(self) -> str:
        """Generate cache key for full transcript content."""
        # Use both user_id and agent_task_id for proper isolation
        if self.user_id and self.user_agent_task_id:
            return f"full_transcript:{self.user_id}:{self.user_agent_task_id}"
        elif self.user_agent_task_id:
            return f"full_transcript:{self.user_agent_task_id}"
        else:
            return "full_transcript:global"

    def _cache_transcript_content(self, file_id: str, content: str, ttl: int = 3600) -> bool:
        """Cache transcript content with TTL."""
        try:
            cache_key = self._get_cache_key(file_id)
            if self.redis_client:
                self.redis_client.setex(cache_key, ttl, content)
                logger.info(f"Cached transcript content for {file_id} with TTL {ttl}s")
                return True
            else:
                # Fallback to memory cache
                self._memory_cache[cache_key] = {
                    'content': content,
                    'expires': datetime.now() + timedelta(seconds=ttl)
                }
                logger.info(f"Cached transcript content in memory for {file_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to cache transcript content: {e}")
            return False

    def _get_cached_transcript_content(self, file_id: str) -> Optional[str]:
        """Retrieve cached transcript content."""
        try:
            cache_key = self._get_cache_key(file_id)
            if self.redis_client:
                content = self.redis_client.get(cache_key)
                if content:
                    logger.info(f"Retrieved cached transcript content for {file_id}")
                    return content
            else:
                # Check memory cache
                if cache_key in self._memory_cache:
                    cache_entry = self._memory_cache[cache_key]
                    if datetime.now() < cache_entry['expires']:
                        logger.info(f"Retrieved cached transcript content from memory for {file_id}")
                        return cache_entry['content']
                    else:
                        # Expired, remove from cache
                        del self._memory_cache[cache_key]
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve cached transcript content: {e}")
            return None

    def _cache_full_transcript_content(self, content: str, ttl: int = 1800) -> bool:
        """Cache full transcript content for summarizer tool."""
        try:
            cache_key = self._get_full_transcript_cache_key()
            if self.redis_client:
                self.redis_client.setex(cache_key, ttl, content)
                logger.info(f"Cached full transcript content with TTL {ttl}s")
                return True
            else:
                # Fallback to memory cache
                self._memory_cache[cache_key] = {
                    'content': content,
                    'expires': datetime.now() + timedelta(seconds=ttl)
                }
                logger.info(f"Cached full transcript content in memory")
                return True
        except Exception as e:
            logger.error(f"Failed to cache full transcript content: {e}")
            return False

    def _get_cached_full_transcript_content(self) -> Optional[str]:
        """Retrieve cached full transcript content."""
        try:
            cache_key = self._get_full_transcript_cache_key()
            if self.redis_client:
                content = self.redis_client.get(cache_key)
                if content:
                    logger.info(f"Retrieved cached full transcript content")
                    return content
            else:
                # Check memory cache
                if cache_key in self._memory_cache:
                    cache_entry = self._memory_cache[cache_key]
                    if datetime.now() < cache_entry['expires']:
                        logger.info(f"Retrieved cached full transcript content from memory")
                        return cache_entry['content']
                    else:
                        # Expired, remove from cache
                        del self._memory_cache[cache_key]
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve cached full transcript content: {e}")
            return None

    def _search_files_sequential(self, queries: List[str], max_results: int = 50) -> List[Dict[str, Any]]:
        """Search files sequentially to prevent segmentation faults, with result caps."""
        try:
            all_files = []
            seen_files = set()
            max_total_files = 200
            
            logger.info(f"Starting sequential search for {len(queries)} queries")
            
            # Process queries one by one to avoid memory issues
            for i, query in enumerate(queries):
                try:
                    logger.info(f"Searching query {i+1}/{len(queries)}: {query[:50]}...")
                    files = self.drive_service.search_files(query, max_results)
                    
                    for file in files:
                        file_id = file.get('id')
                        if file_id and file_id not in seen_files:
                            seen_files.add(file_id)
                            all_files.append(file)
                            if len(all_files) >= max_total_files:
                                logger.info(f"Reached max total files cap: {max_total_files}")
                                return all_files
                    
                    logger.info(f"Query {i+1} completed: {len(files)} files found")
                    
                except Exception as e:
                    logger.error(f"Sequential search failed for query {i+1}: {e}")
                    continue
            
            logger.info(f"Sequential search completed: {len(all_files)} unique files found")
            return all_files
            
        except Exception as e:
            logger.error(f"Sequential search failed: {e}")
            return []

    def _download_file_content_optimized(self, file_id: str, mime_type: str) -> str:
        """Optimized file content download with caching."""
        try:
            # Check cache first
            cached_content = self._get_cached_transcript_content(file_id)
            if cached_content:
                return cached_content
            
            # Download content with memory limits
            if mime_type == "application/vnd.google-apps.document":
                content = self._download_google_doc_content(file_id)
            else:
                content = self.drive_service.download_file_content(file_id)
                if isinstance(content, bytes):
                    try:
                        content = content.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            content = content.decode('latin-1')
                        except UnicodeDecodeError:
                            content = content.decode('utf-8', errors='ignore')
            
            # Limit content size to prevent memory issues (max 1MB)
            max_content_size = 1024 * 1024  # 1MB
            if len(content) > max_content_size:
                content = content[:max_content_size]
                logger.warning(f"Content truncated to {max_content_size} bytes for file {file_id}")
            
            # Cache the content
            self._cache_transcript_content(file_id, content)
            return content
            
        except Exception as e:
            logger.error(f"Error downloading content for file {file_id}: {e}")
            return ""

    def get_cached_transcript_for_summarizer(self) -> Optional[str]:
        """Get cached transcript content for summarizer tool."""
        return self._get_cached_full_transcript_content()

    def clear_cache(self) -> bool:
        """Clear all cached content."""
        try:
            if self.redis_client:
                # Clear all keys for this user_id and agent_task_id combination
                if self.user_id and self.user_agent_task_id:
                    pattern = f"transcript:{self.user_id}:{self.user_agent_task_id}:*"
                elif self.user_agent_task_id:
                    pattern = f"transcript:{self.user_agent_task_id}:*"
                else:
                    pattern = "transcript:global:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                
                # Clear full transcript cache
                full_key = self._get_full_transcript_cache_key()
                self.redis_client.delete(full_key)
                
                logger.info(f"Cleared Redis cache for user_agent_task_id: {self.user_agent_task_id}")
                return True
            else:
                # Clear memory cache
                if self.user_id and self.user_agent_task_id:
                    pattern = f"transcript:{self.user_id}:{self.user_agent_task_id}:"
                elif self.user_agent_task_id:
                    pattern = f"transcript:{self.user_agent_task_id}:"
                else:
                    pattern = "transcript:global:"
                
                keys_to_remove = [k for k in self._memory_cache.keys() if k.startswith(pattern)]
                for key in keys_to_remove:
                    del self._memory_cache[key]
                logger.info(f"Cleared memory cache for user {self.user_id}, agent_task {self.user_agent_task_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False

    def _run(self, query: str = None, run_manager: Optional[CallbackManagerForToolRun] = None, **kwargs) -> str:
        try:
            logger.info(f"Drive Tool executing with query: {query}, kwargs: {kwargs}")
            
            # Handle both JSON string input and keyword arguments
            if query:
                try:
                    input_data = json.loads(query)
                    logger.info(f"Parsed JSON input: {input_data}")
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    logger.info(f"Query content: {query[:200]}...")
                    # If JSON parsing fails, use kwargs instead
                    input_data = kwargs
                    logger.info(f"Falling back to kwargs: {input_data}")
            else:
                # Use keyword arguments as input data
                input_data = kwargs
                logger.info(f"Using kwargs as input: {input_data}")
            
            # Persist last input for downstream decisions (e.g., skip flags)
            try:
                self.last_input_data = input_data
            except Exception:
                pass

            operation = input_data.get("operation", "find_and_download_transcripts")
            logger.info(f"Executing operation: {operation}")
            
            if operation == "find_and_download_transcripts":
                calendar_events = input_data.get("calendar_events", [])
                
                # Handle case where calendar_events is a JSON string (from agent)
                if isinstance(calendar_events, str):
                    try:
                        # Log the JSON string length for debugging
                        logger.info(f"Parsing calendar_events JSON string (length: {len(calendar_events)})")
                        calendar_events = json.loads(calendar_events)
                        logger.info(f"Successfully parsed calendar_events JSON string: {type(calendar_events)}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse calendar_events JSON string: {e}")
                        logger.error(f"JSON string preview: {calendar_events[:200]}...")
                        # Try to extract events from truncated JSON
                        calendar_events = self._extract_events_from_truncated_json(calendar_events)
                        
                        # If still no events, create a fallback event for recent time window
                        if not calendar_events:
                            logger.warning("No events extracted from truncated JSON, creating fallback event")
                            calendar_events = [{
                                "title": "Recent Meeting (Fallback)",
                                "event_id": f"fallback_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                "start_time": (datetime.now() - timedelta(hours=1)).isoformat(),
                                "end_time": datetime.now().isoformat(),
                                "organizer": "unknown",
                                "calendar_id": "primary",
                                "attendees": []
                            }]
                            logger.info(f"Created fallback event: {calendar_events[0]['title']}")
                
                # Handle case where calendar_events is a dictionary (from calendar tool response)
                if isinstance(calendar_events, dict):
                    if "events" in calendar_events:
                        calendar_events = calendar_events["events"]
                        logger.info(f"Extracted {len(calendar_events)} events from calendar tool response")
                    elif "calendar_tool_response" in calendar_events:
                        # Handle nested calendar tool response
                        calendar_tool_response = calendar_events["calendar_tool_response"]
                        if isinstance(calendar_tool_response, dict) and "events" in calendar_tool_response:
                            calendar_events = calendar_tool_response["events"]
                        else:
                            calendar_events = []
                    else:
                        calendar_events = []
                
                # Ensure calendar_events is a list
                if not isinstance(calendar_events, list):
                    calendar_events = []
                
                logger.info(f"Processing {len(calendar_events)} calendar events for transcript matching")
                return self._find_and_download_transcripts(calendar_events)
            elif operation == "search_recent_documents":
                return self._search_recent_documents(input_data.get("query", ""), input_data.get("time_window_mins", 60))
            elif operation == "match_transcript_to_event":
                return self._match_transcript_to_event(input_data.get("event_data"))
            elif operation == "download_transcript_content":
                return self._download_transcript_content(input_data.get("file_id"))
            else:
                return json.dumps({"status": "error", "error": f"Unknown operation: {operation}", "timestamp": datetime.now().isoformat()})
        except Exception as e:
            logger.error(f"Drive Tool error: {e}", exc_info=True)
            return json.dumps({"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()})

    def _search_recent_documents(self, query: str, time_window_mins: int) -> str:
        """
        Search for recent documents in Drive without requiring calendar events.
        This is useful when there are meeting transcripts but no calendar events.
        """
        try:
            logger.info(f"Searching for recent documents with query: '{query}' in last {time_window_mins} minutes")
            
            # Calculate time range - extend search window to catch more documents
            end_time = datetime.now()
            # Search back 3x the time window to catch documents from earlier meetings
            extended_window = max(time_window_mins * 3, 1440)  # At least 24 hours
            start_time = end_time - timedelta(minutes=extended_window)
            
            # Use efficient time-based search queries
            search_queries = [
                f"modifiedTime > '{start_time.isoformat()}Z' and (name contains 'meeting' or name contains 'transcript' or name contains 'notes' or name contains 'summary')",
                f"modifiedTime > '{start_time.isoformat()}Z' and name contains 'Gemini'",
                f"modifiedTime > '{start_time.isoformat()}Z' and name contains 'testing'"
            ]
            
            recent_files = []
            seen_files = set()
            
            for search_query in search_queries:
                try:
                    files = self.drive_service.search_files(search_query)
                    for file in files:
                        file_id = file.get("id")
                        if file_id and file_id not in seen_files:
                            seen_files.add(file_id)
                            recent_files.append(file)
                except Exception as e:
                    logger.warning(f"Search query '{search_query}' failed: {e}")
                    continue
            
            logger.info(f"Found {len(recent_files)} recent documents")
            
            # Convert to transcript format
            transcripts = []
            for file in recent_files:
                transcript = {
                    "file_id": file.get("id"),
                    "file_name": file.get("name", ""),
                    "file_path": file.get("webViewLink", ""),
                    "mime_type": file.get("mimeType", ""),
                    "size": int(file.get("size", 0)),
                    "last_modified": file.get("modifiedTime", ""),
                    "match_score": 1.0,  # High score since it's recent
                    "match_reason": f"Recent document matching query '{query}'",
                    "matched_event_id": "no_calendar_event",
                    "matched_event_title": "Recent Document",
                    "confidence": "high"
                }
                transcripts.append(transcript)
            
            return json.dumps({
                "status": "success",
                "transcripts_found": len(transcripts),
                "transcripts": transcripts,
                "message": f"Found {len(transcripts)} recent documents",
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "minutes_back": time_window_mins
                },
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error searching for recent documents: {e}")
            return json.dumps({
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

    def _extract_events_from_truncated_json(self, truncated_json: str) -> List[Dict[str, Any]]:
        """
        Attempt to extract calendar events from truncated JSON.
        This handles cases where the LLM truncates the JSON parameter.
        """
        try:
            logger.info("Attempting to extract events from truncated JSON")
            logger.info(f"Truncated JSON length: {len(truncated_json)}")
            
            # Look for the events array in the truncated JSON
            events_start = truncated_json.find('"events": [')
            if events_start == -1:
                logger.warning("No events array found in truncated JSON")
                return []
            
            # Find the start of the events array
            array_start = truncated_json.find('[', events_start)
            if array_start == -1:
                logger.warning("No array start found in truncated JSON")
                return []
            
            logger.info(f"Found events array at position {array_start}")
            
            # Extract the content after the opening bracket
            events_content = truncated_json[array_start + 1:]
            logger.info(f"Events content preview: {events_content[:200]}...")
            
            # Try multiple extraction strategies
            events = []
            
            # Strategy 1: Try to find complete event objects
            events.extend(self._extract_complete_events(events_content))
            
            # Strategy 2: If no complete events, try partial extraction
            if not events:
                logger.info("No complete events found, trying partial extraction")
                events.extend(self._extract_partial_events(events_content))
            
            # Strategy 3: If still no events, try regex-based extraction
            if not events:
                logger.info("No partial events found, trying regex extraction")
                events.extend(self._extract_events_with_regex(events_content))
            
            logger.info(f"Extracted {len(events)} events from truncated JSON")
            return events
            
        except Exception as e:
            logger.error(f"Error extracting events from truncated JSON: {e}")
            return []

    def _extract_complete_events(self, events_content: str) -> List[Dict[str, Any]]:
        """Try to extract complete event objects from the events content."""
        events = []
        try:
            brace_count = 0
            in_string = False
            escape_next = False
            event_start = 0
            
            for i, char in enumerate(events_content):
                if escape_next:
                    escape_next = False
                    continue
                
                if char == '\\':
                    escape_next = True
                    continue
                
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                
                if not in_string:
                    if char == '{':
                        if brace_count == 0:
                            event_start = i
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            # Found a complete event object
                            event_json = events_content[event_start:i+1]
                            try:
                                event = json.loads(event_json)
                                logger.info(f"Successfully extracted complete event: {event.get('title', 'Unknown')}")
                                events.append(event)
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse complete event JSON: {e}")
                                continue
        except Exception as e:
            logger.error(f"Error extracting complete events: {e}")
        
        return events

    def _extract_partial_events(self, events_content: str) -> List[Dict[str, Any]]:
        """Try to extract partial event data using pattern matching."""
        events = []
        try:
            # Look for event objects that might be incomplete
            event_pattern = r'\{[^}]*"title"[^}]*'
            matches = re.finditer(event_pattern, events_content, re.DOTALL)
            
            for match in matches:
                partial_json = match.group(0)
                logger.info(f"Found partial event JSON: {partial_json[:100]}...")
                partial_event = self._extract_partial_event_data(partial_json)
                if partial_event:
                    logger.info(f"Successfully extracted partial event: {partial_event.get('title', 'Unknown')}")
                    events.append(partial_event)
        except Exception as e:
            logger.error(f"Error extracting partial events: {e}")
        
        return events

    def _extract_events_with_regex(self, events_content: str) -> List[Dict[str, Any]]:
        """Use regex patterns to extract event data even from heavily truncated JSON."""
        events = []
        try:
            # Extract title
            title_match = re.search(r'"title"\s*:\s*"([^"]*)"', events_content)
            if title_match:
                title = title_match.group(1)
                logger.info(f"Found title via regex: {title}")
                
                # Create a minimal event object
                event = {
                    "title": title,
                    "event_id": f"regex_{hash(title)}",
                    "start_time": (datetime.now() - timedelta(hours=1)).isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "organizer": "unknown",
                    "calendar_id": "primary",
                    "attendees": []
                }
                
                # Try to extract attendees
                attendees_match = re.search(r'"attendees"\s*:\s*\[(.*?)\]', events_content, re.DOTALL)
                if attendees_match:
                    attendees_str = attendees_match.group(1)
                    email_pattern = r'"email"\s*:\s*"([^"]*)"'
                    emails = re.findall(email_pattern, attendees_str)
                    if emails:
                        # Clean and validate email addresses
                        clean_emails = []
                        for email in emails:
                            clean_email = email.strip()
                            if clean_email and '@' in clean_email:
                                clean_emails.append(clean_email)
                        event['attendees'] = clean_emails  # Store as simple string list
                        logger.info(f"Found {len(clean_emails)} clean attendees via regex")
                
                events.append(event)
                logger.info(f"Created regex-based event: {event['title']}")
        except Exception as e:
            logger.error(f"Error extracting events with regex: {e}")
        
        return events

    def _extract_partial_event_data(self, event_data: str) -> Optional[Dict[str, Any]]:
        """
        Extract partial event data from truncated JSON using more robust parsing.
        """
        try:
            logger.info("Extracting partial event data from truncated JSON")
            event = {}
            
            # More robust regex patterns that handle escaped quotes
            patterns = {
                'title': r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"',
                'event_id': r'"event_id"\s*:\s*"((?:[^"\\]|\\.)*)"',
                'start_time': r'"start_time"\s*:\s*"((?:[^"\\]|\\.)*)"',
                'end_time': r'"end_time"\s*:\s*"((?:[^"\\]|\\.)*)"',
                'organizer': r'"organizer"\s*:\s*"((?:[^"\\]|\\.)*)"',
                'calendar_id': r'"calendar_id"\s*:\s*"((?:[^"\\]|\\.)*)"'
            }
            
            # Extract basic fields
            for field, pattern in patterns.items():
                match = re.search(pattern, event_data)
                if match:
                    # Unescape the matched string
                    value = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
                    event[field] = value
                    logger.info(f"Extracted {field}: {value}")
            
            # Extract attendees with better pattern
            attendees_match = re.search(r'"attendees"\s*:\s*\[(.*?)\]', event_data, re.DOTALL)
            if attendees_match:
                attendees_str = attendees_match.group(1)
                # Extract email addresses from attendees
                email_pattern = r'"email"\s*:\s*"((?:[^"\\]|\\.)*)"'
                emails = re.findall(email_pattern, attendees_str)
                if emails:
                    # Clean and validate email addresses
                    clean_emails = []
                    for email in emails:
                        clean_email = email.replace('\\"', '"').replace('\\\\', '\\').strip()
                        if clean_email and '@' in clean_email:
                            clean_emails.append(clean_email)
                    event['attendees'] = clean_emails  # Store as simple string list
                    logger.info(f"Extracted {len(clean_emails)} clean attendees")
            
            # Add default values for missing required fields
            if not event.get('calendar_id'):
                event['calendar_id'] = 'primary'
            if not event.get('attendees'):
                event['attendees'] = []
            
            # Generate event_id if missing but we have title
            if not event.get('event_id') and event.get('title'):
                event['event_id'] = f"event_{hash(event.get('title'))}"
                logger.info(f"Generated event_id: {event['event_id']}")
            
            # Only return if we have at least title
            if event.get('title'):
                logger.info(f"Successfully extracted partial event: {event.get('title')} ({event.get('event_id')})")
                return event
            else:
                logger.warning(f"Insufficient data extracted. Title: {event.get('title')}, Event ID: {event.get('event_id')}")
                return None
            
        except Exception as e:
            logger.error(f"Error extracting partial event data: {e}")
            return None

    def _find_and_download_transcripts(self, calendar_events: List[Dict[str, Any]]) -> str:
        """Optimized transcript finding and downloading with parallel processing and Redis caching."""
        try:
            logger.info(f"Starting optimized transcript search for {len(calendar_events)} events")
            
            if not calendar_events:
                return json.dumps({
                    "status": "success",
                    "transcripts_found": 0,
                    "transcripts": [],
                    "events_processed": 0,
                    "transcript_content": "",
                    "timestamp": datetime.now().isoformat()
                })

            # Parse calendar events
            parsed_events = []
            for event_data in calendar_events:
                event = self._parse_calendar_event(event_data)
                if event:
                    parsed_events.append(event)
            
            if not parsed_events:
                return json.dumps({
                    "status": "success",
                    "transcripts_found": 0,
                    "transcripts": [],
                    "events_processed": 0,
                    "transcript_content": "",
                    "timestamp": datetime.now().isoformat()
                })

            # Generate search queries for all events
            all_queries = []
            for event in parsed_events:
                queries = self._generate_search_queries(event)
                all_queries.extend(queries)
            
            # Remove duplicates and enforce a hard cap on queries
            unique_queries = list(set(all_queries))
            max_query_count = 50  # Increased to accommodate enhanced queries
            if len(unique_queries) > max_query_count:
                logger.info(f"Capping query count from {len(unique_queries)} to {max_query_count}")
                unique_queries = unique_queries[:max_query_count]
            logger.info(f"Generated {len(unique_queries)} enhanced search queries (time-bounded to last 4 hours)")

            # Sequential search to prevent segmentation faults, with a max files cap
            all_files = self._search_files_sequential(unique_queries, max_results=50)
            
            # Match files to events - PATTERN MATCHING FIRST
            all_matches = []
            for event in parsed_events:
                # PRIMARY: Search for Gemini notes by exact pattern and time
                pattern_matches = self._search_for_gemini_notes_by_pattern(event)
                all_matches.extend(pattern_matches)
                
                # SECONDARY: If no pattern matches, try folder search
                if not pattern_matches:
                    folder_matches = self._search_in_specific_folders(event)
                    all_matches.extend(folder_matches)
                
                # FALLBACK: If still no matches, try general search
                if not pattern_matches and not folder_matches:
                    matches = self._match_files_to_event(event, all_files)
                    all_matches.extend(matches)
            
            # Remove duplicates
            unique_matches = {}
            for match in all_matches:
                if match.file_id not in unique_matches or match.match_score > unique_matches[match.file_id].match_score:
                    unique_matches[match.file_id] = match
            
            final_matches = list(unique_matches.values())
            logger.info(f"Found {len(final_matches)} unique transcript matches")
            
            # Download content sequentially to prevent segmentation faults
            downloaded = []
            top_matches = sorted(final_matches, key=lambda x: x.match_score, reverse=True)[:3]  # Limit to top 3
            
            logger.info(f"Downloading content for {len(top_matches)} top matches sequentially for user {self.user_id}")
            # Optionally skip already processed files (DB is source of truth; Redis/memory as helper)
            skip_processed = True
            try:
                # Read from last input if available
                skip_processed = bool(self.last_input_data.get("skip_already_processed", True)) if hasattr(self, "last_input_data") else True
            except Exception:
                skip_processed = True

            for i, match in enumerate(top_matches):
                if skip_processed and (self._is_file_processed_db(match.file_id) or self._is_file_processed(match.file_id)):
                    logger.info(f"Skipping already processed transcript for user {self.user_id}: {match.file_name} ({match.file_id})")
                    continue
                try:
                    logger.info(f"Downloading file {i+1}/{len(top_matches)}: {match.file_name}")
                    content = self._download_file_content_optimized(match.file_id, match.mime_type)
                    
                    # Check if content was successfully downloaded
                    if content and len(content.strip()) > 0:
                        match.content = content
                        downloaded.append(match)
                        logger.info(f"Downloaded transcript: {match.file_name} ({len(content)} characters) for user {self.user_id}")
                        # Mark as processed in DB and cache so future runs skip it
                        self._mark_file_processed_db(match.file_id)
                        self._mark_file_processed(match.file_id)
                        logger.info(f"Marked file {match.file_id} as processed for user {self.user_id}")
                    else:
                        logger.warning(f"Empty content downloaded for {match.file_name}, skipping")
                        continue
                        
                except Exception as e:
                    logger.error(f"Failed to download transcript {match.file_name}: {e}")
                    # Continue to next file instead of failing completely
                    continue
            
            # Prepare transcript content for summarizer
            transcript_content = self._prepare_transcript_content_for_summarizer(downloaded)
            
            # If no content was downloaded, log the issue but don't create fallback
            if not transcript_content or len(transcript_content.strip()) == 0:
                logger.warning("No transcript content available from file downloads")
            
            # Cache full transcript content for summarizer tool
            if transcript_content:
                self._cache_full_transcript_content(transcript_content)
            
            # Prepare data for return
            transcripts_data = []
            for t in downloaded:
                d = asdict(t)
                d['last_modified'] = t.last_modified.isoformat()
                transcripts_data.append(d)

            result = {
                "status": "success",
                "transcripts_found": len(downloaded),
                "transcripts": transcripts_data,
                "events_processed": len(parsed_events),
                "transcript_content": transcript_content,
                "skip_deduplication": len(downloaded) == 0,  # Skip dedup if no transcripts found
                "timestamp": datetime.now().isoformat()
            }

            logger.info(f"Optimized transcript search completed: {len(downloaded)} transcripts found")
            self._log_audit_event("transcript_search_and_download", "success", f"Found and downloaded {len(downloaded)} transcripts", result)
            return json.dumps(result)
            
        except Exception as e:
            logger.error(f"Error in optimized transcript search: {e}")
            return json.dumps({"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()})

    def _match_files_to_event(self, event: CalendarEvent, all_files: List[Dict[str, Any]]) -> List[TranscriptMatch]:
        """Match files to a specific event."""
        try:
            # Calculate time window
            event_start = event.start_time
            event_end = event.end_time
            search_start = event_start - timedelta(hours=1)
            search_end = event_end + timedelta(hours=1)
            
            matches = []
            for file in all_files:
                # Check time window
                modified_time_str = file.get("modifiedTime", "")
                if modified_time_str:
                    try:
                        modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
                        if not (search_start <= modified_time <= search_end):
                            continue
                    except Exception:
                        continue
                
                # Score the match
                score, reason, confidence = self._score_file_match(file, event)
                if score > 0.3:  # Threshold for relevance
                    matches.append(TranscriptMatch(
                        file_id=file.get("id", ""),
                        file_name=file.get("name", ""),
                        file_path=file.get("webViewLink", ""),
                        mime_type=file.get("mimeType", ""),
                        size=int(file.get("size", 0)),
                        last_modified=modified_time,
                        content=None,  # Will be filled during download
                        match_score=score,
                        match_reason=reason,
                        matched_event_id=event.event_id,
                        matched_event_title=event.title,
                        confidence=confidence,
                    ))
            
            return sorted(matches, key=lambda x: x.match_score, reverse=True)
            
        except Exception as e:
            logger.error(f"Error matching files to event: {e}")
            return []

    def _parse_calendar_event(self, event_data: Dict[str, Any]) -> Optional[CalendarEvent]:
        try:
            # Handle different event data formats from Gemini agent
            logger.info(f"Parsing calendar event data: {event_data}")
            
            # Try different possible field names for start/end times
            start_time = None
            end_time = None
            
            # Check for various possible field names
            start_fields = ["start_time", "start", "startTime", "startDateTime"]
            end_fields = ["end_time", "end", "endTime", "endDateTime"]
            
            for field in start_fields:
                if field in event_data and event_data[field]:
                    start_time = self._parse_datetime(event_data[field])
                    if start_time:
                        break
            
            for field in end_fields:
                if field in event_data and event_data[field]:
                    end_time = self._parse_datetime(event_data[field])
                    if end_time:
                        break
            
            # If still no times found, try to parse from datetime field
            if not start_time and "datetime" in event_data:
                datetime_str = event_data["datetime"]
                if isinstance(datetime_str, str) and " to " in datetime_str:
                    parts = datetime_str.split(" to ")
                    if len(parts) == 2:
                        start_time = self._parse_datetime(parts[0].strip())
                        end_time = self._parse_datetime(parts[1].strip())
            
            if not start_time or not end_time:
                logger.warning(f"Could not parse start/end times from event data: {event_data}")
                return None
            
            # Parse attendees
            attendees: List[str] = []
            attendees_data = event_data.get("attendees", [])
            if isinstance(attendees_data, list):
                for attendee in attendees_data:
                    if attendee is None:  # Skip None attendees
                        continue
                    if isinstance(attendee, dict):
                        email = attendee.get("email", "")
                        if email and '@' in email:  # Validate email format
                            attendees.append(email)  # Store as simple string
                    elif isinstance(attendee, str):
                        if attendee and '@' in attendee:  # Validate email format
                            attendees.append(attendee)  # Store as simple string
            
            # Get organizer
            organizer_email = None
            organizer_data = event_data.get("organizer", {})
            if isinstance(organizer_data, dict):
                organizer_email = organizer_data.get("email")
            elif isinstance(organizer_data, str):
                organizer_email = organizer_data
            
            return CalendarEvent(
                event_id=event_data.get("event_id", event_data.get("id", "")),
                title=event_data.get("title", event_data.get("summary", "")),
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                organizer=organizer_email,
                description=event_data.get("description", ""),
                location=event_data.get("location", ""),
                meeting_link=event_data.get("meeting_link", "")
            )
        except Exception as e:
            logger.error(f"Error parsing calendar event: {e}")
            return None

    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        try:
            if isinstance(datetime_str, datetime):
                return datetime_str
            
            if not datetime_str:
                return None
            
            # Handle various datetime formats
            formats = [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ", 
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z"
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(datetime_str, fmt)
                except ValueError:
                    pass
            
            # Try ISO format parsing
            try:
                return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            except ValueError:
                pass
            
            # Try parsing with dateutil if available
            try:
                from dateutil import parser
                return parser.parse(datetime_str)
            except ImportError:
                pass
            except Exception:
                pass
            
            logger.warning(f"Could not parse datetime: {datetime_str}")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing datetime '{datetime_str}': {e}")
            return None

    def _match_transcripts_for_event(self, event: CalendarEvent) -> List[TranscriptMatch]:
        try:
            # Calculate time window for filtering based on calendar event time
            # Use event time ± 2 hours to find related transcripts (extended window)
            event_start = event.start_time
            event_end = event.end_time
            
            # Ensure times are timezone-aware
            if event_start and event_start.tzinfo is None:
                import pytz
                event_start = pytz.UTC.localize(event_start)
            if event_end and event_end.tzinfo is None:
                import pytz
                event_end = pytz.UTC.localize(event_end)
            
            # Extend the search window to ±2 hours around the event
            search_start = event_start - timedelta(hours=2)
            search_end = event_end + timedelta(hours=2)
            
            logger.info(f"Filtering transcripts for event '{event.title}' within event-based time window: {search_start} to {search_end}")
            
            queries = self._generate_search_queries(event)
            all_matches: List[TranscriptMatch] = []
            seen = set()

            # First, try to search in specific folders (Meet Recordings, etc.)
            folder_matches = self._search_in_specific_folders(event)
            for match in folder_matches:
                if match.file_id not in seen:
                    # Filter by event-based time window
                    if search_start <= match.last_modified <= search_end:
                        seen.add(match.file_id)
                        all_matches.append(match)
                        logger.info(f"Added transcript '{match.file_name}' (modified: {match.last_modified})")
                    else:
                        logger.info(f"Skipped transcript '{match.file_name}' (modified: {match.last_modified}) - outside event time window")

            # Then do general search
            for q in queries:
                try:
                    files = self.drive_service.search_files(q)
                    for f in files:
                        fid = f.get("id")
                        if fid in seen:
                            continue
                        seen.add(fid)
                        
                        # Parse modification time
                        modified_time_str = f.get("modifiedTime", "")
                        if modified_time_str:
                            try:
                                modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
                                # Filter by event-based time window
                                if not (search_start <= modified_time <= search_end):
                                    logger.info(f"Skipped file '{f.get('name')}' (modified: {modified_time}) - outside event time window")
                                    continue
                            except Exception as e:
                                logger.warning(f"Failed to parse modification time for file {f.get('name')}: {e}")
                                continue
                        
                        score, reason, conf = self._score_file_match(f, event)
                        if score > 0.3:
                            all_matches.append(TranscriptMatch(
                                file_id=fid,
                                file_name=f.get("name", ""),
                                file_path=f.get("webViewLink", ""),
                                mime_type=f.get("mimeType", ""),
                                size=int(f.get("size", 0)),
                                last_modified=datetime.fromisoformat(f.get("modifiedTime", "").replace('Z', '+00:00')),
                                content=None,
                                match_score=score,
                                match_reason=reason,
                                matched_event_id=event.event_id,
                                matched_event_title=event.title,
                                confidence=conf,
                            ))
                            logger.info(f"Added transcript '{f.get('name')}' (modified: {modified_time})")
                except Exception:
                    continue
            all_matches.sort(key=lambda x: x.match_score, reverse=True)
            logger.info(f"Found {len(all_matches)} transcripts within time window for event '{event.title}'")
            return all_matches[:3]
        except Exception:
            return []

    def _search_in_specific_folders(self, event: CalendarEvent) -> List[TranscriptMatch]:
        """Search for transcripts in specific folders - DIRECT APPROACH."""
        try:
            matches: List[TranscriptMatch] = []

            # Search in "Meet Recordings" folder ONLY
            meet_recordings_matches = self._search_in_meet_recordings_folder(event)
            matches.extend(meet_recordings_matches)

            return matches

        except Exception as e:
            logger.error(f"Error searching in specific folders: {e}")
            return []

    def _search_in_meet_recordings_folder(self, event: CalendarEvent) -> List[TranscriptMatch]:
        """Search for meeting recordings in specific folders - DIRECT APPROACH."""
        try:
            matches: List[TranscriptMatch] = []
            
            # Calculate time window for filtering based on calendar event time
            event_start = event.start_time
            event_end = event.end_time
            search_start = event_start - timedelta(hours=1)
            search_end = event_end + timedelta(hours=1)

            # DIRECT SEARCH: Look for "Meet Recordings" folder first
            folder_query = "name='Meet Recordings' and mimeType='application/vnd.google-apps.folder'"
            folders = self.drive_service.search_files(folder_query)
            
            if not folders:
                logger.info("No 'Meet Recordings' folder found - skipping folder search")
                return matches

            # Search for files in the Meet Recordings folder
            for folder in folders:
                folder_id = folder.get("id")
                if not folder_id:
                    continue

                # Search for files in this folder within time window
                files_query = f"'{folder_id}' in parents and modifiedTime > '{search_start.strftime('%Y-%m-%dT%H:%M:%S%z')}' and modifiedTime < '{search_end.strftime('%Y-%m-%dT%H:%M:%S%z')}'"
                files = self.drive_service.search_files(files_query)

                for f in files:
                    score, reason, conf = self._score_file_match(f, event)
                    if score > 0.3:
                        matches.append(TranscriptMatch(
                            file_id=f.get("id"),
                            file_name=f.get("name", ""),
                            file_path=f.get("webViewLink", ""),
                            mime_type=f.get("mimeType", ""),
                            size=int(f.get("size", 0)),
                            last_modified=datetime.fromisoformat(f.get("modifiedTime", "").replace('Z', '+00:00')),
                            content=None,
                            match_score=score + 0.2,  # Bonus for being in Meet Recordings folder
                            match_reason=f"{reason}; Meet Recordings folder",
                            matched_event_id=event.event_id,
                            matched_event_title=event.title,
                            confidence=conf,
                        ))
                        logger.info(f"Found file in Meet Recordings folder: {f.get('name')}")

            return matches

        except Exception as e:
            logger.error(f"Error searching in Meet Recordings folder: {e}")
            return []

    def _search_for_gemini_notes_by_pattern(self, event: CalendarEvent) -> List[TranscriptMatch]:
        """Search for Gemini notes files by exact name pattern and time matching."""
        try:
            matches: List[TranscriptMatch] = []
            
            # Calculate time window for the event
            event_start = event.start_time
            event_end = event.end_time
            search_start = event_start - timedelta(hours=2)
            search_end = event_end + timedelta(hours=2)
            
            # Format the expected file name pattern
            # Format: "testing115 - 2025/10/19 12:40 GMT+05:30 - Notes by Gemini"
            event_date = event_start.strftime("%Y/%m/%d")
            event_time = event_start.strftime("%H:%M")
            timezone_str = event_start.strftime("%z")
            if timezone_str:
                timezone_str = f"GMT{timezone_str[:3]}:{timezone_str[3:]}"
            else:
                timezone_str = "GMT+05:30"  # Default timezone
            
            # Create search patterns for exact matching
            patterns = [
                f"name contains '{event.title}' and name contains '{event_date}' and name contains 'Notes by Gemini'",
                f"name contains '{event.title}' and name contains '{event_time}' and name contains 'Notes by Gemini'",
                f"name contains '{event.title}' and name contains '{timezone_str}' and name contains 'Notes by Gemini'",
                f"name contains '{event.title}' and name contains 'Notes by Gemini'"
            ]
            
            # Search for files matching the pattern
            for pattern in patterns:
                time_filter = f"modifiedTime > '{search_start.strftime('%Y-%m-%dT%H:%M:%S%z')}' and modifiedTime < '{search_end.strftime('%Y-%m-%dT%H:%M:%S%z')}'"
                full_query = f"{pattern} and {time_filter}"
                
                files = self.drive_service.search_files(full_query)
                
                for f in files:
                    # Verify the file name matches the expected pattern
                    file_name = f.get("name", "")
                    if self._is_gemini_notes_file(file_name, event):
                        score, reason, conf = self._score_file_match(f, event)
                        if score > 0.5:  # Higher threshold for pattern matching
                            matches.append(TranscriptMatch(
                                file_id=f.get("id"),
                                file_name=f.get("name", ""),
                                file_path=f.get("webViewLink", ""),
                                mime_type=f.get("mimeType", ""),
                                size=int(f.get("size", 0)),
                                last_modified=datetime.fromisoformat(f.get("modifiedTime", "").replace('Z', '+00:00')),
                                content=None,
                                match_score=score + 0.3,  # Bonus for pattern matching
                                match_reason=f"{reason}; Gemini notes pattern match",
                                matched_event_id=event.event_id,
                                matched_event_title=event.title,
                                confidence=conf,
                            ))
                            logger.info(f"Found Gemini notes file by pattern: {file_name}")
                            break  # Found a match, no need to try other patterns
                
                if matches:  # If we found matches, no need to try other patterns
                    break
            
            return matches
            
        except Exception as e:
            logger.error(f"Error searching for Gemini notes by pattern: {e}")
            return []
    
    def _is_gemini_notes_file(self, file_name: str, event: CalendarEvent) -> bool:
        """Check if file name matches the expected Gemini notes pattern."""
        try:
            # Expected pattern: "testing115 - 2025/10/19 12:40 GMT+05:30 - Notes by Gemini"
            if "Notes by Gemini" not in file_name:
                return False
            
            # Check if event title is in the file name
            if event.title and event.title.lower() not in file_name.lower():
                return False
            
            # Check if the file name contains date/time patterns
            event_date = event.start_time.strftime("%Y/%m/%d")
            if event_date not in file_name:
                return False
            
            return True
            
        except Exception:
            return False

    def _search_for_gemini_notes(self, event: CalendarEvent) -> List[TranscriptMatch]:
        """Search specifically for Gemini-generated notes with the pattern: [title] - [date/time] - Notes by Gemini."""
        try:
            matches: List[TranscriptMatch] = []
            
            # Get time window around the meeting time instead of fixed 2 hours from now
            # Look for files created within 1 hour before and after the meeting start time
            meeting_start = event.start_time
            if meeting_start:
                # Create a window around the meeting time (±1 hour)
                search_start = meeting_start - timedelta(hours=1)
                search_end = meeting_start + timedelta(hours=1)
                time_filter = f"modifiedTime > '{search_start.isoformat()}' and modifiedTime < '{search_end.isoformat()}'"
            else:
                # Fallback to last 2 hours if no meeting time
                two_hours_ago = datetime.now() - timedelta(hours=2)
                time_filter = f"modifiedTime > '{two_hours_ago.isoformat()}'"

            # Primary search: Look for files with exact "Notes by Gemini" pattern modified in last 2 hours
            primary_query = f"name contains 'Notes by Gemini' and {time_filter}"
            logger.info(f"Searching for latest Gemini notes with query: {primary_query}")
            
            files = self.drive_service.search_files(primary_query)
            logger.info(f"Found {len(files)} files matching 'Notes by Gemini' in last 2 hours")
            
            for f in files:
                file_name = f.get("name", "")
                modified_time_str = f.get("modifiedTime", "")
                
                # Parse modification time
                if modified_time_str:
                    try:
                        modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
                        logger.info(f"Processing Gemini notes file: '{file_name}' (modified: {modified_time})")
                        
                        # Check if file matches the expected pattern: [title] - [date/time] - Notes by Gemini
                        if self._matches_gemini_pattern(file_name):
                            logger.info(f"File matches Gemini pattern: {file_name}")
                            
                            # High score for files matching the exact pattern
                            score = 0.9  # Very high score for pattern match
                            reason = f"Exact Gemini pattern match: {file_name}"
                            confidence = "high"
                            
                            matches.append(TranscriptMatch(
                                file_id=f.get("id"),
                                file_name=file_name,
                                file_path=f.get("webViewLink", ""),
                                mime_type=f.get("mimeType", ""),
                                size=int(f.get("size", 0)),
                                last_modified=modified_time,
                                content=None,
                                match_score=score,
                                match_reason=reason,
                                matched_event_id=event.event_id,
                                matched_event_title=event.title,
                                confidence=confidence,
                            ))
                            logger.info(f"Added Gemini notes file: {file_name} (score: {score})")
                        else:
                            # Still consider files with "Notes by Gemini" but lower score
                            score, reason, conf = self._score_file_match(f, event)
                            if score > 0.3:
                                matches.append(TranscriptMatch(
                                    file_id=f.get("id"),
                                    file_name=file_name,
                                    file_path=f.get("webViewLink", ""),
                                    mime_type=f.get("mimeType", ""),
                                    size=int(f.get("size", 0)),
                                    last_modified=modified_time,
                                    content=None,
                                    match_score=score + 0.2,  # Bonus for having "Notes by Gemini"
                                    match_reason=f"{reason}; Contains 'Notes by Gemini'",
                                    matched_event_id=event.event_id,
                                    matched_event_title=event.title,
                                    confidence=conf,
                                ))
                                logger.info(f"Added Gemini-related file: {file_name} (score: {score + 0.2})")
                    except Exception as e:
                        logger.warning(f"Failed to parse modification time for file {file_name}: {e}")
                        continue

            # Sort by modification time (latest first) and score
            matches.sort(key=lambda x: (x.last_modified, x.match_score), reverse=True)
            logger.info(f"Found {len(matches)} Gemini notes files, sorted by recency")
            
            return matches

        except Exception as e:
            logger.error(f"Error searching for Gemini notes: {e}")
            return []

    def _matches_gemini_pattern(self, file_name: str) -> bool:
        """Check if file name matches the expected Gemini pattern: [title] - [date/time] - Notes by Gemini."""
        try:
            # Pattern: [title] - [date/time] - Notes by Gemini
            # Example: "testing - 2025/10/13 01:09 GMT+05:30 - Notes by Gemini"
            
            if not file_name or "Notes by Gemini" not in file_name:
                return False
            
            # Check if it has the dash pattern: [something] - [date/time] - Notes by Gemini
            parts = file_name.split(" - ")
            if len(parts) >= 3:
                # Last part should be "Notes by Gemini"
                if parts[-1].strip() == "Notes by Gemini":
                    # Second to last part should contain date/time pattern
                    date_part = parts[-2].strip()
                    # Look for date patterns like "2025/10/13" or "2025-10-13"
                    if re.search(r'\d{4}[/-]\d{1,2}[/-]\d{1,2}', date_part):
                        logger.info(f"File matches Gemini pattern: {file_name}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking Gemini pattern for '{file_name}': {e}")
            return False

    def _generate_search_queries(self, event: CalendarEvent) -> List[str]:
        """Generate focused search queries for finding latest Gemini transcripts within last 2 hours."""
        queries: List[str] = []
        
        # Get time window around the meeting time instead of fixed 2 hours from now
        meeting_start = event.start_time
        if meeting_start:
            # Ensure meeting_start is timezone-aware
            if meeting_start.tzinfo is None:
                import pytz
                meeting_start = pytz.UTC.localize(meeting_start)
            
            # Create a window around the meeting time (±2 hours for better coverage)
            search_start = meeting_start - timedelta(hours=2)
            search_end = meeting_start + timedelta(hours=2)
            time_filter = f"modifiedTime > '{search_start.isoformat()}' and modifiedTime < '{search_end.isoformat()}'"
        else:
            # Fallback to last 4 hours if no meeting time (extended window)
            import pytz
            four_hours_ago = datetime.now(pytz.UTC) - timedelta(hours=4)
            time_filter = f"modifiedTime > '{four_hours_ago.isoformat()}'"
        
        # Enhanced search queries for better transcript detection
        
        # Primary search: Look for "Notes by Gemini" files
        queries.append(f"name contains 'Notes by Gemini' and {time_filter}")
        
        # Secondary search: Look for files with event title
        if event.title:
            queries.append(f"name contains '{event.title}' and {time_filter}")
        
        # Tertiary search: Look for any transcript files
        queries.append(f"(name contains 'transcript' or name contains 'meeting notes' or name contains 'summary') and {time_filter}")
        
        # Quaternary search: Look for files with today's date pattern
        today = datetime.now().strftime("%Y/%m/%d")
        queries.append(f"name contains '{today}' and {time_filter}")
        
        # Quinary search: Look for Google Meet recordings (handled by folder search)
        # queries.append(f"name contains 'Meet Recordings' and {time_filter}")
        
        # Senary search: Look for files with exact pattern matching
        if event.title:
            queries.append(f"name contains '{event.title}' and name contains '2025' and name contains 'Notes by Gemini' and {time_filter}")
        
        # Septenary search: Look for files in specific folders (using folder search)
        # This will be handled by _search_in_meet_recordings_folder method instead
        
        # Octonary search: Look for files modified around meeting time (broader search)
        queries.append(f"modifiedTime > '{search_start.isoformat()}' and (name contains 'meeting' or name contains 'transcript' or name contains 'notes')")
        
        # Nonary search: Look for files with attendee names
        if event.attendees:
            for attendee in event.attendees[:2]:  # Limit to first 2 attendees
                # Handle both string emails and dictionary attendee objects
                if isinstance(attendee, str):
                    email_name = attendee.split('@')[0] if '@' in attendee else attendee
                elif isinstance(attendee, dict):
                    email = attendee.get('email', '')
                    email_name = email.split('@')[0] if '@' in email else email
                else:
                    # Skip if attendee is neither string nor dict
                    continue
                
                # Only add query if we have a valid email name
                if email_name and email_name.strip():
                    # Escape single quotes in email name to prevent Drive API syntax errors
                    escaped_email_name = email_name.replace("'", "\\'")
                    queries.append(f"name contains '{escaped_email_name}' and {time_filter}")
        
        # Decenary search: Look for any recent files (fallback)
        queries.append(f"modifiedTime > '{search_start.isoformat()}'")
        
        logger.info(f"Generated {len(queries)} enhanced search queries for better transcript detection")
        return queries

    def _score_file_match(self, file_info: Dict[str, Any], event: CalendarEvent) -> Tuple[float, str, str]:
        score = 0.0
        reasons: List[str] = []
        file_name = file_info.get("name", "").lower()
        file_modified = file_info.get("modifiedTime", "")

        # Check for specific keyword matches (highest priority)
        keyword_score = self._check_keyword_matches(file_name)
        if keyword_score > 0:
            score += keyword_score
            reasons.append(f"Keyword match: {keyword_score:.2f}")

        title_similarity = self._calculate_title_similarity(file_name, event.title)
        if title_similarity > 0.7:
            score += 0.4
            reasons.append(f"Title match: {title_similarity:.2f}")
        attendee_match = self._check_attendee_match(file_name, event.attendees)
        if attendee_match > 0:
            score += 0.3 * min(attendee_match, 1.0)
            reasons.append(f"Attendee match: {attendee_match}")
        time_proximity = self._check_time_proximity(file_modified, event.start_time)
        if time_proximity > 0.5:
            score += 0.2 * time_proximity
            reasons.append(f"Time proximity: {time_proximity:.2f}")
        mime_type = file_info.get("mimeType", "")
        if self._is_transcript_file_type(mime_type):
            score += 0.1
            reasons.append("Relevant file type")
        confidence = "high" if score >= 0.8 else ("medium" if score >= 0.5 else "low")
        return score, "; ".join(reasons) if reasons else "No specific match criteria", confidence

    def _check_keyword_matches(self, file_name: str) -> float:
        """Check for specific keyword matches that indicate high-quality transcript files."""
        try:
            score = 0.0

            # Highest priority: Check for exact Gemini pattern match
            if self._matches_gemini_pattern(file_name):
                score += 0.8  # Highest score for exact pattern match
                logger.info(f"Found exact Gemini pattern file: {file_name}")
                return min(score, 1.0)  # Cap at 1.0

            # High-priority keywords for Gemini-generated notes
            gemini_keywords = [
                "notes by gemini",
                "gemini notes",
                "notes by google",
                "google docs notes"
            ]

            # High-priority keywords for Meet Recordings
            meet_keywords = [
                "meet recordings",
                "meet recording",
                "google meet",
                "meet transcript"
            ]

            # Check for Gemini notes (high priority)
            for keyword in gemini_keywords:
                if keyword in file_name.lower():
                    score += 0.6  # High score for Gemini notes
                    logger.info(f"Found Gemini notes file: {file_name}")
                    break

            # Check for Meet Recordings (high priority)
            for keyword in meet_keywords:
                if keyword in file_name.lower():
                    score += 0.5  # High score for Meet recordings
                    logger.info(f"Found Meet recording file: {file_name}")
                    break

            # Check for other transcript indicators
            transcript_keywords = [
                "transcript",
                "meeting notes",
                "minutes",
                "recording"
            ]

            for keyword in transcript_keywords:
                if keyword in file_name.lower():
                    score += 0.2  # Medium score for general transcript keywords
                    break

            # Check for Google Docs files
            if "google docs" in file_name.lower() or file_name.endswith(".gdoc"):
                score += 0.3  # Medium-high score for Google Docs
                logger.info(f"Found Google Docs file: {file_name}")

            return min(score, 1.0)  # Cap at 1.0

        except Exception as e:
            logger.error(f"Error checking keyword matches: {e}")
            return 0.0

    def _calculate_title_similarity(self, file_name: str, event_title: str) -> float:
        try:
            fw = set(re.findall(r"\b\w+\b", file_name.lower()))
            ew = set(re.findall(r"\b\w+\b", event_title.lower()))
            if not fw or not ew:
                return 0.0
            inter = fw & ew
            union = fw | ew
            return len(inter) / len(union) if union else 0.0
        except Exception:
            return 0.0

    def _check_attendee_match(self, file_name: str, attendees: List[Dict[str, str]]) -> float:
        try:
            matches = 0
            total = len(attendees)
            if total == 0:
                return 0.0
            for a in attendees:
                name = a.get("name", "").lower()
                if name and name in file_name:
                    matches += 1
                else:
                    email = a.get("email", "")
                    if email:
                        username = email.split("@")[0].lower()
                        if username in file_name:
                            matches += 1
            return matches / total
        except Exception:
            return 0.0

    def _check_time_proximity(self, file_modified: str, event_start: datetime) -> float:
        try:
            if not file_modified:
                return 0.0
            file_time = datetime.fromisoformat(file_modified.replace('Z', '+00:00'))
            time_diff = abs((file_time - event_start).total_seconds())
            max_diff = 24 * 3600
            return max(0, 1 - (time_diff / max_diff))
        except Exception:
            return 0.0

    def _is_transcript_file_type(self, mime_type: str) -> bool:
        return mime_type in [
            "text/plain",
            "application/vnd.google-apps.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/pdf",
            "text/csv",
            "application/rtf",
        ]

    def _download_file_content(self, file_id: str, mime_type: str) -> str:
        try:
            if mime_type == "application/vnd.google-apps.document":
                return self._download_google_doc_content(file_id)
            content = self.drive_service.download_file_content(file_id)
            if isinstance(content, bytes):
                try:
                    content = content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        content = content.decode('latin-1')
                    except UnicodeDecodeError:
                        content = content.decode('utf-8', errors='ignore')
            return content
        except Exception as e:
            logger.error("Error downloading content for file %s: %s", file_id, e)
            return ""

    def _download_google_doc_content(self, file_id: str) -> str:
        try:
            content = self.drive_service.export_file(file_id, "text/plain")
            return content.decode('utf-8') if isinstance(content, bytes) else content
        except Exception as e:
            logger.error("Error downloading Google Doc content: %s", e)
            return ""

    def _match_transcript_to_event(self, event_data: Dict[str, Any]) -> str:
        try:
            event = self._parse_calendar_event(event_data)
            if not event:
                return json.dumps({"status": "error", "error": "Failed to parse calendar event", "timestamp": datetime.now().isoformat()})
            matches = self._match_transcripts_for_event(event)
            matches_data: List[Dict[str, Any]] = []
            for m in matches:
                d = asdict(m)
                d['last_modified'] = m.last_modified.isoformat()
                matches_data.append(d)
            return json.dumps({
                "status": "success",
                "event_id": event.event_id,
                "event_title": event.title,
                "matches_found": len(matches),
                "matches": matches_data,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error("Error matching transcript to event: %s", e)
            return json.dumps({"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()})

    def _download_transcript_content(self, file_id: str) -> str:
        try:
            file_info = self.drive_service.get_file_metadata(file_id)
            if not file_info:
                return json.dumps({"status": "error", "error": f"File not found: {file_id}", "timestamp": datetime.now().isoformat()})
            content = self._download_file_content(file_id, file_info.get("mimeType", ""))
            return json.dumps({
                "status": "success",
                "file_id": file_id,
                "file_name": file_info.get("name", ""),
                "content": content,
                "content_length": len(content),
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error("Error downloading transcript content: %s", e)
            return json.dumps({"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()})

    def _store_transcript_metadata(self, match: TranscriptMatch, calendar_events: List[Dict[str, Any]]) -> None:
        """Store transcript metadata in the database."""
        try:
            if not self.database_service:
                logger.warning("Database service not available for storing transcript metadata")
                return

            # Find the matching calendar event
            matching_event = None
            for event_data in calendar_events:
                if event_data.get("event_id") == match.matched_event_id:
                    matching_event = event_data
                    break

            # Prepare metadata for database storage
            metadata = {
                "file_id": match.file_id,
                "file_name": match.file_name,
                "file_path": match.file_path,
                "mime_type": match.mime_type,
                "file_size": match.size,
                "last_modified": match.last_modified.isoformat(),
                "match_score": match.match_score,
                "match_reason": match.match_reason,
                "matched_event_id": match.matched_event_id,
                "matched_event_title": match.matched_event_title,
                "content_length": len(match.content) if match.content else 0,
                "user_id": self.user_id,
                "agent_id": self.agent_id,
                "workflow_id": self.workflow_id,
                "created_at": datetime.now().isoformat(),
                "calendar_event": matching_event
            }

            # Store in database
            self.database_service.store_transcript_metadata(metadata)
            logger.info(f"Stored transcript metadata for {match.file_name} in database")

        except Exception as e:
            logger.error(f"Failed to store transcript metadata: {e}")

    def _prepare_transcript_content_for_summarizer(self, downloaded_transcripts: List[TranscriptMatch]) -> str:
        """Prepare transcript content for the summarizer tool."""
        try:
            if not downloaded_transcripts:
                return ""

            # Combine all transcript content
            combined_content = []
            for transcript in downloaded_transcripts:
                if transcript.content:
                    # Add header with meeting info
                    header = f"\n=== TRANSCRIPT: {transcript.matched_event_title} ===\n"
                    header += f"File: {transcript.file_name}\n"
                    header += f"Event ID: {transcript.matched_event_id}\n"
                    header += f"Match Score: {transcript.match_score:.2f}\n"
                    header += f"Content Length: {len(transcript.content)} characters\n"
                    header += "=" * 50 + "\n\n"

                    combined_content.append(header + transcript.content)

            return "\n\n".join(combined_content)

        except Exception as e:
            logger.error(f"Failed to prepare transcript content for summarizer: {e}")
            return ""


    def _log_audit_event(self, action: str, status: str, message: str, data: Dict[str, Any] = None):
        try:
            if self.agent_integration:
                self.agent_integration.log_audit_event(
                    agent_task_id=self.user_agent_task_id or "default_task",
                    activity_type="file_operation",
                    log_status=status,
                    log_text=message,
                    action=action,
                    action_required="monitor_file_access",
                    outcome="file_accessed" if status == "success" else "file_access_failed",
                    tool_id="drive_tool",
                    step_id="transcript_download",
                    log_data=data or {},
                )
        except Exception as e:
            logger.warning("Failed to log audit event: %s", e)