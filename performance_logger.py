"""
Performance Logger for Enhanced Meeting Intelligence Agent
Handles performance monitoring and metrics collection
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from functools import wraps
from sqlalchemy import text

from src.services.database_service_new import DatabaseService

logger = logging.getLogger(__name__)


class PerformanceLogger:
    """Performance logger for monitoring execution times and metrics"""

    def __init__(self):
        """Initialize the performance logger"""
        self.db_service = DatabaseService()
        self.agent_id = os.getenv('AGENT_ID', 'meeting_agent_001')
        self.org_id = os.getenv('ORG_ID', 'default_org')
        self._metrics_cache = {}

    def log_execution_time(self, operation: str, execution_time_ms: int,
                          user_id: str = None, workflow_id: str = None,
                          additional_metrics: Dict[str, Any] = None) -> str:
        """Log execution time for an operation"""
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
                    "performance_metric": True,
                    "operation": operation,
                    "execution_time_ms": execution_time_ms,
                    "additional_metrics": additional_metrics or {},
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id or f"perf_{operation}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "performance_metric",
                    "event_source": "performance_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged performance metric: {operation} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log performance metric: {e}")
            return None

    def log_memory_usage(self, operation: str, memory_mb: float,
                        user_id: str = None, workflow_id: str = None) -> str:
        """Log memory usage for an operation"""
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
                    "memory_usage": True,
                    "operation": operation,
                    "memory_mb": memory_mb,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": workflow_id or f"mem_{operation}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "memory_usage",
                    "event_source": "performance_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged memory usage: {operation} ({memory_mb}MB)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log memory usage: {e}")
            return None

    def log_api_response_time(self, endpoint: str, method: str, response_time_ms: int,
                            status_code: int, user_id: str = None) -> str:
        """Log API response times"""
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
                    "api_response_time": True,
                    "endpoint": endpoint,
                    "method": method,
                    "response_time_ms": response_time_ms,
                    "status_code": status_code,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": f"api_{endpoint}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "api_response_time",
                    "event_source": "performance_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged API response time: {method} {endpoint} ({response_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log API response time: {e}")
            return None

    def log_database_query_time(self, query_type: str, execution_time_ms: int,
                               rows_affected: int = 0, user_id: str = None) -> str:
        """Log database query execution times"""
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
                    "database_query_time": True,
                    "query_type": query_type,
                    "execution_time_ms": execution_time_ms,
                    "rows_affected": rows_affected,
                    "timestamp": datetime.now().isoformat()
                }

                session.execute(insert_query, {
                    "log_id": log_id,
                    "workflow_id": f"db_{query_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "agent_id": self.agent_id,
                    "user_id": user_id,
                    "event_type": "database_query_time",
                    "event_source": "performance_logger",
                    "event_data": json.dumps(event_data)
                })
                session.commit()

                logger.debug(f"Logged database query time: {query_type} ({execution_time_ms}ms)")
                return log_id

        except Exception as e:
            logger.error(f"Failed to log database query time: {e}")
            return None

    def get_performance_summary(self, user_id: str = None, hours: int = 24) -> Dict[str, Any]:
        """Get performance summary for a user or all users"""
        try:
            with self.db_service.get_session() as session:
                # Base query for performance metrics
                base_query = """
                    SELECT
                        event_type,
                        AVG(JSON_EXTRACT(event_data, '$.execution_time_ms')) as avg_time_ms,
                        MIN(JSON_EXTRACT(event_data, '$.execution_time_ms')) as min_time_ms,
                        MAX(JSON_EXTRACT(event_data, '$.execution_time_ms')) as max_time_ms,
                        COUNT(*) as operation_count
                    FROM audit_logs
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL :hours HOUR)
                    AND event_source = 'performance_logger'
                """

                params = {"hours": hours}

                if user_id:
                    base_query += " AND user_id = :user_id"
                    params["user_id"] = user_id

                base_query += " GROUP BY event_type ORDER BY avg_time_ms DESC"

                result = session.execute(text(base_query), params)

                performance_metrics = {}
                total_operations = 0

                for row in result.fetchall():
                    performance_metrics[row.event_type] = {
                        "avg_time_ms": round(float(row.avg_time_ms or 0), 2),
                        "min_time_ms": int(row.min_time_ms or 0),
                        "max_time_ms": int(row.max_time_ms or 0),
                        "operation_count": row.operation_count
                    }
                    total_operations += row.operation_count

                return {
                    "user_id": user_id,
                    "time_range_hours": hours,
                    "total_operations": total_operations,
                    "performance_metrics": performance_metrics,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to get performance summary: {e}")
            return {"error": str(e)}

    def health_check(self) -> Dict[str, Any]:
        """Check performance logger health"""
        try:
            with self.db_service.get_session() as session:
                # Check performance events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source = 'performance_logger'
                """))
                total_performance_events = result.scalar()

                # Check recent performance events
                result = session.execute(text("""
                    SELECT COUNT(*) as count
                    FROM audit_logs
                    WHERE event_source = 'performance_logger'
                    AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                """))
                recent_performance_events = result.scalar()

                return {
                    "status": "healthy",
                    "database_connected": True,
                    "total_performance_events": total_performance_events,
                    "recent_performance_events_24h": recent_performance_events,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "database_connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# Performance monitoring decorator
def monitor_performance(operation_name: str = None, user_id: str = None):
    """Decorator to monitor function execution time"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            perf_logger = get_performance_logger()
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                execution_time_ms = int((time.time() - start_time) * 1000)

                # Log successful execution
                perf_logger.log_execution_time(
                    operation=operation_name or func.__name__,
                    execution_time_ms=execution_time_ms,
                    user_id=user_id
                )

                return result

            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)

                # Log failed execution
                perf_logger.log_execution_time(
                    operation=f"{operation_name or func.__name__}_error",
                    execution_time_ms=execution_time_ms,
                    user_id=user_id,
                    additional_metrics={"error": str(e)}
                )

                raise

        return wrapper
    return decorator


# Singleton instance
_performance_logger = None

def get_performance_logger() -> PerformanceLogger:
    """Get singleton performance logger instance"""
    global _performance_logger
    if _performance_logger is None:
        _performance_logger = PerformanceLogger()
    return _performance_logger