"""
Configuration Validation and Management

This module provides utilities for validating configuration settings
and ensuring all required environment variables are properly set.
"""

import os
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ConfigSeverity(Enum):
    """Configuration validation severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""
    is_valid: bool
    severity: ConfigSeverity
    message: str
    missing_vars: List[str]
    invalid_vars: List[str]
    warnings: List[str]


class ConfigurationValidator:
    """Validates application configuration and environment variables."""
    
    def __init__(self):
        self.required_vars = {
            # Database
            "MYSQL_HOST": "Database host",
            "MYSQL_USERNAME": "Database username", 
            "MYSQL_PASSWORD": "Database password",
            "MYSQL_DATABASE": "Database name",
            
            # Google APIs
            "GOOGLE_CLIENT_ID": "Google OAuth client ID",
            "GOOGLE_CLIENT_SECRET": "Google OAuth client secret",
            "GEMINI_API_KEY": "Google Gemini API key",
            
            # Security
            "JWT_SECRET_KEY": "JWT secret key",
            "ENCRYPTION_KEY": "Data encryption key",
            "ENCRYPTION_IV": "Data encryption IV",
            
            # Email
            "SENDGRID_API_KEY": "SendGrid API key",
            "SENDGRID_FROM_EMAIL": "SendGrid from email",
        }
        
        self.optional_vars = {
            "APP_ENV": "development",
            "PORT": "8000",
            "DEBUG": "False",
            "LOG_LEVEL": "INFO",
            "TIME_WINDOW_MINUTES": "30",
            "CALENDAR_LOOKBACK_MINUTES": "30",
        }
        
        self.validation_rules = {
            "PORT": self._validate_port,
            "DEBUG": self._validate_boolean,
            "TIME_WINDOW_MINUTES": self._validate_positive_int,
            "CALENDAR_LOOKBACK_MINUTES": self._validate_positive_int,
            "JWT_EXPIRATION_HOURS": self._validate_positive_int,
        }
    
    def validate_configuration(self) -> ConfigValidationResult:
        """
        Validate the entire application configuration.
        
        Returns:
            ConfigValidationResult with validation details
        """
        missing_vars = []
        invalid_vars = []
        warnings = []
        
        # Check required variables
        for var_name, description in self.required_vars.items():
            value = os.getenv(var_name)
            if not value or value.strip() == "":
                missing_vars.append(f"{var_name} ({description})")
        
        # Check optional variables and validate their values
        for var_name, default_value in self.optional_vars.items():
            value = os.getenv(var_name, default_value)
            
            # Validate if there's a validation rule
            if var_name in self.validation_rules:
                is_valid, error_msg = self.validation_rules[var_name](value)
                if not is_valid:
                    invalid_vars.append(f"{var_name}: {error_msg}")
        
        # Check for common configuration issues
        warnings.extend(self._check_common_issues())
        
        # Determine overall validity and severity
        if missing_vars:
            severity = ConfigSeverity.CRITICAL
            is_valid = False
            message = f"Critical configuration issues: {len(missing_vars)} required variables missing"
        elif invalid_vars:
            severity = ConfigSeverity.ERROR
            is_valid = False
            message = f"Configuration validation errors: {len(invalid_vars)} invalid values"
        elif warnings:
            severity = ConfigSeverity.WARNING
            is_valid = True
            message = f"Configuration warnings: {len(warnings)} issues found"
        else:
            severity = ConfigSeverity.INFO
            is_valid = True
            message = "Configuration validation passed"
        
        return ConfigValidationResult(
            is_valid=is_valid,
            severity=severity,
            message=message,
            missing_vars=missing_vars,
            invalid_vars=invalid_vars,
            warnings=warnings
        )
    
    def _validate_port(self, value: str) -> Tuple[bool, str]:
        """Validate port number."""
        try:
            port = int(value)
            if 1 <= port <= 65535:
                return True, ""
            else:
                return False, f"Port must be between 1 and 65535, got {port}"
        except ValueError:
            return False, f"Port must be a number, got '{value}'"
    
    def _validate_boolean(self, value: str) -> Tuple[bool, str]:
        """Validate boolean value."""
        if value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return True, ""
        else:
            return False, f"Boolean value must be true/false, got '{value}'"
    
    def _validate_positive_int(self, value: str) -> Tuple[bool, str]:
        """Validate positive integer."""
        try:
            num = int(value)
            if num > 0:
                return True, ""
            else:
                return False, f"Must be positive integer, got {num}"
        except ValueError:
            return False, f"Must be a number, got '{value}'"
    
    def _check_common_issues(self) -> List[str]:
        """Check for common configuration issues."""
        warnings = []
        
        # Check for development settings in production
        app_env = os.getenv("APP_ENV", "development")
        debug = os.getenv("DEBUG", "False").lower() == "true"
        
        if app_env.lower() == "production" and debug:
            warnings.append("DEBUG=True in production environment")
        
        # Check for weak secrets
        jwt_secret = os.getenv("JWT_SECRET_KEY", "")
        if jwt_secret and len(jwt_secret) < 32:
            warnings.append("JWT_SECRET_KEY is too short (should be at least 32 characters)")
        
        encryption_key = os.getenv("ENCRYPTION_KEY", "")
        if encryption_key and len(encryption_key) < 32:
            warnings.append("ENCRYPTION_KEY is too short (should be at least 32 characters)")
        
        # Check for placeholder values
        placeholder_values = [
            "your_", "placeholder", "example", "test", "demo"
        ]
        
        for var_name in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GEMINI_API_KEY"]:
            value = os.getenv(var_name, "")
            if any(placeholder in value.lower() for placeholder in placeholder_values):
                warnings.append(f"{var_name} appears to contain placeholder value")
        
        # Check database connection string
        mysql_host = os.getenv("MYSQL_HOST", "")
        if mysql_host and mysql_host.startswith("your_"):
            warnings.append("MYSQL_HOST appears to contain placeholder value")
        
        return warnings
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of the current configuration."""
        config = {}
        
        # Add all environment variables (mask sensitive ones)
        sensitive_vars = {
            "MYSQL_PASSWORD", "GOOGLE_CLIENT_SECRET", "GEMINI_API_KEY",
            "JWT_SECRET_KEY", "ENCRYPTION_KEY", "ENCRYPTION_IV",
            "SENDGRID_API_KEY", "API_SECRET", "PLATFORM_TASK_API_SECRET"
        }
        
        for var_name in self.required_vars.keys():
            value = os.getenv(var_name)
            if var_name in sensitive_vars and value:
                config[var_name] = "***MASKED***"
            else:
                config[var_name] = value
        
        for var_name in self.optional_vars.keys():
            value = os.getenv(var_name, self.optional_vars[var_name])
            if var_name in sensitive_vars and value:
                config[var_name] = "***MASKED***"
            else:
                config[var_name] = value
        
        return config
    
    def generate_env_file(self, output_path: str = ".env") -> bool:
        """
        Generate a .env file with current configuration.
        
        Args:
            output_path: Path where to write the .env file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(output_path, 'w') as f:
                f.write("# Generated .env file\n")
                f.write("# Meeting Intelligence Agent Configuration\n\n")
                
                # Write required variables
                f.write("# Required Configuration\n")
                for var_name in self.required_vars.keys():
                    value = os.getenv(var_name, "")
                    f.write(f"{var_name}={value}\n")
                
                f.write("\n# Optional Configuration\n")
                for var_name, default_value in self.optional_vars.items():
                    value = os.getenv(var_name, default_value)
                    f.write(f"{var_name}={value}\n")
            
            logger.info(f"Generated .env file at {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate .env file: {e}")
            return False


def validate_startup_configuration() -> bool:
    """
    Validate configuration during application startup.
    
    Returns:
        True if configuration is valid, False otherwise
    """
    validator = ConfigurationValidator()
    result = validator.validate_configuration()
    
    if result.severity == ConfigSeverity.CRITICAL:
        logger.critical(f"CRITICAL: {result.message}")
        logger.critical(f"Missing variables: {', '.join(result.missing_vars)}")
        return False
    
    elif result.severity == ConfigSeverity.ERROR:
        logger.error(f"ERROR: {result.message}")
        logger.error(f"Invalid variables: {', '.join(result.invalid_vars)}")
        return False
    
    elif result.severity == ConfigSeverity.WARNING:
        logger.warning(f"WARNING: {result.message}")
        for warning in result.warnings:
            logger.warning(f"  - {warning}")
        return True
    
    else:
        logger.info("Configuration validation passed")
        return True


def get_configuration_status() -> Dict[str, Any]:
    """
    Get current configuration status for health checks.
    
    Returns:
        Dict with configuration status information
    """
    validator = ConfigurationValidator()
    result = validator.validate_configuration()
    config_summary = validator.get_configuration_summary()
    
    return {
        "is_valid": result.is_valid,
        "severity": result.severity.value,
        "message": result.message,
        "missing_vars_count": len(result.missing_vars),
        "invalid_vars_count": len(result.invalid_vars),
        "warnings_count": len(result.warnings),
        "configuration": config_summary
    }


# Global validator instance
_config_validator = ConfigurationValidator()


def get_config_validator() -> ConfigurationValidator:
    """Get the global configuration validator instance."""
    return _config_validator
