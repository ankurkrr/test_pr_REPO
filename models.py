"""
Database Models

Contains all database models and data classes used throughout the application.
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, Any, Optional, List

@dataclass
class WorkflowData:
    """Workflow execution data"""
    id: str
    agent_id: str
    user_id: Optional[str] = None
    workflow_type: str = '7_step_meeting_workflow'
    status: str = 'running'
    input_parameters: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    meetings_processed: int = 0

@dataclass
class MeetingData:
    """Meeting metadata aligned with `meetings` table"""
    id: str
    user_id: str
    organization_id: str
    agent_task_id: str
    external_id: Optional[str] = None
    title: str = ''
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None
    location: Optional[str] = None
    meeting_url: Optional[str] = None
    status: str = 'scheduled'
    attendees: Optional[List[str]] = None  # List of attendee email addresses
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class SummaryData:
    """Meeting summary data aligned with `meeting_summaries` table"""
    id: str
    meeting_id: str
    user_id: str
    summary_type: str = 'executive'
    content: str = ''
    word_count: Optional[int] = None
    ai_model: Optional[str] = None
    generation_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class TaskData:
    """Meeting task data aligned with `tasks` table"""
    id: str
    user_id: str
    organization_id: str
    agent_task_id: str
    meeting_id: Optional[str] = None
    title: str = ''
    description: Optional[str] = None
    assignee_email: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: str = 'medium'
    status: str = 'pending'
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    external_task_id: Optional[str] = None
    external_system: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None