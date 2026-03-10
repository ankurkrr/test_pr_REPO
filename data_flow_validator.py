#!/usr/bin/env python3
"""
Data Flow Validator Service
Ensures seamless data connectivity between workflow tools
"""

import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class DataFlowValidator:
    """Validates and transforms data between workflow steps."""

    def __init__(self):
        self.validation_history = []

    def validate_calendar_to_drive_flow(self, calendar_output: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Validate calendar tool output for drive tool input.

        Args:
            calendar_output: Output from CalendarTool

        Returns:
            Tuple of (is_valid, processed_events, error_message)
        """
        try:
            # Check required fields from calendar output
            if not isinstance(calendar_output, dict):
                return False, [], "Calendar output must be a dictionary"

            if calendar_output.get("status") != "success":
                return False, [], f"Calendar tool failed: {calendar_output.get('error', 'Unknown error')}"

            events = calendar_output.get("events", [])
            if not isinstance(events, list):
                return False, [], "Events must be a list"

            # Validate each event has required fields for drive tool
            processed_events = []
            for i, event in enumerate(events):
                if not isinstance(event, dict):
                    logger.warning(f"Event {i} is not a dictionary, skipping")
                    continue

                # Ensure required fields exist
                required_fields = ["event_id", "title", "start_time", "end_time"]
                missing_fields = [field for field in required_fields if not event.get(field)]

                if missing_fields:
                    logger.warning(f"Event {i} missing fields: {missing_fields}, adding defaults")

                # Create standardized event object for drive tool
                standardized_event = {
                    "event_id": event.get("event_id", f"unknown_event_{i}"),
                    "title": event.get("title", "Unknown Meeting"),
                    "start_time": event.get("start_time", ""),
                    "end_time": event.get("end_time", ""),
                    "attendees": event.get("attendees", []),
                    "description": event.get("description", ""),
                    "location": event.get("location", ""),
                    "organizer": event.get("organizer", {}),
                    "creator": event.get("creator", {}),
                    # Add metadata for drive tool processing
                    "drive_search_metadata": {
                        "search_terms": [
                            event.get("title", "").lower(),
                            event.get("event_id", ""),
                        ],
                        "date_range": {
                            "start": event.get("start_time", ""),
                            "end": event.get("end_time", "")
                        }
                    }
                }

                processed_events.append(standardized_event)

            logger.info(f" Calendar→Drive validation: {len(processed_events)} events processed")
            return True, processed_events, ""

        except Exception as e:
            error_msg = f"Calendar→Drive validation failed: {str(e)}"
            logger.error(error_msg)
            return False, [], error_msg

    def validate_drive_to_summarizer_flow(self, processed_events: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Validate drive tool output for summarizer tool input.

        Args:
            processed_events: Events with transcripts from DriveTool

        Returns:
            Tuple of (is_valid, summarizer_ready_data, error_message)
        """
        try:
            if not isinstance(processed_events, list):
                return False, [], "Processed events must be a list"

            summarizer_ready_data = []

            for event_data in processed_events:
                if not isinstance(event_data, dict):
                    continue

                event = event_data.get("event", {})
                transcripts = event_data.get("transcripts", [])

                if not transcripts:
                    logger.info(f"No transcripts for event: {event.get('title', 'Unknown')}")
                    continue

                # Create summarizer input for each transcript
                for transcript in transcripts:
                    if not transcript.get("content"):
                        logger.warning(f"Transcript missing content: {transcript.get('file_name', 'Unknown')}")
                        continue

                    summarizer_input = {
                        # Event context
                        "event_id": event.get("event_id"),
                        "event_title": event.get("title", "Unknown Meeting"),
                        "event_start_time": event.get("start_time"),
                        "event_end_time": event.get("end_time"),
                        "attendees": event.get("attendees", []),
                        "organizer": event.get("organizer", {}),
                        "description": event.get("description", ""),
                        "location": event.get("location", ""),

                        # Transcript data
                        "transcript_file_id": transcript.get("file_id"),
                        "transcript_file_name": transcript.get("file_name"),
                        "transcript_content": transcript.get("content"),
                        "transcript_metadata": transcript.get("metadata", {}),

                        # Validation metadata
                        "event_context": transcript.get("event_context", {}),
                        "strict_match": transcript.get("event_context", {}).get("strict_match", False),

                        # Processing instructions for summarizer
                        "summarization_context": {
                            "meeting_type": self._infer_meeting_type(event.get("title", "")),
                            "attendee_count": len(event.get("attendees", [])),
                            "duration_minutes": self._calculate_duration(
                                event.get("start_time"),
                                event.get("end_time")
                            ),
                            "priority_level": self._infer_priority(event, transcript)
                        }
                    }

                    summarizer_ready_data.append(summarizer_input)

            logger.info(f" Drive→Summarizer validation: {len(summarizer_ready_data)} transcript-event pairs ready")
            return True, summarizer_ready_data, ""

        except Exception as e:
            error_msg = f"Drive→Summarizer validation failed: {str(e)}"
            logger.error(error_msg)
            return False, [], error_msg

    def validate_summarizer_to_dedup_flow(self, summaries: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Validate summarizer output for dedup tool input.

        Args:
            summaries: Generated summaries from SummarizerTool

        Returns:
            Tuple of (is_valid, dedup_ready_summaries, error_message)
        """
        try:
            if not isinstance(summaries, list):
                return False, [], "Summaries must be a list"

            dedup_ready_summaries = []

            for summary in summaries:
                if not isinstance(summary, dict):
                    continue

                # Ensure required fields for dedup tool
                dedup_summary = {
                    "event_id": summary.get("event_id"),
                    "event_title": summary.get("event_title", "Unknown Meeting"),
                    "transcript_file_id": summary.get("transcript_file_id"),
                    "transcript_file_name": summary.get("transcript_file_name"),
                    "summary_content": summary.get("summary_content", ""),
                    "generated_at": summary.get("generated_at", datetime.now().isoformat()),

                    # Meeting metadata for task extraction
                    "meeting_metadata": summary.get("meeting_metadata", {}),

                    # Enhanced data for dedup processing
                    "dedup_context": {
                        "meeting_title": summary.get("event_title", ""),
                        "meeting_date": summary.get("meeting_metadata", {}).get("start_time", ""),
                        "attendees": summary.get("meeting_metadata", {}).get("attendees", []),
                        "summary_length": len(summary.get("summary_content", "")),
                        "processing_timestamp": datetime.now().isoformat()
                    }
                }

                # Validate summary content exists
                if not dedup_summary["summary_content"]:
                    logger.warning(f"Empty summary content for event: {dedup_summary['event_title']}")
                    continue

                dedup_ready_summaries.append(dedup_summary)

            logger.info(f" Summarizer→Dedup validation: {len(dedup_ready_summaries)} summaries ready")
            return True, dedup_ready_summaries, ""

        except Exception as e:
            error_msg = f"Summarizer→Dedup validation failed: {str(e)}"
            logger.error(error_msg)
            return False, [], error_msg

    def validate_summarizer_to_email_flow(self, summaries: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Validate summarizer output for email tool input.

        Args:
            summaries: Generated summaries from SummarizerTool

        Returns:
            Tuple of (is_valid, email_ready_summaries, error_message)
        """
        try:
            if not isinstance(summaries, list):
                return False, [], "Summaries must be a list"

            email_ready_summaries = []

            for summary in summaries:
                if not isinstance(summary, dict):
                    continue

                # Ensure required fields for email tool
                email_summary = {
                    "event_id": summary.get("event_id"),
                    "event_title": summary.get("event_title", "Unknown Meeting"),
                    "transcript_file_id": summary.get("transcript_file_id"),
                    "transcript_file_name": summary.get("transcript_file_name"),
                    "summary_content": summary.get("summary_content", ""),
                    "generated_at": summary.get("generated_at", datetime.now().isoformat()),
                    "meeting_metadata": summary.get("meeting_metadata", {}),

                    # Enhanced data for email formatting
                    "email_context": {
                        "recipient_list": self._extract_email_recipients(summary.get("meeting_metadata", {})),
                        "meeting_title": summary.get("event_title", ""),
                        "meeting_date": summary.get("meeting_metadata", {}).get("start_time", ""),
                        "meeting_duration": self._calculate_duration(
                            summary.get("meeting_metadata", {}).get("start_time"),
                            summary.get("meeting_metadata", {}).get("end_time")
                        ),
                        "attendee_names": self._extract_attendee_names(summary.get("meeting_metadata", {})),
                        "summary_preview": summary.get("summary_content", "")[:200] + "..." if len(summary.get("summary_content", "")) > 200 else summary.get("summary_content", "")
                    }
                }

                # Validate summary content and recipients exist
                if not email_summary["summary_content"]:
                    logger.warning(f"Empty summary content for email: {email_summary['event_title']}")
                    continue

                if not email_summary["email_context"]["recipient_list"]:
                    logger.warning(f"No email recipients found for: {email_summary['event_title']}")
                    continue

                email_ready_summaries.append(email_summary)

            logger.info(f" Summarizer→Email validation: {len(email_ready_summaries)} summaries ready")
            return True, email_ready_summaries, ""

        except Exception as e:
            error_msg = f"Summarizer→Email validation failed: {str(e)}"
            logger.error(error_msg)
            return False, [], error_msg

    def _infer_meeting_type(self, title: str) -> str:
        """Infer meeting type from title."""
        title_lower = title.lower()
        if any(word in title_lower for word in ["standup", "daily", "scrum"]):
            return "standup"
        elif any(word in title_lower for word in ["review", "retrospective", "retro"]):
            return "review"
        elif any(word in title_lower for word in ["planning", "plan", "roadmap"]):
            return "planning"
        elif any(word in title_lower for word in ["1:1", "one-on-one", "1-on-1"]):
            return "one_on_one"
        else:
            return "general"

    def _calculate_duration(self, start_time: str, end_time: str) -> int:
        """Calculate meeting duration in minutes."""
        try:
            if not start_time or not end_time:
                return 60  # Default 1 hour
            # This is a simplified calculation - you might want to use proper datetime parsing
            return 60  # Default for now
        except:
            return 60

    def _infer_priority(self, event: Dict[str, Any], transcript: Dict[str, Any]) -> str:
        """Infer priority level from event and transcript data."""
        # Simple heuristics - can be enhanced
        attendee_count = len(event.get("attendees", []))
        if attendee_count > 10:
            return "high"
        elif attendee_count > 5:
            return "medium"
        else:
            return "low"

    def _extract_email_recipients(self, meeting_metadata: Dict[str, Any]) -> List[str]:
        """Extract email addresses from meeting metadata."""
        recipients = []
        attendees = meeting_metadata.get("attendees", [])

        for attendee in attendees:
            if isinstance(attendee, dict):
                email = attendee.get("email")
                if email:
                    recipients.append(email)
            elif isinstance(attendee, str) and "@" in attendee:
                recipients.append(attendee)

        return list(set(recipients))  # Remove duplicates

    def _extract_attendee_names(self, meeting_metadata: Dict[str, Any]) -> List[str]:
        """Extract attendee names from meeting metadata."""
        names = []
        attendees = meeting_metadata.get("attendees", [])

        for attendee in attendees:
            if isinstance(attendee, dict):
                name = attendee.get("name") or attendee.get("displayName") or attendee.get("email", "").split("@")[0]
                if name:
                    names.append(name)
            elif isinstance(attendee, str):
                names.append(attendee.split("@")[0] if "@" in attendee else attendee)

        return names

    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of all validations performed."""
        return {
            "total_validations": len(self.validation_history),
            "validation_history": self.validation_history[-10:],  # Last 10 validations
            "timestamp": datetime.now().isoformat()
        }