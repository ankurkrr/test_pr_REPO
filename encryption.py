"""
Encryption utilities for the Meeting Intelligence Agent API.
Contains AES encryption/decryption functions with JWT support.
"""

import os
import base64
import re
from datetime import datetime
from typing import Dict, Optional

import jwt
from jwt import InvalidTokenError
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _try_decode_key_or_iv(value: str) -> bytes:
    """
    Try to decode a key/iv in base64 first, then hex. Raises ValueError if neither works.
    """
    if value is None:
        raise ValueError("Key/IV value is None")

    # Try base64
    try:
        return base64.b64decode(value)
    except (base64.binascii.Error, ValueError):
        pass

    # Try hex
    try:
        return bytes.fromhex(value)
    except ValueError:
        pass

    raise ValueError("Key/IV must be base64 or hex-encoded bytes")


def decrypt_aes_cbc_base64(
    ciphertext_b64: str, key_bytes: bytes, iv_bytes: bytes
) -> str:
    """
    Decrypts base64 encoded AES-CBC (PKCS7) ciphertext and returns utf-8 string.
    """
    if ciphertext_b64 is None:
        return None

    try:
        ct = base64.b64decode(ciphertext_b64)
    except Exception as e:
        raise ValueError("ciphertext is not valid base64") from e

    if len(iv_bytes) not in (16,):
        raise ValueError("IV must be 16 bytes for AES-CBC")

    if len(key_bytes) not in (16, 24, 32):
        raise ValueError("Key must be 16, 24, or 32 bytes (AES-128/192/256)")

    backend = default_backend()
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes), backend=backend)
    decryptor = cipher.decryptor()
    padded_plain = decryptor.update(ct) + decryptor.finalize()

    # Unpad PKCS7
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded_plain) + unpadder.finalize()

    return plain.decode("utf-8")


def _get_env(name: str, default: Optional[str] = None) -> str:
    """Get environment variable with smart fallbacks for legacy names.

    Fallback mapping ensures compatibility with existing .env files:
      - PLATFORM_AES_SECRET_HEX -> ENCRYPTION_KEY
      - PLATFORM_AES_IV_HEX     -> ENCRYPTION_IV, ENCRYPT_IV
      - PLATFORM_JWT_SECRET     -> JWT_SECRET_KEY
    """
    value = os.getenv(name, default)
    if value is not None:
        return value

    # Provide compatibility fallbacks for common legacy env var names
    fallback_map = {
        "PLATFORM_AES_SECRET_HEX": ["ENCRYPTION_KEY"],
        "PLATFORM_AES_IV_HEX": ["ENCRYPTION_IV", "ENCRYPT_IV"],
        "PLATFORM_JWT_SECRET": ["JWT_SECRET_KEY"],
    }

    for fallback_name in fallback_map.get(name, []):
        value = os.getenv(fallback_name)
        if value:
            return value

    raise ValueError(f"Missing required environment variable: {name}")


def decrypt_token(encrypted_token: str, secret_hex: str, iv_hex: str) -> str:
    """
    Decrypt an AES-CBC encrypted token using cryptography library.
    Input priority: expects hexadecimal-encoded token; falls back to base64 for legacy inputs.

    Args:
        encrypted_token: Hex or Base64 encoded encrypted token
        secret_hex: Hex string of secret key
        iv_hex: Hex string of IV

    Returns:
        Decrypted JWT string
    """
    try:
        # Clean potential whitespace/gaps from token input
        cleaned_token = re.sub(r"\s+", "", encrypted_token or "")
        secret_key = bytes.fromhex(secret_hex)
        iv = bytes.fromhex(iv_hex)

        try:
            encrypted_bytes = bytes.fromhex(cleaned_token)
        except ValueError:
            encrypted_bytes = base64.b64decode(cleaned_token)

        if len(encrypted_bytes) % 16 != 0:  # AES block size
            raise ValueError(
                "Decoded data length is not a multiple of 16 bytes. Cannot decrypt."
            )

        # Use cryptography library for consistency
        backend = default_backend()
        cipher = Cipher(algorithms.AES(secret_key), modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()
        padded_plain = decryptor.update(encrypted_bytes) + decryptor.finalize()

        # Unpad PKCS7
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded_plain) + unpadder.finalize()

        return plain.decode("utf-8")
    except Exception as e:
        raise ValueError(f"Token decryption failed: {str(e)}")


def verify_and_decode_jwt(jwt_token: str, jwt_secret: str, algorithm: str = "HS256") -> Dict[str, Optional[str]]:
    """
    Verify JWT signature and decode payload. Returns user_id and org_id.
    Accepts common claim aliases for portability across platforms.

    Args:
        jwt_token: JWT token string
        jwt_secret: Secret key for verification
        algorithm: JWT algorithm (default: HS256)

    Returns:
        Dict containing user_id, org_id, and exp
    """
    try:
        payload = jwt.decode(jwt_token, jwt_secret, algorithms=[algorithm])

        user_claim_candidates = ["user_id", "userId", "uid", "id", "sub"]
        org_claim_candidates = [
            "org_id",
            "orgId",
            "organization_id",
            "rg_id",
            "rgId",
            "rg",
            "rgid",
        ]
        email_claim_candidates = [
            "email",
            "user_email",
            "emailAddress",
            "mail",
            "email_id",
            "userEmail",
        ]

        found_user_id = next((payload[k] for k in user_claim_candidates if k in payload), None)
        found_org_id = next((payload[k] for k in org_claim_candidates if k in payload), None)

        found_email = next((payload[k] for k in email_claim_candidates if k in payload), None)

        if found_user_id is None or found_org_id is None:
            available_keys = ", ".join(sorted(payload.keys()))
            raise ValueError(
                "Missing required claims. Looked for user: "
                + "/".join(user_claim_candidates)
                + ", org: "
                + "/".join(org_claim_candidates)
                + f". Available keys: {available_keys}"
            )

        return {"user_id": found_user_id, "org_id": found_org_id, "email": found_email, "exp": payload.get("exp")}
    except InvalidTokenError as e:
        raise ValueError(f"JWT verification failed: {str(e)}")


def process_token_with_env(encrypted_token: str) -> Dict[str, Optional[str]]:
    """
    High-level convenience that pulls keys from environment variables and returns user/org ids.

    Env vars used:
    - PLATFORM_AES_SECRET_HEX: hex key for AES-CBC
    - PLATFORM_AES_IV_HEX: hex IV for AES-CBC
    - PLATFORM_JWT_SECRET: secret to verify JWT (HS256 by default)
    - PLATFORM_JWT_ALG (optional): algorithm, default HS256

    Args:
        encrypted_token: Encrypted token to decrypt and verify

    Returns:
        Dict containing user_id, org_id, and exp
    """
    secret_hex = _get_env("PLATFORM_AES_SECRET_HEX")
    iv_hex = _get_env("PLATFORM_AES_IV_HEX")
    jwt_secret = _get_env("PLATFORM_JWT_SECRET")
    jwt_alg = os.getenv("PLATFORM_JWT_ALG", "HS256")

    # Clean token first to handle whitespace/gaps
    cleaned_token = re.sub(r"\s+", "", encrypted_token or "")
    decrypted = decrypt_token(cleaned_token, secret_hex, iv_hex)
    return verify_and_decode_jwt(decrypted, jwt_secret, jwt_alg)


__all__ = [
    "_try_decode_key_or_iv",
    "decrypt_aes_cbc_base64",
    "decrypt_token",
    "verify_and_decode_jwt",
    "process_token_with_env",
    "_get_env",
]