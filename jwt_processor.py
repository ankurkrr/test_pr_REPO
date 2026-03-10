"""
jwt_processor.py
Single file that:
1. Cleans tokens by removing whitespace/gaps
2. Decrypts AES-encrypted token using secret_hex + iv_hex (Hexadecimal encoding with Base64 fallback)
3. Verifies JWT signature with jwt_secret
4. Extracts user_id, org_id, and email if present
"""

import base64
import re
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import jwt
from jwt import InvalidTokenError


def clean_token(token_with_gaps: str) -> str:
    """
    Remove all whitespace from a token string to handle gaps/line breaks.
    """
    return re.sub(r"\s+", "", token_with_gaps or "")


def decrypt_token(encrypted_token: str, secret_hex: str, iv_hex: str) -> str:
    """
    Decrypt an AES-CBC encrypted token.
    ASSUMING THE INPUT IS NOW HEXADECIMAL ENCODED, NOT BASE64.
    :param encrypted_token: Hexadecimal encoded encrypted token string
    :param secret_hex: Hex string of secret key
    :param iv_hex: Hex string of IV
    :return: Decrypted JWT string
    """

    try:
        secret_key = bytes.fromhex(secret_hex)
        iv = bytes.fromhex(iv_hex)
        # Clean token first to handle whitespace/gaps
        encrypted_token = clean_token(encrypted_token)
        # Attempt hexadecimal decoding, fallback to Base64 for legacy inputs
        try:
            encrypted_bytes = bytes.fromhex(encrypted_token)
        except ValueError:
            # Fallback to Base64 in case an old token is passed (good practice)
            encrypted_bytes = base64.b64decode(encrypted_token)
        # ---------------------------------------------
        # Security check: Ensure the length is a multiple of the block size (16 bytes)
        # This will catch the error you saw previously if the wrong encoding was used.
        if len(encrypted_bytes) % AES.block_size != 0:
            raise ValueError(
                "Decoded data length is not a multiple of 16 bytes. Cannot decrypt."
            )
        cipher = AES.new(secret_key, AES.MODE_CBC, iv)
        decrypted_bytes = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        # Catch AES-specific errors (like key size) and decoding errors (like Invalid padding)
        raise ValueError(f"Token decryption failed: {str(e)}")


def verify_and_decode_jwt(
    jwt_token: str, jwt_secret: str, algorithm: str = "HS256"
) -> dict:
    """
    Verify JWT signature and decode payload.
    :param jwt_token: The decrypted JWT string
    :param jwt_secret: Secret key used to sign the JWT
    :param algorithm: JWT algorithm (default: HS256)
    :return: Decoded payload as dict with user_id and org_id
    """
    try:
        # jwt.decode will automatically check expiry and signature
        payload = jwt.decode(jwt_token, jwt_secret, algorithms=[algorithm])
        # Accept common alternative claim names
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
        found_user_id = None
        for key in user_claim_candidates:
            if key in payload:
                found_user_id = payload[key]
                break
        found_org_id = None
        for key in org_claim_candidates:
            if key in payload:
                found_org_id = payload[key]
                break
        found_email = None
        for key in email_claim_candidates:
            if key in payload:
                found_email = payload[key]
                break

        if found_user_id is None or found_org_id is None:
            available_keys = ", ".join(sorted(payload.keys()))
            raise ValueError(
                "Missing required claims. Looked for user: "
                + "/".join(user_claim_candidates)
                + ", org: "
                + "/".join(org_claim_candidates)
                + f". Available keys: {available_keys}"
            )
        return {
            "user_id": found_user_id,
            "org_id": found_org_id,
            "email": found_email,
            "exp": payload.get("exp"),
        }
    except InvalidTokenError as e:
        raise ValueError(f"JWT verification failed: {str(e)}")


def process_token(
    encrypted_token: str, secret_hex: str, iv_hex: str, jwt_secret: str
) -> dict:
    """
    High-level function that:
    1. Cleans token (removes whitespace/gaps)
    2. Decrypts token
    3. Verifies JWT signature
    4. Returns user_id, org_id, email (if present)
    """
    cleaned = clean_token(encrypted_token)
    decrypted_jwt = decrypt_token(cleaned, secret_hex, iv_hex)
    result = verify_and_decode_jwt(decrypted_jwt, jwt_secret)
    return result


if __name__ == "__main__":
    # Example Usage
    encrypted_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IkFTREtiTzZ3YXYiLCJsb2dpbkxvZ0lkIjoiWHBUS0dhOUVQSiIsImlhdCI6MTc2MDA2NTYxNiwiZXhwIjoxNzYyNjU3NjE2fQ.kLlzmK1viJuarmOWk2wBSr5e8NX50zOp78ldnGDcS6w"
    # encrypted_token = ""
    # NOTE: The keys are not 16 bytes (32 hex chars) long, which may cause AES to fail or misbehave.
    # I am keeping them as provided to maintain your test environment, but they are highly non-standard.
    secret_hex = "9369aef3c449205fe2b8802844b997d0"
    iv_hex = "9b6a2074e6253017801e23d8f9f4a475"
    jwt_secret = "jwt_l7fnbhaBN4_elevationBasecloud_Pl1G4zoMUs"

    if not encrypted_token or not secret_hex or not iv_hex:
        print(
            "No test data provided. Please set encrypted_token, secret_hex, and iv_hex to test the functionality."
        )
        print("Example usage:")
        print(
            "  result = process_token(your_encrypted_token, your_secret_hex, your_iv_hex, jwt_secret)"
        )
    else:
        try:
            result = process_token(encrypted_token, secret_hex, iv_hex, jwt_secret)
            print(f"Token valid.")
            print(f"   user_id: {result['user_id']}")
            print(f"   org_id: {result['org_id']}")
            if result.get("exp"):
                print(f"   expires at: {datetime.utcfromtimestamp(result['exp'])}")
        except ValueError as e:
            print(f"Token processing failed: {e}")
