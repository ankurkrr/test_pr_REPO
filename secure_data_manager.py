#!/usr/bin/env python3
"""
 Comprehensive Secure Data Manager
Integrates encryption, user isolation, audit logging, and secure deletion
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple, Union
from datetime import datetime, timedelta
from contextlib import contextmanager
from sqlalchemy import (
    create_engine,
    text,
    Column,
    String,
    DateTime,
    Boolean,
    Text,
    Integer,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from .data_encryption import (
    FieldEncryption,
    ComprehensiveAuditLogger,
    SecureDataDeletion,
    UserDataIsolation,
)

logger = logging.getLogger(__name__)

Base = declarative_base()


class SecureDataRecord(Base):
    """Database model for secure data storage"""

    __tablename__ = "secure_data"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    data_type = Column(String(100), nullable=False)
    record_id = Column(String(255), nullable=False)
    encrypted_data = Column(Text, nullable=False)
    record_metadata = Column(
        Text
    )  # Changed from 'metadata' to avoid SQLAlchemy conflict
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_deleted = Column(Boolean, default=False)


class SecureDataManager:
    """
    Comprehensive secure data manager with encryption, isolation, and auditing
    """

    def __init__(
        self, db_url: str = None, encryption_key: str = None, audit_enabled: bool = True
    ):
        """
        Initialize secure data manager

        Args:
            db_url: Database connection URL
            encryption_key: Master encryption key
            audit_enabled: Enable comprehensive audit logging
        """
        self.db_url = db_url or os.getenv("DATABASE_URL", "sqlite:///secure_data.db")
        self.encryption = FieldEncryption(master_key=encryption_key)
        self.audit_enabled = audit_enabled
        self.user_isolation = UserDataIsolation()
        self.secure_deletion = SecureDataDeletion()
        self._lock = threading.Lock()

        # Initialize database
        self._setup_database()

        # Initialize audit logger
        if audit_enabled:
            self.audit_logger = ComprehensiveAuditLogger(
                log_file="logs/secure_data_audit.log", db_connection=self.db_url
            )
        else:
            self.audit_logger = None

    def _setup_database(self):
        """Setup database connection and tables"""
        try:
            self.engine = create_engine(self.db_url, echo=False)
            self.SessionLocal = sessionmaker(bind=self.engine)

            # Create tables
            Base.metadata.create_all(self.engine)

            logger.info("Secure data manager database initialized")

        except Exception as e:
            logger.error(f"Database setup failed: {e}")
            raise

    @contextmanager
    def get_session(self):
        """Get database session with automatic cleanup"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def store_sensitive_data(
        self,
        user_id: str,
        data_type: str,
        record_id: str,
        data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: str = None,
    ) -> bool:
        """
        Store sensitive data with encryption and user isolation

        Args:
            user_id: User ID for isolation
            data_type: Type of data (e.g., 'meeting', 'profile', 'credentials')
            record_id: Unique record identifier
            data: Sensitive data to encrypt and store
            metadata: Additional metadata
            ip_address: Client IP for audit logging

        Returns:
            Success status
        """
        try:
            with self._lock:
                # Encrypt sensitive data
                encrypted_data = {}
                for field_name, field_value in data.items():
                    if self._is_sensitive_field(field_name):
                        encrypted_data[field_name] = self.encryption.encrypt_field(
                            field_value, field_name, user_id, metadata
                        )
                    else:
                        encrypted_data[field_name] = field_value

                # Store in database with user isolation
                with self.get_session() as session:
                    # Check if record exists
                    existing = (
                        session.query(SecureDataRecord)
                        .filter_by(
                            user_id=user_id,
                            data_type=data_type,
                            record_id=record_id,
                            is_deleted=False,
                        )
                        .first()
                    )

                    if existing:
                        # Update existing record
                        existing.encrypted_data = json.dumps(encrypted_data)
                        existing.record_metadata = (
                            json.dumps(metadata) if metadata else None
                        )
                        existing.updated_at = datetime.now()
                        operation = "UPDATE"
                    else:
                        # Create new record
                        new_record = SecureDataRecord(
                            user_id=user_id,
                            data_type=data_type,
                            record_id=record_id,
                            encrypted_data=json.dumps(encrypted_data),
                            record_metadata=json.dumps(metadata) if metadata else None,
                        )
                        session.add(new_record)
                        operation = "CREATE"

                # Audit logging
                if self.audit_logger:
                    self.audit_logger.log_data_access(
                        user_id=user_id,
                        data_type=data_type,
                        operation=operation,
                        record_id=record_id,
                        success=True,
                    )

                    # Log encryption operations for sensitive fields
                    for field_name in data.keys():
                        if self._is_sensitive_field(field_name):
                            self.audit_logger.log_encryption_operation(
                                user_id=user_id,
                                field_name=field_name,
                                operation="ENCRYPT",
                                success=True,
                            )

                logger.info(
                    f"Sensitive data stored: {data_type}:{record_id} for user {user_id}"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to store sensitive data: {e}")

            # Audit failure
            if self.audit_logger:
                self.audit_logger.log_data_access(
                    user_id=user_id,
                    data_type=data_type,
                    operation="CREATE/UPDATE",
                    record_id=record_id,
                    success=False,
                )

            return False

    def retrieve_sensitive_data(
        self,
        user_id: str,
        data_type: str,
        record_id: str = None,
        ip_address: str = None,
    ) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Retrieve and decrypt sensitive data with user isolation

        Args:
            user_id: User ID for isolation
            data_type: Type of data to retrieve
            record_id: Specific record ID (optional)
            ip_address: Client IP for audit logging

        Returns:
            Decrypted data or None if not found
        """
        try:
            with self.get_session() as session:
                # Build query with user isolation
                query = session.query(SecureDataRecord).filter_by(
                    user_id=user_id, data_type=data_type, is_deleted=False
                )

                if record_id:
                    query = query.filter_by(record_id=record_id)
                    records = [query.first()]
                else:
                    records = query.all()

                if not records or (record_id and not records[0]):
                    # Audit access attempt
                    if self.audit_logger:
                        self.audit_logger.log_data_access(
                            user_id=user_id,
                            data_type=data_type,
                            operation="READ",
                            record_id=record_id,
                            success=False,
                        )
                    return None

                # Decrypt data
                decrypted_records = []
                for record in records:
                    if record:
                        encrypted_data = json.loads(record.encrypted_data)
                        decrypted_data = {}

                        for field_name, field_value in encrypted_data.items():
                            if self._is_sensitive_field(field_name) and isinstance(
                                field_value, str
                            ):
                                try:
                                    decrypted_value, field_metadata = (
                                        self.encryption.decrypt_field(
                                            field_value, field_name, user_id
                                        )
                                    )
                                    decrypted_data[field_name] = decrypted_value

                                    # Log decryption
                                    if self.audit_logger:
                                        self.audit_logger.log_encryption_operation(
                                            user_id=user_id,
                                            field_name=field_name,
                                            operation="DECRYPT",
                                            success=True,
                                        )

                                except Exception as e:
                                    logger.error(
                                        f"Failed to decrypt field {field_name}: {e}"
                                    )
                                    decrypted_data[field_name] = None
                            else:
                                decrypted_data[field_name] = field_value

                        # Add metadata
                        if record.record_metadata:
                            decrypted_data["_metadata"] = json.loads(
                                record.record_metadata
                            )

                        decrypted_records.append(decrypted_data)

                # Audit successful access
                if self.audit_logger:
                    self.audit_logger.log_data_access(
                        user_id=user_id,
                        data_type=data_type,
                        operation="READ",
                        record_id=record_id,
                        success=True,
                    )

                # Return single record or list
                if record_id:
                    return decrypted_records[0] if decrypted_records else None
                else:
                    return decrypted_records

        except Exception as e:
            logger.error(f"Failed to retrieve sensitive data: {e}")

            # Audit failure
            if self.audit_logger:
                self.audit_logger.log_data_access(
                    user_id=user_id,
                    data_type=data_type,
                    operation="READ",
                    record_id=record_id,
                    success=False,
                )

            return None

    def secure_delete_data(
        self, user_id: str, data_type: str, record_id: str, ip_address: str = None
    ) -> bool:
        """
        Securely delete sensitive data with multiple overwrite passes

        Args:
            user_id: User ID for isolation
            data_type: Type of data to delete
            record_id: Record ID to delete
            ip_address: Client IP for audit logging

        Returns:
            Success status
        """
        try:
            with self._lock:
                with self.get_session() as session:
                    # Find record with user isolation
                    record = (
                        session.query(SecureDataRecord)
                        .filter_by(
                            user_id=user_id,
                            data_type=data_type,
                            record_id=record_id,
                            is_deleted=False,
                        )
                        .first()
                    )

                    if not record:
                        return False

                    # Secure overwrite of encrypted data
                    original_data = record.encrypted_data

                    # Multiple overwrite passes
                    for i in range(3):
                        # Overwrite with random data of same length
                        random_data = os.urandom(len(original_data.encode()))
                        record.encrypted_data = random_data.hex()
                        session.flush()

                    # Mark as deleted
                    record.is_deleted = True
                    record.updated_at = datetime.now()

                # Audit deletion
                if self.audit_logger:
                    self.audit_logger.log_data_access(
                        user_id=user_id,
                        data_type=data_type,
                        operation="DELETE",
                        record_id=record_id,
                        success=True,
                    )

                logger.info(
                    f"Sensitive data securely deleted: {data_type}:{record_id} for user {user_id}"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to securely delete data: {e}")

            # Audit failure
            if self.audit_logger:
                self.audit_logger.log_data_access(
                    user_id=user_id,
                    data_type=data_type,
                    operation="DELETE",
                    record_id=record_id,
                    success=False,
                )

            return False

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if field contains sensitive data that should be encrypted"""
        sensitive_patterns = [
            "password",
            "secret",
            "key",
            "token",
            "credential",
            "private",
            "confidential",
            "sensitive",
            "email",
            "phone",
            "address",
            "ssn",
            "credit_card",
            "transcript",
            "summary",
            "notes",
            "content",
        ]

        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in sensitive_patterns)

    def get_user_data_summary(self, user_id: str) -> Dict[str, Any]:
        """Get summary of user's stored data for privacy compliance"""
        try:
            with self.get_session() as session:
                records = (
                    session.query(SecureDataRecord)
                    .filter_by(user_id=user_id, is_deleted=False)
                    .all()
                )

                summary = {
                    "user_id": user_id,
                    "total_records": len(records),
                    "data_types": {},
                    "created_range": None,
                    "last_updated": None,
                }

                if records:
                    # Group by data type
                    for record in records:
                        data_type = record.data_type
                        if data_type not in summary["data_types"]:
                            summary["data_types"][data_type] = 0
                        summary["data_types"][data_type] += 1

                    # Date ranges
                    created_dates = [r.created_at for r in records]
                    updated_dates = [r.updated_at for r in records]

                    summary["created_range"] = {
                        "earliest": min(created_dates).isoformat(),
                        "latest": max(created_dates).isoformat(),
                    }
                    summary["last_updated"] = max(updated_dates).isoformat()

                return summary

        except Exception as e:
            logger.error(f"Failed to get user data summary: {e}")
            return {"error": str(e)}


# Global instance
_secure_data_manager = None


def get_secure_data_manager() -> SecureDataManager:
    """Get global secure data manager instance"""
    global _secure_data_manager
    if _secure_data_manager is None:
        _secure_data_manager = SecureDataManager()
    return _secure_data_manager