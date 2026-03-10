
"""
Agent Integration Service
Connects the new agent tables with LangChain agent flow
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import text

# from src.services.database_service import DatabaseService  # TODO: Replace with new service structure

logger = logging.getLogger(__name__)


class AgentIntegrationService:
    """Service for integrating agent tables with LangChain workflow"""

    def __init__(self):
        """Initialize the agent integration service"""
        from src.services.database_service_new import get_database_service
        self.db_service = get_database_service()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')


    def create_user_agent_task(self, user_id: str, task_name: str, description: str = None) -> str:
        """
        Create a new user agent task

        Args:
            user_id: User identifier
            task_name: Name of the task
            description: Task description

        Returns:
            Task ID if successful, None otherwise
        """
        try:
            # Ensure referenced agent exists (FK safety)
            self.ensure_agent_exists()

            task_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO user_agent_task (
                        agent_task_id, org_id, user_id, name, description,
                        ready_to_use, status
                    ) VALUES (
                        :task_id, :org_id, :user_id, :name, :description,
                        1, 1
                    )
                """)

                workflow_data = {
                    "task_type": "meeting_intelligence",
                    "created_at": datetime.now().isoformat(),
                    "steps_completed": 0,
                    "total_steps": 7
                }

                session.execute(insert_query, {
                    "task_id": task_id,
                    "org_id": self.org_id,
                    "user_id": user_id,
                    "name": task_name,
                    "description": description or f"Meeting intelligence task for {user_id}",
                    
                })
                session.commit()

                logger.info(f"Created user agent task: {task_id} for user: {user_id}")
                return task_id

        except Exception as e:
            logger.error(f"Failed to create user agent task: {e}")
            return None
    def ensure_agent_exists(self) -> None:
        """Ensure the agent row exists to satisfy foreign keys."""
        try:
            with self.db_service.get_session() as session:
                upsert = text(
                    """
                    INSERT INTO agent (id, org_id, name, agent_type, agent_used_for, status, created_by)
                    VALUES (:id, :org_id, :name, 'google_meeting', 'meeting_intelligence', 1, 'system')
                    ON DUPLICATE KEY UPDATE updated = CURRENT_TIMESTAMP(6)
                    """
                )
                session.execute(upsert, {
                    "id": self.agent_id,
                    "org_id": self.org_id,
                    "name": os.getenv('AGENT_NAME', 'Unified Meeting Agent')
                })
                session.commit()
        except Exception as e:
            logger.warning(f"ensure_agent_exists failed (continuing): {e}")


    def log_agent_function(self, user_agent_task_id: str, activity_type: str,
                          log_for_status: str, tool_name: str, log_text: str,
                          log_data: Dict[str, Any] = None, **kwargs) -> str:
        """
        Log agent function execution

        Args:
            user_agent_task_id: User agent task ID
            activity_type: Type of activity (task, integration)
            log_for_status: Status (success, error)
            tool_name: Name of the tool used
            log_text: Log message
            log_data: Additional log data
            **kwargs: Additional fields (outcome, action_required, etc.)

        Returns:
            Log ID if successful, None otherwise
        """
        try:
            log_id = str(uuid.uuid4())
            status_value = kwargs.get('status', 1)

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO agent_function_log (
                        id, org_id, agent_id, agent_task_id, activity_type,
                        log_for_status, log_text, log_data, status
                    ) VALUES (
                        :log_id, :org_id, :agent_id, :agent_task_id, :activity_type,
                        :log_for_status, :log_text, :log_data, :status
                    )
                """)

                session.execute(insert_query, {
                    "log_id": log_id,
                    "org_id": self.org_id,
                    "agent_id": self.agent_id,
                    "agent_task_id": user_agent_task_id,
                    "activity_type": activity_type,
                    "log_for_status": log_for_status,
                    "log_text": log_text,
                    "log_data": json.dumps(log_data) if log_data else None,
                    "status": status_value
                })
                session.commit()

                logger.debug(f"Logged agent function: {log_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent function: {e}")
            return None

    def update_task_progress(self, user_agent_task_id: str, complete_count: int) -> bool:
        """
        Update task progress

        Args:
            user_agent_task_id: User agent task ID
            complete_count: Number of completed steps

        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_service.get_session() as session:
                update_query = text("""
                    UPDATE user_agent_task
                    SET updated = CURRENT_TIMESTAMP(6)
                    WHERE agent_task_id = :task_id
                """)

                session.execute(update_query, {
                    "task_id": user_agent_task_id,
                    "complete_count": complete_count,
                    "run_status": run_status
                })
                session.commit()

                logger.debug(f"Updated task progress: {user_agent_task_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to update task progress: {e}")
            return False

    def log_audit_event(self, agent_task_id: str, activity_type: str, log_status: str, log_text: str,
                        action: Optional[str] = None, action_required: Optional[str] = None,
                        outcome: Optional[str] = None, tool_id: Optional[str] = None,
                        step_id: Optional[str] = None, log_data: Optional[Dict[str, Any]] = None
                       ) -> Optional[str]:
        return self.log_agent_function(
            user_agent_task_id=agent_task_id, activity_type=activity_type, log_for_status=log_status,
            tool_name=tool_id or "agent_tool", log_text=log_text, log_data=log_data or {},
            outcome=outcome, action_required=action_required, scope=activity_type,
            step_str=step_id or action, status=1 if (log_status or "").lower()=="success" else 0
        )

    def get_user_tasks(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get user agent tasks

        Args:
            user_id: User identifier
            limit: Maximum number of tasks to return

        Returns:
            List of user tasks
        """
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT agent_task_id as id, name, description, ready_to_use,
                           created, updated
                    FROM user_agent_task
                    WHERE user_id = :user_id AND status = 1
                    ORDER BY created DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {"user_id": user_id, "limit": limit})
                tasks = []

                for row in result.fetchall():
                    tasks.append({
                        "id": row.id,
                        "name": row.name,
                        "description": row.description,
                        "ready_to_use": row.ready_to_use,
                        "created": row.created.isoformat() if row.created else None,
                        "updated": row.updated.isoformat() if row.updated else None
                    })

                return tasks

        except Exception as e:
            logger.error(f"Failed to get user tasks: {e}")
            return []

    def get_task_logs(self, user_agent_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get logs for a specific task

        Args:
            user_agent_task_id: User agent task ID
            limit: Maximum number of logs to return

        Returns:
            List of task logs
        """
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT id, activity_type, log_for_status, log_text, tool_str,
                           outcome, action_required, created
                    FROM agent_function_log
                    WHERE user_agent_task_id = :task_id AND status = 1
                    ORDER BY created DESC
                    LIMIT :limit
                """)

                result = session.execute(query, {"task_id": user_agent_task_id, "limit": limit})
                logs = []

                for row in result.fetchall():
                    logs.append({
                        "id": row.id,
                        "activity_type": row.activity_type,
                        "log_for_status": row.log_for_status,
                        "log_text": row.log_text,
                        "tool_str": row.tool_str,
                        "outcome": row.outcome,
                        "action_required": row.action_required,
                        "created": row.created.isoformat() if row.created else None
                    })

                return logs

        except Exception as e:
            logger.error(f"Failed to get task logs: {e}")
            return []

    def get_agent_info(self) -> Optional[Dict[str, Any]]:
        """
        Get agent information

        Returns:
            Agent information dict or None
        """
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT id, name, agent_type, agent_used_for, description,
                           system_prompt, workflow_data, created, updated
                    FROM agent
                    WHERE id = :agent_id AND status = 1
                """)

                result = session.execute(query, {"agent_id": self.agent_id})
                row = result.fetchone()

                if row:
                    return {
                        "id": row.id,
                        "name": row.name,
                        "agent_type": row.agent_type,
                        "agent_used_for": row.agent_used_for,
                        "description": row.description,
                        "system_prompt": row.system_prompt,
                        "workflow_data": row.workflow_data,
                        "created": row.created.isoformat() if row.created else None,
                        "updated": row.updated.isoformat() if row.updated else None
                    }

                return None

        except Exception as e:
            logger.error(f"Failed to get agent info: {e}")
            return None


# Global instance
_agent_integration_service = None

def get_agent_integration_service() -> AgentIntegrationService:
    """Get the global agent integration service instance"""
    global _agent_integration_service
    if _agent_integration_service is None:
        _agent_integration_service = AgentIntegrationService()
    return _agent_integration_service