"""LangChain Summarizer Tool for autonomous meeting intelligence with Redis caching."""

import asyncio
import json
import logging
import re
import redis
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
import os

# Import prompt loader
from src.utils.prompt_loader import PromptLoader
# Import tool configs and categories
from src.constants.app import AVAILABLE_TOOLS
from src.services.google import GoogleDriveService

logger = logging.getLogger(__name__)


class SummarizerToolInput(BaseModel):
    """Input schema for the summarizer tool."""
    transcript_content: str = Field(
        description="Meeting transcript content to be summarized into structured JSON format"
    )


class LangchainSummarizerTool(BaseTool):
    """
    LangChain tool for AI-powered meeting transcript summarization using the AI debrief prompt.

    This tool:
    - Uses the specific ai_debrief_prompt.txt for consistent JSON output
    - Returns ONLY JSON format for other tools to consume
    - Processes meeting transcripts into structured task data
    - Extracts decisions, action items, and follow-up requirements
    """

    name: str = "summarizer_tool"
    description: str = "AI-powered meeting transcript summarization using structured prompts. Returns JSON format with tasks, decisions, and follow-up requirements."
    category: str = "ai_processing"
    args_schema: type[BaseModel] = SummarizerToolInput

    # Declare these as proper Pydantic fields
    auth: Optional[Any] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    drive_folder_id: Optional[str] = None
    llm: Optional[Any] = None
    prompt_loader: Optional[PromptLoader] = None
    drive_service: Optional[Any] = None
    redis_client: Optional[redis.Redis] = None
    drive_tool: Optional[Any] = None  # Reference to drive tool for cache access

    def __init__(self, auth=None, user_id=None, org_id=None, agent_task_id=None, drive_folder_id=None, drive_tool=None):
        super().__init__(auth=auth, user_id=user_id, org_id=org_id, agent_task_id=agent_task_id, drive_folder_id=drive_folder_id)

        # Initialize prompt loader
        self.prompt_loader = PromptLoader()
        # Initialize Drive service if auth provided (for optional upload)
        self.drive_service = GoogleDriveService(auth) if auth else None
        # Reference to drive tool for cache access
        self.drive_tool = drive_tool

        # Initialize Redis client
        try:
            from ..configuration.config import REDIS_URL
            self.redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established successfully for summarizer")
        except Exception as e:
            logger.warning(f"Redis connection failed for summarizer: {e}. Using in-memory fallback.")
            self.redis_client = None
            self._memory_cache = {}

        try:
            # Initialize Gemini LLM for summarization using runtime environment
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

            if gemini_api_key:
                self.llm = ChatGoogleGenerativeAI(
                    model=gemini_model,
                    google_api_key=gemini_api_key,
                    temperature=0.1,  # Low temperature for consistent JSON output
                    convert_system_message_to_human=True
                )
                logger.info("Gemini LLM initialized successfully for summarization")
            else:
                logger.error("GEMINI_API_KEY is missing from environment; summarizer will use fallback behavior")
                self.llm = None
        except Exception as e:
            logger.error("Failed to initialize Gemini LLM: %s", e)
            self.llm = None

    def _get_cached_transcript_content(self) -> Optional[str]:
        """Get cached transcript content from the drive tool."""
        try:
            if self.drive_tool:
                cached_content = self.drive_tool.get_cached_transcript_for_summarizer()
                if cached_content:
                    logger.info(f"Retrieved cached transcript content: {len(cached_content)} characters")
                    return cached_content
            return None
        except Exception as e:
            logger.error(f"Failed to get cached transcript content: {e}")
            return None

    def run(
        self,
        tool_input: Any,
        **kwargs,
    ) -> str:
        """Override run method to handle input correctly."""
        logger.info(f"Summarizer tool run() called with input: {tool_input}, kwargs: {kwargs}")
        return self._run(tool_input, **kwargs)

    def _run(
        self,
        query = None,
        **kwargs,
    ) -> str:
        """Execute summarization operations using AI debrief prompt."""
        try:
            # Handle both query parameter and keyword arguments
            if query:
                transcript_content = self._extract_transcript_content(query)
            else:
                # Extract transcript content from keyword arguments
                transcript_content = kwargs.get('transcript_content', '')
            
            if not transcript_content:
                return json.dumps({
                    "error": "No transcript content provided",
                    "status": "failed"
                })

            # Use AI debrief prompt for summarization
            return self._summarize_with_debrief_prompt(transcript_content, str(query) if query else str(kwargs))

        except Exception as e:
            logger.error("Summarizer tool error: %s", e)
            return json.dumps({
                "error": f"Summarization failed: {str(e)}",
                "status": "failed"
            })

    async def _arun(
        self,
        query: str,
        *args,
        **kwargs,
    ) -> str:
        """Execute summarization operations asynchronously."""
        # Run synchronous _run in a thread to avoid blocking event loop
        return await asyncio.to_thread(self._run, query, *args, **kwargs)

    def _extract_transcript_content(self, query) -> str:
        """Extract transcript content from the query or cache."""
        try:
            # First, try to get from cache if available
            cached_content = self._get_cached_transcript_content()
            if cached_content:
                logger.info("Using cached transcript content for summarization")
                return cached_content

            # Fallback to parsing from query
            logger.info("No cached content found, parsing from query")
            
            # Handle both dict and string inputs
            if isinstance(query, dict):
                # Check if it's drive tool output with transcript_content
                if "transcript_content" in query:
                    return query["transcript_content"]
                # Check if it's a direct transcript content
                elif "content" in query:
                    return query["content"]
                # If it's a dict but no transcript content, return empty
                else:
                    logger.warning("Dict input but no transcript content found")
                    return ""
            
            # Try to parse as JSON string (from drive tool)
            try:
                data = json.loads(query)
                if isinstance(data, dict):
                    # Check if it's drive tool output with transcript_content
                    if "transcript_content" in data:
                        return data["transcript_content"]
                    # Check if it's a direct transcript content
                    elif "content" in data:
                        return data["content"]
            except json.JSONDecodeError:
                pass

            # Look for transcript content in various formats
            if "transcript content:" in query.lower():
                content_part = query.split("transcript content:")[1]
                if "with meeting_title:" in content_part:
                    return content_part.split("with meeting_title:")[0].strip()
                else:
                    return content_part.strip()
            elif "content:" in query.lower():
                content_part = query.split("content:")[1]
                if "with" in content_part:
                    return content_part.split("with")[0].strip()
                else:
                    return content_part.strip()
            elif "summarize transcript" in query.lower():
                # Try to extract content after "summarize transcript"
                parts = query.split("summarize transcript", 1)
                if len(parts) > 1:
                    content = parts[1].strip()
                    # Remove common prefixes
                    for prefix in ["content:", "file:", "data:"]:
                        if content.lower().startswith(prefix):
                            content = content[len(prefix):].strip()
                    return content
            
            # If no specific pattern found, return the whole query as content
            return query.strip()
            
        except Exception as e:
            logger.error(f"Error extracting transcript content: {e}")
            return ""
    
    def _extract_meeting_title_from_query(self, query: str) -> Optional[str]:
        """Extract meeting title from the query string."""
        try:
            if not query or not isinstance(query, str):
                return None
            
            # Look for "with meeting_title:" pattern
            if "with meeting_title:" in query:
                parts = query.split("with meeting_title:")
                if len(parts) > 1:
                    title_part = parts[1].strip()
                    # Extract title before "and attendees:" or end of string
                    if "and attendees:" in title_part:
                        title = title_part.split("and attendees:")[0].strip()
                    else:
                        title = title_part.strip()
                    if title:
                        logger.info(f"Extracted meeting_title from query: {title}")
                        return title
            
            # Look for "meeting_title:" pattern
            if "meeting_title:" in query:
                parts = query.split("meeting_title:")
                if len(parts) > 1:
                    title_part = parts[1].strip()
                    if "and" in title_part:
                        title = title_part.split("and")[0].strip()
                    else:
                        title = title_part.strip()
                    if title:
                        logger.info(f"Extracted meeting_title from query: {title}")
                        return title
            
            return None
        except Exception as e:
            logger.error(f"Error extracting meeting title from query: {e}")
            return None
    
    def _extract_attendees_from_query(self, query: str) -> List[str]:
        """Extract attendees from the query string."""
        try:
            if not query or not isinstance(query, str):
                return []
            
            # Look for "and attendees:" pattern
            if "and attendees:" in query:
                parts = query.split("and attendees:")
                if len(parts) > 1:
                    attendees_part = parts[1].strip()
                    # Try to parse as list
                    try:
                        # Remove brackets if present
                        attendees_part = attendees_part.strip("[]")
                        # Split by comma
                        attendees = [a.strip().strip('"\'') for a in attendees_part.split(",") if a.strip()]
                        if attendees:
                            logger.info(f"Extracted attendees from query: {attendees}")
                            return attendees
                    except Exception:
                        pass
            
            return []
        except Exception as e:
            logger.error(f"Error extracting attendees from query: {e}")
            return []

    def _summarize_with_debrief_prompt(self, transcript_content: str, original_query: str) -> str:
        """Summarize transcript using the AI debrief prompt and return JSON only."""
        try:
            # Extract meeting title and attendees from query
            meeting_title = self._extract_meeting_title_from_query(original_query)
            attendees = self._extract_attendees_from_query(original_query)
            
            if not self.llm:
                return self._create_fallback_json(transcript_content, meeting_title, attendees)

            # Load the AI debrief prompt
            prompt_template = self.prompt_loader.load_prompt("ai_debrief_prompt.txt")
            if not prompt_template:
                logger.error("Failed to load ai_debrief_prompt.txt")
                return self._create_fallback_json(transcript_content, meeting_title, attendees)

            # Format the prompt with transcript content
            formatted_prompt = prompt_template.format(transcript_content=transcript_content)

            # Get LLM response
            logger.info("Generating AI summary using debrief prompt")
            response = self.llm.invoke(formatted_prompt)

            # Extract JSON from response
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Try to extract JSON from the response
            json_content = self._extract_json_from_response(response_text)
            if json_content:
                logger.info("Successfully generated JSON summary")
                # Inject identity context and meeting metadata so downstream tools (dedup, sheets) never fall back
                try:
                    if isinstance(json_content, dict):
                        json_content.setdefault("user_id", self.user_id)
                        json_content.setdefault("org_id", self.org_id)
                        json_content.setdefault("agent_task_id", self.agent_task_id)
                        
                        # Ensure meeting_metadata exists with title and attendees
                        if "meeting_metadata" not in json_content:
                            json_content["meeting_metadata"] = {}
                        
                        meeting_metadata = json_content["meeting_metadata"]
                        # Set meeting title from query if not already set or if it's a fallback value
                        if meeting_title and (not meeting_metadata.get("title") or meeting_metadata.get("title") == "Meeting Summary" or meeting_metadata.get("title") == "Unknown Meeting"):
                            meeting_metadata["title"] = meeting_title
                            logger.info(f"Set meeting_title from query: {meeting_title}")
                        
                        # Set attendees from query if not already set
                        if attendees and not meeting_metadata.get("attendees"):
                            meeting_metadata["attendees"] = attendees
                            logger.info(f"Set attendees from query: {attendees}")
                        
                        # Also set event_title for backward compatibility
                        if meeting_title and not json_content.get("event_title"):
                            json_content["event_title"] = meeting_title
                except Exception as e:
                    logger.error(f"Error injecting metadata: {e}")

                json_str = json.dumps(json_content, indent=2)
                self._maybe_upload_summary_to_drive(json_str)
                return json_str
            else:
                logger.warning("No valid JSON found in LLM response, using fallback")
                fallback = self._create_fallback_json(transcript_content, meeting_title, attendees)
                # Ensure identity context exists
                try:
                    fb = json.loads(fallback)
                    fb.setdefault("user_id", self.user_id)
                    fb.setdefault("org_id", self.org_id)
                    fb.setdefault("agent_task_id", self.agent_task_id)
                    fallback = json.dumps(fb, indent=2)
                except Exception:
                    pass
                self._maybe_upload_summary_to_drive(fallback)
                return fallback

        except Exception as e:
            logger.error("Error in AI debrief summarization: %s", e)
            logger.info("Using fallback JSON due to AI error")
            meeting_title = self._extract_meeting_title_from_query(original_query)
            attendees = self._extract_attendees_from_query(original_query)
            fallback = self._create_fallback_json(transcript_content, meeting_title, attendees)
            # Ensure identity context exists
            try:
                fb = json.loads(fallback)
                fb.setdefault("user_id", self.user_id)
                fb.setdefault("org_id", self.org_id)
                fb.setdefault("agent_task_id", self.agent_task_id)
                fallback = json.dumps(fb, indent=2)
            except Exception:
                pass
            self._maybe_upload_summary_to_drive(fallback)
            return fallback

    def _extract_json_from_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response."""
        try:
            # Look for JSON in the response
            if "{" in response_text and "}" in response_text:
                # Find the JSON part
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1

                if start_idx != -1 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    return json.loads(json_str)

            return None
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON from response: %s", e)
            return None





        except Exception as e:
            logger.error("Error extracting JSON: %s", e)
            return None

    def _create_fallback_json(self, transcript_content: str, meeting_title: Optional[str] = None, attendees: Optional[List[str]] = None) -> str:
        """Create a fallback JSON when AI is not available."""
        try:
            # Use provided meeting_title or extract from transcript
            if not meeting_title:
                # Extract basic info from transcript
                lines = transcript_content.split('\n')
                meeting_title = "Meeting Summary"

                # Try to find a title in the first few lines
                for line in lines[:5]:
                    if line.strip() and len(line.strip()) > 5:
                        meeting_title = line.strip()[:100]  # Limit length
                        break

            fallback_data = {
                "meeting_metadata": {
                    "id": f"meeting_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "title": meeting_title,
                    "video_url": "",
                    "transcript_url": "",
                    "attendees": attendees if attendees else []
                },
                "event_title": meeting_title,  # Add for backward compatibility
                "executive_summary": f"Meeting summary for {meeting_title}. AI processing was not available, so this is a basic summary.",
                "tasks": [
                    {
                        "title": "Review Meeting Content",
                        "description": "Please review the meeting transcript manually for detailed information",
                        "expected_outcome": "Complete understanding of meeting outcomes",
                        "assignee_name": None,  # No assignee - requires manual review
                        "priority": "medium",
                        "task_status": "todo",
                        "end_date": "",
                        "sub_tasks": []
                    }
                ],
                "decisions": [
                    {
                        "decision": "Meeting discussion took place",
                        "context": "Regular team communication session",
                        "participants_involved": []  # No participants extracted - requires manual review
                    }
                ],
                "unresolved_questions": [
                    {
                        "question": "What were the main topics discussed?",
                        "speaker": "System",
                        "context": "AI processing was not available for detailed analysis"
                    }
                ],
                "follow_up_needs": [
                    {
                        "topic": "Meeting Review",
                        "action_required": "Manual review of meeting content",
                        "suggested_attendees": ["Team"]
                    }
                ]
            }

            return json.dumps(fallback_data, indent=2)

        except Exception as e:
            logger.error("Error creating fallback JSON: %s", e)
            return json.dumps({
                "error": f"Failed to create summary: {str(e)}",
                "status": "failed"
            })

    def _maybe_upload_summary_to_drive(self, json_str: str) -> None:
        """Upload the summary JSON to the configured Drive folder if available."""
        try:
            if not self.drive_service or not self.drive_folder_id:
                return

            # Ensure folder exists (use existing folder id if provided)
            parent_folder_id = self.drive_folder_id

            # Compose a file name with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"meeting_summary_{timestamp}.json"

            uploaded = self.drive_service.upload_file(
                file_name=file_name,
                content=json_str.encode("utf-8"),
                mime_type="application/json",
                parent_folder_id=parent_folder_id,
            )
            if uploaded:
                logger.info("Uploaded summary JSON to Drive: %s", uploaded.get("webViewLink"))
            else:
                logger.warning("Failed to upload summary JSON to Drive")
        except Exception as e:
            logger.warning("Summary upload to Drive failed: %s", e)