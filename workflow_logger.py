"""
Workflow Logger for Enhanced Meeting Intelligence Agent
Handles detailed workflow execution logging and monitoring
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


class WorkflowLogger:
    """Enhanced workflow logger for detailed workflow execution tracking"""

    def __init__(self):
        """Initialize the workflow logger"""
        self.db_service = DatabaseService()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')

    def log_workflow_start(self, workflow_id: str, user_id: str,
                          workflow_type: str = "meeting_intelligence",
                          input_parameters: Dict[str, Any] = None) -> str:
        """Log workflow start with detailed context"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "workflow_started": True,
                    "workflow_type": workflow_type,
                    "input_parameters": input_parameters or {},
                    "timestamp": datetime.now().isoformat(),
                    "status": "running"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_started",
                    "event_source": "workflow_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged workflow start: {workflow_id} ({workflow_type})")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow start: {e}")
            return None

    def log_workflow_step_start(self, workflow_id: str, user_id: str,
                               step_name: str, step_number: int,
                               step_input: Dict[str, Any] = None) -> str:
        """Log individual workflow step start"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "workflow_step_started": True,
                    "step_name": step_name,
                    "step_number": step_number,
                    "step_input": step_input or {},
                    "timestamp": datetime.now().isoformat(),
                    "status": "running"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_step_started",
                    "event_source": "workflow_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged workflow step start: {step_name} (step {step_number})")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow step start: {e}")
            return None

    def log_workflow_step_complete(self, workflow_id: str, user_id: str,
                                  step_name: str, step_number: int,
                                  step_output: Dict[str, Any] = None,
                                  execution_time_ms: int = 0,
                                  success: bool = True) -> str:
        """Log individual workflow step completion"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "workflow_step_completed": True,
                    "step_name": step_name,
                    "step_number": step_number,
                    "step_output": step_output or {},
                    "execution_time_ms": execution_time_ms,
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                    "status": "completed" if success else "failed"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_step_completed",
                    "event_source": "workflow_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged workflow step complete: {step_name} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow step complete: {e}")
            return None

    def log_workflow_complete(self, workflow_id: str, user_id: str,
                             workflow_type: str = "meeting_intelligence",
                             results: Dict[str, Any] = None,
                             meetings_processed: int = 0,
                             execution_time_ms: int = 0,
                             success: bool = True) -> str:
        """Log workflow completion with comprehensive results"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "workflow_completed": True,
                    "workflow_type": workflow_type,
                    "results": results or {},
                    "meetings_processed": meetings_processed,
                    "execution_time_ms": execution_time_ms,
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                    "status": "completed" if success else "failed"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_completed",
                    "event_source": "workflow_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged workflow completion: {workflow_id} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow completion: {e}")
            return None

    def log_agent_execution(self, workflow_id: str, user_id: str,
                           agent_query: str, agent_result: Dict[str, Any] = None,
                           execution_time_ms: int = 0) -> str:
        """Log LangChain agent execution details"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "agent_execution": True,
                    "agent_query": agent_query,
                    "agent_result": agent_result or {},
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_execution",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged agent execution: {execution_time_ms}ms")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent execution: {e}")
            return None

    def log_tool_invocation(self, workflow_id: str, user_id: str, tool_name: str,
                           tool_input: Dict[str, Any] = None,
                           execution_time_ms: int = 0) -> str:
        """Log tool invocation with detailed input/output"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "tool_invoked": True,
                    "tool_name": tool_name,
                    "tool_input": tool_input or {},
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "tool_invoked",
                    "event_source": tool_name,
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged tool invocation: {tool_name} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log tool invocation: {e}")
            return None

    def log_tool_completion(self, workflow_id: str, user_id: str, tool_name: str,
                           tool_output: Dict[str, Any] = None,
                           execution_time_ms: int = 0,
                           success: bool = True) -> str:
        """Log tool completion with detailed output"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "tool_completed": True,
                    "tool_name": tool_name,
                    "tool_output": tool_output or {},
                    "execution_time_ms": execution_time_ms,
                    "success": success,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "tool_completed",
                    "event_source": tool_name,
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged tool completion: {tool_name} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log tool completion: {e}")
            return None

    def log_workflow_error(self, workflow_id: str, user_id: str,
                          error_type: str, error_message: str,
                          error_context: Dict[str, Any] = None,
                          step_name: str = None) -> str:
        """Log workflow errors with detailed context"""
        try:
            log_id = str(uuid.uuid4())

            with self.db_service.get_session() as session:
                insert_query = text("""
                    INSERT INTO audit_logs (
                        id, workflow_id, agent_id, user_id, event_type,
                        event_source, event_data, created_at
                    ) VALUES (
                        :log_id, :workflow_id, :agent_id, :user_id, :event_type,
                        :event_source, :event_data, NOW(6)
                    )
                """)

                event_data = {
                    "workflow_error": True,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_context": error_context or {},
                    "step_name": step_name,
                    "timestamp": datetime.now().isoformat(),
                    "status": "failed"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_error",
                    "event_source": "workflow_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.error(f"Logged workflow error: {error_type} - {error_message}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow error: {e}")
            return None

    def get_workflow_execution_summary(self, workflow_id: str) -> Dict[str, Any]:
        """Get comprehensive workflow execution summary"""
        try:
            with self.db_service.get_session() as session:
                # Get workflow start/end times
                query = text("""
                    SELECT
                        MIN(created_at) as start_time,
                        MAX(created_at) as end_time,
                        COUNT(*) as total_events
                    FROM audit_logs
                    WHERE workflow_id = :workflow_id
                """)

                result = session.execute(query, {"workflow_id": workflow_id})
                row = result.fetchone()

                if not row:
                    return {"error": "Workflow not found"}

                # Get step details
                step_query = text("""
                    SELECT
                        event_type,
                        event_data,
                        created_at
                    FROM audit_logs
                    WHERE workflow_id = :workflow_id
                    ORDER BY created_at ASC
                """)

                step_result = session.execute(step_query, {"workflow_id": workflow_id})

                steps = []
                for step_row in step_result.fetchall():
                    try:
                        event_data = json.loads(step_row.event_data) if step_row.event_data else {}
                    except json.JSONDecodeError:
                        event_data = step_row.event_data

                    steps.append({
                        "event_type": step_row.event_type,
                        "event_data": event_data,
                        "timestamp": step_row.created_at.isoformat() if step_row.created_at else None
                    })

                # Calculate execution time
                execution_time_ms = 0
                if row.start_time and row.end_time:
                    execution_time_ms = int((row.end_time - row.start_time).total_seconds() * 1000)

                return {
                    "workflow_id": workflow_id,
                    "start_time": row.start_time.isoformat() if row.start_time else None,
                    "end_time": row.end_time.isoformat() if row.end_time else None,
                    "execution_time_ms": execution_time_ms,
                    "total_events": row.total_events,
                    "steps": steps,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to get workflow execution summary: {e}")
            return {"error": str(e)}

    def get_workflow_performance_metrics(self, user_id: str = None,
                                       hours: int = 24) -> Dict[str, Any]:
        """Get workflow performance metrics"""
        try:
            with self.db_service.get_session() as session:
                # Base query for workflow metrics
                base_query = """
                    SELECT
                        workflow_id,
                        COUNT(*) as event_count,
                        MIN(created_at) as start_time,
                        MAX(created_at) as end_time,
                        SUM(CASE WHEN event_type = 'workflow_completed' THEN 1 ELSE 0 END) as completed_count,
                        SUM(CASE WHEN event_type = 'workflow_error' THEN 1 ELSE 0 END) as error_count
                    FROM audit_logs
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
                    AND event_source IN ('workflow_logger', 'langchain_agent')
                """

                params = {"hours": hours}

                if user_id:
                    base_query += " AND user_id = :user_id"
                    params["user_id"] = user_id

                base_query += " GROUP BY workflow_id ORDER BY start_time DESC LIMIT 50"

                result = session.execute(text(base_query), params)

                workflows = []
                total_execution_time = 0
                successful_workflows = 0

                for row in result.fetchall():
                    execution_time_ms = 0
                    if row.start_time and row.end_time:
                        execution_time_ms = int((row.end_time - row.start_time).total_seconds() * 1000)
                        total_execution_time += execution_time_ms

                    is_successful = row.completed_count > 0 and row.error_count == 0
                    if is_successful:
                        successful_workflows += 1

                    workflows.append({
                        "workflow_id": row.workflow_id,
                        "event_count": row.event_count,
                        "start_time": row.start_time.isoformat() if row.start_time else None,
                        "end_time": row.end_time.isoformat() if row.end_time else None,
                        "execution_time_ms": execution_time_ms,
                        "completed": row.completed_count > 0,
                        "errors": row.error_count,
                        "successful": is_successful
                    })

                avg_execution_time = total_execution_time / len(workflows) if workflows else 0
                success_rate = (successful_workflows / len(workflows) * 100) if workflows else 0

                return {
                    "user_id": user_id,
                    "time_range_hours": hours,
                    "total_workflows": len(workflows),
                    "successful_workflows": successful_workflows,
                    "success_rate_percent": round(success_rate, 2),
                    "average_execution_time_ms": round(avg_execution_time, 2),
                    "total_execution_time_ms": total_execution_time,
                    "workflows": workflows,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to get workflow performance metrics: {e}")
            return {"error": str(e)}

    def health_check(self) -> Dict[str, Any]:
        """Check workflow logger health"""
        try:
            with self.db_service.get_session() as session:
                # Check workflow-related events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source IN ('workflow_logger', 'langchain_agent')
                """))
                total_workflow_events = result.scalar()

                # Check recent workflow events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source IN ('workflow_logger', 'langchain_agent')
                    AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                """))
                recent_workflow_events = result.scalar()

                return {
                    "status": "healthy",
                    "database_connected": True,
                    "total_workflow_events": total_workflow_events,
                    "recent_workflow_events_24h": recent_workflow_events,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "database_connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# Singleton instance
_workflow_logger = None

def get_workflow_logger() -> WorkflowLogger:
    """Get singleton workflow logger instance"""
    global _workflow_logger
    if _workflow_logger is None:
        _workflow_logger = WorkflowLogger()
    return _workflow_logger