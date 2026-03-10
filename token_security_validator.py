#!/usr/bin/env python3
"""
Token Security Validator and Migration Tool
Validates token security, migrates plain text tokens to encrypted storage,
and enforces scope-based validation with expiry checking.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import hashlib

from .token_manager import get_token_manager, TokenSecurityError

logger = logging.getLogger(__name__)

class TokenSecurityValidator:
    """
    Comprehensive token security validator and migration tool
    """

    def __init__(self):
        """Initialize the token security validator"""
        self.token_manager = get_token_manager()
        self.validation_results = []
        self.migration_results = []

    def scan_for_insecure_tokens(self, scan_paths: List[str] = None) -> Dict[str, Any]:
        """
        Scan for insecure token storage across the codebase

        Args:
            scan_paths: List of paths to scan (defaults to common locations)

        Returns:
            Dictionary with scan results
        """
        if scan_paths is None:
            scan_paths = [
                "./keys",
                "./tokens",
                "./credentials",
                "./config",
                "."
            ]

        insecure_tokens = []
        scan_summary = {
            "total_files_scanned": 0,
            "insecure_tokens_found": 0,
            "high_risk_files": [],
            "medium_risk_files": [],
            "low_risk_files": []
        }

        logger.info(" Scanning for insecure token storage...")

        for scan_path in scan_paths:
            if not os.path.exists(scan_path):
                continue

            for root, dirs, files in os.walk(scan_path):
                for file in files:
                    if file.endswith(('.json', '.txt', '.env', '.config')):
                        file_path = os.path.join(root, file)
                        scan_summary["total_files_scanned"] += 1

                        risk_level = self._analyze_file_for_tokens(file_path)
                        if risk_level:
                            insecure_tokens.append({
                                "file_path": file_path,
                                "risk_level": risk_level,
                                "file_size": os.path.getsize(file_path),
                                "last_modified": datetime.fromtimestamp(
                                    os.path.getmtime(file_path)
                                ).isoformat()
                            })

                            scan_summary["insecure_tokens_found"] += 1
                            scan_summary[f"{risk_level}_risk_files"].append(file_path)

        scan_summary["insecure_tokens"] = insecure_tokens

        logger.info(f" Scan complete: {scan_summary['insecure_tokens_found']} insecure tokens found")
        return scan_summary

    def _analyze_file_for_tokens(self, file_path: str) -> Optional[str]:
        """
        Analyze a file for potential token storage

        Returns:
            Risk level: 'high', 'medium', 'low', or None
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().lower()

            # High risk indicators
            high_risk_patterns = [
                'access_token',
                'refresh_token',
                'client_secret',
                'private_key',
                'api_key',
                'bearer',
                'oauth'
            ]

            # Medium risk indicators
            medium_risk_patterns = [
                'token',
                'secret',
                'key',
                'credential',
                'auth'
            ]

            # Check for high risk
            for pattern in high_risk_patterns:
                if pattern in content:
                    # Additional check for JSON structure
                    if self._looks_like_token_json(file_path):
                        return "high"

            # Check for medium risk
            for pattern in medium_risk_patterns:
                if pattern in content:
                    if self._looks_like_token_json(file_path):
                        return "medium"

            return None

        except Exception as e:
            logger.warning(f"Failed to analyze file {file_path}: {e}")
            return None

    def _looks_like_token_json(self, file_path: str) -> bool:
        """Check if file looks like a token JSON file"""
        try:
            if not file_path.endswith('.json'):
                return False

            with open(file_path, 'r') as f:
                data = json.load(f)

            # Check for common token JSON structures
            token_indicators = [
                'access_token', 'refresh_token', 'token', 'client_id',
                'client_secret', 'scopes', 'expiry', 'token_uri'
            ]

            if isinstance(data, dict):
                keys = set(str(k).lower() for k in data.keys())
                matches = sum(1 for indicator in token_indicators if indicator in keys)
                return matches >= 2  # At least 2 token-related fields

            return False

        except (json.JSONDecodeError, Exception):
            return False

    def validate_token_security(self, token_data: Dict[str, Any],
                              required_scopes: List[str] = None) -> Dict[str, Any]:
        """
        Validate token security properties

        Args:
            token_data: Token data to validate
            required_scopes: Required scopes for validation

        Returns:
            Validation results
        """
        validation = {
            "is_valid": True,
            "issues": [],
            "warnings": [],
            "security_score": 100,
            "recommendations": []
        }

        # Check token expiry
        if "expiry" in token_data or "expires_at" in token_data:
            expiry_field = token_data.get("expiry") or token_data.get("expires_at")
            if expiry_field:
                try:
                    if isinstance(expiry_field, str):
                        expiry = datetime.fromisoformat(expiry_field.replace('Z', '+00:00'))
                    else:
                        expiry = expiry_field

                    if expiry <= datetime.now().astimezone():
                        validation["issues"].append("Token is expired")
                        validation["is_valid"] = False
                        validation["security_score"] -= 50
                    elif expiry <= datetime.now().astimezone() + timedelta(hours=1):
                        validation["warnings"].append("Token expires within 1 hour")
                        validation["security_score"] -= 10

                except Exception as e:
                    validation["warnings"].append(f"Could not parse expiry: {e}")
                    validation["security_score"] -= 5
        else:
            validation["warnings"].append("No expiry information found")
            validation["security_score"] -= 15

        # Check required scopes
        if required_scopes:
            token_scopes = token_data.get("scopes", [])
            if isinstance(token_scopes, str):
                token_scopes = token_scopes.split()

            missing_scopes = set(required_scopes) - set(token_scopes)
            if missing_scopes:
                validation["issues"].append(f"Missing required scopes: {list(missing_scopes)}")
                validation["is_valid"] = False
                validation["security_score"] -= 30

        # Check for sensitive data exposure
        sensitive_fields = ["client_secret", "private_key", "refresh_token"]
        for field in sensitive_fields:
            if field in token_data:
                value = str(token_data[field])
                if len(value) < 20:  # Suspiciously short
                    validation["warnings"].append(f"{field} appears to be too short")
                    validation["security_score"] -= 5

        # Security recommendations
        if validation["security_score"] < 90:
            validation["recommendations"].append("Consider token refresh or re-authentication")
        if validation["security_score"] < 70:
            validation["recommendations"].append("Immediate token replacement recommended")
        if validation["security_score"] < 50:
            validation["recommendations"].append("CRITICAL: Token should not be used")

        return validation

    def migrate_plain_text_tokens(self, source_paths: List[str] = None) -> Dict[str, Any]:
        """
        Migrate plain text tokens to secure encrypted storage

        Args:
            source_paths: Paths to scan for plain text tokens

        Returns:
            Migration results
        """
        if source_paths is None:
            source_paths = ["./keys/google-token.json"]

        migration_results = {
            "total_files_processed": 0,
            "successful_migrations": 0,
            "failed_migrations": 0,
            "skipped_files": 0,
            "migration_details": []
        }

        logger.info(" Starting token migration to secure storage...")

        for source_path in source_paths:
            if not os.path.exists(source_path):
                migration_results["skipped_files"] += 1
                continue

            migration_results["total_files_processed"] += 1

            try:
                # Load plain text token
                with open(source_path, 'r') as f:
                    token_data = json.load(f)

                # Validate token before migration
                validation = self.validate_token_security(token_data)

                if not validation["is_valid"]:
                    logger.warning(f"Skipping invalid token: {source_path}")
                    migration_results["skipped_files"] += 1
                    migration_results["migration_details"].append({
                        "file": source_path,
                        "status": "skipped",
                        "reason": "Invalid token",
                        "issues": validation["issues"]
                    })
                    continue

                # Generate secure token ID
                file_name = os.path.basename(source_path)
                token_id = f"migrated_{file_name}_{hashlib.md5(source_path.encode()).hexdigest()[:8]}"

                # Encrypt and store
                encrypted_token = self.token_manager.encrypt_token(
                    token_data=token_data,
                    token_id=token_id,
                    expiry_hours=24 * 7  # 7 days
                )

                metadata = {
                    "migrated_from": source_path,
                    "migration_date": datetime.now().isoformat(),
                    "original_file_size": os.path.getsize(source_path),
                    "token_type": "migrated_plain_text",
                    "validation_score": validation["security_score"]
                }

                self.token_manager.store_token(token_id, encrypted_token, metadata)

                # Create backup of original file
                backup_path = f"{source_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                os.rename(source_path, backup_path)

                migration_results["successful_migrations"] += 1
                migration_results["migration_details"].append({
                    "file": source_path,
                    "status": "success",
                    "token_id": token_id,
                    "backup_path": backup_path,
                    "security_score": validation["security_score"]
                })

                logger.info(f" Migrated token: {source_path} -> secure storage")

            except Exception as e:
                migration_results["failed_migrations"] += 1
                migration_results["migration_details"].append({
                    "file": source_path,
                    "status": "failed",
                    "error": str(e)
                })
                logger.error(f" Failed to migrate {source_path}: {e}")

        logger.info(f" Migration complete: {migration_results['successful_migrations']} successful, "
                   f"{migration_results['failed_migrations']} failed")

        return migration_results

    def generate_security_report(self) -> Dict[str, Any]:
        """Generate comprehensive security report"""

        # Scan for insecure tokens
        scan_results = self.scan_for_insecure_tokens()

        # Check secure token storage status
        secure_tokens = self.token_manager.list_tokens()

        # Generate recommendations
        recommendations = []

        if scan_results["insecure_tokens_found"] > 0:
            recommendations.append("Migrate plain text tokens to secure encrypted storage")

        if len(secure_tokens) == 0:
            recommendations.append("No secure tokens found - consider implementing secure token storage")

        if scan_results["insecure_tokens_found"] > len(secure_tokens):
            recommendations.append("More insecure tokens than secure tokens - prioritize migration")

        report = {
            "timestamp": datetime.now().isoformat(),
            "scan_results": scan_results,
            "secure_tokens_count": len(secure_tokens),
            "secure_tokens": secure_tokens,
            "security_status": "SECURE" if scan_results["insecure_tokens_found"] == 0 else "AT_RISK",
            "risk_level": self._calculate_risk_level(scan_results),
            "recommendations": recommendations,
            "next_actions": self._generate_next_actions(scan_results, secure_tokens)
        }

        return report

    def _calculate_risk_level(self, scan_results: Dict[str, Any]) -> str:
        """Calculate overall risk level"""
        high_risk = len(scan_results.get("high_risk_files", []))
        medium_risk = len(scan_results.get("medium_risk_files", []))

        if high_risk > 0:
            return "HIGH"
        elif medium_risk > 2:
            return "MEDIUM"
        elif medium_risk > 0:
            return "LOW"
        else:
            return "MINIMAL"

    def _generate_next_actions(self, scan_results: Dict[str, Any],
                             secure_tokens: List[Dict]) -> List[str]:
        """Generate actionable next steps"""
        actions = []

        if scan_results["insecure_tokens_found"] > 0:
            actions.append("Run token migration: python -m src.security.token_security_validator migrate")

        if len(secure_tokens) > 0:
            actions.append("Verify secure token functionality")

        actions.append("Implement regular token security audits")
        actions.append("Set up automated token expiry monitoring")

        return actions

def main():
    """CLI interface for token security validation"""
    import sys

    validator = TokenSecurityValidator()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "scan":
            results = validator.scan_for_insecure_tokens()
            print(json.dumps(results, indent=2))
        elif command == "migrate":
            results = validator.migrate_plain_text_tokens()
            print(json.dumps(results, indent=2))
        elif command == "report":
            report = validator.generate_security_report()
            print(json.dumps(report, indent=2))
        else:
            print("Usage: python -m src.security.token_security_validator [scan|migrate|report]")
    else:
        # Generate full report by default
        report = validator.generate_security_report()
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()