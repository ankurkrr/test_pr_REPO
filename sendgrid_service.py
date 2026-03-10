"""
SendGrid Email Service - Refactored and improved.

This service provides a clean, well-structured interface for sending
emails via SendGrid with proper error handling and configuration management.
"""

import os
import json
import logging
import http.client
import ssl
from typing import Any, Dict, List, Optional
from datetime import datetime

from ...base.service_base import BaseService, ServiceResult
from ...base.interfaces import IEmailService

logger = logging.getLogger(__name__)


class SendGridEmailService(BaseService, IEmailService):
    """
    SendGrid email service with improved architecture.

    This service provides:
    - Clean async interface
    - Proper error handling
    - Configuration management
    - Health checks
    - Bulk email support
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the SendGrid email service."""
        super().__init__(config)
        self.api_key = None
        self.from_email = None
        self.from_name = None
        self.api_url = "api.sendgrid.com"
        self.api_version = "v3"

        # Initialize configuration
        self._perform_initialization()

    def _perform_initialization(self) -> None:
        """Initialize SendGrid configuration."""
        # Get configuration from config dict or environment
        from src.configuration.config import SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, SENDGRID_FROM_NAME
        self.api_key = self.get_config_value("api_key") or SENDGRID_API_KEY
        self.from_email = self.get_config_value("from_email") or SENDGRID_FROM_EMAIL
        self.from_name = self.get_config_value("from_name") or SENDGRID_FROM_NAME

        # Debug logging
        # Avoid unicode symbols that may break Windows consoles
        self.logger.info("SendGrid config - API Key: %s, From Email: %s, From Name: %s",
                         'SET' if self.api_key else 'MISSING', self.from_email, self.from_name)

        # Validate required configuration
        if not self.api_key or not self.from_email:
            raise ValueError(f"SendGrid configuration incomplete. API Key: {'[OK]' if self.api_key else '[MISSING]'}, From Email: {'[OK]' if self.from_email else '[MISSING]'}")

        self.logger.info("SendGrid email service initialized successfully")

    async def send_email(self, to_email: str, subject: str, body: str,
                        html_body: Optional[str] = None) -> ServiceResult[Dict[str, Any]]:
        """
        Send a single email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            ServiceResult containing send results
        """
        try:
            self.log_operation("send_email", to_email=to_email, subject=subject)

            # Validate inputs
            if not to_email or not subject or not body:
                return ServiceResult.error_result("Missing required email parameters")

            # Prepare email payload
            payload = self._build_email_payload([to_email], subject, body, html_body)

            # Send email
            result = await self._send_via_api(payload)

            if result.success:
                return ServiceResult.success_result({
                    "message_id": result.data.get("message_id"),
                    "status": "sent",
                    "recipient": to_email,
                    "sent_at": datetime.now().isoformat()
                })
            else:
                return ServiceResult.error_result(result.error)

        except Exception as e:
            return self.handle_error(e, "send_email")

    async def send_bulk_email(self, recipients: List[str], subject: str, body: str,
                             html_body: Optional[str] = None) -> ServiceResult[Dict[str, Any]]:
        """
        Send bulk email to multiple recipients.

        Args:
            recipients: List of recipient email addresses
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            ServiceResult containing bulk send results
        """
        try:
            self.log_operation("send_bulk_email", recipient_count=len(recipients), subject=subject)

            # Validate inputs
            if not recipients or not subject or not body:
                return ServiceResult.error_result("Missing required bulk email parameters")

            if not isinstance(recipients, list):
                return ServiceResult.error_result("Recipients must be a list")

            # Prepare email payload
            payload = self._build_email_payload(recipients, subject, body, html_body)

            # Send email
            result = await self._send_via_api(payload)

            if result.success:
                return ServiceResult.success_result({
                    "message_id": result.data.get("message_id"),
                    "status": "sent",
                    "recipients": recipients,
                    "recipient_count": len(recipients),
                    "sent_at": datetime.now().isoformat()
                })
            else:
                return ServiceResult.error_result(result.error)

        except Exception as e:
            return self.handle_error(e, "send_bulk_email")

    async def send_meeting_summary(self, meeting_data: Dict[str, Any],
                                  recipients: List[str]) -> ServiceResult[Dict[str, Any]]:
        """
        Send meeting summary email.

        Args:
            meeting_data: Meeting data including summary information
            recipients: List of recipient email addresses

        Returns:
            ServiceResult containing send results
        """
        try:
            self.log_operation("send_meeting_summary", meeting_id=meeting_data.get("id"))

            # Generate email content
            subject, body, html_body = self._generate_meeting_summary_content(meeting_data)

            # Send email
            result = await self.send_bulk_email(recipients, subject, body, html_body)

            if result.success:
                return ServiceResult.success_result({
                    **result.data,
                    "meeting_id": meeting_data.get("id"),
                    "summary_type": "meeting_summary"
                })
            else:
                return ServiceResult.error_result(result.error)

        except Exception as e:
            return self.handle_error(e, "send_meeting_summary")

    def _build_email_payload(self, recipients: List[str], subject: str,
                           body: str, html_body: Optional[str] = None) -> Dict[str, Any]:
        """Build SendGrid API payload."""
        # Handle both string emails and dict format with email/name
        to_list = []
        for recipient in recipients:
            if isinstance(recipient, dict):
                to_list.append({
                    "email": recipient.get("email"),
                    "name": recipient.get("name", recipient.get("email"))
                })
            else:
                to_list.append({"email": recipient})

        payload = {
            "personalizations": [{"to": to_list}],
            "from": {
                "email": self.from_email,
                "name": self.from_name
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body}
            ]
        }

        if html_body:
            payload["content"].append({"type": "text/html", "value": html_body})

        return payload

    async def _send_via_api(self, payload: Dict[str, Any]) -> ServiceResult[Dict[str, Any]]:
        """Send email via SendGrid API."""
        try:
            # Prepare request
            data = json.dumps(payload)
            context = ssl.create_default_context()

            # Make HTTPS request
            conn = http.client.HTTPSConnection(self.api_url, context=context, timeout=30)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            endpoint = f"/{self.api_version}/mail/send"
            conn.request("POST", endpoint, body=data, headers=headers)

            # Get response
            response = conn.getresponse()
            status_code = response.status
            response_body = response.read().decode("utf-8", errors="ignore")
            conn.close()

            # Process response
            if 200 <= status_code < 300 or status_code == 202:
                return ServiceResult.success_result({
                    "message_id": f"msg_{datetime.now().timestamp()}",
                    "status_code": status_code,
                    "provider": "sendgrid"
                })
            else:
                error_msg = f"SendGrid API error: {status_code} - {response_body}"
                self.logger.error(error_msg)
                return ServiceResult.error_result(error_msg)

        except Exception as e:
            error_msg = f"SendGrid API request failed: {str(e)}"
            self.logger.error(error_msg)
            return ServiceResult.error_result(error_msg)

    def _generate_meeting_summary_content(self, meeting_data: Dict[str, Any]) -> tuple[str, str, str]:
        """Generate email content for meeting summary."""
        meeting_title = meeting_data.get("title", "Meeting Summary")
        meeting_date = meeting_data.get("start_time", "Unknown date")
        attendees = meeting_data.get("attendees", [])
        summary = meeting_data.get("summary", {})

        # Generate subject
        subject = f"Meeting Summary: {meeting_title}"

        # Generate plain text body
        body = f"Meeting: {meeting_title}\n"
        body += f"Date: {meeting_date}\n"
        body += f"Attendees: {', '.join(attendees) if attendees else 'Not specified'}\n\n"

        if summary:
            body += f"Executive Summary:\n{summary.get('executive_summary', 'No summary available')}\n\n"

            key_points = summary.get('key_points', [])
            if key_points:
                body += "Key Points:\n"
                for point in key_points:
                    body += f"• {point}\n"
                body += "\n"

            action_items = summary.get('action_items', [])
            if action_items:
                body += "Action Items:\n"
                for item in action_items:
                    body += f"• {item}\n"
                body += "\n"

        body += "\n---\n"
        body += "This summary was generated by Meeting Intelligence Agent"

        # Generate HTML body
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2c3e50;">{meeting_title}</h2>
            <p><strong>Date:</strong> {meeting_date}</p>
            <p><strong>Attendees:</strong> {', '.join(attendees) if attendees else 'Not specified'}</p>
        """

        if summary:
            html_body += f"""
            <h3 style="color: #34495e;">Executive Summary</h3>
            <p>{summary.get('executive_summary', 'No summary available')}</p>
            """

            key_points = summary.get('key_points', [])
            if key_points:
                html_body += "<h3 style='color: #34495e;'>Key Points</h3><ul>"
                for point in key_points:
                    html_body += f"<li>{point}</li>"
                html_body += "</ul>"

            action_items = summary.get('action_items', [])
            if action_items:
                html_body += "<h3 style='color: #34495e;'>Action Items</h3><ul>"
                for item in action_items:
                    html_body += f"<li>{item}</li>"
                html_body += "</ul>"

        html_body += """
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;">
            <p style="font-size: 12px; color: #666;">
                This summary was generated by Meeting Intelligence Agent
            </p>
        </body>
        </html>
        """

        return subject, body, html_body

    def _check_service_health(self) -> Dict[str, Any]:
        """Check service-specific health."""
        return {
            "api_key_configured": bool(self.api_key),
            "from_email_configured": bool(self.from_email),
            "from_name": self.from_name,
            "api_url": self.api_url,
            "api_version": self.api_version
        }