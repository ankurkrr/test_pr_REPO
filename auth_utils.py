"""
Authentication utilities for the Meeting Intelligence Agent API.
This module provides backward compatibility by re-exporting functions from the consolidated utils.encryption module.
"""

# Re-export all functions from the consolidated encryption module
from .utils.encryption import (
    decrypt_token,
    verify_and_decode_jwt,
    process_token_with_env,
    _get_env,
)

__all__ = [
    "decrypt_token",
    "verify_and_decode_jwt",
    "process_token_with_env",
    "_get_env",
]