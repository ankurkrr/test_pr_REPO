"""
Cryptographic utilities for secure token management
Provides AES-CBC decryption functionality for encrypted tokens
"""

import base64
import os
import logging
from typing import Optional, Dict, Any

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes

logger = logging.getLogger(__name__)

class CryptoUtils:
    """Utility class for cryptographic operations"""

    @staticmethod
    def decrypt_aes_cbc_base64(encrypted_b64: str, key: bytes, iv: bytes) -> str:
        """
        Decrypt AES-CBC encrypted base64 string

        Args:
            encrypted_b64: Base64 encoded encrypted data
            key: AES encryption key (bytes)
            iv: Initialization vector (bytes)

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails or data is invalid
            Exception: For other decryption errors
        """
        try:
            # Decode base64 → raw ciphertext
            ciphertext = base64.b64decode(encrypted_b64)

            # Validate key and IV lengths
            if len(key) not in [16, 24, 32]:  # AES-128, AES-192, AES-256
                raise ValueError(f"Invalid key length: {len(key)}. Must be 16, 24, or 32 bytes")

            if len(iv) != 16:  # AES block size is always 16 bytes
                raise ValueError(f"Invalid IV length: {len(iv)}. Must be 16 bytes")

            # AES-CBC decrypt
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(ciphertext)

            # PKCS7 padding removal
            pad_len = decrypted[-1]

            # Validate padding
            if pad_len < 1 or pad_len > 16:
                raise ValueError("Invalid PKCS7 padding")

            # Check if all padding bytes are the same
            for i in range(pad_len):
                if decrypted[-(i+1)] != pad_len:
                    raise ValueError("Invalid PKCS7 padding structure")

            decrypted = decrypted[:-pad_len]

            return decrypted.decode("utf-8")

        except base64.binascii.Error as e:
            logger.error(f"Base64 decode error: {e}")
            raise ValueError("Invalid base64 encoding") from e
        except UnicodeDecodeError as e:
            logger.error(f"Unicode decode error: {e}")
            raise ValueError("Decrypted data contains invalid UTF-8") from e
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise Exception(f"Token decryption failed: {str(e)}") from e

    @staticmethod
    def get_encryption_key_from_env() -> Optional[bytes]:
        """
        Get encryption key from environment variable

        Returns:
            Encryption key as bytes, or None if not found
        """
        key_str = os.getenv("ENCRYPTION_KEY")
        if not key_str:
            logger.warning("ENCRYPTION_KEY environment variable not found")
            return None

        try:
            # Try to decode as base64 first
            return base64.b64decode(key_str)
        except Exception:
            # If not base64, treat as raw string and encode to bytes
            return key_str.encode('utf-8')

    @staticmethod
    def get_encryption_iv_from_env() -> Optional[bytes]:
        """
        Get encryption IV from environment variable

        Returns:
            Encryption IV as bytes, or None if not found
        """
        iv_str = os.getenv("ENCRYPTION_IV")
        if not iv_str:
            logger.warning("ENCRYPTION_IV environment variable not found")
            return None

        try:
            # Try to decode as base64 first
            return base64.b64decode(iv_str)
        except Exception:
            # If not base64, treat as raw string and encode to bytes
            return iv_str.encode('utf-8')

class TokenDecryptor:
    """Helper class for decrypting auth tokens from workflow data"""

    def __init__(self):
        self.encryption_key = CryptoUtils.get_encryption_key_from_env()
        self.encryption_iv = CryptoUtils.get_encryption_iv_from_env()

        if not self.encryption_key or not self.encryption_iv:
            logger.warning("Encryption key or IV not available. Token decryption will be disabled.")

    def decrypt_auth_tokens(self, workflow_data: list) -> Optional[Dict[str, str]]:
        """
        Extract and decrypt auth tokens from workflow data

        Args:
            workflow_data: List of workflow steps containing tool configurations

        Returns:
            Dictionary with decrypted tokens or None if no tokens found
        """
        if not self.encryption_key or not self.encryption_iv:
            logger.error("Cannot decrypt tokens: encryption key or IV missing")
            return None

        try:
            # Look for Google account integration in workflow data
            for step in workflow_data:
                tools = step.get("tool_to_use", [])

                for tool in tools:
                    if tool.get("integration_type") == "google_calender":  # Note: typo in original
                        fields = tool.get("fields_json", [])

                        # Find access_token and refresh_token
                        access_token_encrypted = None
                        refresh_token_encrypted = None

                        for field in fields:
                            if field.get("field") == "access_token":
                                access_token_encrypted = field.get("value")
                            elif field.get("field") == "refresh_token":
                                refresh_token_encrypted = field.get("value")

                        # Decrypt tokens if found
                        if access_token_encrypted:
                            try:
                                access_token = CryptoUtils.decrypt_aes_cbc_base64(
                                    access_token_encrypted,
                                    self.encryption_key,
                                    self.encryption_iv
                                )

                                refresh_token = None
                                if refresh_token_encrypted:
                                    refresh_token = CryptoUtils.decrypt_aes_cbc_base64(
                                        refresh_token_encrypted,
                                        self.encryption_key,
                                        self.encryption_iv
                                    )

                                logger.info("Successfully decrypted Google auth tokens")
                                return {
                                    "access_token": access_token,
                                    "refresh_token": refresh_token
                                }

                            except Exception as e:
                                logger.error(f"Failed to decrypt auth tokens: {e}")
                                return None

            logger.debug("No Google auth tokens found in workflow data")
            return None

        except Exception as e:
            logger.error(f"Error extracting auth tokens: {e}")
            return None

    def is_decryption_available(self) -> bool:
        """Check if token decryption is available"""
        return bool(self.encryption_key and self.encryption_iv)

# Convenience functions for backward compatibility
def decrypt_aes_cbc_base64(encrypted_b64: str, key: bytes, iv: bytes) -> str:
    """Convenience function for AES-CBC decryption"""
    return CryptoUtils.decrypt_aes_cbc_base64(encrypted_b64, key, iv)

# Global decryptor instance
_token_decryptor: Optional[TokenDecryptor] = None

def get_token_decryptor() -> TokenDecryptor:
    """Get singleton token decryptor instance"""
    global _token_decryptor
    if _token_decryptor is None:
        _token_decryptor = TokenDecryptor()
    return _token_decryptor