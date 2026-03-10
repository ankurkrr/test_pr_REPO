"""
Agent Tracking Service
Tracks agent execution metrics in the agent table
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import text

logger = logging.getLogger(__name__)


class AgentTrackingService:
    """
    Service to track agent executions with metrics
    Records each agent run in the agent table with detailed metrics
    """
    
    def __init__(self, db_service):
        """
        Initialize the agent tracking service
        
        Args:
            db_service: Database service instance
        """
        self.db_service = db_service
    
    def start_agent_execution(
        self,
        user_id: str,
        org_id: str,
        agent_task_id: str,
        agent_name: str = None,
        description: str = "langchain_meeting_agent"
    ) -> int:
        """
        Start tracking an agent execution
        
        Args:
            user_id: User ID
            org_id: Organization ID
            agent_task_id: Agent task ID
            agent_name: Name of the agent (e.g., "agent_1", "agent_A")
            description: Agent description
            
        Returns:
            Agent record ID if successful, None otherwise
        """
        try:
            # Generate agent name if not provided
            if not agent_name:
                agent_name = self._generate_agent_name(user_id)
            
            # Insert agent execution record
            query = text("""
                INSERT INTO agent (
                    org_id, name, description, user_id, agent_task_id,
                    status, created
                ) VALUES (
                    :org_id, :name, :description, :user_id, :agent_task_id,
                    'running', NOW()
                )
            """)
            
            with self.db_service.get_session() as session:
                result = session.execute(query, {
                    'org_id': org_id,
                    'name': agent_name,
                    'description': description,
                    'user_id': user_id,
                    'agent_task_id': agent_task_id
                })
                session.commit()
                
                # Get the inserted ID
                agent_id = result.lastrowid
                logger.info(f"Started tracking agent execution: agent_id={agent_id}, user_id={user_id}")
                
                # Store for tracking
                self._current_agent_id = agent_id
                self._start_time = datetime.utcnow()
                
                return agent_id
                
        except Exception as e:
            logger.error(f"Failed to start agent execution tracking: {e}")
            return None
    
    def update_metrics(self, metrics: Dict[str, int]) -> bool:
        """
        Update agent execution metrics (deprecated - metrics removed from table)
        
        Args:
            metrics: Dictionary of metric names and values (ignored)
            
        Returns:
            True (no-op, kept for backward compatibility)
        """
        # Metrics columns have been removed from agent table
        # This method is kept for backward compatibility but does nothing
        return True
    
    def complete_agent_execution(
        self,
        status: str = 'completed',
        error_message: str = None
    ) -> bool:
        """
        Complete agent execution tracking
        
        Args:
            status: Final status (completed, failed)
            error_message: Error message if failed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not hasattr(self, '_current_agent_id'):
                logger.warning("No active agent execution to complete")
                return False
            
            # Calculate execution time
            execution_time_seconds = 0
            if hasattr(self, '_start_time'):
                execution_time_seconds = int((datetime.utcnow() - self._start_time).total_seconds())
            
            # Update agent record
            query = text("""
                UPDATE agent
                SET status = :status,
                    error_message = :error_message,
                    execution_time_seconds = :execution_time
                WHERE id = :agent_id
            """)
            
            with self.db_service.get_session() as session:
                session.execute(query, {
                    'agent_id': self._current_agent_id,
                    'status': status,
                    'error_message': error_message,
                    'execution_time': execution_time_seconds
                })
                session.commit()
                
            logger.info(f"Completed tracking agent execution: agent_id={self._current_agent_id}, status={status}")
            
            # Clear tracking
            delattr(self, '_current_agent_id')
            if hasattr(self, '_start_time'):
                delattr(self, '_start_time')
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete agent execution tracking: {e}")
            return False
    
    def _generate_agent_name(self, user_id: str) -> str:
        """
        Generate a unique agent name
        
        Args:
            user_id: User ID
            
        Returns:
            Agent name (e.g., "agent_1", "agent_2")
        """
        try:
            # Get the latest agent number for this user
            query = text("""
                SELECT COUNT(*) FROM agent WHERE user_id = :user_id
            """)
            
            with self.db_service.get_session() as session:
                result = session.execute(query, {'user_id': user_id})
                count = result.scalar() or 0
            
            # Generate sequential name
            return f"agent_{count + 1}"
            
        except Exception as e:
            logger.error(f"Failed to generate agent name: {e}")
            return f"agent_{uuid.uuid4().hex[:8]}"
    
    def get_agent_metrics(self, agent_id: int) -> Optional[Dict[str, Any]]:
        """
        Get metrics for a specific agent execution
        
        Args:
            agent_id: Agent execution ID
            
        Returns:
            Dictionary with agent metrics, None if not found
        """
        try:
            query = text("""
                SELECT * FROM agent WHERE id = :agent_id
            """)
            
            with self.db_service.get_session() as session:
                result = session.execute(query, {'agent_id': agent_id})
                row = result.fetchone()
                
                if row:
                    # Convert to dictionary
                    return dict(row._mapping)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get agent metrics: {e}")
            return None
    
    def get_user_agent_history(self, user_id: str, limit: int = 10) -> list:
        """
        Get agent execution history for a user
        
        Args:
            user_id: User ID
            limit: Maximum number of records to return
            
        Returns:
            List of agent execution records
        """
        try:
            query = text("""
                SELECT * FROM agent 
                WHERE user_id = :user_id 
                ORDER BY created DESC 
                LIMIT :limit
            """)
            
            with self.db_service.get_session() as session:
                result = session.execute(query, {'user_id': user_id, 'limit': limit})
                rows = result.fetchall()
                
                return [dict(row._mapping) for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to get user agent history: {e}")
            return []


def get_agent_tracking_service(db_service) -> AgentTrackingService:
    """
    Get an instance of AgentTrackingService
    
    Args:
        db_service: Database service instance
        
    Returns:
        AgentTrackingService instance
    """
    return AgentTrackingService(db_service)

