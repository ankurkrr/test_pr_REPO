"""
Memory Repository

Handles all AI memory and conversation-related database operations.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

class MemoryRepository:
    """Repository for AI memory and conversation data operations"""

    def __init__(self, db_session: Session):
        self.db_session = db_session

    def create_memory(
        self,
        user_id: str,
        organization_id: str,
        memory_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        importance_score: int = 5,
        expires_at: Optional[datetime] = None
    ) -> str:
        """Create a new AI memory"""
        try:
            memory_id = str(uuid.uuid4())
            self.db_session.execute(
                text("""
                    INSERT INTO ai_memories (
                        id, user_id, organization_id, memory_type, content,
                        metadata, importance_score, expires_at, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :organization_id, :memory_type, :content,
                        :metadata, :importance_score, :expires_at, :created_at, :updated_at
                    )
                """),
                {
                    "id": memory_id,
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "memory_type": memory_type,
                    "content": content,
                    "metadata": json.dumps(metadata) if metadata else None,
                    "importance_score": importance_score,
                    "expires_at": expires_at,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
            )
            self.db_session.commit()
            return memory_id
        except Exception as e:
            logger.error(f"Error creating memory for user {user_id}: {e}")
            self.db_session.rollback()
            raise

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID"""
        try:
            result = self.db_session.execute(
                text("""
                    SELECT id, user_id, organization_id, memory_type, content,
                           metadata, importance_score, access_count, last_accessed_at,
                           expires_at, created_at, updated_at
                    FROM ai_memories
                    WHERE id = :memory_id
                """),
                {"memory_id": memory_id}
            ).fetchone()

            if result:
                return {
                    "id": result.id,
                    "user_id": result.user_id,
                    "organization_id": result.organization_id,
                    "memory_type": result.memory_type,
                    "content": result.content,
                    "metadata": json.loads(result.metadata) if result.metadata else None,
                    "importance_score": result.importance_score,
                    "access_count": result.access_count,
                    "last_accessed_at": result.last_accessed_at,
                    "expires_at": result.expires_at,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at
                }
            return None
        except Exception as e:
            logger.error(f"Error getting memory {memory_id}: {e}")
            return None

    def get_memories_by_user(
        self,
        user_id: str,
        memory_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get memories for a user with optional filtering"""
        try:
            where_clause = "WHERE user_id = :user_id"
            params = {"user_id": user_id, "limit": limit, "offset": offset}

            if memory_type:
                where_clause += " AND memory_type = :memory_type"
                params["memory_type"] = memory_type

            results = self.db_session.execute(
                text(f"""
                    SELECT id, user_id, organization_id, memory_type, content,
                           metadata, importance_score, access_count, last_accessed_at,
                           expires_at, created_at, updated_at
                    FROM ai_memories
                    {where_clause}
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params
            ).fetchall()

            memories = []
            for result in results:
                memories.append({
                    "id": result.id,
                    "user_id": result.user_id,
                    "organization_id": result.organization_id,
                    "memory_type": result.memory_type,
                    "content": result.content,
                    "metadata": json.loads(result.metadata) if result.metadata else None,
                    "importance_score": result.importance_score,
                    "access_count": result.access_count,
                    "last_accessed_at": result.last_accessed_at,
                    "expires_at": result.expires_at,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at
                })
            return memories
        except Exception as e:
            logger.error(f"Error getting memories for user {user_id}: {e}")
            return []

    def search_memories(
        self,
        user_id: str,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search memories using full-text search"""
        try:
            where_clause = "WHERE user_id = :user_id AND MATCH(content) AGAINST(:query IN NATURAL LANGUAGE MODE)"
            params = {"user_id": user_id, "query": query, "limit": limit}

            if memory_type:
                where_clause += " AND memory_type = :memory_type"
                params["memory_type"] = memory_type

            results = self.db_session.execute(
                text(f"""
                    SELECT id, user_id, organization_id, memory_type, content,
                           metadata, importance_score, access_count, last_accessed_at,
                           expires_at, created_at, updated_at,
                           MATCH(content) AGAINST(:query IN NATURAL LANGUAGE MODE) as relevance_score
                    FROM ai_memories
                    {where_clause}
                    ORDER BY relevance_score DESC, importance_score DESC
                    LIMIT :limit
                """),
                params
            ).fetchall()

            memories = []
            for result in results:
                memories.append({
                    "id": result.id,
                    "user_id": result.user_id,
                    "organization_id": result.organization_id,
                    "memory_type": result.memory_type,
                    "content": result.content,
                    "metadata": json.loads(result.metadata) if result.metadata else None,
                    "importance_score": result.importance_score,
                    "access_count": result.access_count,
                    "last_accessed_at": result.last_accessed_at,
                    "expires_at": result.expires_at,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at,
                    "relevance_score": result.relevance_score
                })
            return memories
        except Exception as e:
            logger.error(f"Error searching memories for user {user_id}: {e}")
            return []

    def update_memory_access(self, memory_id: str) -> bool:
        """Update memory access count and last accessed time"""
        try:
            result = self.db_session.execute(
                text("""
                    UPDATE ai_memories
                    SET access_count = access_count + 1,
                        last_accessed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :memory_id
                """),
                {"memory_id": memory_id}
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating memory access for {memory_id}: {e}")
            self.db_session.rollback()
            return False

    def update_memory_importance(self, memory_id: str, importance_score: int) -> bool:
        """Update memory importance score"""
        try:
            result = self.db_session.execute(
                text("""
                    UPDATE ai_memories
                    SET importance_score = :importance_score, updated_at = NOW()
                    WHERE id = :memory_id
                """),
                {"memory_id": memory_id, "importance_score": importance_score}
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating memory importance for {memory_id}: {e}")
            self.db_session.rollback()
            return False

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory"""
        try:
            result = self.db_session.execute(
                text("DELETE FROM ai_memories WHERE id = :memory_id"),
                {"memory_id": memory_id}
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting memory {memory_id}: {e}")
            self.db_session.rollback()
            return False

    def cleanup_expired_memories(self) -> int:
        """Clean up expired memories"""
        try:
            result = self.db_session.execute(
                text("""
                    DELETE FROM ai_memories
                    WHERE expires_at < NOW() AND expires_at IS NOT NULL
                """)
            )
            self.db_session.commit()
            return result.rowcount
        except Exception as e:
            logger.error(f"Error cleaning up expired memories: {e}")
            self.db_session.rollback()
            return 0

    def create_conversation_session(
        self,
        user_id: str,
        organization_id: str,
        session_type: str,
        title: Optional[str] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new conversation session"""
        try:
            session_id = str(uuid.uuid4())
            self.db_session.execute(
                text("""
                    INSERT INTO conversation_sessions (
                        id, user_id, organization_id, session_type, title,
                        context_data, status, started_at, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :organization_id, :session_type, :title,
                        :context_data, :status, :started_at, :created_at, :updated_at
                    )
                """),
                {
                    "id": session_id,
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "session_type": session_type,
                    "title": title,
                    "context_data": json.dumps(context_data) if context_data else None,
                    "status": "active",
                    "started_at": datetime.now(),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
            )
            self.db_session.commit()
            return session_id
        except Exception as e:
            logger.error(f"Error creating conversation session for user {user_id}: {e}")
            self.db_session.rollback()
            raise

    def add_conversation_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
        token_count: Optional[int] = None
    ) -> str:
        """Add a message to a conversation session"""
        try:
            message_id = str(uuid.uuid4())
            self.db_session.execute(
                text("""
                    INSERT INTO conversation_messages (
                        id, session_id, user_id, role, content, message_type,
                        metadata, token_count, created_at
                    ) VALUES (
                        :id, :session_id, :user_id, :role, :content, :message_type,
                        :metadata, :token_count, :created_at
                    )
                """),
                {
                    "id": message_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "role": role,
                    "content": content,
                    "message_type": message_type,
                    "metadata": json.dumps(metadata) if metadata else None,
                    "token_count": token_count,
                    "created_at": datetime.now()
                }
            )

            # Update session message count
            self.db_session.execute(
                text("""
                    UPDATE conversation_sessions
                    SET message_count = message_count + 1, updated_at = NOW()
                    WHERE id = :session_id
                """),
                {"session_id": session_id}
            )

            self.db_session.commit()
            return message_id
        except Exception as e:
            logger.error(f"Error adding message to session {session_id}: {e}")
            self.db_session.rollback()
            raise

    def get_conversation_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get messages from a conversation session"""
        try:
            results = self.db_session.execute(
                text("""
                    SELECT id, session_id, user_id, role, content, message_type,
                           metadata, token_count, created_at
                    FROM conversation_messages
                    WHERE session_id = :session_id
                    ORDER BY created_at ASC
                    LIMIT :limit OFFSET :offset
                """),
                {"session_id": session_id, "limit": limit, "offset": offset}
            ).fetchall()

            messages = []
            for result in results:
                messages.append({
                    "id": result.id,
                    "session_id": result.session_id,
                    "user_id": result.user_id,
                    "role": result.role,
                    "content": result.content,
                    "message_type": result.message_type,
                    "metadata": json.loads(result.metadata) if result.metadata else None,
                    "token_count": result.token_count,
                    "created_at": result.created_at
                })
            return messages
        except Exception as e:
            logger.error(f"Error getting messages for session {session_id}: {e}")
            return []

    def get_active_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active conversation sessions for a user"""
        try:
            results = self.db_session.execute(
                text("""
                    SELECT id, user_id, organization_id, session_type, title,
                           context_data, status, started_at, ended_at, message_count,
                           created_at, updated_at
                    FROM conversation_sessions
                    WHERE user_id = :user_id AND status = 'active'
                    ORDER BY started_at DESC
                """),
                {"user_id": user_id}
            ).fetchall()

            sessions = []
            for result in results:
                sessions.append({
                    "id": result.id,
                    "user_id": result.user_id,
                    "organization_id": result.organization_id,
                    "session_type": result.session_type,
                    "title": result.title,
                    "context_data": json.loads(result.context_data) if result.context_data else None,
                    "status": result.status,
                    "started_at": result.started_at,
                    "ended_at": result.ended_at,
                    "message_count": result.message_count,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at
                })
            return sessions
        except Exception as e:
            logger.error(f"Error getting active sessions for user {user_id}: {e}")
            return []

    def end_conversation_session(self, session_id: str) -> bool:
        """End a conversation session"""
        try:
            result = self.db_session.execute(
                text("""
                    UPDATE conversation_sessions
                    SET status = 'completed', ended_at = NOW(), updated_at = NOW()
                    WHERE id = :session_id
                """),
                {"session_id": session_id}
            )
            self.db_session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error ending session {session_id}: {e}")
            self.db_session.rollback()
            return False