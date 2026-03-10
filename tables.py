"""
Database Table Definitions
Defines SQLAlchemy ORM models for the 3-table audit system
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Agent(Base):
    """
    Agent table - tracks each agent execution with metrics
    Stores per-user agent runs with execution status and metrics
    """
    __tablename__ = "agent"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # e.g., "agent_1", "agent_2", "agent_A", "agent_B"
    description = Column(String(500))  # e.g., "langchain_meeting_agent"
    user_id = Column(String(255), nullable=False, index=True)
    agent_task_id = Column(String(255), nullable=True, index=True)
    status = Column(String(50), default='running')  # running, completed, failed
    created = Column(DateTime, default=datetime.utcnow)
    
    # Additional tracking
    error_message = Column(Text, nullable=True)
    execution_time_seconds = Column(Integer, default=0)
    
    # Composite index for common queries
    __table_args__ = (
        Index('idx_agent_user_status', 'user_id', 'status'),
        Index('idx_agent_org_user', 'org_id', 'user_id'),
        Index('idx_agent_created', 'created'),
    )
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'org_id': self.org_id,
            'name': self.name,
            'description': self.description,
            'user_id': self.user_id,
            'agent_task_id': self.agent_task_id,
            'status': self.status,
            'created': self.created.isoformat() if self.created else None,
            'error_message': self.error_message,
            'execution_time_seconds': self.execution_time_seconds
        }


class UserAgentTask(Base):
    """
    User Agent Task table - tracks user agent configurations
    References agent instances for each user
    """
    __tablename__ = "user_agent_task"
    
    agent_task_id = Column(String(255), primary_key=True)
    org_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Integer, default=1)  # 1 = active, 0 = inactive
    ready_to_use = Column(Integer, default=1)  # 1 = ready, 0 = not ready
    created = Column(DateTime, default=datetime.utcnow)
    updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Additional fields
    drive_folder_id = Column(String(255), nullable=True)
    sheets_id = Column(String(255), nullable=True)
    
    __table_args__ = (
        Index('idx_user_task_user_status', 'user_id', 'status'),
        Index('idx_user_task_org_user', 'org_id', 'user_id'),
        Index('idx_user_task_created', 'created'),
    )
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'agent_task_id': self.agent_task_id,
            'org_id': self.org_id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'ready_to_use': self.ready_to_use,
            'created': self.created.isoformat() if self.created else None,
            'updated': self.updated.isoformat() if self.updated else None,
            'drive_folder_id': self.drive_folder_id,
            'sheets_id': self.sheets_id
        }


class AgentFunctionLog(Base):
    """
    Agent Function Log table - detailed audit logging
    Tracks individual function/tool calls within agent executions
    """
    __tablename__ = "agent_function_log"
    
    id = Column(String(255), primary_key=True)
    org_id = Column(String(255), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    agent_task_id = Column(String(255), nullable=True, index=True)
    activity_type = Column(String(100), nullable=False)  # task, integration, chain, etc.
    log_for_status = Column(String(50), nullable=False)  # success, error, info
    log_text = Column(Text, nullable=False)
    log_data = Column(Text, nullable=True)  # JSON string
    status = Column(Integer, default=1)  # 1 = active, 0 = inactive
    created = Column(DateTime, default=datetime.utcnow)
    
    # Additional fields from original design
    tool_name = Column(String(255), nullable=True)
    outcome = Column(String(255), nullable=True)
    action_required = Column(String(255), nullable=True)
    scope = Column(String(255), nullable=True)
    step_str = Column(String(255), nullable=True)
    
    __table_args__ = (
        Index('idx_log_agent_task', 'agent_task_id', 'created'),
        Index('idx_log_agent_status', 'agent_id', 'activity_type'),
        Index('idx_log_created', 'created'),
    )
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'org_id': self.org_id,
            'agent_id': self.agent_id,
            'agent_task_id': self.agent_task_id,
            'activity_type': self.activity_type,
            'log_for_status': self.log_for_status,
            'log_text': self.log_text,
            'log_data': self.log_data,
            'status': self.status,
            'created': self.created.isoformat() if self.created else None,
            'tool_name': self.tool_name,
            'outcome': self.outcome,
            'action_required': self.action_required,
            'scope': self.scope,
            'step_str': self.step_str
        }


def get_core_tables():
    """Return list of core table classes"""
    return [Agent, UserAgentTask, AgentFunctionLog]

