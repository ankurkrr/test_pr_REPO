"""
Database Service

Main database service that coordinates all repository operations.
"""

import logging
import os
from contextlib import contextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import quote_plus
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from .data.repositories.workflow_repository import WorkflowRepository
from .data.repositories.meeting_repository import MeetingRepository
from .data.repositories.token_repository import TokenRepository
from .data.repositories.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)

class DatabaseService:
    """Main database service with repository coordination"""

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database connection"""
        try:
            # Import configuration to get DB_URL
            from ..configuration.config import DB_URL
            connection_string = DB_URL

            # Create engine with optimized connection pooling for production
            self.engine = create_engine(
                connection_string,
                poolclass=QueuePool,
                pool_size=10,  # Increased for production
                max_overflow=20,  # Increased for production
                pool_pre_ping=True,  # Test connections before use
                pool_recycle=3600,  # Recycle connections every hour
                pool_timeout=30,  # Optimized timeout
                echo=False,
                connect_args={
                    "connect_timeout": 10,
                    "charset": "utf8mb4",
                    "autocommit": False,
                    "sql_mode": "TRADITIONAL",
                    "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"
                }
            )

            # Create session factory
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

            logger.info("Database connection initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")
            raise

    def health_check(self) -> Dict[str, Any]:
        """Return basic database health information.

        Executes a lightweight SELECT 1 to validate connectivity and returns
        a dict with status and timing. Never raises; returns error info on failure.
        """
        try:
            import time
            start = time.perf_counter()
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "status": "ok",
                "latency_ms": elapsed_ms
            }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    @contextmanager
    def get_session(self):
        """Get database session context manager"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[tuple]:
        """Execute raw SQL query with comprehensive logging"""
        import time
        start_time = time.perf_counter()
        
        # Log query start
        logger.info(f"DB_QUERY_START: Executing query with {len(params) if params else 0} parameters")
        logger.debug(f"DB_QUERY_SQL: {query[:200]}{'...' if len(query) > 200 else ''}")
        if params:
            logger.debug(f"DB_QUERY_PARAMS: {params}")
        
        try:
            with self.get_session() as session:
                result = session.execute(text(query), params or {})
                
                # Check if this is a SELECT query that returns rows
                query_upper = query.strip().upper()
                if query_upper.startswith(('SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN')):
                    rows = result.fetchall()
                    # Log query completion
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.info(f"DB_QUERY_SUCCESS: Query completed in {elapsed_ms}ms, returned {len(rows)} rows")
                    return rows
                else:
                    # For INSERT/UPDATE/DELETE queries, commit the transaction
                    session.commit()
                    # Log query completion
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.info(f"DB_QUERY_SUCCESS: Query completed in {elapsed_ms}ms, rows affected: {result.rowcount}")
                    return []
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"DB_QUERY_ERROR: Query failed after {elapsed_ms}ms - {e}")
            logger.error(f"DB_QUERY_FAILED_SQL: {query[:200]}{'...' if len(query) > 200 else ''}")
            if params:
                logger.error(f"DB_QUERY_FAILED_PARAMS: {params}")
            raise

    def get_workflow_repository(self) -> WorkflowRepository:
        """Get workflow repository instance"""
        with self.get_session() as session:
            return WorkflowRepository(session)

    def get_meeting_repository(self) -> MeetingRepository:
        """Get meeting repository instance"""
        with self.get_session() as session:
            return MeetingRepository(session)

    def get_token_repository(self) -> TokenRepository:
        """Get token repository instance"""
        with self.get_session() as session:
            return TokenRepository(session)

    def get_memory_repository(self) -> MemoryRepository:
        """Get memory repository instance"""
        with self.get_session() as session:
            return MemoryRepository(session)

    @lru_cache(maxsize=100)
    def get_user_resource_ids(self, user_id: str) -> Dict[str, Optional[str]]:
        """
        Get user resource IDs (drive_folder_id, sheets_id) from database with caching

        Args:
            user_id: User ID to look up

        Returns:
            Dict containing drive_folder_id and sheets_id
        """
        try:
            result = self.execute_query("""
                SELECT drive_folder_id, sheets_id
                FROM user_agent_task
                WHERE user_id = :user_id AND status = 1
                ORDER BY created DESC
                LIMIT 1
            """, {"user_id": user_id})

            if result and len(result) > 0:
                row = result[0]
                return {
                    "drive_folder_id": row[0],
                    "sheets_id": row[1]
                }

            # Return empty dict if no user found
            return {"drive_folder_id": None, "sheets_id": None}

        except Exception as e:
            logger.error(f"Error getting user resource IDs for {user_id}: {e}")
            return {"drive_folder_id": None, "sheets_id": None}
    
    def invalidate_user_cache(self, user_id: str):
        """Invalidate cache for a specific user"""
        self.get_user_resource_ids.cache_clear()

    # Convenience methods that delegate to repositories
    def store_workflow_data(
        self,
        user_id: str,
        org_id: str,
        agent_task_id: str,
        workflow_data: List[Dict[str, Any]],
        timezone: Optional[str] = None,
        notify_to: Optional[str] = None
    ) -> bool:
        """Store workflow data"""
        workflow_repo = self.get_workflow_repository()
        return workflow_repo.store_workflow_data(
            user_id, org_id, agent_task_id, workflow_data, timezone, notify_to
        )

    def store_google_tokens(
        self,
        user_id: str,
        org_id: str,
        agent_task_id: str,
        access_token: str,
        refresh_token: str,
        scope: str,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """Store Google OAuth tokens"""
        token_repo = self.get_token_repository()
        return token_repo.store_google_tokens(
            user_id, org_id, agent_task_id, access_token, refresh_token, scope, expires_at
        )

    def store_workflow_activity_log(
        self,
        agent_task_id: str,
        activity_type: str = "task",
        log_for_status: str = "success",
        log_text: str = "",
        action: str = "Execute",
        action_issue_event: str = "",
        action_required: str = "None",
        outcome: str = "",
        step_str: str = "",
        tool_str: str = "N/A",
        log_data: Optional[Dict[str, Any]] = None,
        api_sent: bool = False
    ) -> bool:
        """Store workflow activity log in database"""
        try:
            import json
            from datetime import datetime
            
            # Convert log_data to JSON string
            log_data_json = json.dumps(log_data or {})
            
            # Insert into workflow_activity_logs table
            self.execute_query("""
                INSERT INTO workflow_activity_logs 
                (agent_task_id, activity_type, log_for_status, log_text, action, 
                 action_issue_event, action_required, outcome, step_str, tool_str, 
                 log_data, api_sent, created_at)
                VALUES (:agent_task_id, :activity_type, :log_for_status, :log_text, :action,
                        :action_issue_event, :action_required, :outcome, :step_str, :tool_str,
                        :log_data, :api_sent, :created_at)
            """, {
                "agent_task_id": agent_task_id,
                "activity_type": activity_type,
                "log_for_status": log_for_status,
                "log_text": log_text,
                "action": action,
                "action_issue_event": action_issue_event,
                "action_required": action_required,
                "outcome": outcome,
                "step_str": step_str,
                "tool_str": tool_str,
                "log_data": log_data_json,
                "api_sent": api_sent,
                "created_at": datetime.now()
            })
            
            logger.debug(f"Stored workflow activity log for agent_task_id: {agent_task_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store workflow activity log: {e}")
            return False

# Global instance
_database_service = None

def get_database_service() -> DatabaseService:
    """Get global database service instance"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
    return _database_service