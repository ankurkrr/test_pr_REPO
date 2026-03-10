"""
Base repository class for data access operations.

This class provides common patterns for:
- Database operations
- Error handling
- Transaction management
- Query building
- Result mapping
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypeVar, Generic
from dataclasses import dataclass
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class QueryResult(Generic[T]):
    """Generic result wrapper for database queries."""
    success: bool
    data: Optional[List[T]] = None
    count: int = 0
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def success_result(cls, data: List[T], count: Optional[int] = None) -> 'QueryResult[T]':
        """Create a successful query result."""
        return cls(
            success=True,
            data=data,
            count=count or len(data) if data else 0
        )

    @classmethod
    def error_result(cls, error: str, metadata: Optional[Dict[str, Any]] = None) -> 'QueryResult[T]':
        """Create an error result."""
        return cls(success=False, error=error, metadata=metadata)


class BaseRepository(ABC):
    """
    Base class for all repository implementations.

    Provides common functionality for:
    - Database operations
    - Transaction management
    - Error handling
    - Query building
    - Result mapping
    """

    def __init__(self, database_service: Any):
        """
        Initialize the repository.

        Args:
            database_service: Database service instance
        """
        self.database_service = database_service
        self.logger = logging.getLogger(self.__class__.__name__)

    @contextmanager
    def get_session(self):
        """
        Get a database session with automatic cleanup.

        Yields:
            Database session
        """
        session = None
        try:
            session = self.database_service.get_session()
            yield session
            session.commit()
        except Exception as e:
            if session:
                session.rollback()
            self.logger.error(f"Database session error: {e}")
            raise
        finally:
            if session:
                session.close()

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> QueryResult[Dict[str, Any]]:
        """
        Execute a raw SQL query.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            QueryResult containing the results
        """
        try:
            with self.get_session() as session:
                from sqlalchemy import text
                result = session.execute(text(query), params or {})

                if query.strip().upper().startswith('SELECT'):
                    rows = result.fetchall()
                    data = [dict(row._mapping) for row in rows]
                    return QueryResult.success_result(data, len(data))
                else:
                    return QueryResult.success_result([], result.rowcount)

        except Exception as e:
            self.logger.error(f"Query execution failed: {e}")
            return QueryResult.error_result(str(e))

    def find_by_id(self, table: str, id_value: Any, id_column: str = "id") -> QueryResult[Dict[str, Any]]:
        """
        Find a record by ID.

        Args:
            table: Table name
            id_value: ID value to search for
            id_column: ID column name (default: "id")

        Returns:
            QueryResult containing the record
        """
        query = f"SELECT * FROM {table} WHERE {id_column} = :id_value"
        params = {"id_value": id_value}

        result = self.execute_query(query, params)
        if result.success and result.data:
            # Return single record instead of list
            return QueryResult.success_result([result.data[0]], 1)
        return result

    def find_by_criteria(self, table: str, criteria: Dict[str, Any],
                        limit: Optional[int] = None, offset: Optional[int] = None) -> QueryResult[Dict[str, Any]]:
        """
        Find records by criteria.

        Args:
            table: Table name
            criteria: Search criteria
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            QueryResult containing the records
        """
        if not criteria:
            query = f"SELECT * FROM {table}"
            params = {}
        else:
            where_clauses = [f"{key} = :{key}" for key in criteria.keys()]
            query = f"SELECT * FROM {table} WHERE {' AND '.join(where_clauses)}"
            params = criteria

        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"

        return self.execute_query(query, params)

    def insert_record(self, table: str, data: Dict[str, Any]) -> QueryResult[str]:
        """
        Insert a new record.

        Args:
            table: Table name
            data: Record data

        Returns:
            QueryResult containing the new record ID
        """
        try:
            columns = list(data.keys())
            placeholders = [f":{col}" for col in columns]

            query = f"""
                INSERT INTO {table} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """

            result = self.execute_query(query, data)
            if result.success:
                # Get the last inserted ID
                id_result = self.execute_query(f"SELECT LAST_INSERT_ID() as id")
                if id_result.success and id_result.data:
                    return QueryResult.success_result([id_result.data[0]["id"]], 1)

            return result

        except Exception as e:
            self.logger.error(f"Insert failed: {e}")
            return QueryResult.error_result(str(e))

    def update_record(self, table: str, id_value: Any, data: Dict[str, Any],
                     id_column: str = "id") -> QueryResult[bool]:
        """
        Update a record by ID.

        Args:
            table: Table name
            id_value: ID value to update
            data: Updated data
            id_column: ID column name (default: "id")

        Returns:
            QueryResult indicating success
        """
        try:
            if not data:
                return QueryResult.success_result([True], 1)

            set_clauses = [f"{key} = :{key}" for key in data.keys()]
            query = f"""
                UPDATE {table}
                SET {', '.join(set_clauses)}
                WHERE {id_column} = :id_value
            """

            params = {**data, "id_value": id_value}
            result = self.execute_query(query, params)

            if result.success:
                return QueryResult.success_result([result.count > 0], 1)
            return result

        except Exception as e:
            self.logger.error(f"Update failed: {e}")
            return QueryResult.error_result(str(e))

    def delete_record(self, table: str, id_value: Any, id_column: str = "id") -> QueryResult[bool]:
        """
        Delete a record by ID.

        Args:
            table: Table name
            id_value: ID value to delete
            id_column: ID column name (default: "id")

        Returns:
            QueryResult indicating success
        """
        try:
            query = f"DELETE FROM {table} WHERE {id_column} = :id_value"
            params = {"id_value": id_value}

            result = self.execute_query(query, params)
            if result.success:
                return QueryResult.success_result([result.count > 0], 1)
            return result

        except Exception as e:
            self.logger.error(f"Delete failed: {e}")
            return QueryResult.error_result(str(e))

    def count_records(self, table: str, criteria: Optional[Dict[str, Any]] = None) -> QueryResult[int]:
        """
        Count records matching criteria.

        Args:
            table: Table name
            criteria: Search criteria (optional)

        Returns:
            QueryResult containing the count
        """
        if criteria:
            where_clauses = [f"{key} = :{key}" for key in criteria.keys()]
            query = f"SELECT COUNT(*) as count FROM {table} WHERE {' AND '.join(where_clauses)}"
            params = criteria
        else:
            query = f"SELECT COUNT(*) as count FROM {table}"
            params = {}

        result = self.execute_query(query, params)
        if result.success and result.data:
            count = result.data[0]["count"]
            return QueryResult.success_result([count], 1)
        return result

    def exists(self, table: str, criteria: Dict[str, Any]) -> QueryResult[bool]:
        """
        Check if records exist matching criteria.

        Args:
            table: Table name
            criteria: Search criteria

        Returns:
            QueryResult containing existence boolean
        """
        count_result = self.count_records(table, criteria)
        if count_result.success and count_result.data:
            exists = count_result.data[0] > 0
            return QueryResult.success_result([exists], 1)
        return count_result