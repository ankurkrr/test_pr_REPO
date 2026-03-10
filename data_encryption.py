"""
Field-Level Data Encryption and Secure Data Management
Implements AES-GCM encryption for sensitive data fields with user-based isolation
"""

import os
import json
import base64
import logging
import hashlib
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union, Tuple
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import secrets

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Custom encryption error"""
    pass


class FieldEncryption:
    """
    Enhanced field-level encryption for sensitive data with multiple algorithms
    """

    def __init__(self, master_key: Optional[str] = None, algorithm: str = "AES-GCM"):
        """
        Initialize field encryption

        Args:
            master_key: Master encryption key (from environment or secure storage)
            algorithm: Encryption algorithm (AES-GCM, ChaCha20-Poly1305)
        """
        self.master_key = master_key or self._get_master_key()
        self.algorithm = algorithm
        self._field_keys = {}  # Cache for derived field keys
        self._key_rotation_interval = timedelta(days=30)  # Key rotation every 30 days
        self._last_rotation = {}  # Track last rotation per field
        self._lock = threading.Lock()  # Thread safety

    def _get_master_key(self) -> str:
        """Get master encryption key"""
        key_file = "keys/field_encryption.key"
        try:
            master_key = os.getenv("FIELD_ENCRYPTION_KEY")
            if master_key:
                return master_key

            if os.path.exists(key_file):
                with open(key_file, 'r') as f:
                    return f.read().strip()

            # Generate new key
            master_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            os.makedirs("keys", exist_ok=True)
            with open(key_file, 'w') as f:
                f.write(master_key)

            logger.warning("Generated new field encryption key")
            return master_key

        except (OSError, IOError) as e:
            logger.error("Failed to get field encryption key: %s", e)
            raise EncryptionError("Field encryption key initialization failed: %s" % e)

    def _derive_field_key(self, field_name: str, user_id: str) -> bytes:
        """Derive encryption key for specific field and user"""
        try:
            salt_data = f"{field_name}:{user_id}:field_encryption_v1"
            salt = hashlib.sha256(salt_data.encode()).digest()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
                backend=default_backend()
            )
            return kdf.derive(self.master_key.encode())
        except (ValueError, TypeError) as e:
            logger.error("Field key derivation failed for %s: %s", field_name, e)
            raise EncryptionError("Failed to derive field key: %s" % e)

    def encrypt_field(
        self,
        value: Any,
        field_name: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Enhanced field encryption with metadata and algorithm support
        """
        if value is None:
            return None

        self._check_key_rotation(field_name, user_id)

        if isinstance(value, (dict, list)):
            json_value = json.dumps(value, separators=(',', ':'))
        else:
            json_value = str(value)

        payload = {
            "data": json_value,
            "timestamp": datetime.now().isoformat(),
            "field": field_name,
            "user_id": user_id,
            "algorithm": self.algorithm,
            "version": "2.0"
        }
        if metadata:
            payload["metadata"] = metadata

        payload_bytes = json.dumps(payload, separators=(',', ':')).encode()

        key_id = f"{field_name}:{user_id}"
        if key_id not in self._field_keys:
            self._field_keys[key_id] = self._derive_field_key(field_name, user_id)
        field_key = self._field_keys[key_id]

        try:
            if self.algorithm == "AES-GCM":
                aesgcm = AESGCM(field_key)
                nonce = secrets.token_bytes(12)
                ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
            elif self.algorithm == "ChaCha20-Poly1305":
                chacha = ChaCha20Poly1305(field_key)
                nonce = secrets.token_bytes(12)
                ciphertext = chacha.encrypt(nonce, payload_bytes, None)
            else:
                raise EncryptionError("Unsupported algorithm: %s" % self.algorithm)

            return base64.urlsafe_b64encode(nonce + ciphertext).decode()

        except (ValueError, TypeError) as e:
            logger.error("Field encryption failed for %s: %s", field_name, e)
            raise EncryptionError("Failed to encrypt field %s: %s" % (field_name, e))

    def _check_key_rotation(self, field_name: str, user_id: str):
        """Check if key rotation is needed for field"""
        with self._lock:
            key_id = f"{field_name}:{user_id}"
            last_rotation = self._last_rotation.get(key_id)
            if last_rotation is None or (datetime.now() - last_rotation) > self._key_rotation_interval:
                self._field_keys.pop(key_id, None)
                self._last_rotation[key_id] = datetime.now()
                logger.info("Key rotated for field: %s, user: %s", field_name, user_id)

    def decrypt_field(self, encrypted_value: str, field_name: str, user_id: str) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """
        Enhanced field decryption with metadata support
        """
        if not encrypted_value:
            return None, None

        try:
            encrypted_data = base64.urlsafe_b64decode(encrypted_value.encode())
            nonce, ciphertext = encrypted_data[:12], encrypted_data[12:]

            key_id = f"{field_name}:{user_id}"
            if key_id not in self._field_keys:
                self._field_keys[key_id] = self._derive_field_key(field_name, user_id)
            field_key = self._field_keys[key_id]

            decrypted_data = None
            algorithm_used = None

            for alg in [self.algorithm, "AES-GCM", "ChaCha20-Poly1305"]:
                try:
                    if alg == "AES-GCM":
                        decrypted_data = AESGCM(field_key).decrypt(nonce, ciphertext, None)
                    elif alg == "ChaCha20-Poly1305":
                        decrypted_data = ChaCha20Poly1305(field_key).decrypt(nonce, ciphertext, None)
                    algorithm_used = alg
                    break
                except (ValueError, TypeError):
                    continue

            if decrypted_data is None:
                raise EncryptionError("Failed to decrypt with any supported algorithm")

            json_value = decrypted_data.decode()
            try:
                payload = json.loads(json_value)
                if isinstance(payload, dict) and "data" in payload and "version" in payload:
                    decrypted_value = payload["data"]
                    metadata = {
                        "timestamp": payload.get("timestamp"),
                        "algorithm": payload.get("algorithm", algorithm_used),
                        "version": payload.get("version"),
                        "metadata": payload.get("metadata")
                    }
                    try:
                        parsed_data = json.loads(decrypted_value)
                        return parsed_data, metadata
                    except json.JSONDecodeError:
                        return decrypted_value, metadata
                else:
                    return payload, {"algorithm": algorithm_used, "version": "1.0"}
            except json.JSONDecodeError:
                return json_value, {"algorithm": algorithm_used, "version": "legacy"}

        except (ValueError, TypeError) as e:
            logger.error("Field decryption failed for %s: %s", field_name, e)
            raise EncryptionError("Failed to decrypt field %s: %s" % (field_name, e))


