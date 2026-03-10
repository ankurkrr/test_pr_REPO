"""
Meeting Repository

Handles all meeting-related database operations.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from ..models import MeetingData, SummaryData

logger = logging.getLogger(__name__)

class MeetingRepository:
    """Repository for meeting data operations"""

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def create_meeting(self, meeting_data: MeetingData) -> str:
        """Create a new meeting record"""
        try:
            meeting_id = str(uuid.uuid4())
            # Serialize attendees list to JSON string for database storage
            attendees_json = json.dumps(meeting_data.attendees) if meeting_data.attendees else None
            
            self.db_session.execute(
                text(
                    """
                    INSERT INTO meetings (
                        id, user_id, org_id, agent_task_id, external_id,
                        title, description, start_time, end_time, timezone,
                        location, meeting_url, status, attendees, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :organization_id, :agent_task_id, :external_id,
                        :title, :description, :start_time, :end_time, :timezone,
                        :location, :meeting_url, :status, :attendees, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": meeting_id,
                    "user_id": meeting_data.user_id,
                    "organization_id": meeting_data.organization_id,
                    "agent_task_id": meeting_data.agent_task_id,
                    "external_id": meeting_data.external_id,
                    "title": meeting_data.title,
                    "description": meeting_data.description,
                    "start_time": meeting_data.start_time,
                    "end_time": meeting_data.end_time,
                    "timezone": meeting_data.timezone,
                    "location": meeting_data.location,
                    "meeting_url": meeting_data.meeting_url,
                    "status": meeting_data.status,
                    "attendees": attendees_json,
                    "created_at": meeting_data.created_at,
                    "updated_at": meeting_data.updated_at,
                },
            )
            self.db_session.commit()
            return meeting_id
        except Exception as e:
            logger.error(f"Error creating meeting: {e}")
            self.db_session.rollback()
            raise

    def get_meeting(self, meeting_id: str) -> Optional[MeetingData]:
        """Get meeting by ID"""
        try:
            result = self.db_session.execute(
                text(
                    """
                    SELECT id, user_id, org_id as organization_id, agent_task_id, external_id,
                           title, description, start_time, end_time, timezone,
                           location, meeting_url, status, attendees, created_at, updated_at
                    FROM meetings
                    WHERE id = :meeting_id
                    """
                ),
                {"meeting_id": meeting_id},
            ).fetchone()

            if result:
                # Deserialize attendees from JSON string
                attendees = None
                if hasattr(result, 'attendees') and result.attendees:
                    try:
                        attendees = json.loads(result.attendees)
                    except (json.JSONDecodeError, TypeError):
                        attendees = None
                
                return MeetingData(
                    id=result.id,
                    user_id=result.user_id,
                    organization_id=result.organization_id,
                    agent_task_id=result.agent_task_id,
                    external_id=result.external_id,
                    title=result.title,
                    description=result.description,
                    start_time=result.start_time,
                    end_time=result.end_time,
                    timezone=result.timezone,
                    location=result.location,
                    meeting_url=result.meeting_url,
                    status=result.status,
                    attendees=attendees,
                    created_at=result.created_at,
                    updated_at=result.updated_at,
                )
            return None
        except Exception as e:
            logger.error(f"Error getting meeting {meeting_id}: {e}")
            return None

    def update_meeting(self, meeting_id: str, updates: Dict[str, Any]) -> bool:
        """Update meeting data"""
        try:
            set_clauses = []
            params = {"meeting_id": meeting_id}

            for key, value in updates.items():
                if key in [
                    "title",
                    "description",
                    "start_time",
                    "end_time",
                    "timezone",
                    "location",
                    "meeting_url",
                    "status",
                ]:
                    set_clauses.append(f"{key} = :{key}")
                    params[key] = value

            if not set_clauses:
                return False

            set_clauses.append("updated_at = NOW()")

            result = self.db_session.execute(
                text(
                    f"""
                    UPDATE meetings
                    SET {', '.join(set_clauses)}
                    WHERE id = :meeting_id
                    """
                ),
                params,
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating meeting {meeting_id}: {e}")
            self.db_session.rollback()
            return False

    def get_meetings_by_workflow(self, workflow_id: str) -> List[MeetingData]:
        """Get all meetings for a workflow"""
        try:
            results = self.db_session.execute(
                text(
                    """
                    SELECT id, user_id, org_id as organization_id, agent_task_id, external_id,
                           title, description, start_time, end_time, timezone,
                           location, meeting_url, status, created_at, updated_at
                    FROM meetings
                    WHERE agent_task_id = :workflow_id
                    ORDER BY start_time ASC
                    """
                ),
                {"workflow_id": workflow_id},
            ).fetchall()

            meetings = []
            for result in results:
                meetings.append(
                    MeetingData(
                        id=result.id,
                        user_id=result.user_id,
                        organization_id=result.organization_id,
                        agent_task_id=result.agent_task_id,
                        external_id=result.external_id,
                        title=result.title,
                        description=result.description,
                        start_time=result.start_time,
                        end_time=result.end_time,
                        timezone=result.timezone,
                        location=result.location,
                        meeting_url=result.meeting_url,
                        status=result.status,
                        created_at=result.created_at,
                        updated_at=result.updated_at,
                    )
                )
            return meetings
        except Exception as e:
            logger.error(f"Error getting meetings for workflow {workflow_id}: {e}")
            return []

    def create_summary(self, summary_data: SummaryData) -> str:
        """Create a new summary record"""
        try:
            summary_id = str(uuid.uuid4())
            self.db_session.execute(
                text(
                    """
                    INSERT INTO meeting_summaries (
                        id, meeting_id, user_id, summary_type, content,
                        word_count, ai_model, generation_time_ms, created_at, updated_at
                    ) VALUES (
                        :id, :meeting_id, :user_id, :summary_type, :content,
                        :word_count, :ai_model, :generation_time_ms, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": summary_id,
                    "meeting_id": summary_data.meeting_id,
                    "user_id": summary_data.user_id,
                    "summary_type": summary_data.summary_type,
                    "content": summary_data.content,
                    "word_count": summary_data.word_count,
                    "ai_model": summary_data.ai_model,
                    "generation_time_ms": summary_data.generation_time_ms,
                    "created_at": summary_data.created_at,
                    "updated_at": summary_data.updated_at,
                },
            )
            self.db_session.commit()
            return summary_id
        except Exception as e:
            logger.error(f"Error creating summary: {e}")
            self.db_session.rollback()
            raise

    def get_summary(self, summary_id: str) -> Optional[SummaryData]:
        """Get summary by ID"""
        try:
            result = self.db_session.execute(
                text(
                    """
                    SELECT id, meeting_id, user_id, summary_type, content,
                           word_count, ai_model, generation_time_ms, created_at, updated_at
                    FROM meeting_summaries
                    WHERE id = :summary_id
                    """
                ),
                {"summary_id": summary_id},
            ).fetchone()

            if result:
                return SummaryData(
                    id=result.id,
                    meeting_id=result.meeting_id,
                    user_id=result.user_id,
                    summary_type=result.summary_type,
                    content=result.content,
                    word_count=result.word_count,
                    ai_model=result.ai_model,
                    generation_time_ms=result.generation_time_ms,
                    created_at=result.created_at,
                    updated_at=result.updated_at,
                )
            return None
        except Exception as e:
            logger.error(f"Error getting summary {summary_id}: {e}")
            return None