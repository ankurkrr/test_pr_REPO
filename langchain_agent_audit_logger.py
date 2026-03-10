"""
LangChain Agent Audit Logger for Enhanced Meeting Intelligence Agent
Handles detailed LangChain agent execution logging and monitoring
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


class LangChainAgentAuditLogger:
    """LangChain agent audit logger for detailed agent execution tracking"""

    def __init__(self):
        """Initialize the LangChain agent audit logger"""
        self.db_service = DatabaseService()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')

    def log_agent_start(self, workflow_id: str, user_id: str,
                       agent_config: Dict[str, Any] = None,
                       input_query: str = None) -> str:
        """Log LangChain agent start"""
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
                    "langchain_agent_started": True,
                    "agent_config": agent_config or {},
                    "input_query": input_query,
                    "timestamp": datetime.now().isoformat(),
                    "status": "running"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "langchain_agent_started",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged LangChain agent start: {workflow_id}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log LangChain agent start: {e}")
            return None

    def log_agent_tool_selection(self, workflow_id: str, user_id: str,
                               tool_name: str, tool_input: Dict[str, Any] = None,
                               reasoning: str = None) -> str:
        """Log agent tool selection"""
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
                    "agent_tool_selected": True,
                    "tool_name": tool_name,
                    "tool_input": tool_input or {},
                    "reasoning": reasoning,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_tool_selected",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged agent tool selection: {tool_name}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent tool selection: {e}")
            return None

    def log_agent_tool_execution(self, workflow_id: str, user_id: str,
                               tool_name: str, tool_input: Dict[str, Any] = None,
                               tool_output: Dict[str, Any] = None,
                               execution_time_ms: int = 0) -> str:
        """Log agent tool execution"""
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
                    "agent_tool_executed": True,
                    "tool_name": tool_name,
                    "tool_input": tool_input or {},
                    "tool_output": tool_output or {},
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_tool_executed",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged agent tool execution: {tool_name} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent tool execution: {e}")
            return None

    def log_agent_thought(self, workflow_id: str, user_id: str,
                         thought: str, step_number: int = None) -> str:
        """Log agent thought process"""
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
                    "agent_thought": True,
                    "thought": thought,
                    "step_number": step_number,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_thought",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged agent thought: step {step_number}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent thought: {e}")
            return None

    def log_agent_action(self, workflow_id: str, user_id: str,
                       action: str, action_input: Dict[str, Any] = None,
                       step_number: int = None) -> str:
        """Log agent action"""
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
                    "agent_action": True,
                    "action": action,
                    "action_input": action_input or {},
                    "step_number": step_number,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_action",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged agent action: {action} (step {step_number})")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent action: {e}")
            return None

    def log_agent_observation(self, workflow_id: str, user_id: str,
                             observation: str, step_number: int = None) -> str:
        """Log agent observation"""
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
                    "agent_observation": True,
                    "observation": observation,
                    "step_number": step_number,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_observation",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged agent observation: step {step_number}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent observation: {e}")
            return None

    def log_agent_final_answer(self, workflow_id: str, user_id: str,
                              final_answer: str, total_steps: int = None,
                              execution_time_ms: int = 0) -> str:
        """Log agent final answer"""
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
                    "agent_final_answer": True,
                    "final_answer": final_answer,
                    "total_steps": total_steps,
                    "execution_time_ms": execution_time_ms,
                    "timestamp": datetime.now().isoformat(),
                    "status": "completed"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_final_answer",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.info(f"Logged agent final answer: {total_steps} steps ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent final answer: {e}")
            return None

    def log_agent_error(self, workflow_id: str, user_id: str,
                       error_type: str, error_message: str,
                       error_context: Dict[str, Any] = None,
                       step_number: int = None) -> str:
        """Log agent error"""
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
                    "agent_error": True,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_context": error_context or {},
                    "step_number": step_number,
                    "timestamp": datetime.now().isoformat(),
                    "status": "failed"
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id,
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "agent_error",
                    "event_source": "langchain_agent",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.error(f"Logged agent error: {error_type} - {error_message}")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log agent error: {e}")
            return None

    def get_agent_execution_trace(self, workflow_id: str) -> Dict[str, Any]:
        """Get complete agent execution trace"""
        try:
            with self.db_service.get_session() as session:
                query = text("""
                    SELECT
                        event_type,
                        event_data,
                        created_at
                    FROM audit_logs
                    WHERE workflow_id = :workflow_id
                    AND event_source = 'langchain_agent'
                    ORDER BY created_at ASC
                """)

                result = session.execute(query, {"workflow_id": workflow_id})

                execution_trace = {
                    "workflow_id": workflow_id,
                    "steps": [],
                    "total_steps": 0,
                    "execution_time_ms": 0,
                    "timestamp": datetime.now().isoformat()
                }

                start_time = None
                end_time = None

                for row in result.fetchall():
                    try:
                        event_data = json.loads(row.event_data) if row.event_data else {}
                    except json.JSONDecodeError:
                        event_data = row.event_data

                    if not start_time:
                        start_time = row.created_at
                    end_time = row.created_at

                    execution_trace["steps"].append({
                        "event_type": row.event_type,
                        "event_data": event_data,
                        "timestamp": row.created_at.isoformat() if row.created_at else None
                    })

                execution_trace["total_steps"] = len(execution_trace["steps"])

                if start_time and end_time:
                    execution_trace["execution_time_ms"] = int((end_time - start_time).total_seconds() * 1000)

                return execution_trace

        except Exception as e:
            logger.error(f"Failed to get agent execution trace: {e}")
            return {"error": str(e)}

    def get_agent_performance_metrics(self, user_id: str = None, hours: int = 24) -> Dict[str, Any]:
        """Get agent performance metrics"""
        try:
            with self.db_service.get_session() as session:
                # Base query for agent metrics
                base_query = """
                    SELECT
                        workflow_id,
                        COUNT(*) as total_events,
                        SUM(CASE WHEN event_type = 'agent_final_answer' THEN 1 ELSE 0 END) as completed_executions,
                        SUM(CASE WHEN event_type = 'agent_error' THEN 1 ELSE 0 END) as error_count,
                        AVG(CASE WHEN event_type = 'agent_final_answer' THEN JSON_EXTRACT(event_data, '$.execution_time_ms') ELSE NULL END) as avg_execution_time_ms,
                        MIN(created_at) as start_time,
                        MAX(created_at) as end_time
                    FROM audit_logs
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
                    AND event_source = 'langchain_agent'
                """

                params = {"hours": hours}

                if user_id:
                    base_query += " AND user_id = :user_id"
                    params["user_id"] = user_id

                base_query += " GROUP BY workflow_id ORDER BY start_time DESC LIMIT 50"

                result = session.execute(text(base_query), params)

                agent_executions = []
                total_executions = 0
                successful_executions = 0
                total_execution_time = 0

                for row in result.fetchall():
                    execution_time_ms = 0
                    if row.start_time and row.end_time:
                        execution_time_ms = int((row.end_time - row.start_time).total_seconds() * 1000)
                        total_execution_time += execution_time_ms

                    is_successful = row.completed_executions > 0 and row.error_count == 0
                    if is_successful:
                        successful_executions += 1

                    total_executions += 1

                    agent_executions.append({
                        "workflow_id": row.workflow_id,
                        "total_events": row.total_events,
                        "completed": row.completed_executions > 0,
                        "errors": row.error_count,
                        "avg_execution_time_ms": round(float(row.avg_execution_time_ms or 0), 2),
                        "successful": is_successful
                    })

                avg_execution_time = total_execution_time / total_executions if total_executions > 0 else 0
                success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0

                return {
                    "user_id": user_id,
                    "time_range_hours": hours,
                    "total_executions": total_executions,
                    "successful_executions": successful_executions,
                    "success_rate_percent": round(success_rate, 2),
                    "average_execution_time_ms": round(avg_execution_time, 2),
                    "total_execution_time_ms": total_execution_time,
                    "agent_executions": agent_executions,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to get agent performance metrics: {e}")
            return {"error": str(e)}

    def health_check(self) -> Dict[str, Any]:
        """Check LangChain agent audit logger health"""
        try:
            with self.db_service.get_session() as session:
                # Check agent events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source = 'langchain_agent'
                """))
                total_agent_events = result.scalar()

                # Check recent agent events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source = 'langchain_agent'
                    AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                """))
                recent_agent_events = result.scalar()

                return {
                    "status": "healthy",
                    "database_connected": True,
                    "total_agent_events": total_agent_events,
                    "recent_agent_events_24h": recent_agent_events,
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
_langchain_agent_audit_logger = None

def get_langchain_audit_logger() -> LangChainAgentAuditLogger:
    """Get singleton LangChain agent audit logger instance"""
    global _langchain_agent_audit_logger
    if _langchain_agent_audit_logger is None:
        _langchain_agent_audit_logger = LangChainAgentAuditLogger()
    return _langchain_agent_audit_logger