"""
Secure Token Manager with AES-GCM Encryption
Handles secure token storage, encryption/decryption, validation, and automatic refresh
"""

import os
import json
import base64
import logging
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend


logger = logging.getLogger(__name__)


class TokenSecurityError(Exception):
    """Custom exception for token security operations"""


class SecureTokenManager:
    """
    Production-grade token manager with AES-GCM encryption and comprehensive security features
    """

    def __init__(
        self,
        master_key: Optional[str] = None,
        storage_path: str = "keys/secure_tokens",
        key_rotation_days: int = 30,
    ):
        """
        Initialize secure token manager

        Args:
            master_key: Master encryption key (from environment or secure storage)
            storage_path: Path for encrypted token storage
            key_rotation_days: Days before key rotation is required
        """
        self.storage_path = storage_path
        self.key_rotation_days = key_rotation_days
        self._master_key = master_key or self._get_master_key()
        self._encryption_key = self._derive_encryption_key()
        self._aesgcm = AESGCM(self._encryption_key)

        # Ensure storage directory exists
        os.makedirs(self.storage_path, exist_ok=True)

        # Initialize key rotation tracking
        self._check_key_rotation()

        logger.info("SecureTokenManager initialized with AES-GCM encryption")

    def _get_master_key(self) -> str:
        """Get or generate master encryption key"""
        try:
            master_key = os.getenv("TOKEN_MASTER_KEY")
            if master_key:
                return master_key

            key_file = os.path.join(self.storage_path, "master.key")
            if os.path.exists(key_file):
                with open(key_file, "r") as f:
                    return f.read().strip()

            # Generate new master key
            master_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            with open(key_file, "w") as f:
                f.write(master_key)

            logger.warning(
                "Generated new master key - ensure it's stored securely in production"
            )
            return master_key

        except (OSError, IOError) as e:
            logger.error("Failed to get master key: %s", e, exc_info=True)
            raise TokenSecurityError("Master key initialization failed: %s" % e)

    def _derive_encryption_key(self) -> bytes:
        """Derive encryption key from master key using PBKDF2"""
        try:
            salt = b"secure_token_manager_salt_v1"
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend(),
            )
            return kdf.derive(self._master_key.encode())

        except Exception as e:
            logger.error("Key derivation failed: %s", e, exc_info=True)
            raise TokenSecurityError("Encryption key derivation failed: %s" % e)

    def _check_key_rotation(self):
        """Check if key rotation is needed"""
        rotation_file = os.path.join(self.storage_path, "key_rotation.json")
        try:
            if os.path.exists(rotation_file):
                with open(rotation_file, "r") as f:
                    rotation_data = json.load(f)

                last_rotation = datetime.fromisoformat(
                    rotation_data.get("last_rotation")
                )
                if datetime.now() - last_rotation > timedelta(
                    days=self.key_rotation_days
                ):
                    logger.warning(
                        "Key rotation required - keys are older than rotation period"
                    )
            else:
                rotation_data = {
                    "last_rotation": datetime.now().isoformat(),
                    "rotation_count": 0,
                }
                with open(rotation_file, "w") as f:
                    json.dump(rotation_data, f, indent=2)
        except (OSError, IOError, json.JSONDecodeError, KeyError) as e:
            logger.error("Key rotation check failed: %s", e, exc_info=True)

    def encrypt_token(
        self, token_data: Dict[str, Any], token_id: str, expiry_hours: int = 24
    ) -> str:
        """Encrypt token data with AES-GCM"""
        try:
            token_payload = {
                "data": token_data,
                "token_id": token_id,
                "created_at": datetime.now().isoformat(),
                "expires_at": (
                    datetime.now() + timedelta(hours=expiry_hours)
                ).isoformat(),
                "version": "1.0",
            }

            json_data = json.dumps(token_payload, separators=(",", ":")).encode()
            nonce = secrets.token_bytes(12)
            ciphertext = self._aesgcm.encrypt(nonce, json_data, None)
            encrypted_token = base64.urlsafe_b64encode(nonce + ciphertext).decode()

            logger.info("Token encrypted successfully: %s", token_id)
            return encrypted_token

        except Exception as e:
            logger.error("Token encryption failed: %s", e, exc_info=True)
            raise TokenSecurityError("Failed to encrypt token: %s" % e)

    def decrypt_token(self, encrypted_token: str) -> Tuple[Dict[str, Any], bool]:
        """Decrypt and validate token"""
        try:
            encrypted_data = base64.urlsafe_b64decode(encrypted_token.encode())
            nonce = encrypted_data[:12]
            ciphertext = encrypted_data[12:]
            decrypted_data = self._aesgcm.decrypt(nonce, ciphertext, None)
            token_payload = json.loads(decrypted_data.decode())
            is_valid = self._validate_token(token_payload)

            if is_valid:
                logger.debug(
                    "Token decrypted successfully: %s", token_payload.get("token_id")
                )
            else:
                logger.warning(
                    "Token validation failed: %s", token_payload.get("token_id")
                )

            return token_payload, is_valid

        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Token decryption failed: %s", e, exc_info=True)
            return {}, False

    def _validate_token(self, token_payload: Dict[str, Any]) -> bool:
        """Validate token payload"""
        try:
            required_fields = [
                "data",
                "token_id",
                "created_at",
                "expires_at",
                "version",
            ]
            for field in required_fields:
                if field not in token_payload:
                    logger.warning("Missing required field: %s", field)
                    return False

            expires_at = datetime.fromisoformat(token_payload["expires_at"])
            if datetime.now() > expires_at:
                logger.warning("Token has expired")
                return False

            if token_payload["version"] != "1.0":
                logger.warning(
                    "Unsupported token version: %s", token_payload["version"]
                )
                return False

            return True

        except (KeyError, ValueError) as e:
            logger.error("Token validation error: %s", e, exc_info=True)
            return False

    def store_token(
        self, token_id: str, encrypted_token: str, metadata: Optional[Dict] = None
    ):
        """Store encrypted token securely"""
        token_file = os.path.join(self.storage_path, "%s.token" % token_id)
        try:
            storage_data = {
                "encrypted_token": encrypted_token,
                "stored_at": datetime.now().isoformat(),
                "metadata": metadata or {},
            }

            with open(token_file, "w") as f:
                json.dump(storage_data, f, indent=2)
            os.chmod(token_file, 0o600)
            logger.info("Token stored securely: %s", token_id)

        except (OSError, IOError) as e:
            logger.error("Token storage failed: %s", e, exc_info=True)
            raise TokenSecurityError("Failed to store token: %s" % e)

    def retrieve_token(self, token_id: str) -> Optional[str]:
        """Retrieve encrypted token from storage"""
        token_file = os.path.join(self.storage_path, "%s.token" % token_id)
        try:
            if not os.path.exists(token_file):
                return None
            with open(token_file, "r") as f:
                storage_data = json.load(f)
            return storage_data.get("encrypted_token")
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.error("Token retrieval failed: %s", e, exc_info=True)
            return None

    def delete_token(self, token_id: str) -> bool:
        """Securely delete token"""
        token_file = os.path.join(self.storage_path, "%s.token" % token_id)
        try:
            if os.path.exists(token_file):
                self._secure_delete_file(token_file)
                logger.info("Token securely deleted: %s", token_id)
                return True
            return False
        except (OSError, IOError) as e:
            logger.error("Token deletion failed: %s", e, exc_info=True)
            return False

    def _secure_delete_file(self, file_path: str):
        """Securely delete file with multiple overwrites"""
        try:
            file_size = os.path.getsize(file_path)
            for _ in range(3):
                with open(file_path, "wb") as f:
                    f.write(secrets.token_bytes(file_size))
                    f.flush()
                    os.fsync(f.fileno())
            os.remove(file_path)
        except (OSError, IOError) as e:
            logger.error("Secure file deletion failed: %s", e, exc_info=True)
            raise

    def list_tokens(self) -> List[Dict[str, Any]]:
        """List all stored tokens with metadata"""
        tokens = []
        try:
            for filename in os.listdir(self.storage_path):
                if filename.endswith(".token"):
                    token_id = filename[:-6]
                    try:
                        with open(os.path.join(self.storage_path, filename), "r") as f:
                            storage_data = json.load(f)
                        tokens.append(
                            {
                                "token_id": token_id,
                                "stored_at": storage_data.get("stored_at"),
                                "metadata": storage_data.get("metadata", {}),
                            }
                        )
                    except (OSError, IOError, json.JSONDecodeError) as e:
                        logger.warning("Failed to read token file %s: %s", filename, e)
            return tokens
        except (OSError, IOError) as e:
            logger.error("Token listing failed: %s", e, exc_info=True)
            return []

    def rotate_encryption_key(self) -> bool:
        """Rotate encryption keys (re-encrypt all tokens with new key)"""
        try:
            logger.info("Starting key rotation process")
            tokens = self.list_tokens()
            decrypted_tokens = []

            for token_info in tokens:
                encrypted_token = self.retrieve_token(token_info["token_id"])
                if encrypted_token:
                    token_payload, is_valid = self.decrypt_token(encrypted_token)
                    if is_valid:
                        decrypted_tokens.append((token_info["token_id"], token_payload))

            old_master_key = self._master_key
            self._master_key = base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).decode()
            self._encryption_key = self._derive_encryption_key()
            self._aesgcm = AESGCM(self._encryption_key)

            for token_id, token_payload in decrypted_tokens:
                new_encrypted_token = self.encrypt_token(
                    token_payload["data"], token_id, 24
                )
                self.store_token(token_id, new_encrypted_token)

            rotation_file = os.path.join(self.storage_path, "key_rotation.json")
            rotation_data = {
                "last_rotation": datetime.now().isoformat(),
                "rotation_count": 1,
                "previous_key_hash": hashlib.sha256(
                    old_master_key.encode()
                ).hexdigest()[:16],
            }
            with open(rotation_file, "w") as f:
                json.dump(rotation_data, f, indent=2)

            logger.info(
                "Key rotation completed successfully - %d tokens re-encrypted",
                len(decrypted_tokens),
            )
            return True
        except Exception as e:
            logger.error("Key rotation failed: %s", e, exc_info=True)
            return False


# Global instance
_token_manager: Optional[SecureTokenManager] = None


def get_token_manager() -> SecureTokenManager:
    """Get global token manager instance"""
    global _token_manager
    if _token_manager is None:
        _token_manager = SecureTokenManager()
    return _token_manager