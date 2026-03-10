"""
LangChain DedupTool for Meeting Intelligence Workflow

This tool processes meeting summaries to extract tasks and deduplicate them
before storing in the Google Sheet created during OAuth consent flow.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field

# Import utilities for task processing
import hashlib
from difflib import SequenceMatcher

# Import Google Sheets utilities
from src.auth.google_auth_handler import GoogleAuthHandler

logger = logging.getLogger(__name__)


class DedupToolInput(BaseModel):
    """Input schema for the dedup tool."""
    summary_data: str = Field(
        description="JSON string containing meeting summary data with extracted tasks"
    )


@dataclass
class TaskData:
    """Data class for extracted task information."""
    task_id: str
    task_text: str
    meeting_title: str
    assignees: List[str]
    priority_level: str
    due_date: Optional[str] = None
    status: str = "pending"
    created_at: str = None
    task_hash: str = None
    original_task_item: Optional[Dict[str, Any]] = None  # Store original task structure from summarizer

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.task_hash is None:
            self.task_hash = self._generate_task_hash()

    def _generate_task_hash(self) -> str:
        """Generate a stable hash for task deduplication."""
        # Normalize text for consistent hashing
        normalized_text = self.task_text.lower().strip()
        normalized_text = ' '.join(normalized_text.split())  # Normalize whitespace
        return hashlib.md5(normalized_text.encode('utf-8')).hexdigest()[:12]


class LangchainDedupTool(BaseTool):
    """
    LangChain tool for task deduplication and storage.

    This tool:
    - Extracts tasks from meeting summaries
    - Deduplicates tasks using semantic comparison
    - Stores unique tasks in Google Sheets
    - Manages task metadata and assignments
    """

    name: str = "dedup_tool"
    description: str = """
    Extracts tasks from meeting summaries, deduplicates them, and stores unique tasks in Google Sheets.
    Input should be a JSON string containing meeting summary data with extracted tasks.
    """
    args_schema: type[BaseModel] = DedupToolInput

    # Google Sheets integration (holds GoogleAuthHandler)
    auth: Optional[GoogleAuthHandler] = None
    sheet_id: Optional[str] = None

    def __init__(self, auth: Optional[GoogleAuthHandler] = None, sheets_id: Optional[str] = None):
        super().__init__()
        self.auth = auth
        self.sheet_id = sheets_id  # Use provided sheets_id or None
        logger.info(f"DedupTool initialized with auth: {auth is not None}, sheets_id: {sheets_id}")

    def _get_sheet_id(self) -> Optional[str]:
        """Get sheet ID from user_agent_tables, preferring the provided sheets_id."""
        if self.sheet_id is None:
            try:
                # Get sheet_id from user_agent_tables using the auth handler's user context
                if self.auth and hasattr(self.auth, 'user_id') and hasattr(self.auth, 'org_id') and hasattr(self.auth, 'agent_task_id'):
                    from src.services.database_service_new import get_database_service
                    db_service = get_database_service()
                    
                    # Query user_agent_tables for sheets_id
                    query = """
                    SELECT sheets_id 
                    FROM user_agent_task 
                    WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
                    AND sheets_id IS NOT NULL AND sheets_id != ''
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                    rows = db_service.execute_query(query, {
                        'user_id': self.auth.user_id,
                        'org_id': self.auth.org_id, 
                        'agent_task_id': self.auth.agent_task_id
                    })
                    
                    if rows and len(rows) > 0:
                        self.sheet_id = rows[0][0] if isinstance(rows[0], (list, tuple)) else rows[0].get('sheets_id')
                        logger.info(f"Loaded sheet_id from user_agent_tables: {self.sheet_id}")
                    else:
                        logger.warning("No sheets_id found in user_agent_tables")
                        self.sheet_id = None
                else:
                    logger.warning("Auth handler missing required user context for database lookup")
                    self.sheet_id = None
            except Exception as e:
                logger.warning(f"Failed to get sheet_id from user_agent_tables: {e}")
                self.sheet_id = None
        else:
            logger.info(f"Using provided sheets_id: {self.sheet_id}")
        return self.sheet_id

    def _run(
        self,
        summary_data: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """Process meeting summary and extract/deduplicate tasks."""
        try:
            # Parse the summary data
            if isinstance(summary_data, str):
                try:
                    logger.info(f"Attempting to parse JSON string: {summary_data[:200]}...")
                    # Try to clean the JSON string first
                    cleaned_json = summary_data.strip()
                    data = json.loads(cleaned_json)
                    logger.info(f"Successfully parsed JSON. Keys: {list(data.keys())}")
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing failed: {e}")
                    logger.error(f"Raw string: {summary_data[:500]}...")
                    # Try to fix common JSON issues
                    try:
                        # Fix invalid escape sequences
                        fixed_json = summary_data
                        # Fix invalid \' escape sequences
                        fixed_json = fixed_json.replace('\\\'', "'")
                        # Fix any other invalid escape sequences
                        import re
                        # Replace invalid escape sequences with valid ones
                        fixed_json = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', fixed_json)
                        data = json.loads(fixed_json)
                        logger.info(f"Successfully parsed after fixing JSON. Keys: {list(data.keys())}")
                    except json.JSONDecodeError as e2:
                        logger.error(f"JSON parsing still failed after fixes: {e2}")
                        # Try one more approach - use ast.literal_eval for safer parsing
                        try:
                            import ast
                            # Convert to Python dict and back to JSON
                            python_dict = ast.literal_eval(summary_data.replace('\\\'', "'"))
                            data = python_dict
                            logger.info(f"Successfully parsed using ast.literal_eval. Keys: {list(data.keys())}")
                        except Exception as e3:
                            logger.error(f"All parsing methods failed: {e3}")
                            # If not JSON, treat as raw summary text
                            data = {"summary_content": summary_data}
            else:
                data = summary_data

            # Extract tasks from the summary
            tasks = self._extract_tasks_from_summary(data)

            if not tasks:
                return json.dumps({
                    "status": "no_tasks_found",
                    "message": "No tasks were extracted from the summary",
                    "timestamp": datetime.now().isoformat()
                })

            # Process each task through deduplication
            processed_tasks = []
            for task in tasks:
                result = self._process_single_task(task)
                processed_tasks.append(result)

            # Compile results
            total_tasks = len(tasks)
            added_tasks = sum(1 for t in processed_tasks if t["decision"] == "ADDED")
            discarded_tasks = sum(1 for t in processed_tasks if t["decision"] == "DISCARDED")

            # Send tasks to task management API
            api_result = self._send_tasks_to_api(data, processed_tasks)

            return json.dumps({
                "status": "success",
                "total_tasks_processed": total_tasks,
                "tasks_added": added_tasks,
                "tasks_discarded": discarded_tasks,
                "processed_tasks": processed_tasks,
                "api_result": api_result,
                "timestamp": datetime.now().isoformat()
            })

        except Exception as e:
            logger.error(f"DedupTool error: {e}")
            return json.dumps({
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

    async def _arun(
        self,
        summary_data: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """Execute deduplication operations asynchronously."""
        return self._run(summary_data, run_manager)

    def _extract_tasks_from_summary(self, summary_data: Dict[str, Any]) -> List[TaskData]:
        """Extract tasks from meeting summary data using the new JSON format from summarizer tool."""
        tasks = []

        # Debug logging
        logger.info(f"Processing summary data with keys: {list(summary_data.keys())}")
        logger.info(f"Summary data type: {type(summary_data)}")
        logger.info(f"Full summary_data structure: {json.dumps(summary_data, indent=2)[:1000]}...")

        # Extract tasks from the new JSON format
        # Handle nested structure from summarizer tool
        if "summarizer_tool_response" in summary_data:
            summarizer_data = summary_data["summarizer_tool_response"]
            tasks_list = summarizer_data.get("tasks", [])
            # Also get meeting metadata from nested structure
            meeting_metadata = summarizer_data.get("meeting_metadata", {})
            meeting_title = meeting_metadata.get("title", summarizer_data.get("event_title", "Unknown Meeting"))
            logger.info(f"Found summarizer_tool_response with {len(tasks_list)} tasks, meeting_title: '{meeting_title}'")
        else:
            # Direct format - check if it's already the summarizer output
            tasks_list = summary_data.get("tasks", [])
            meeting_metadata = summary_data.get("meeting_metadata", {})
            meeting_title = meeting_metadata.get("title", summary_data.get("event_title", "Unknown Meeting"))
            logger.info(f"Direct format with {len(tasks_list)} tasks, meeting_title: '{meeting_title}'")
        
        # Fallback: Try to get meeting title from database if still "Unknown Meeting"
        if meeting_title == "Unknown Meeting" and self.auth:
            try:
                if hasattr(self.auth, 'user_id') and hasattr(self.auth, 'org_id') and hasattr(self.auth, 'agent_task_id'):
                    user_id = self.auth.user_id
                    agent_task_id = self.auth.agent_task_id
                    
                    from src.services.database_service_new import get_database_service
                    db_service = get_database_service()
                    
                    meetings_query = """
                    SELECT title
                    FROM meetings
                    WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                      AND start_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                    ORDER BY start_time DESC
                    LIMIT 1
                    """
                    meetings = db_service.execute_query(meetings_query, {
                        "user_id": user_id,
                        "agent_task_id": agent_task_id
                    })
                    
                    if meetings and len(meetings) > 0:
                        meeting_row = meetings[0]
                        # Handle different row types
                        if hasattr(meeting_row, '_mapping'):
                            db_meeting_title = meeting_row.title
                        elif isinstance(meeting_row, dict):
                            db_meeting_title = meeting_row.get("title")
                        else:
                            db_meeting_title = meeting_row[0] if len(meeting_row) > 0 else None
                        
                        if db_meeting_title and db_meeting_title != "Unknown Meeting":
                            meeting_title = db_meeting_title
                            logger.info(f"[SUCCESS] Fetched meeting_title from database in _extract_tasks_from_summary: '{meeting_title}'")
            except Exception as e:
                logger.warning(f"Error fetching meeting title from database in _extract_tasks_from_summary: {e}")

        # If no tasks found, try to extract from other possible structures
        if not tasks_list:
            # Check for summary_content key first
            if "summary_content" in summary_data:
                summary_content = summary_data["summary_content"]
                logger.info(f"Found summary_content, parsing it...")
                # Try to parse summary_content as JSON
                try:
                    if isinstance(summary_content, str):
                        content_data = json.loads(summary_content)
                    else:
                        content_data = summary_content
                    
                    # Look for tasks in the parsed content
                    if "summarizer_tool_response" in content_data:
                        summarizer_data = content_data["summarizer_tool_response"]
                        tasks_list = summarizer_data.get("tasks", [])
                        meeting_metadata = summarizer_data.get("meeting_metadata", {})
                        meeting_title = meeting_metadata.get("title", "Unknown Meeting")
                        logger.info(f"Found {len(tasks_list)} tasks in summary_content")
                    else:
                        tasks_list = content_data.get("tasks", [])
                        meeting_metadata = content_data.get("meeting_metadata", {})
                        meeting_title = meeting_metadata.get("title", "Unknown Meeting")
                        logger.info(f"Found {len(tasks_list)} tasks directly in summary_content")
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Failed to parse summary_content: {e}")
                    tasks_list = []
            
            # Check for alternative task structures
            if not tasks_list and "action_items" in summary_data:
                tasks_list = summary_data["action_items"]
                logger.info(f"Found action_items with {len(tasks_list)} items")
            elif not tasks_list and "action_items" in summary_data.get("meeting_metadata", {}):
                tasks_list = summary_data["meeting_metadata"]["action_items"]
                logger.info(f"Found action_items in meeting_metadata with {len(tasks_list)} items")
            elif not tasks_list and "decisions" in summary_data and summary_data["decisions"]:
                # Convert decisions to tasks
                tasks_list = []
                for decision in summary_data["decisions"]:
                    if isinstance(decision, dict):
                        tasks_list.append({
                            "title": decision.get("decision", "Decision"),
                            "description": decision.get("context", ""),
                            "assignee_name": ", ".join(decision.get("participants_involved", [])),
                            "priority": "medium",
                            "task_status": "todo",
                            "end_date": ""
                        })
                logger.info(f"Converted {len(tasks_list)} decisions to tasks")

        if not tasks_list:
            logger.error("No tasks found in summary data after checking all possible structures")
            logger.error(f"Available keys in summary_data: {list(summary_data.keys())}")
            raise ValueError("No valid task data found in summary")

        logger.info(f"Processing {len(tasks_list)} tasks from JSON format for meeting: {meeting_title}")
        
        # Store the final meeting_title for use in task creation
        final_meeting_title = meeting_title

        for i, task_item in enumerate(tasks_list):
            if isinstance(task_item, dict):
                # Extract task information directly from summarizer output - preserve all fields
                task_title = task_item.get("title", "")
                description = task_item.get("description", "")

                # Use title as task_text for deduplication, but preserve original structure
                if not task_title:
                    if description:
                        task_title = description
                else:
                        continue  # Skip tasks without title or description

                # Extract assignee information
                assignee_name = task_item.get("assignee_name", "")
                assignees = [assignee_name] if assignee_name else []

                # Extract priority and status
                priority = task_item.get("priority", "medium")
                task_status = task_item.get("task_status", "todo")

                # Extract due date
                due_date = task_item.get("end_date", "")

                # Create task data - preserve original task_item for later use
                task = TaskData(
                    task_id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(tasks)}",
                    task_text=task_title,  # Use title as task_text for deduplication
                    meeting_title=final_meeting_title,
                    assignees=assignees,
                    priority_level=priority,
                    due_date=due_date if due_date else None,
                    status=task_status,
                    original_task_item=task_item  # Store original structure from summarizer
                )
                tasks.append(task)
                logger.info(f"Extracted task {len(tasks)}: title='{task_title[:50]}...', description='{description[:50] if description else 'N/A'}...'")

                # Note: Sub-tasks are preserved in original_task_item and will be extracted later
                # when preparing for platform API to maintain nested structure
            else:
                logger.warning(f"Task item {i} is not a dictionary: {type(task_item)}")

        logger.info(f"Total tasks extracted: {len(tasks)}")
        return tasks

    def _extract_tasks_from_text(self, text: str) -> List[str]:
        """Extract task-like items from text using pattern matching."""
        tasks = []

        # Common task patterns
        patterns = [
            r"- \[ \] (.+)",  # Checkbox tasks
            r"- (.+)",        # Bullet points
            r"• (.+)",        # Bullet points
            r"(\d+\.\s*)(.+)", # Numbered items
            r"(COMPLETED|TASK|ACTION):\s*(.+)",  # Explicit task markers
            r"([A-Z][^.!?]*\b(?:will|should|need to|must|have to)\b[^.!?]*[.!?]?)",  # Action sentences
            r"([A-Z][^.!?]*\b(?:discussed|assigned|planned|decided|agreed)\b[^.!?]*[.!?]?)",  # Meeting action sentences
        ]

        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            for pattern in patterns:
                matches = re.findall(pattern, line, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        task_text = match[-1].strip()  # Take the last group
                    else:
                        task_text = match.strip()

                    if task_text and len(task_text) > 5:  # Reduced minimum length filter
                        tasks.append(task_text)

        # If no patterns matched, try to extract meaningful sentences as potential tasks
        if not tasks and len(text) > 20:
            sentences = re.split(r'[.!?]+', text)
            for sentence in sentences:
                sentence = sentence.strip()
                if (len(sentence) > 10 and
                    any(keyword in sentence.lower() for keyword in ['task', 'goal', 'action', 'plan', 'discuss', 'assign', 'decide', 'agree'])):
                    tasks.append(sentence)

        return list(set(tasks))  # Remove duplicates

    def _ensure_sheet_structure(self, sheets_service) -> bool:
        """Ensure the Google Sheet has the correct structure with stable columns."""
        try:
            # Define stable column structure aligned with GoogleSheetsService
            headers = [
                "Task ID", "Task Text", "Meeting Title",
                "Assignees", "Priority Level", "Due Date", "Status",
                "Created Date"
            ]

            # Check if sheet exists and has headers
            try:
                result = sheets_service.spreadsheets().values().get(
                    spreadsheetId=self._get_sheet_id(),
                    range="A1:H1"
                ).execute()

                existing_headers = result.get('values', [[]])[0] if result.get('values') else []

                # If headers don't match, update them
                if existing_headers != headers:
                    logger.info("[LIST] Setting up stable column structure...")
                    sheets_service.spreadsheets().values().update(
                        spreadsheetId=self._get_sheet_id(),
                        range="A1:H1",
                        valueInputOption="RAW",
                        body={"values": [headers]}
                    ).execute()
                    logger.info("[OK] Sheet structure initialized")

            except Exception as e:
                logger.error(f"Error checking sheet structure: {e}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error ensuring sheet structure: {e}")
            return False

    def _get_existing_task_hashes(self, sheets_service) -> set:
        """Get all existing task texts for idempotent deduplication (column B)."""
        try:
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="B:B"  # Task Text column after header update
            ).execute()

            rows = result.get('values', [])
            # Skip header row and extract task texts
            texts = set()
            for row in rows[1:]:  # Skip header
                if row and len(row) > 0 and row[0]:
                    texts.add(row[0])

            logger.info(f"[DATA] Found {len(texts)} existing task texts")
            return texts

        except Exception as e:
            logger.error(f"Error getting existing hashes: {e}")
            return set()

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two task texts."""
        # Normalize texts
        norm1 = text1.lower().strip()
        norm2 = text2.lower().strip()

        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, norm1, norm2).ratio()

    def _find_similar_tasks(self, task: TaskData, sheets_service) -> tuple:
        """Find similar existing tasks and return best match info."""
        try:
            # Get all existing tasks
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A:H"  # All columns after header update
            ).execute()

            rows = result.get('values', [])
            if len(rows) <= 1:  # Only header or empty
                return 0.0, ""

            best_similarity = 0.0
            best_match = ""

            # Compare with existing tasks (skip header)
            for row in rows[1:]:
                if len(row) >= 2:  # Ensure we have task text
                    existing_text = row[1]  # Task Text column (B)
                    similarity = self._calculate_similarity(task.task_text, existing_text)

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = existing_text

            return best_similarity, best_match

        except Exception as e:
            logger.error(f"Error finding similar tasks: {e}")
            return 0.0, ""

    def _process_single_task(self, task: TaskData) -> Dict[str, Any]:
        """Process a single task through the idempotent deduplication pipeline."""
        try:
            if not self._get_sheet_id():
                return {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "decision": "ERROR",
                    "confidence": 0.0,
                    "matched_text": "",
                    "error": "No Google Sheet configured"
                }

            # Get the Google Sheet service
            from src.auth.google_auth_handler import GoogleAuthHandler
            authenticator = self.auth
            sheets_service = authenticator.get_sheets_service()

            if not sheets_service:
                return {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "decision": "ERROR",
                    "confidence": 0.0,
                    "matched_text": "",
                    "error": "Could not access Google Sheets"
                }

            # Ensure sheet has proper structure
            if not self._ensure_sheet_structure(sheets_service):
                return {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "decision": "ERROR",
                    "confidence": 0.0,
                    "matched_text": "",
                    "error": "Could not setup sheet structure"
                }

            # Step 1: Check for exact hash match (idempotent)
            existing_texts = self._get_existing_task_hashes(sheets_service)
            if task.task_text in existing_texts:
                logger.info(f" Task already exists (exact text match): {task.task_text[:50]}...")
                result = {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "meeting_title": task.meeting_title,
                    "assignees": task.assignees,
                    "priority_level": task.priority_level,
                    "decision": "DISCARDED",
                    "confidence": 1.0,
                    "matched_text": "[exact text match]",
                    "timestamp": datetime.now().isoformat()
                }
                # Include original_task_item if available
                if hasattr(task, 'original_task_item') and task.original_task_item:
                    result["original_task_item"] = task.original_task_item
                return result

            # Step 2: Check for semantic similarity
            similarity, matched_text = self._find_similar_tasks(task, sheets_service)

            # Decision thresholds
            HIGH_DISCARD_THRESHOLD = 0.85

            if similarity >= HIGH_DISCARD_THRESHOLD:
                logger.info(f" Task discarded (similar): {task.task_text[:50]}... (similarity: {similarity:.2f})")
                result = {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "meeting_title": task.meeting_title,
                    "assignees": task.assignees,
                    "priority_level": task.priority_level,
                    "decision": "DISCARDED",
                    "confidence": similarity,
                    "matched_text": matched_text,
                    "timestamp": datetime.now().isoformat()
                }
                # Include original_task_item if available
                if hasattr(task, 'original_task_item') and task.original_task_item:
                    result["original_task_item"] = task.original_task_item
                return result

            # Step 3: Add new task to sheet
            try:
                # Align with Google Sheets headers: Task ID, Task Text, Meeting Title, Assignees, Priority Level, Due Date, Status, Created Date
                new_row = [
                    task.task_id,                    # Column A: Task ID
                    task.task_text,                  # Column B: Task Text
                    task.meeting_title,              # Column C: Meeting Title
                    ", ".join(task.assignees) if task.assignees else "",  # Column D: Assignees
                    task.priority_level,             # Column E: Priority Level
                    task.due_date or "",             # Column F: Due Date
                    task.status,                     # Column G: Status
                    task.created_at,                 # Column H: Created Date
                ]

                # Append to sheet with retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        sheets_service.spreadsheets().values().append(
                            spreadsheetId=self._get_sheet_id(),
                            range="A:H",
                            valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS",
                            body={"values": [new_row]}
                        ).execute()

                        logger.info(f"[OK] Added task to sheet: {task.task_text[:50]}... (attempt {attempt + 1})")
                        break

                    except Exception as e:
                        if attempt == max_retries - 1:
                            raise e
                        logger.warning(f"[WARN] Retry {attempt + 1} for task addition: {e}")

                result = {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "meeting_title": task.meeting_title,
                    "assignees": task.assignees,
                    "priority_level": task.priority_level,
                    "decision": "ADDED",
                    "confidence": similarity,
                    "matched_text": matched_text,
                    "timestamp": datetime.now().isoformat()
                }
                # Include original_task_item if available
                if hasattr(task, 'original_task_item') and task.original_task_item:
                    result["original_task_item"] = task.original_task_item
                return result

            except Exception as e:
                logger.error(f" Error adding task to sheet: {e}")
                return {
                    "task_id": task.task_id,
                    "task_text": task.task_text,
                    "decision": "ERROR",
                    "confidence": 0.0,
                    "matched_text": "",
                    "error": f"Failed to add to sheet: {str(e)}"
                }

        except Exception as e:
            logger.error(f" Error processing task: {e}")
            return {
                "task_id": task.task_id,
                "task_text": task.task_text,
                "decision": "ERROR",
                "confidence": 0.0,
                "matched_text": "",
                "error": str(e)
            }

    def _send_tasks_to_api(self, summary_data: Dict[str, Any], processed_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send processed tasks using unified task service (both Sheets and Platform)."""
        try:
            from src.services.integration.unified_task_service import get_unified_task_service

            # Get user context from auth handler if available, otherwise from summary data
            if self.auth and hasattr(self.auth, 'user_id') and hasattr(self.auth, 'org_id') and hasattr(self.auth, 'agent_task_id'):
                user_id = self.auth.user_id
                org_id = self.auth.org_id
                agent_task_id = self.auth.agent_task_id
                logger.info(f"Using user context from auth handler: {user_id}/{org_id}/{agent_task_id}")
            else:
                # Fallback to summary data
                user_id = summary_data.get("user_id", "unknown")
                org_id = summary_data.get("org_id", "default_org")
                agent_task_id = summary_data.get("agent_task_id", "default_task")
                logger.warning(f"Using fallback user context from summary data: {user_id}/{org_id}/{agent_task_id}")

            # Create unified task service
            task_service = get_unified_task_service(
                user_id=user_id,
                org_id=org_id,
                agent_task_id=agent_task_id,
                google_auth=self.auth
            )

            # Extract meeting title from nested structures (same logic as _extract_tasks_from_summary)
            meeting_title = "Unknown Meeting"
            attendees = []
            
            # Try to get meeting title from various possible locations
            logger.info(f"Attempting to extract meeting_title from summary_data. Available keys: {list(summary_data.keys())}")
            
            if "summarizer_tool_response" in summary_data:
                summarizer_data = summary_data["summarizer_tool_response"]
                meeting_metadata = summarizer_data.get("meeting_metadata", {})
                meeting_title = meeting_metadata.get("title", summarizer_data.get("event_title", "Unknown Meeting"))
                attendees = meeting_metadata.get("attendees", [])
                logger.info(f"Extracted meeting_title from summarizer_tool_response: '{meeting_title}' (from meeting_metadata: {meeting_metadata.get('title')}, event_title: {summarizer_data.get('event_title')})")
            elif "meeting_metadata" in summary_data:
                meeting_metadata = summary_data["meeting_metadata"]
                meeting_title = meeting_metadata.get("title", summary_data.get("event_title", "Unknown Meeting"))
                attendees = meeting_metadata.get("attendees", [])
                logger.info(f"Extracted meeting_title from meeting_metadata: '{meeting_title}' (from meeting_metadata: {meeting_metadata.get('title')}, event_title: {summary_data.get('event_title')})")
            elif "event_title" in summary_data:
                meeting_title = summary_data.get("event_title", "Unknown Meeting")
                attendees = summary_data.get("attendees", [])
                logger.info(f"Extracted meeting_title from event_title: '{meeting_title}'")
            elif "meeting_title" in summary_data:
                meeting_title = summary_data.get("meeting_title", "Unknown Meeting")
                attendees = summary_data.get("attendees", [])
                logger.info(f"Extracted meeting_title from meeting_title: '{meeting_title}'")
            else:
                # Fallback: Try to get from first task if available
                if processed_tasks and len(processed_tasks) > 0:
                    first_task = processed_tasks[0]
                    task_meeting_title = first_task.get("meeting_title") or first_task.get("meeting_title", "")
                    if task_meeting_title and task_meeting_title != "Unknown Meeting":
                        meeting_title = task_meeting_title
                        logger.info(f"Extracted meeting_title from first task: '{meeting_title}'")
                    else:
                        logger.warning(f"Could not extract meeting_title from summary_data. Keys available: {list(summary_data.keys())}. Using 'Unknown Meeting'")
                else:
                    logger.warning(f"Could not extract meeting_title from summary_data and no tasks available. Keys: {list(summary_data.keys())}. Using 'Unknown Meeting'")
            
            # Final fallback: Try to get meeting title from database if still "Unknown Meeting"
            if meeting_title == "Unknown Meeting":
                try:
                    # Get user context from auth handler
                    if self.auth and hasattr(self.auth, 'user_id') and hasattr(self.auth, 'org_id') and hasattr(self.auth, 'agent_task_id'):
                        user_id = self.auth.user_id
                        org_id = self.auth.org_id
                        agent_task_id = self.auth.agent_task_id
                        
                        # Query meetings table for the most recent meeting
                        from src.services.database_service_new import get_database_service
                        db_service = get_database_service()
                        
                        meetings_query = """
                        SELECT title, attendees
                        FROM meetings
                        WHERE user_id = :user_id AND agent_task_id = :agent_task_id
                          AND start_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                        ORDER BY start_time DESC
                        LIMIT 1
                        """
                        meetings = db_service.execute_query(meetings_query, {
                            "user_id": user_id,
                            "agent_task_id": agent_task_id
                        })
                        
                        if meetings and len(meetings) > 0:
                            meeting_row = meetings[0]
                            # Handle different row types
                            if hasattr(meeting_row, '_mapping'):
                                # SQLAlchemy Row object
                                db_meeting_title = meeting_row.title
                                db_attendees = meeting_row.attendees
                            elif isinstance(meeting_row, dict):
                                # Dictionary access
                                db_meeting_title = meeting_row.get("title")
                                db_attendees = meeting_row.get("attendees")
                            else:
                                # Tuple/list access (fallback)
                                db_meeting_title = meeting_row[0] if len(meeting_row) > 0 else None
                                db_attendees = meeting_row[1] if len(meeting_row) > 1 else None
                            
                            if db_meeting_title and db_meeting_title != "Unknown Meeting":
                                meeting_title = db_meeting_title
                                logger.info(f"[SUCCESS] Fetched meeting_title from database: '{meeting_title}'")
                                
                                # Also update attendees if not already set
                                if not attendees and db_attendees:
                                    try:
                                        if isinstance(db_attendees, str):
                                            attendees = json.loads(db_attendees)
                                        else:
                                            attendees = db_attendees
                                    except (json.JSONDecodeError, TypeError):
                                        attendees = []
                            else:
                                logger.warning(f"Database meeting title is also 'Unknown Meeting' or None")
                        else:
                            logger.warning(f"No meetings found in database for user {user_id}, agent_task {agent_task_id}")
                    else:
                        logger.warning("Auth handler missing required user context for database lookup")
                except Exception as e:
                    logger.error(f"Error fetching meeting title from database: {e}")
            
            # Final validation - log if we still have "Unknown Meeting"
            if meeting_title == "Unknown Meeting":
                logger.error(f"[WARNING] Meeting title is still 'Unknown Meeting' after all extraction attempts including database lookup. Summary data structure: {json.dumps(summary_data, indent=2)[:500]}")
            else:
                logger.info(f"[SUCCESS] Successfully extracted meeting_title: '{meeting_title}'")
            
            # Prepare meeting data with extracted information
            meeting_data = {
                "id": summary_data.get("meeting_id", f"M-{datetime.now().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}"),
                "title": meeting_title,
                "attendees": attendees if attendees else summary_data.get("attendees", []),
                "executive_summary": summary_data.get("executive_summary", ""),
                "video_url": summary_data.get("video_url", ""),
                "transcript_url": summary_data.get("transcript_url", "")
            }
            
            logger.info(f"Final meeting_data: title='{meeting_data['title']}', attendees={len(meeting_data['attendees'])}")

            # Prepare raw tasks for processing - preserve nested subtask structure
            # First, get the original task structure from summary_data to preserve subtasks
            original_tasks_map = {}
            if "summarizer_tool_response" in summary_data:
                summarizer_data = summary_data["summarizer_tool_response"]
                original_tasks_list = summarizer_data.get("tasks", [])
            else:
                original_tasks_list = summary_data.get("tasks", [])
            
            # Create a map of task titles to original task structures (for subtask preservation)
            for orig_task in original_tasks_list:
                if isinstance(orig_task, dict):
                    task_title = orig_task.get("title", "")
                    if task_title:
                        original_tasks_map[task_title] = orig_task
            
            raw_tasks = []
            processed_task_map = {}  # Map to track which processed tasks are main tasks vs subtasks
            
            # First pass: identify main tasks (those that don't start with "[Sub-task]")
            for task in processed_tasks:
                task_text = task.get("task_text", "")
                if not task_text or task_text.startswith("[Sub-task]"):
                    continue  # Skip subtasks in first pass
                
                # Get original task structure - prefer from task dict, fallback to map
                original_task = None
                if "original_task_item" in task and task.get("original_task_item"):
                    original_task = task.get("original_task_item")
                else:
                    # Fallback: try to find in original_tasks_map
                    for orig_title, orig_task_data in original_tasks_map.items():
                        if orig_title in task_text or task_text.startswith(orig_title):
                            original_task = orig_task_data
                            break
                
                # Use original task structure directly from summarizer - all fields dynamic
                if original_task:
                    # Extract assignee from original task or processed task
                    assignee_name = original_task.get("assignee_name", "")
                    if not assignee_name:
                        # Try to get assignee from task object if not in original_task
                        if "assignees" in task:
                            if isinstance(task["assignees"], list):
                                assignee_name = ", ".join([str(a) for a in task["assignees"] if a])
                            else:
                                assignee_name = str(task["assignees"]) if task["assignees"] else ""
                        elif "assignee" in task:
                            assignee_name = str(task["assignee"]) if task["assignee"] else ""
                        elif "assignee_name" in task:
                            assignee_name = str(task["assignee_name"]) if task["assignee_name"] else ""
                    
                    task_meeting_title = task.get("meeting_title", meeting_title)
                    if task_meeting_title == "Unknown Meeting" and meeting_title != "Unknown Meeting":
                        task_meeting_title = meeting_title
                    
                    # Use all fields directly from original task structure (dynamic from summarizer)
                    raw_task = {
                        "title": original_task.get("title", task_text),  # Use original title from summarizer
                        "description": original_task.get("description", ""),  # Use original description from summarizer
                        "expected_outcome": original_task.get("expected_outcome", ""),  # Use original expected_outcome from summarizer
                        "assignee_name": assignee_name or original_task.get("assignee_name", ""),
                        "priority": original_task.get("priority", task.get("priority", task.get("priority_level", "medium"))),
                        "task_status": original_task.get("task_status", task.get("status", "todo")),
                        "end_date": original_task.get("end_date", task.get("due_date", "")),
                        "meeting_title": task_meeting_title,
                        "decision": task.get("decision", "unknown"),
                        "confidence": task.get("confidence", 0.0),
                        "sub_tasks": []
                    }
                    
                    # Add subtasks from original task structure - all fields dynamic from summarizer
                    if "sub_tasks" in original_task:
                        for sub_task_item in original_task["sub_tasks"]:
                            if isinstance(sub_task_item, dict):
                                raw_task["sub_tasks"].append({
                                    "title": sub_task_item.get("title", ""),  # Dynamic from summarizer
                                    "description": sub_task_item.get("description", ""),  # Dynamic from summarizer
                                    "expected_outcome": sub_task_item.get("expected_outcome", ""),  # Dynamic from summarizer
                                    "assignee_name": sub_task_item.get("assignee_name", assignee_name),
                                    "priority": sub_task_item.get("priority", raw_task["priority"]),
                                    "task_status": sub_task_item.get("task_status", "todo"),
                                    "end_date": sub_task_item.get("end_date", "")
                                })
                else:
                    # Fallback if original task structure not available
                    assignee_name = ""
                    if "assignees" in task:
                        if isinstance(task["assignees"], list):
                            assignee_name = ", ".join([str(a) for a in task["assignees"] if a])
                        else:
                            assignee_name = str(task["assignees"]) if task["assignees"] else ""
                    elif "assignee" in task:
                        assignee_name = str(task["assignee"]) if task["assignee"] else ""
                    elif "assignee_name" in task:
                        assignee_name = str(task["assignee_name"]) if task["assignee_name"] else ""
                    
                    task_meeting_title = task.get("meeting_title", meeting_title)
                    if task_meeting_title == "Unknown Meeting" and meeting_title != "Unknown Meeting":
                        task_meeting_title = meeting_title
                    
                    raw_task = {
                    "title": task_text,
                    "description": task_text,
                        "expected_outcome": "",
                    "assignee_name": assignee_name,
                        "priority": task.get("priority", task.get("priority_level", "medium")),
                        "task_status": task.get("status", "todo"),
                        "end_date": task.get("due_date", ""),
                        "meeting_title": task_meeting_title,
                    "decision": task.get("decision", "unknown"),
                        "confidence": task.get("confidence", 0.0),
                        "sub_tasks": []
                    }
                
                raw_tasks.append(raw_task)
                processed_task_map[task_text] = raw_task
                
                logger.debug(f"Task prepared: title='{raw_task['title'][:50]}...', description='{raw_task['description'][:50] if raw_task.get('description') else 'N/A'}...', expected_outcome='{raw_task.get('expected_outcome', '')[:50] if raw_task.get('expected_outcome') else 'N/A'}...', assignee='{raw_task['assignee_name']}', subtasks={len(raw_task['sub_tasks'])}")

            if not raw_tasks:
                return {
                    "success": True,
                    "message": "No tasks to process",
                    "tasks_sent": 0
                }

            # Process and distribute tasks using unified service
            import asyncio
            result = asyncio.run(task_service.process_and_distribute_tasks(meeting_data, raw_tasks))

            return {
                "success": result.get("success", False),
                "message": result.get("message", "Tasks processed"),
                "tasks_sent": result.get("deduplicated_count", 0),
                "sheets_result": result.get("results", {}).get("google_sheets", {}),
                "platform_result": result.get("results", {}).get("platform_webhook", {})
            }

        except Exception as e:
            logger.error(f"Failed to send tasks via unified service: {e}")
            return {
                "success": False,
                "error": str(e)
            }