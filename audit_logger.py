"""
Audit Logger for Enhanced Meeting Intelligence Agent
Handles audit logging using the new simplified schema
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


class AuditLogger:
    """Enhanced audit logger using the simplified schema"""

    def __init__(self):
        """Initialize the audit logger"""
        self.db_service = DatabaseService()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')

    def log_workflow_start(self, workflow_id: str, user_id: str,
                          input_parameters: Dict[str, Any] = None) -> str:
        """Log workflow start in audit_logs table"""
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
                    "input_parameters": input_parameters or {},
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_started",
                    "event_source": "enhanced_meeting_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged workflow start: {workflow_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow start: {e}")
            return None

    def log_workflow_complete(self, workflow_id: str, user_id: str,
                             results: Dict[str, Any] = None,
                             meetings_processed: int = 0,
                             execution_time_ms: int = 0) -> str:
        """Log workflow completion in audit_logs table"""
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
                    "results": results or {},
                    "meetings_processed": meetings_processed,
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "workflow_completed",
                    "event_source": "enhanced_meeting_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged workflow completion: {workflow_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log workflow completion: {e}")
            return None

    def log_tool_invocation(self, workflow_id: str, user_id: str, tool_name: str,
                           tool_input: Dict[str, Any] = None,
                           execution_time_ms: int = 0) -> str:
        """Log tool invocation in audit_logs table"""
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

                logger.debug(f"Logged tool invocation: {tool_name}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log tool invocation: {e}")
            return None

    def log_tool_completion(self, workflow_id: str, user_id: str, tool_name: str,
                           tool_output: Dict[str, Any] = None,
                           execution_time_ms: int = 0,
                           success: bool = True) -> str:
        """Log tool completion in audit_logs table"""
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

                logger.debug(f"Logged tool completion: {tool_name}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log tool completion: {e}")
            return None

    def get_workflow_logs(self, workflow_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all logs for a specific workflow"""
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT id, event_type, event_source, event_data, created_at
                    FROM audit_logs
                    WHERE workflow_id = :workflow_id
                    ORDER BY created_at ASC
                    LIMIT :limit
                """)

                result = session.execute(query, {
                    "workflow_id": workflow_id,
                    "limit": limit
                })

                logs = []
                for row in result.fetchall():
                    log_data = {
                        "id": row.id,
                        "event_type": row.event_type,
                        "event_source": row.event_source,
                        "created_at": row.created_at.isoformat() if row.created_at else None
                    }

                    # Parse event_data if it's JSON
                    if row.event_data:
                        try:
                            log_data["event_data"] = json.loads(row.event_data)
                        except json.JSONDecodeError:
                            log_data["event_data"] = row.event_data

                    logs.append(log_data)

                return logs

        except Exception as e:
            logger.error(f"Failed to get workflow logs: {e}")
            return []

    def log_scheduled_workflow_start(self, user_id: str, time_window_mins: int = 15) -> str:
        """Log scheduled workflow start event"""
        try:
            log_id = str(uuid.uuid4())
            workflow_id = f"scheduled_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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
                    "scheduled_workflow_started": True,
                    "time_window_mins": time_window_mins,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "scheduled_workflow_started",
                    "event_source": "workflow_scheduler",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged scheduled workflow start: {workflow_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log scheduled workflow start: {e}")
            return None

    def log_scheduled_workflow_stop(self, user_id: str, events_processed: int,
                                   events_found: int, execution_time_ms: int) -> str:
        """Log scheduled workflow stop event"""
        try:
            log_id = str(uuid.uuid4())
            workflow_id = f"scheduled_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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
                    "scheduled_workflow_stopped": True,
                    "events_processed": events_processed,
                    "events_found": events_found,
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "scheduled_workflow_stopped",
                    "event_source": "workflow_scheduler",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged scheduled workflow stop: {workflow_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log scheduled workflow stop: {e}")
            return None

    def log_event_processed(self, workflow_id: str, user_id: str, event_title: str,
                           event_id: str, status: str, processing_time_ms: int = 0) -> str:
        """Log individual event processing"""
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
                    "event_processed": True,
                    "event_title": event_title,
                    "event_id": event_id,
                    "status": status,
                    "processing_time_ms": processing_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "event_processed",
                    "event_source": "meeting_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged event processed: {event_title}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log event processed: {e}")
            return None

    def log_tasks_created(self, workflow_id: str, user_id: str, task_count: int,
                         task_details: List[Dict[str, Any]] = None) -> str:
        """Log tasks created during workflow execution"""
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
                    "tasks_created": True,
                    "task_count": task_count,
                    "task_details": task_details or [],
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "tasks_created",
                    "event_source": "dedup_tool",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged tasks created: {task_count} tasks")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log tasks created: {e}")
            return None

    def log_error(self, workflow_id: str, user_id: str, error_type: str,
                 error_message: str, error_context: Dict[str, Any] = None) -> str:
        """Log error events"""
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
                    "error_occurred": True,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_context": error_context or {},
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "error",
                    "event_source": "meeting_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.error(f"Logged error: {error_type} - {error_message}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log error: {e}")
            return None

    def log_sensitive_operation(self, operation: str, user_id: str, resource_type: str,
                               resource_id: str, details: Dict[str, Any] = None,
                               ip_address: str = None, success: bool = True,
                               risk_level: str = "LOW") -> str:
        """Log sensitive operations for security auditing"""
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
                    "sensitive_operation": True,
                    "operation": operation,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": details or {},
                    "ip_address": ip_address,
                    "success": success,
                    "risk_level": risk_level,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": f"audit_{operation}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "sensitive_operation",
                    "event_source": "security_audit",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged sensitive operation: {operation}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log sensitive operation: {e}")
            return None

    def get_audit_summary(self, user_id: str = None, hours: int = 24) -> Dict[str, Any]:
        """Get audit summary for a user or all users"""
        try:
            with self.db_service.get_session() as session:
                # Base query
                base_query = """
                    SELECT
                        event_type,
                        COUNT(*) as count,
                        MAX(created_at) as last_occurrence
                    FROM audit_logs
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
                """

                params = {"hours": hours}

                if user_id:
                    base_query += " AND user_id = :user_id"
                    params["user_id"] = user_id

                base_query += " GROUP BY event_type ORDER BY count DESC"

                result = session.execute(text(base_query), params)

                summary = {
                    "user_id": user_id,
                    "time_range_hours": hours,
                    "event_counts": {},
                    "total_events": 0,
                    "timestamp": datetime.now().isoformat()
                }

                for row in result.fetchall():
                    summary["event_counts"][row.event_type] = {
                        "count": row.count,
                        "last_occurrence": row.last_occurrence.isoformat() if row.last_occurrence else None
                    }
                    summary["total_events"] += row.count

                return summary

        except Exception as e:
            logger.error(f"Failed to get audit summary: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def health_check(self) -> Dict[str, Any]:
        """Check audit logger health"""
        try:
            with self.db_service.get_session() as session:
                # Check audit_logs table
                result = session.execute(text("SELECT COUNT(*) as count FROM audit_logs"))
                total_events = result.scalar()

                # Check recent events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                """))
                recent_events = result.scalar()

                return {
                    "status": "healthy",
                    "database_connected": True,
                    "total_events": total_events,
                    "recent_events_24h": recent_events,
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
_audit_logger = None

def get_audit_logger() -> AuditLogger:
    """Get singleton audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger