"""
Advanced Input Validation and Sanitization
Implements comprehensive validation with regex patterns, sanitization, and security checks
"""

import re
import os
import logging
import mimetypes
from typing import Any, Dict, List, Optional, Union, Callable
from pathlib import Path
import bleach
from pydantic import BaseModel, validator, Field
from fastapi import HTTPException, UploadFile
import html

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom validation error"""
    pass

class SecurityPatterns:
    """Comprehensive security-focused regex patterns for validation"""

    # Basic patterns
    EMAIL = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    ALPHANUMERIC = re.compile(r'^[a-zA-Z0-9]+$')
    SAFE_STRING = re.compile(r'^[a-zA-Z0-9\s\-_.]+$')
    NUMERIC = re.compile(r'^[0-9]+$')
    DECIMAL = re.compile(r'^[0-9]+(\.[0-9]+)?$')

    # Enhanced security patterns - comprehensive attack detection
    SQL_INJECTION = re.compile(r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|SCRIPT|TRUNCATE|GRANT|REVOKE)\b|--|\/\*|\*\/|;|\'|"|\bOR\b|\bAND\b)', re.IGNORECASE)
    XSS_PATTERNS = re.compile(r'(<script|</script|javascript:|vbscript:|onload=|onerror=|onclick=|onmouseover=|onfocus=|onblur=|onchange=|onsubmit=|<iframe|<object|<embed|<link|<meta|<style|expression\(|url\(|@import)', re.IGNORECASE)
    PATH_TRAVERSAL = re.compile(r'(\.\./|\.\.\\|%2e%2e%2f|%2e%2e\\|%2e%2e%5c|\.\.%2f|\.\.%5c|%252e%252e%252f)')
    COMMAND_INJECTION = re.compile(r'(;|\||&|`|\$\(|\${|>|<|\||\n|\r|%0a|%0d|%3b|%7c|%26)', re.IGNORECASE)
    LDAP_INJECTION = re.compile(r'(\*|\(|\)|\\|\/|\+|=|<|>|;|,|"|\||&)', re.IGNORECASE)
    XML_INJECTION = re.compile(r'(<\?xml|<!DOCTYPE|<!ENTITY|<!\[CDATA\[)', re.IGNORECASE)

    # Advanced XSS patterns
    XSS_ADVANCED = re.compile(r'(data:text\/html|data:text\/javascript|data:application\/javascript|&#x|&#\d+|%3c|%3e|%22|%27|%3d)', re.IGNORECASE)

    # File patterns - enhanced
    SAFE_FILENAME = re.compile(r'^[a-zA-Z0-9\-_.]+$')
    IMAGE_EXTENSION = re.compile(r'\.(jpg|jpeg|png|gif|bmp|webp|svg)$', re.IGNORECASE)
    DOCUMENT_EXTENSION = re.compile(r'\.(pdf|doc|docx|txt|rtf|odt|ods|odp)$', re.IGNORECASE)
    EXECUTABLE_EXTENSION = re.compile(r'\.(exe|bat|cmd|com|pif|scr|vbs|js|jar|app|deb|rpm|dmg|pkg)$', re.IGNORECASE)
    ARCHIVE_EXTENSION = re.compile(r'\.(zip|rar|7z|tar|gz|bz2)$', re.IGNORECASE)

    # API patterns - enhanced
    API_KEY = re.compile(r'^[a-zA-Z0-9]{32,128}$')
    JWT_TOKEN = re.compile(r'^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$')
    BEARER_TOKEN = re.compile(r'^Bearer\s+[A-Za-z0-9\-._~+/]+=*$')

    # User input patterns - enhanced
    USERNAME = re.compile(r'^[a-zA-Z0-9_]{3,30}$')
    PASSWORD_STRONG = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')
    PHONE_NUMBER = re.compile(r'^\+?[1-9]\d{1,14}$')
    URL = re.compile(r'^https?:\/\/[a-zA-Z0-9\-._~:/?#[\]@!$&\'()*+,;=%]+$')

    # Content validation patterns
    HTML_TAGS = re.compile(r'<[^>]+>')
    BASE64 = re.compile(r'^[A-Za-z0-9+/]*={0,2}$')
    JSON_STRUCTURE = re.compile(r'^[\[\{].*[\]\}]$', re.DOTALL)

    # Network and system patterns
    IP_ADDRESS = re.compile(r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
    DOMAIN_NAME = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')

    # Dangerous content patterns
    SCRIPT_TAGS = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
    STYLE_TAGS = re.compile(r'<style[^>]*>.*?</style>', re.IGNORECASE | re.DOTALL)
    LINK_TAGS = re.compile(r'<link[^>]*>', re.IGNORECASE)
    META_TAGS = re.compile(r'<meta[^>]*>', re.IGNORECASE)

class InputSanitizer:
    """Input sanitization utilities"""

    @staticmethod
    def sanitize_html(input_text: str, allowed_tags: List[str] = None) -> str:
        """Sanitize HTML input to prevent XSS"""
        try:
            if not input_text:
                return ""

            # Default allowed tags (very restrictive)
            if allowed_tags is None:
                allowed_tags = ['b', 'i', 'em', 'strong', 'p', 'br']

            # Sanitize with bleach
            sanitized = bleach.clean(
                input_text,
                tags=allowed_tags,
                attributes={},
                strip=True
            )

            return sanitized

        except Exception as e:
            logger.error(f"HTML sanitization failed: {e}")
            # Return escaped version as fallback
            return html.escape(input_text)

    @staticmethod
    def sanitize_sql_input(input_text: str) -> str:
        """Sanitize input to prevent SQL injection"""
        try:
            if not input_text:
                return ""

            # Remove potential SQL injection patterns
            sanitized = re.sub(SecurityPatterns.SQL_INJECTION, '', input_text)

            # Escape single quotes
            sanitized = sanitized.replace("'", "''")

            return sanitized

        except Exception as e:
            logger.error(f"SQL sanitization failed: {e}")
            return ""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename to prevent path traversal"""
        try:
            if not filename:
                return ""

            # Remove path traversal patterns
            sanitized = re.sub(SecurityPatterns.PATH_TRAVERSAL, '', filename)

            # Keep only safe characters
            sanitized = re.sub(r'[^a-zA-Z0-9\-_.]', '_', sanitized)

            # Limit length
            sanitized = sanitized[:255]

            # Ensure it doesn't start with dot
            if sanitized.startswith('.'):
                sanitized = 'file_' + sanitized

            return sanitized

        except Exception as e:
            logger.error(f"Filename sanitization failed: {e}")
            return "sanitized_file"

    @staticmethod
    def sanitize_user_input(input_text: str, max_length: int = 1000, strict: bool = False) -> str:
        """Comprehensive user input sanitization with multiple security layers"""
        try:
            if not input_text:
                return ""

            # Limit length first
            sanitized = input_text[:max_length]

            # Remove control characters (except allowed whitespace)
            sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\n\r\t')

            # Remove potential XSS patterns (basic and advanced)
            sanitized = re.sub(SecurityPatterns.XSS_PATTERNS, '', sanitized)
            sanitized = re.sub(SecurityPatterns.XSS_ADVANCED, '', sanitized)

            # Remove HTML tags if strict mode
            if strict:
                sanitized = re.sub(SecurityPatterns.HTML_TAGS, '', sanitized)
                sanitized = re.sub(SecurityPatterns.SCRIPT_TAGS, '', sanitized)
                sanitized = re.sub(SecurityPatterns.STYLE_TAGS, '', sanitized)

            # Remove potential SQL injection patterns
            sanitized = re.sub(SecurityPatterns.SQL_INJECTION, '', sanitized)

            # Remove potential command injection patterns
            sanitized = re.sub(SecurityPatterns.COMMAND_INJECTION, '', sanitized)

            # Remove LDAP injection patterns
            sanitized = re.sub(SecurityPatterns.LDAP_INJECTION, '', sanitized)

            # Remove XML injection patterns
            sanitized = re.sub(SecurityPatterns.XML_INJECTION, '', sanitized)

            # Normalize whitespace
            sanitized = ' '.join(sanitized.split())

            return sanitized.strip()

        except Exception as e:
            logger.error(f"User input sanitization failed: {e}")
            return ""

    @staticmethod
    def sanitize_sql_input(input_text: str) -> str:
        """Specialized SQL injection prevention sanitization"""
        try:
            if not input_text:
                return ""

            # Remove SQL keywords and dangerous characters
            sanitized = re.sub(SecurityPatterns.SQL_INJECTION, '', input_text)

            # Escape single quotes
            sanitized = sanitized.replace("'", "''")

            # Remove double quotes
            sanitized = sanitized.replace('"', '')

            # Remove semicolons
            sanitized = sanitized.replace(';', '')

            # Remove comments
            sanitized = re.sub(r'--.*$', '', sanitized, flags=re.MULTILINE)
            sanitized = re.sub(r'/\*.*?\*/', '', sanitized, flags=re.DOTALL)

            return sanitized.strip()

        except Exception as e:
            logger.error(f"SQL input sanitization failed: {e}")
            return ""

    @staticmethod
    def sanitize_html_content(html_content: str, allowed_tags: List[str] = None) -> str:
        """Sanitize HTML content with allowlist approach"""
        try:
            if not html_content:
                return ""

            # Default allowed tags (very restrictive)
            if allowed_tags is None:
                allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li']

            # Remove all script and style tags
            sanitized = re.sub(SecurityPatterns.SCRIPT_TAGS, '', html_content)
            sanitized = re.sub(SecurityPatterns.STYLE_TAGS, '', sanitized)
            sanitized = re.sub(SecurityPatterns.LINK_TAGS, '', sanitized)
            sanitized = re.sub(SecurityPatterns.META_TAGS, '', sanitized)

            # Remove dangerous attributes
            dangerous_attrs = ['onclick', 'onload', 'onerror', 'onmouseover', 'onfocus', 'onblur', 'onchange', 'onsubmit']
            for attr in dangerous_attrs:
                sanitized = re.sub(f'{attr}=["\'][^"\']*["\']', '', sanitized, flags=re.IGNORECASE)

            # Remove javascript: and vbscript: URLs
            sanitized = re.sub(r'javascript:[^"\']*', '', sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(r'vbscript:[^"\']*', '', sanitized, flags=re.IGNORECASE)

            return sanitized

        except Exception as e:
            logger.error(f"HTML content sanitization failed: {e}")
            return ""

    @staticmethod
    def sanitize_json_input(json_str: str, max_depth: int = 10) -> str:
        """Sanitize JSON input with depth and content validation"""
        try:
            if not json_str:
                return ""

            # Basic JSON structure validation
            if not SecurityPatterns.JSON_STRUCTURE.match(json_str.strip()):
                logger.warning("Invalid JSON structure detected")
                return ""

            # Parse and validate JSON
            try:
                import json
                parsed = json.loads(json_str)

                # Check depth
                def check_depth(obj, current_depth=0):
                    if current_depth > max_depth:
                        raise ValueError("JSON depth exceeds maximum allowed")

                    if isinstance(obj, dict):
                        for value in obj.values():
                            check_depth(value, current_depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            check_depth(item, current_depth + 1)

                check_depth(parsed)

                # Sanitize string values recursively
                def sanitize_json_values(obj):
                    if isinstance(obj, dict):
                        return {k: sanitize_json_values(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [sanitize_json_values(item) for item in obj]
                    elif isinstance(obj, str):
                        return InputSanitizer.sanitize_user_input(obj, strict=True)
                    else:
                        return obj

                sanitized_obj = sanitize_json_values(parsed)
                return json.dumps(sanitized_obj)

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON format: {e}")
                return ""

        except Exception as e:
            logger.error(f"JSON input sanitization failed: {e}")
            return ""

class FileValidator:
    """Comprehensive file upload validation and security checks"""

    ALLOWED_MIME_TYPES = {
        'image': ['image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp'],
        'document': ['application/pdf', 'text/plain', 'application/msword',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.oasis.opendocument.text', 'application/rtf'],
        'text': ['text/plain', 'text/csv', 'application/json', 'text/markdown'],
        'archive': ['application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed']
    }

    MAX_FILE_SIZES = {
        'image': 10 * 1024 * 1024,      # 10MB
        'document': 50 * 1024 * 1024,   # 50MB
        'text': 1 * 1024 * 1024,        # 1MB
        'archive': 100 * 1024 * 1024    # 100MB
    }

    # Dangerous file signatures (magic bytes)
    DANGEROUS_SIGNATURES = {
        b'\x4D\x5A': 'PE executable',
        b'\x7F\x45\x4C\x46': 'ELF executable',
        b'\xCA\xFE\xBA\xBE': 'Java class file',
        b'\xFE\xED\xFA\xCE': 'Mach-O executable',
        b'\xCE\xFA\xED\xFE': 'Mach-O executable',
        b'\x50\x4B\x03\x04': 'ZIP archive (potential)',
        b'\x52\x61\x72\x21': 'RAR archive'
    }

    # File content validation patterns
    SCRIPT_PATTERNS = [
        b'<script',
        b'javascript:',
        b'vbscript:',
        b'<?php',
        b'<%',
        b'#!/bin/',
        b'#!/usr/bin/',
        b'powershell',
        b'cmd.exe'
    ]

    @classmethod
    def validate_file(cls, file: UploadFile, file_type: str = 'document', strict_mode: bool = True) -> Dict[str, Any]:
        """
        Comprehensive file validation with multiple security layers

        Args:
            file: Uploaded file
            file_type: Type of file (image, document, text, archive)
            strict_mode: Enable strict security validation

        Returns:
            Validation result dictionary
        """
        try:
            result = {
                'valid': False,
                'errors': [],
                'warnings': [],
                'file_info': {},
                'security_score': 0
            }

            # Check file exists
            if not file or not file.filename:
                result['errors'].append("No file provided")
                return result

            # Sanitize filename and check for dangerous patterns
            safe_filename = InputSanitizer.sanitize_filename(file.filename)
            result['file_info']['original_filename'] = file.filename
            result['file_info']['safe_filename'] = safe_filename

            # Check for executable extensions (security critical)
            if SecurityPatterns.EXECUTABLE_EXTENSION.search(file.filename.lower()):
                result['errors'].append(f"Executable file type not allowed: {file.filename}")
                return result

            # Check file size
            max_size = cls.MAX_FILE_SIZES.get(file_type, 1024 * 1024)
            if file.size and file.size > max_size:
                result['errors'].append(f"File size exceeds limit ({max_size} bytes)")
                return result

            # Minimum file size check (prevent empty files)
            if file.size and file.size < 1:
                result['errors'].append("File is empty")
                return result

            # Check MIME type
            allowed_types = cls.ALLOWED_MIME_TYPES.get(file_type, [])
            if file.content_type not in allowed_types:
                result['errors'].append(f"File type not allowed: {file.content_type}")
                return result

            # Validate file extension matches MIME type
            file_ext = Path(safe_filename).suffix.lower()
            if not cls._validate_extension(file_ext, file_type):
                result['errors'].append(f"File extension not allowed: {file_ext}")
                return result

            # MIME type spoofing detection
            mime_validation = cls._validate_mime_consistency(file, file_type)
            if not mime_validation['valid']:
                result['errors'].extend(mime_validation['errors'])
                result['warnings'].extend(mime_validation['warnings'])
                if strict_mode:
                    return result

            # Content validation (magic bytes, dangerous patterns)
            content_validation = cls._validate_file_content(file, file_type, strict_mode)
            if not content_validation['valid']:
                result['errors'].extend(content_validation['errors'])
                result['warnings'].extend(content_validation['warnings'])
                if strict_mode and content_validation['errors']:
                    return result

            # Calculate security score
            result['security_score'] = cls._calculate_security_score(result, file, file_type)

            # File passed all validations
            result['valid'] = True
            result['file_info']['validated_type'] = file_type
            result['file_info']['mime_type'] = file.content_type
            result['file_info']['size'] = file.size

            return result

        except Exception as e:
            logger.error(f"File validation failed: {e}")
            return {
                'valid': False,
                'errors': [f"Validation failed: {str(e)}"],
                'warnings': [],
                'file_info': {},
                'security_score': 0
            }

    @classmethod
    def _validate_mime_consistency(cls, file: UploadFile, file_type: str) -> Dict[str, Any]:
        """Validate MIME type consistency with file content"""
        result = {'valid': True, 'errors': [], 'warnings': []}

        try:
            # Read first few bytes to check magic bytes
            file.file.seek(0)
            header = file.file.read(512)
            file.file.seek(0)

            # Check for dangerous file signatures
            for signature, description in cls.DANGEROUS_SIGNATURES.items():
                if header.startswith(signature):
                    result['errors'].append(f"Dangerous file signature detected: {description}")
                    result['valid'] = False
                    return result

            # MIME type specific validation
            if file_type == 'image':
                # Check image headers
                image_signatures = {
                    b'\xFF\xD8\xFF': 'JPEG',
                    b'\x89\x50\x4E\x47': 'PNG',
                    b'\x47\x49\x46\x38': 'GIF',
                    b'\x42\x4D': 'BMP',
                    b'\x52\x49\x46\x46': 'WEBP'
                }

                valid_image = any(header.startswith(sig) for sig in image_signatures.keys())
                if not valid_image:
                    result['warnings'].append("Image file signature not recognized")

            elif file_type == 'document':
                # Check document headers
                if file.content_type == 'application/pdf' and not header.startswith(b'%PDF'):
                    result['errors'].append("PDF file signature mismatch")
                    result['valid'] = False

            return result

        except Exception as e:
            logger.error(f"MIME consistency validation failed: {e}")
            result['errors'].append(f"MIME validation failed: {str(e)}")
            result['valid'] = False
            return result

    @classmethod
    def _validate_file_content(cls, file: UploadFile, file_type: str, strict_mode: bool = True) -> Dict[str, Any]:
        """Validate file content for dangerous patterns"""
        result = {'valid': True, 'errors': [], 'warnings': []}

        try:
            # Read file content for analysis
            file.file.seek(0)
            content = file.file.read(8192)  # Read first 8KB
            file.file.seek(0)

            # Check for script patterns in content
            for pattern in cls.SCRIPT_PATTERNS:
                if pattern in content.lower():
                    if strict_mode:
                        result['errors'].append(f"Dangerous script pattern detected in file content")
                        result['valid'] = False
                    else:
                        result['warnings'].append(f"Potential script content detected")

            # Check for embedded executables
            if b'MZ' in content[:1024]:  # PE header
                result['errors'].append("Embedded executable detected")
                result['valid'] = False

            # Check for suspicious URLs
            if b'http://' in content or b'https://' in content:
                result['warnings'].append("URLs detected in file content")

            # File type specific content validation
            if file_type == 'text':
                # Validate text encoding
                try:
                    content.decode('utf-8')
                except UnicodeDecodeError:
                    result['warnings'].append("File contains non-UTF-8 content")

            elif file_type == 'image':
                # Check for embedded scripts in image metadata
                if b'<script' in content.lower() or b'javascript:' in content.lower():
                    result['errors'].append("Script content detected in image file")
                    result['valid'] = False

            return result

        except Exception as e:
            logger.error(f"File content validation failed: {e}")
            result['errors'].append(f"Content validation failed: {str(e)}")
            result['valid'] = False
            return result

    @classmethod
    def _calculate_security_score(cls, validation_result: Dict[str, Any], file: UploadFile, file_type: str) -> int:
        """Calculate security score for the file (0-100)"""
        score = 100

        # Deduct points for errors and warnings
        score -= len(validation_result['errors']) * 25
        score -= len(validation_result['warnings']) * 10

        # Bonus points for safe file types
        safe_types = ['text', 'image']
        if file_type in safe_types:
            score += 10

        # Deduct points for large files
        if file.size and file.size > 10 * 1024 * 1024:  # > 10MB
            score -= 15

        # Ensure score is within bounds
        return max(0, min(100, score))

    @classmethod
    def _validate_extension(cls, extension: str, file_type: str) -> bool:
        """Validate file extension against type"""
        extension_patterns = {
            'image': SecurityPatterns.IMAGE_EXTENSION,
            'document': SecurityPatterns.DOCUMENT_EXTENSION,
            'text': re.compile(r'\.(txt|csv|json)$', re.IGNORECASE)
        }

        pattern = extension_patterns.get(file_type)
        if pattern:
            return bool(pattern.search(extension))

        return False

    @classmethod
    def _validate_file_content(cls, file: UploadFile, file_type: str) -> Dict[str, Any]:
        """Validate file content for security threats"""
        try:
            result = {'valid': True, 'errors': []}

            # Read first chunk for content analysis
            file.file.seek(0)
            content_chunk = file.file.read(1024)
            file.file.seek(0)  # Reset file pointer

            # Check for executable content
            if cls._contains_executable_content(content_chunk):
                result['valid'] = False
                result['errors'].append("File contains potentially executable content")

            # Check for embedded scripts
            if cls._contains_script_content(content_chunk):
                result['valid'] = False
                result['errors'].append("File contains embedded scripts")

            return result

        except Exception as e:
            logger.error(f"File content validation failed: {e}")
            return {'valid': False, 'errors': [f"Content validation error: {str(e)}"]}

    @staticmethod
    def _contains_executable_content(content: bytes) -> bool:
        """Check for executable file signatures"""
        executable_signatures = [
            b'\x4d\x5a',  # PE executable
            b'\x7f\x45\x4c\x46',  # ELF executable
            b'\xfe\xed\xfa',  # Mach-O executable
            b'#!/bin/',  # Shell script
            b'#!/usr/bin/',  # Shell script
        ]

        for signature in executable_signatures:
            if content.startswith(signature):
                return True

        return False

    @staticmethod
    def _contains_script_content(content: bytes) -> bool:
        """Check for embedded script content"""
        try:
            content_str = content.decode('utf-8', errors='ignore').lower()

            script_patterns = [
                '<script',
                'javascript:',
                'vbscript:',
                'onload=',
                'onerror=',
                'eval(',
                'document.write'
            ]

            for pattern in script_patterns:
                if pattern in content_str:
                    return True

            return False

        except Exception:
            return False

class SecureValidator:
    """Pydantic-based secure validators"""

    @staticmethod
    def validate_email(email: str) -> str:
        """Validate email format"""
        if not SecurityPatterns.EMAIL.match(email):
            raise ValueError("Invalid email format")
        return email.lower()

    @staticmethod
    def validate_uuid(uuid_str: str) -> str:
        """Validate UUID format"""
        if not SecurityPatterns.UUID.match(uuid_str):
            raise ValueError("Invalid UUID format")
        return uuid_str.lower()

    @staticmethod
    def validate_safe_string(text: str, max_length: int = 255) -> str:
        """Validate safe string (alphanumeric + basic punctuation)"""
        if len(text) > max_length:
            raise ValueError(f"String too long (max {max_length} characters)")

        if not SecurityPatterns.SAFE_STRING.match(text):
            raise ValueError("String contains invalid characters")

        return text

    @staticmethod
    def validate_api_key(api_key: str) -> str:
        """Validate API key format"""
        if not SecurityPatterns.API_KEY.match(api_key):
            raise ValueError("Invalid API key format")
        return api_key

    @staticmethod
    def validate_jwt_token(token: str) -> str:
        """Validate JWT token format"""
        if not SecurityPatterns.JWT_TOKEN.match(token):
            raise ValueError("Invalid JWT token format")
        return token

    @staticmethod
    def validate_username(username: str) -> str:
        """Validate username format"""
        if not SecurityPatterns.USERNAME.match(username):
            raise ValueError("Invalid username format (3-30 alphanumeric characters)")
        return username.lower()

    @staticmethod
    def validate_strong_password(password: str) -> str:
        """Validate strong password"""
        if not SecurityPatterns.PASSWORD_STRONG.match(password):
            raise ValueError("Password must be at least 8 characters with uppercase, lowercase, digit, and special character")
        return password

# Pydantic models with security validation
class SecureUserInput(BaseModel):
    """Secure user input model"""
    username: str = Field(..., min_length=3, max_length=30)
    email: str = Field(..., max_length=255)
    full_name: str = Field(..., max_length=100)

    @validator('username')
    def validate_username(cls, v):
        return SecureValidator.validate_username(v)

    @validator('email')
    def validate_email(cls, v):
        return SecureValidator.validate_email(v)

    @validator('full_name')
    def validate_full_name(cls, v):
        return InputSanitizer.sanitize_user_input(v, 100)

class SecureAPIRequest(BaseModel):
    """Secure API request model"""
    api_key: str = Field(..., min_length=32, max_length=128)
    request_data: Dict[str, Any] = Field(...)

    @validator('api_key')
    def validate_api_key(cls, v):
        return SecureValidator.validate_api_key(v)

    @validator('request_data')
    def validate_request_data(cls, v):
        # Sanitize all string values in the request data
        return cls._sanitize_dict(v)

    @classmethod
    def _sanitize_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively sanitize dictionary values"""
        sanitized = {}

        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = InputSanitizer.sanitize_user_input(value)
            elif isinstance(value, dict):
                sanitized[key] = cls._sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    InputSanitizer.sanitize_user_input(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

def validate_path_traversal(file_path: str) -> str:
    """Validate and sanitize file path to prevent traversal attacks"""
    try:
        # Remove path traversal patterns
        safe_path = re.sub(SecurityPatterns.PATH_TRAVERSAL, '', file_path)

        # Normalize path
        normalized = os.path.normpath(safe_path)

        # Ensure path doesn't go outside allowed directory
        if normalized.startswith('/') or normalized.startswith('..'):
            raise ValidationError("Invalid file path")

        return normalized

    except Exception as e:
        logger.error(f"Path validation failed: {e}")
        raise ValidationError(f"Path validation failed: {e}")

# Global validation functions
def create_input_validator(patterns: Dict[str, re.Pattern]) -> Callable:
    """Create custom input validator with specified patterns"""
    def validator(value: str, field_name: str) -> str:
        pattern = patterns.get(field_name)
        if pattern and not pattern.match(value):
            raise ValidationError(f"Invalid format for {field_name}")
        return value

    return validator