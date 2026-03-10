"""
Workflow Repository

Handles all workflow-related database operations.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from ..models import WorkflowData

logger = logging.getLogger(__name__)

class WorkflowRepository:
    """Repository for workflow data operations"""

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def create_workflow(self, workflow_data: WorkflowData) -> str:
        """Create a new workflow record"""
        try:
            query = """
                INSERT INTO workflow_data (agent_task_id, user_id, org_id, workflow_data, timezone, notify_to, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  workflow_data = VALUES(workflow_data),
                  timezone = VALUES(timezone),
                  notify_to = VALUES(notify_to),
                  updated_at = VALUES(updated_at)
            """
            params = (
                workflow_data.agent_id,
                workflow_data.user_id,
                "default_org",  # Could be passed as parameter
                json.dumps(workflow_data.input_parameters or {}),
                None,  # timezone
                None,  # notify_to
                datetime.now(),
                datetime.now()
            )

            self.db_session.execute(text(query), params)
            self.db_session.commit()
            return workflow_data.agent_id
        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            self.db_session.rollback()
            raise

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowData]:
        """Get workflow by ID"""
        try:
            query = "SELECT * FROM workflow_data WHERE agent_task_id = %s"
            result = self.db_session.execute(text(query), (workflow_id,)).fetchone()

            if result:
                return WorkflowData(
                    id=result[0],
                    agent_id=result[1],
                    user_id=result[2],
                    workflow_type=result[3] or '7_step_meeting_workflow',
                    status=result[4] or 'running',
                    input_parameters=json.loads(result[5]) if result[5] else None,
                    results=json.loads(result[6]) if result[6] else None,
                    error_message=result[7],
                    meetings_processed=result[8] or 0
                )
            return None
        except Exception as e:
            logger.error(f"Error getting workflow: {e}")
            return None

    def update_workflow_status(self, workflow_id: str, status: str, error_message: Optional[str] = None) -> bool:
        """Update workflow status"""
        try:
            query = """
                UPDATE workflow_data
                SET status = %s, error_message = %s, updated_at = %s
                WHERE agent_task_id = %s
            """
            params = (status, error_message, datetime.now(), workflow_id)

            result = self.db_session.execute(text(query), params)
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating workflow status: {e}")
            self.db_session.rollback()
            return False

    def store_workflow_data(
        self,
        user_id: str,
        org_id: str,
        agent_task_id: str,
        workflow_data: List[Dict[str, Any]],
        timezone: Optional[str] = None,
        notify_to: Optional[str] = None
    ) -> bool:
        """Store workflow data for a specific agent task"""
        try:
            # Check if workflow data already exists
            check_query = "SELECT id FROM workflow_data WHERE agent_task_id = %s"
            existing = self.db_session.execute(text(check_query), (agent_task_id,)).fetchone()

            if existing:
                # Update existing record
                update_query = """
                    UPDATE workflow_data
                    SET workflow_data = %s, timezone = %s, notify_to = %s, updated_at = %s
                    WHERE agent_task_id = %s
                """
                params = (
                    json.dumps(workflow_data),
                    timezone,
                    notify_to,
                    datetime.now(),
                    agent_task_id
                )
                self.db_session.execute(text(update_query), params)
            else:
                # Insert new record
                insert_query = """
                    INSERT INTO workflow_data (id, agent_task_id, user_id, org_id, workflow_data, timezone, notify_to, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    str(uuid.uuid4()),
                    agent_task_id,
                    user_id,
                    org_id,
                    json.dumps(workflow_data),
                    timezone,
                    notify_to,
                    datetime.now(),
                    datetime.now()
                )
                self.db_session.execute(text(insert_query), params)

            self.db_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error storing workflow data: {e}")
            self.db_session.rollback()
            return False

    def get_workflow_data(self, agent_task_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get workflow data for a specific agent task"""
        try:
            query = "SELECT workflow_data FROM workflow_data WHERE agent_task_id = %s"
            result = self.db_session.execute(text(query), (agent_task_id,)).fetchone()

            if result and result[0]:
                return json.loads(result[0])
            return None
        except Exception as e:
            logger.error(f"Error getting workflow data: {e}")
            return None

    def delete_workflow_data(self, agent_task_id: str) -> bool:
        """Delete workflow data for a specific agent task"""
        try:
            query = "DELETE FROM workflow_data WHERE agent_task_id = %s"
            result = self.db_session.execute(text(query), (agent_task_id,))
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting workflow data: {e}")
            self.db_session.rollback()
            return False