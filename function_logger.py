"""
Function Logger for Enhanced Meeting Intelligence Agent
Handles function execution logging using agent_function_log table
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import text

from src.services.database_service_new import DatabaseService

logger = logging.getLogger(__name__)


class FunctionLogger:
    """Function execution logger using agent_function_log table"""

    def __init__(self):
        """Initialize the function logger"""
        self.db_service = DatabaseService()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')

    def log_function_execution(self, user_agent_task_id: str, tool_name: str,
                              activity_type: str = "task", log_for_status: str = "success",
                              log_text: str = "", log_data: Dict[str, Any] = None,
                              outcome: str = None, action_required: str = None,
                              scope: str = None, step_str: str = None) -> str:
        """Log function execution to agent_function_log table"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO agent_function_log (
                        id, org_id, agent_id, user_agent_task_id, activity_type,
                        log_for_status, log_text, tool_str, log_data,
                        outcome, action_required, scope, step_str, created, status
                    ) VALUES (
                        :log_id, :org_id, :agent_id, :user_agent_task_id, :activity_type,
                        :log_for_status, :log_text, :tool_str, :log_data,
                        :outcome, :action_required, :scope, :step_str, CURRENT_TIMESTAMP, 1
                    )
                """)

                session.execute(insert_query, {
                    "log_id": log_id,
                    "org_id": self.org_id,
                    "agent_id": self.agent_id,
                    "user_agent_task_id": user_agent_task_id,
                    "activity_type": activity_type,
                    "log_for_status": log_for_status,
                    "log_text": log_text,
                    "tool_str": tool_name,
                    "log_data": json.dumps(log_data) if log_data else None,
                    "outcome": outcome,
                    "action_required": action_required,
                    "scope": scope,
                    "step_str": step_str
                })
                session.commit()

                logger.debug(f"Logged function execution: {tool_name}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log function execution: {e}")
            return None

    def log_tool_start(self, user_agent_task_id: str, tool_name: str,
                      input_data: Dict[str, Any] = None, step_str: str = None) -> str:
        """Log tool start"""
        log_text = f"Started {tool_name}"
        if input_data:
            log_text += f" with input: {json.dumps(input_data, default=str)[:200]}..."

        return self.log_function_execution(
            user_agent_task_id=user_agent_task_id,
            tool_name=tool_name,
            activity_type="task",
            log_for_status="info",
            log_text=log_text,
            log_data=input_data,
            outcome="tool_started",
            scope="tool_execution",
            step_str=step_str
        )

    def log_tool_success(self, user_agent_task_id: str, tool_name: str,
                        output_data: Dict[str, Any] = None, execution_time_ms: int = 0,
                        step_str: str = None) -> str:
        """Log tool success"""
        log_text = f"Successfully completed {tool_name}"
        if execution_time_ms > 0:
            log_text += f" in {execution_time_ms}ms"

        log_data = output_data or {}
        if execution_time_ms > 0:
            log_data["execution_time_ms"] = execution_time_ms

        return self.log_function_execution(
            user_agent_task_id=user_agent_task_id,
            tool_name=tool_name,
            activity_type="task",
            log_for_status="success",
            log_text=log_text,
            log_data=log_data,
            outcome="tool_completed",
            scope="tool_execution",
            step_str=step_str
        )

    def log_tool_error(self, user_agent_task_id: str, tool_name: str,
                      error_message: str, error_data: Dict[str, Any] = None,
                      step_str: str = None) -> str:
        """Log tool error"""
        log_text = f"Error in {tool_name}: {error_message}"

        log_data = error_data or {}
        log_data["error_message"] = error_message
        log_data["timestamp"] = datetime.now().isoformat()

        return self.log_function_execution(
            user_agent_task_id=user_agent_task_id,
            tool_name=tool_name,
            activity_type="task",
            log_for_status="error",
            log_text=log_text,
            log_data=log_data,
            outcome="tool_failed",
            action_required="investigate_error",
            scope="tool_execution",
            step_str=step_str
        )

    def log_workflow_step(self, user_agent_task_id: str, step_number: int,
                         step_name: str, step_status: str = "completed",
                         step_data: Dict[str, Any] = None) -> str:
        """Log workflow step completion"""
        log_text = f"Workflow step {step_number}: {step_name} - {step_status}"

        log_data = step_data or {}
        log_data["step_number"] = step_number
        log_data["step_name"] = step_name
        log_data["step_status"] = step_status

        return self.log_function_execution(
            user_agent_task_id=user_agent_task_id,
            tool_name="workflow_manager",
            activity_type="workflow",
            log_for_status="success" if step_status == "completed" else "info",
            log_text=log_text,
            log_data=log_data,
            outcome=f"step_{step_status}",
            scope="workflow_step",
            step_str=f"step_{step_number}_{step_name.lower().replace(' ', '_')}"
        )

    def get_task_logs(self, user_agent_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all logs for a specific user agent task"""
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT id, tool_str, activity_type, log_for_status, log_text,
                           outcome, scope, step_str, log_data, created
                    FROM agent_function_log
                    WHERE user_agent_task_id = :task_id AND status = 1
                    ORDER BY created ASC
                    LIMIT :limit
                """)

                result = session.execute(query, {
                    "task_id": user_agent_task_id,
                    "limit": limit
                })

                logs = []
                for row in result.fetchall():
                    log_data = {
                        "id": row.id,
                        "tool_str": row.tool_str,
                        "activity_type": row.activity_type,
                        "log_for_status": row.log_for_status,
                        "log_text": row.log_text,
                        "outcome": row.outcome,
                        "scope": row.scope,
                        "step_str": row.step_str,
                        "created": row.created.isoformat() if row.created else None
                    }

                    # Parse log_data if it's JSON
                    if row.log_data:
                        try:
                            log_data["log_data"] = json.loads(row.log_data)
                        except json.JSONDecodeError:
                            log_data["log_data"] = row.log_data

                    logs.append(log_data)

                return logs

        except Exception as e:
            logger.error(f"Failed to get task logs: {e}")
            return []

    def get_tool_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get tool usage statistics"""
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT tool_str, activity_type, log_for_status, COUNT(*) as count
                    FROM agent_function_log
                    WHERE created >= DATE_SUB(NOW(), INTERVAL :days DAY) AND status = 1
                    GROUP BY tool_str, activity_type, log_for_status
                    ORDER BY count DESC
                """)

                result = session.execute(query, {"days": days})

                statistics = {}
                for row in result.fetchall():
                    tool_name = row.tool_str or "unknown"
                    if tool_name not in statistics:
                        statistics[tool_name] = {
                            "total_executions": 0,
                            "success_count": 0,
                            "error_count": 0,
                            "activity_types": {}
                        }

                    statistics[tool_name]["total_executions"] += row.count

                    if row.log_for_status == "success":
                        statistics[tool_name]["success_count"] += row.count
                    elif row.log_for_status == "error":
                        statistics[tool_name]["error_count"] += row.count

                    activity_type = row.activity_type or "unknown"
                    if activity_type not in statistics[tool_name]["activity_types"]:
                        statistics[tool_name]["activity_types"][activity_type] = 0
                    statistics[tool_name]["activity_types"][activity_type] += row.count

                # Calculate success rates
                for tool_stats in statistics.values():
                    total = tool_stats["total_executions"]
                    if total > 0:
                        tool_stats["success_rate"] = (tool_stats["success_count"] / total) * 100
                    else:
                        tool_stats["success_rate"] = 0

                return statistics

        except Exception as e:
            logger.error(f"Failed to get tool statistics: {e}")
            return {}


# Singleton instance
_function_logger = None

def get_function_logger() -> FunctionLogger:
    """Get singleton function logger instance"""
    global _function_logger
    if _function_logger is None:
        _function_logger = FunctionLogger()
    return _function_logger