"""
Integrated Email Workflow Service
Connects AI summarization, email template generation, and database persistence
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from jinja2 import Template
# Note: AISummarizer is no longer used - replaced by direct Gemini integration in summarizer tool
# from src.services.database_service import get_database_service  # TODO: Replace with new service structure
from src.tools.langchain_email_notification_tool import LangchainEmailNotificationTool
from src.auth.google_auth_handler import GoogleAuthHandler
from src.services.integration.platform_webhook_service import get_platform_webhook_service

logger = logging.getLogger(__name__)


class IntegratedEmailWorkflowService:
    """
    Integrated service that handles the complete workflow:
    1. Process meeting transcript with AI summarization
    2. Generate dynamic HTML email using template
    3. Store all data in database
    4. Optionally send emails
    """

    def __init__(self, user_id: str, org_id: str, agent_task_id: str):
        self.user_id = user_id
        self.org_id = org_id
        self.agent_task_id = agent_task_id

        # Initialize services
        self.db_service = get_database_service()
        self.ai_summarizer = AISummarizer()

        # Initialize email tool
        try:
            auth = GoogleAuthHandler(user_id, org_id, agent_task_id)
            self.email_tool = LangchainEmailNotificationTool(auth=auth, user_id=user_id)
        except Exception as e:
            logger.warning(f"Could not initialize email tool: {e}")
            self.email_tool = None

        # Load email template
        self.email_template = self._load_email_template()

        logger.info(f"Initialized IntegratedEmailWorkflowService for {user_id}/{org_id}/{agent_task_id}")

    def _load_email_template(self) -> str:
        """Load the HTML email template"""
        try:
            # Try dynamic template first, then fallback to static template
            template_paths = [
                Path("client/meeting_agent_email.html")
            ]

            for template_path in template_paths:
                if template_path.exists():
                    logger.info(f"Loading email template from {template_path}")
                    return template_path.read_text(encoding='utf-8')

            logger.error("No email template found")
            return self._get_fallback_template()
        except Exception as e:
            logger.error(f"Failed to load email template: {e}")
            return self._get_fallback_template()

    def _get_fallback_template(self) -> str:
        """Fallback email template if main template is not available"""
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Meeting Summary</title></head>
        <body>
            <h1>{{ meeting_title }}</h1>
            <h2>Executive Summary</h2>
            <p>{{ executive_summary }}</p>

            <h2>Key Decisions</h2>
            <ul>
            {% for decision in decisions %}
                <li><strong>{{ decision.decision }}</strong> - {{ decision.context }}</li>
            {% endfor %}
            </ul>

            <h2>Action Items</h2>
            <ul>
            {% for task in tasks %}
                <li><strong>{{ task.title }}</strong> ({{ task.assignee_name }}) - Due: {{ task.end_date or 'TBD' }}</li>
            {% endfor %}
            </ul>
        </body>
        </html>
        """

    async def process_meeting_transcript(self, transcript_content: str, meeting_title: str = None,
                                       meeting_date: datetime = None, attendees: List[str] = None,
                                       save_email_locally: bool = True, send_email: bool = False,
                                       recipient_scope: str = "all_participants",
                                       send_webhook: bool = False) -> Dict[str, Any]:
        """
        Complete workflow: transcript → AI summary → email generation → database storage → webhook

        Args:
            transcript_content: Raw meeting transcript text
            meeting_title: Title of the meeting
            meeting_date: Date/time of the meeting
            attendees: List of attendee email addresses
            save_email_locally: Whether to save generated email to local file
            send_email: Whether to actually send the email
            recipient_scope: Who to send to ('all_participants' or 'only_me')
            send_webhook: Whether to send tasks to platform via webhook

        Returns:
            Dict with workflow results and IDs
        """
        workflow_start_time = datetime.now()

        try:
            # Step 1: Store transcript in database
            logger.info("Step 1: Storing meeting transcript in database")
            transcript_id = self.db_service.store_meeting_transcript(
                user_id=self.user_id,
                org_id=self.org_id,
                agent_task_id=self.agent_task_id,
                meeting_title=meeting_title or "Meeting Summary",
                transcript_content=transcript_content,
                meeting_date=meeting_date or datetime.now(),
                attendees=attendees or [],
                duration_minutes=self._estimate_duration_from_transcript(transcript_content)
            )

            # Step 2: Generate AI summary
            logger.info("Step 2: Generating AI summary")
            transcript_data = TranscriptData(
                file_path=Path("transcript.txt"),  # Virtual path
                content=transcript_content,
                metadata={
                    "attendees": attendees or [],
                    "meeting_title": meeting_title or "Meeting Summary",
                    "meeting_date": meeting_date or datetime.now()
                }
            )

            ai_start_time = datetime.now()
            meeting_summary = self.ai_summarizer.summarize_transcript(transcript_data)
            ai_processing_time = int((datetime.now() - ai_start_time).total_seconds() * 1000)

            # Step 3: Store AI summary in database
            logger.info("Step 3: Storing AI summary in database")
            summary_json = json.dumps(meeting_summary.meeting_data.__dict__, default=str, indent=2)
            summary_id = self.db_service.store_ai_summary(
                transcript_id=transcript_id,
                user_id=self.user_id,
                org_id=self.org_id,
                agent_task_id=self.agent_task_id,
                executive_summary=meeting_summary.meeting_data.executive_summary,
                summary_json=summary_json,
                html_summary=meeting_summary.html_summary,
                ai_model_used="gemini-2.5-flash-lite",
                processing_time_ms=ai_processing_time
            )

            # Step 4: Generate dynamic email content
            logger.info("Step 4: Generating dynamic email content")
            email_content = self._generate_dynamic_email(
                meeting_summary=meeting_summary,
                meeting_title=meeting_title or "Meeting Summary",
                meeting_date=meeting_date or datetime.now(),
                attendees=attendees or []
            )

            # Step 5: Store email workflow in database
            logger.info("Step 5: Storing email workflow in database")
            email_subject = f"Meeting Summary: {meeting_title or 'Weekly Review'}"
            workflow_id = self.db_service.store_email_workflow(
                summary_id=summary_id,
                user_id=self.user_id,
                org_id=self.org_id,
                agent_task_id=self.agent_task_id,
                email_subject=email_subject,
                email_html_content=email_content['html'],
                email_plain_content=email_content['plain'],
                recipient_scope=recipient_scope,
                recipients=attendees,
                template_used="client/meeting_agent_email.html"
            )

            # Step 6: Save email locally if requested
            if save_email_locally:
                self._save_email_locally(email_content, workflow_id, meeting_title)

            # Step 7: Send email if requested
            email_sent = False
            email_results = None
            if send_email and self.email_tool:
                logger.info("Step 7: Sending email")
                try:
                    # Prepare summary data for email tool
                    summary_data = {
                        "meeting_metadata": {
                            "title": meeting_title or "Meeting Summary",
                            "attendees": attendees or []
                        },
                        "executive_summary": meeting_summary.meeting_data.executive_summary,
                        "tasks": getattr(meeting_summary.meeting_data, 'tasks', []),
                        "decisions": getattr(meeting_summary.meeting_data, 'decisions', []),
                        "unresolved_questions": getattr(meeting_summary.meeting_data, 'unresolved_questions', []),
                        "follow_up_needs": getattr(meeting_summary.meeting_data, 'follow_up_needs', [])
                    }

                    # Use sync version for now (email tool needs async refactoring)
                    email_result = self.email_tool._run(
                        summary_data=json.dumps(summary_data),
                        recipient_scope=recipient_scope
                    )
                    email_results = json.loads(email_result)
                    email_sent = email_results.get('status') == 'completed'

                    # Update database with send status
                    self.db_service.update_email_workflow_status(
                        workflow_id=workflow_id,
                        send_status='sent' if email_sent else 'failed',
                        delivery_results=email_results,
                        error_message=email_results.get('error') if not email_sent else None
                    )

                except Exception as e:
                    logger.error(f"Failed to send email: {e}")
                    self.db_service.update_email_workflow_status(
                        workflow_id=workflow_id,
                        send_status='failed',
                        error_message=str(e)
                    )

            # Calculate total processing time
            total_processing_time = int((datetime.now() - workflow_start_time).total_seconds() * 1000)

            # Step 7: Send webhook to platform (if enabled)
            webhook_result = None
            if send_webhook:
                try:
                    logger.info("Step 7: Sending tasks to platform via webhook")
                    webhook_service = get_platform_webhook_service(
                        user_id=self.user_id,
                        org_id=self.org_id,
                        agent_task_id=self.agent_task_id
                    )

                    # Prepare AI summary data for webhook
                    ai_summary_data = {
                        "meeting_metadata": {
                            "title": meeting_title or "Meeting Summary",
                            "id": f"M-{datetime.now().strftime('%Y-%m-%d')}-{transcript_id[:8]}",
                            "event_name": meeting_title or "Meeting Summary",
                            "video_url": "",
                            "transcript_url": ""
                        },
                        "tasks": meeting_summary.meeting_data.tasks if hasattr(meeting_summary, 'meeting_data') else [],
                        "decisions": meeting_summary.meeting_data.decisions if hasattr(meeting_summary, 'meeting_data') else [],
                        "executive_summary": meeting_summary.meeting_data.executive_summary if hasattr(meeting_summary, 'meeting_data') else ""
                    }

                    webhook_result = await webhook_service.send_tasks_to_platform(
                        ai_summary_data=ai_summary_data,
                        meeting_metadata={
                            "attendees": attendees or [],
                            "meeting_date": meeting_date or datetime.now()
                        }
                    )
                    logger.info(f"Webhook result: {webhook_result.get('status', 'unknown')}")

                except Exception as webhook_error:
                    logger.error(f"Webhook sending failed: {webhook_error}")
                    webhook_result = {
                        "status": "error",
                        "error": str(webhook_error),
                        "timestamp": datetime.now().isoformat()
                    }

            # Return comprehensive results
            return {
                "status": "success",
                "workflow_id": workflow_id,
                "transcript_id": transcript_id,
                "summary_id": summary_id,
                "meeting_title": meeting_title,
                "processing_time_ms": total_processing_time,
                "ai_processing_time_ms": ai_processing_time,
                "email_generated": True,
                "email_sent": email_sent,
                "email_results": email_results,
                "summary_data": {
                    "executive_summary": meeting_summary.meeting_data.executive_summary,
                    "tasks_count": len(getattr(meeting_summary.meeting_data, 'tasks', [])),
                    "decisions_count": len(getattr(meeting_summary.meeting_data, 'decisions', [])),
                    "questions_count": len(getattr(meeting_summary.meeting_data, 'unresolved_questions', []))
                },
                "database_stored": True,
                "webhook_sent": send_webhook,
                "webhook_result": webhook_result,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Workflow failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def _generate_dynamic_email(self, meeting_summary, meeting_title: str,
                              meeting_date: datetime, attendees: List[str]) -> Dict[str, str]:
        """Generate dynamic email content using Jinja2 template"""
        try:
            # Prepare template data
            template_data = {
                "meeting_title": meeting_title,
                "meeting_date": meeting_date.strftime("%B %d, %Y"),
                "executive_summary": meeting_summary.meeting_data.executive_summary,
                "decisions": getattr(meeting_summary.meeting_data, 'decisions', []),
                "tasks": getattr(meeting_summary.meeting_data, 'tasks', []),
                "unresolved_questions": getattr(meeting_summary.meeting_data, 'unresolved_questions', []),
                "follow_up_needs": getattr(meeting_summary.meeting_data, 'follow_up_needs', []),
                "attendees": attendees,
                "year": datetime.now().year
            }

            # Render HTML template
            template = Template(self.email_template)
            html_content = template.render(**template_data)

            # Generate plain text version
            plain_content = self._html_to_plain_text(template_data)

            return {
                "html": html_content,
                "plain": plain_content
            }

        except Exception as e:
            logger.error(f"Failed to generate email content: {e}")
            raise

    def _html_to_plain_text(self, template_data: Dict[str, Any]) -> str:
        """Convert template data to plain text email"""
        lines = [
            f"Meeting Summary: {template_data['meeting_title']}",
            f"Date: {template_data['meeting_date']}",
            "",
            "EXECUTIVE SUMMARY",
            "=" * 50,
            template_data['executive_summary'],
            "",
        ]

        if template_data.get('decisions'):
            lines.extend([
                "KEY DECISIONS",
                "=" * 50,
            ])
            for i, decision in enumerate(template_data['decisions'], 1):
                lines.append(f"{i}. {decision.get('decision', 'N/A')}")
                if decision.get('context'):
                    lines.append(f"   Context: {decision['context']}")
            lines.append("")

        if template_data.get('tasks'):
            lines.extend([
                "ACTION ITEMS",
                "=" * 50,
            ])
            for task in template_data['tasks']:
                assignee = task.get('assignee_name', 'Unassigned')
                due_date = task.get('end_date', 'TBD')
                lines.append(f"• {task.get('title', 'N/A')} ({assignee}) - Due: {due_date}")
            lines.append("")

        return "\n".join(lines)

    def _estimate_duration_from_transcript(self, transcript_content: str) -> int:
        """Estimate meeting duration from transcript timestamps"""
        try:
            import re
            timestamps = re.findall(r'\[(\d{2}):(\d{2}):(\d{2})\]', transcript_content)
            if timestamps:
                last_timestamp = timestamps[-1]
                minutes = int(last_timestamp[1]) + (int(last_timestamp[0]) * 60)
                return minutes
            return 0
        except:
            return 0

    def _save_email_locally(self, email_content: Dict[str, str], workflow_id: str, meeting_title: str):
        """Save generated email to local files"""
        try:
            # Create output directory
            output_dir = Path("generated_emails")
            output_dir.mkdir(exist_ok=True)

            # Save HTML version
            html_file = output_dir / f"{workflow_id}_email.html"
            html_file.write_text(email_content['html'], encoding='utf-8')

            # Save plain text version
            txt_file = output_dir / f"{workflow_id}_email.txt"
            txt_file.write_text(email_content['plain'], encoding='utf-8')

            logger.info(f"Saved email files: {html_file} and {txt_file}")

        except Exception as e:
            logger.error(f"Failed to save email locally: {e}")


def get_integrated_workflow_service(user_id: str, org_id: str, agent_task_id: str) -> IntegratedEmailWorkflowService:
    """Factory function to get workflow service instance"""
    return IntegratedEmailWorkflowService(user_id, org_id, agent_task_id)