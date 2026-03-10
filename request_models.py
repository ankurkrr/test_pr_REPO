"""
Request models for the Meeting Intelligence Agent API.
Contains all Pydantic request models with validation.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from ...security.input_validation import InputSanitizer, SecurityPatterns, ValidationError


class ToolField(BaseModel):
    """Secure model for tool field with input validation"""

    type: Optional[str] = Field(None, max_length=100)
    field: Optional[str] = Field(None, max_length=255)
    value: Optional[Any] = None
    options: Optional[List[Dict[str, Any]]] = Field(None, max_items=100)

    @field_validator("type", "field")
    @classmethod
    def validate_string_fields(cls, v):
        """Validate string fields and sanitize"""
        if v is not None:
            return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)
        return v

    @field_validator("value")
    @classmethod
    def validate_value(cls, v):
        """Sanitize string values only"""
        if isinstance(v, str):
            return InputSanitizer.sanitize_user_input(v, max_length=10000, strict=False)
        return v


class ToolToUse(BaseModel):
    """Secure model for tool to use with validation"""

    id: Optional[str] = Field(None, max_length=255)
    title: Optional[str] = Field(None, max_length=500)
    fields_json: List[ToolField] = Field(default_factory=list, max_items=50)
    integration_type: Optional[str] = Field(None, max_length=100)
    integration_status: Optional[str] = Field(None, max_length=100)
    confirmation_status: Optional[str] = Field(None, max_length=100)

    @field_validator(
        "id", "title", "integration_type", "integration_status", "confirmation_status"
    )
    @classmethod
    def validate_string_fields(cls, v):
        """Validate string fields and sanitize"""
        if v is not None:
            return InputSanitizer.sanitize_user_input(v, max_length=500, strict=True)
        return v


class WorkflowDataItem(BaseModel):
    """Secure model for workflow data item with validation"""

    id: str = Field(..., max_length=255)
    text: str = Field(..., max_length=50000)
    tool_to_use: List[ToolToUse] = Field(default_factory=list, max_items=20)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v):
        """Validate ID format and sanitize"""
        if not SecurityPatterns.SAFE_STRING.match(v):
            raise ValueError("Invalid ID format")
        return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)

    @field_validator("text")
    @classmethod
    def validate_text(cls, v):
        """Validate text length and sanitize"""
        return InputSanitizer.sanitize_user_input(v, max_length=50000, strict=False)


class WorkflowRequest(BaseModel):
    """Secure model for workflow request with comprehensive validation"""

    token: str = Field(..., min_length=10, max_length=10000)
    agent_task_id: str = Field(..., min_length=1, max_length=255)
    workflow_data: List[WorkflowDataItem] = Field(default_factory=list, max_items=100)
    encryption_key: Optional[str] = Field(None, min_length=32, max_length=128)
    encryption_iv: Optional[str] = Field(None, min_length=16, max_length=64)
    timezone: Optional[str] = Field(None, max_length=100)

    @field_validator("agent_task_id")
    @classmethod
    def validate_agent_task_id(cls, v):
        """Validate agent task ID format"""
        if not SecurityPatterns.SAFE_STRING.match(v):
            raise ValueError("Invalid agent task ID format")
        return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)

    @field_validator("token")
    @classmethod
    def validate_token(cls, v):
        """Validate token length and basic checks"""
        # Basic token format validation
        if len(v.strip()) < 10:
            raise ValueError("Token too short")
        return v.strip()

    @field_validator("encryption_key", "encryption_iv")
    @classmethod
    def validate_encryption_params(cls, v):
        """Validate base64 format of encryption parameters"""
        if v is not None:
            if not SecurityPatterns.BASE64.match(v.replace("-", "+").replace("_", "/")):
                raise ValueError("Invalid encryption parameter format")
        return v


class RunAgentRequest(BaseModel):
    """Secure request model for running agent workflow"""

    agent_task_id: str = Field(..., min_length=1, max_length=255)
    workflow_data: List[WorkflowDataItem] = Field(default_factory=list, max_items=100)
    user_id: Optional[str] = Field(None, max_length=255)
    use_agent: bool = Field(default=True)
    auth_tokens: Optional[Dict[str, Optional[str]]] = Field(None, max_items=10)

    @field_validator("agent_task_id", "user_id")
    @classmethod
    def validate_ids(cls, v):
        """Validate ID format and sanitize"""
        if v is not None:
            if not SecurityPatterns.SAFE_STRING.match(v):
                raise ValueError("Invalid ID format")
            return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)
        return v

    @field_validator("auth_tokens")
    @classmethod
    def validate_auth_tokens(cls, v):
        """Validate auth token keys and sanitize values"""
        if v is not None:
            # Validate token keys and sanitize values
            allowed_keys = {
                "token",
                "access_token",
                "refresh_token",
                "api_key",
                "client_secret",
            }
            sanitized_tokens = {}
            for key, value in v.items():
                if key not in allowed_keys:
                    raise ValueError(f"Invalid token key: {key}")
                if value is not None and isinstance(value, str):
                    if len(value) > 10000:  # Reasonable token length limit
                        raise ValueError(f"Token value too long for key: {key}")
                    sanitized_tokens[key] = value
                else:
                    sanitized_tokens[key] = value
            return sanitized_tokens
        return v


class StopRequest(BaseModel):
    """Secure request model for stopping agent"""

    token: str = Field(..., min_length=10, max_length=10000)
    agent_task_id: str = Field(..., min_length=1, max_length=255)
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("agent_task_id")
    @classmethod
    def validate_agent_task_id(cls, v):
        """Validate agent task ID format"""
        if not SecurityPatterns.SAFE_STRING.match(v):
            raise ValueError("Invalid agent task ID format")
        return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)

    @field_validator("token")
    @classmethod
    def validate_token(cls, v):
        """Validate token length and basic checks"""
        if len(v.strip()) < 10:
            raise ValueError("Token too short")
        return v.strip()


class DeleteRequest(BaseModel):
    """Secure request model for deleting agent/user data"""

    token: str = Field(..., min_length=10, max_length=10000)
    agent_task_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("agent_task_id")
    @classmethod
    def validate_agent_task_id(cls, v):
        """Validate agent task ID format"""
        if not SecurityPatterns.SAFE_STRING.match(v):
            raise ValueError("Invalid agent task ID format")
        return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)

    @field_validator("token")
    @classmethod
    def validate_token(cls, v):
        """Validate token length and basic checks"""
        if len(v.strip()) < 10:
            raise ValueError("Token too short")
        return v.strip()


class LatestAgentRequest(BaseModel):
    """Secure request model for fetching latest agent details"""

    org_id: str = Field(..., min_length=1, max_length=255)
    user_id: str = Field(..., min_length=1, max_length=255)
    agent_task_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("org_id", "user_id", "agent_task_id")
    @classmethod
    def validate_ids(cls, v):
        """Validate ID format and sanitize"""
        if not SecurityPatterns.SAFE_STRING.match(v):
            raise ValueError(
                "Invalid ID format - only alphanumeric, spaces, hyphens, underscores, and dots allowed"
            )
        return InputSanitizer.sanitize_user_input(v, max_length=255, strict=True)