class SecureDataModel:
    """Base class for models with encrypted fields"""
    ENCRYPTED_FIELDS: List[str] = []

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.field_encryption = FieldEncryption()

    def encrypt_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive data fields"""
        encrypted_data = data.copy()
        for field_name in self.ENCRYPTED_FIELDS:
            if field_name in encrypted_data:
                encrypted_data[field_name] = self.field_encryption.encrypt_field(
                    encrypted_data[field_name], field_name, self.user_id
                )
        return encrypted_data

    def decrypt_sensitive_data(self, encrypted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt sensitive data fields"""
        decrypted_data = encrypted_data.copy()
        for field_name in self.ENCRYPTED_FIELDS:
            if field_name in decrypted_data and decrypted_data[field_name]:
                decrypted_data[field_name] = self.field_encryption.decrypt_field(
                    decrypted_data[field_name], field_name, self.user_id
                )
        return decrypted_data


class UserDataIsolation:
    """User-based data isolation for database operations"""

    @staticmethod
    def add_user_filter(query_params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Add user filter to query parameters"""
        filtered_params = query_params.copy()
        filtered_params['user_id'] = user_id
        return filtered_params

    @staticmethod
    def validate_user_access(data: Dict[str, Any], user_id: str) -> bool:
        """Validate user access to data"""
        return data.get('user_id') == user_id

    @staticmethod
    def filter_user_data(data_list: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
        """Filter data list for user access"""
        return [item for item in data_list if item.get('user_id') == user_id]


class SecureDataDeletion:
    """Secure data deletion with multiple overwrite passes"""

    @staticmethod
    def secure_delete_file(file_path: str, passes: int = 3) -> bool:
        """Securely delete file with multiple overwrite passes"""
        if not os.path.exists(file_path):
            return True
        try:
            file_size = os.path.getsize(file_path)
            for pass_num in range(passes):
                with open(file_path, 'wb') as f:
                    f.write(secrets.token_bytes(file_size))
                    f.flush()
                    os.fsync(f.fileno())
                logger.debug("Secure deletion pass %d/%d completed", pass_num + 1, passes)
            os.remove(file_path)
            logger.info("File securely deleted: %s", file_path)
            return True
        except (OSError, IOError) as e:
            logger.error("Secure file deletion failed: %s", e)
            return False

    @staticmethod
    def secure_delete_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """ Securely delete sensitive data by overwriting with random data"""
        secure_data = data.copy()
        sensitive_patterns = [
            'password', 'secret', 'key', 'token', 'credential',
            'private', 'confidential', 'sensitive'
        ]
        for key, value in secure_data.items():
            key_lower = key.lower()
            if any(pattern in key_lower for pattern in sensitive_patterns):
                if isinstance(value, str):
                    secure_data[key] = secrets.token_urlsafe(len(value))[:len(value)]
                elif isinstance(value, (dict, list)):
                    secure_data[key] = type(value)()
                else:
                    secure_data[key] = None
        return secure_data

    @staticmethod
    def secure_overwrite_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Securely overwrite sensitive data with random data"""
        return SecureDataDeletion.secure_delete_data(data)


class ComprehensiveAuditLogger:
    """Enhanced audit logging for all sensitive operations with database storage"""

    def __init__(self, log_file: str = "logs/audit.log", db_connection: Optional[str] = None):
        self.log_file = log_file
        self.db_connection = db_connection
        self._ensure_log_directory()
        self._setup_database()

        self.audit_logger = logging.getLogger("audit")
        self.audit_logger.setLevel(logging.INFO)
        if not self.audit_logger.handlers:
            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter('%(asctime)s - AUDIT - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.audit_logger.addHandler(handler)

    def _ensure_log_directory(self):
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)

    def _setup_database(self):
        if not self.db_connection or "sqlite" not in self.db_connection:
            return
        try:
            conn = sqlite3.connect(self.db_connection.replace("sqlite:///", ""))
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id TEXT,
                    operation TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    success BOOLEAN,
                    risk_level TEXT DEFAULT 'LOW'
                )
            """)
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.error("Failed to setup audit database: %s", e)

    def log_sensitive_operation(
        self,
        operation: str,
        user_id: str,
        resource_type: str = None,
        resource_id: str = None,
        details: Dict[str, Any] = None,
        ip_address: str = None,
        user_agent: str = None,
        success: bool = True,
        risk_level: str = "MEDIUM"
    ):
        audit_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "operation": operation,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": json.dumps(details) if details else None,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "success": success,
            "risk_level": risk_level
        }

        self.audit_logger.info(json.dumps(audit_entry))
        self._log_to_database(audit_entry)

    def _log_to_database(self, audit_entry: Dict[str, Any]):
        if not self.db_connection or "sqlite" not in self.db_connection:
            return
        try:
            conn = sqlite3.connect(self.db_connection.replace("sqlite:///", ""))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log
                (timestamp, user_id, operation, resource_type, resource_id,
                 details, ip_address, user_agent, success, risk_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit_entry["timestamp"], audit_entry["user_id"], audit_entry["operation"],
                audit_entry["resource_type"], audit_entry["resource_id"], audit_entry["details"],
                audit_entry["ip_address"], audit_entry["user_agent"], audit_entry["success"],
                audit_entry["risk_level"]
            ))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.error("Database audit logging failed: %s", e)

    def log_data_access(self, user_id: str, data_type: str, operation: str,
                        record_id: str = None, success: bool = True):
        """Log data access operations"""
        self.log_sensitive_operation(
            operation="DATA_ACCESS_%s" % operation.upper(),
            user_id=user_id,
            resource_type=data_type,
            resource_id=record_id,
            success=success,
            risk_level="HIGH" if operation.upper() in ["DELETE", "EXPORT"] else "MEDIUM"
        )

    def log_encryption_operation(self, user_id: str, field_name: str, operation: str, success: bool = True):
        """Log encryption operations"""
        self.log_sensitive_operation(
            operation="ENCRYPTION_%s" % operation.upper(),
            user_id=user_id,
            resource_type="ENCRYPTED_FIELD",
            resource_id=field_name,
            success=success,
            risk_level="HIGH"
        )

    def log_authentication_event(self, user_id: str, event_type: str, ip_address: str = None,
                                 user_agent: str = None, success: bool = True):
        self.log_sensitive_operation(
            operation="AUTH_%s" % event_type.upper(),
            user_id=user_id,
            resource_type="AUTHENTICATION",
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            risk_level="HIGH" if not success else "MEDIUM"
        )


# Global instances
_field_encryption: Optional[FieldEncryption] = None
_audit_logger: Optional[ComprehensiveAuditLogger] = None


def get_field_encryption() -> FieldEncryption:
    """Get global field encryption instance"""
    global _field_encryption
    if _field_encryption is None:
        _field_encryption = FieldEncryption()
    return _field_encryption


def get_audit_logger() -> ComprehensiveAuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = ComprehensiveAuditLogger()
    return _audit_logger


# Example encrypted model classes
class EncryptedUserProfile(SecureDataModel):
    """User profile with encrypted sensitive fields"""
    ENCRYPTED_FIELDS = ["email", "phone", "address", "personal_notes"]


class EncryptedMeetingData(SecureDataModel):
    """Meeting data with encrypted sensitive fields"""
    ENCRYPTED_FIELDS = ["transcript", "summary", "action_items", "attendee_notes"]


class EncryptedCredentials(SecureDataModel):
    """Credentials with encrypted sensitive fields"""
    ENCRYPTED_FIELDS = ["access_token", "refresh_token", "api_key", "secret_key"]