"""
Google Sheets Service for Meeting Intelligence Workflow
"""

import logging
import os
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from googleapiclient.errors import HttpError
# from ...configuration.config import get_config_service

logger = logging.getLogger(__name__)

class SimpleConfigService:
    """Simple config service for storing sheet IDs"""
    def __init__(self, config_file: str = "agent_config.json"):
        self.config_file = config_file
        self.meeting_sheet_id = None
    
    def set_meeting_sheet_id(self, sheet_id: str) -> bool:
        """Set the meeting sheet ID"""
        self.meeting_sheet_id = sheet_id
        return True
    
    def get_meeting_sheet_id(self) -> str:
        """Get the meeting sheet ID"""
        return self.meeting_sheet_id

def get_config_service(config_file: str = "agent_config.json") -> SimpleConfigService:
    """Get a simple config service instance"""
    return SimpleConfigService(config_file)


class GoogleSheetsService:
    """
    Google Sheets service for managing meeting tasks and other data.
    """

    def __init__(self, auth, config_file: str = "agent_config.json"):
        """
        Initialize Sheets service.

        Args:
            auth: GoogleAuthenticator instance
            config_file: Path to configuration file for persistent storage
        """
        self.auth = auth
        self.service = None
        self.meeting_tasks_sheet_id = None
        self.config_service = get_config_service(config_file)

        # Initialize the service
        self._get_service()

        # Try to load existing meeting tasks sheet ID (do not auto-create here)
        self._ensure_meeting_tasks_sheet()

    def _get_service(self):
        """Get Google Sheets service."""
        if not self.service:
            self.service = self.auth.get_sheets_service()
        return self.service

    def _ensure_meeting_tasks_sheet(self):
        """Ensure meeting tasks sheet ID is loaded if it exists; do not create automatically."""
        try:
            # Check if sheet ID is already stored persistently
            self.meeting_tasks_sheet_id = getattr(
                self.config_service, "meeting_sheet_id", None
            )

            # Also check environment variable for backward compatibility
            if not self.meeting_tasks_sheet_id:
                self.meeting_tasks_sheet_id = os.getenv(
                    "GOOGLE_SHEETS_MEETING_TASKS_ID"
                )
                # If found in environment, migrate to persistent storage
                if self.meeting_tasks_sheet_id:
                    self.config_service.set_meeting_sheet_id(
                        self.meeting_tasks_sheet_id
                    )
                    logger.info(
                        "Migrated sheet ID from environment to persistent storage: %s",
                        self.meeting_tasks_sheet_id,
                    )

            if self.meeting_tasks_sheet_id:
                # Verify the sheet exists
                if self._verify_sheet_exists(self.meeting_tasks_sheet_id):
                    logger.info(
                        "Using existing meeting tasks sheet: %s",
                        self.meeting_tasks_sheet_id,
                    )
                    return
                logger.warning(
                    "Stored sheet ID %s not found, creating new sheet",
                    self.meeting_tasks_sheet_id,
                )
                self.meeting_tasks_sheet_id = None

            # Do not auto-create here; leave as None and let callers decide creation strategy
            logger.info("No existing meeting tasks sheet ID found; will create on demand")

        except HttpError as e:
            logger.error("HTTP error ensuring meeting tasks sheet: %s", e)
            self.meeting_tasks_sheet_id = None
        except OSError as e:
            logger.error("OS error ensuring meeting tasks sheet: %s", e)
            self.meeting_tasks_sheet_id = None

    def _verify_sheet_exists(self, sheet_id: str) -> bool:
        """Verify that a sheet exists and is accessible."""
        try:
            service = self._get_service()
            if not service:
                return False

            # Try to get sheet metadata
            result = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            return result is not None

        except HttpError as e:
            if e.resp.status == 404:
                return False
            logger.error("Error verifying sheet existence: %s", e)
            return False
        except KeyError as e:
            logger.error("Key error verifying sheet existence: %s", e)
            return False
        except ValueError as e:
            logger.error("Value error verifying sheet existence: %s", e)
            return False

    def _create_meeting_tasks_sheet(self) -> Optional[str]:
        """Create a new Google Sheet for meeting tasks."""
        try:
            service = self._get_service()
            if not service:
                logger.error("Sheets service not available")
                return None

            # Create spreadsheet with proper structure
            spreadsheet = {
                "properties": {
                    "title": "Meeting Tasks - %s" % datetime.now().strftime("%Y-%m-%d")
                },
                "sheets": [
                    {
                        "properties": {
                            "title": "Meeting Tasks",
                            "gridProperties": {"rowCount": 1000, "columnCount": 12},
                        }
                    }
                ],
            }

            result = service.spreadsheets().create(body=spreadsheet).execute()
            sheet_id = result.get("spreadsheetId")

            if sheet_id:
                # Set up the sheet structure
                self._setup_sheet_structure(sheet_id)
                return sheet_id

            return None

        except HttpError as e:
            logger.error("HTTP error creating meeting tasks sheet: %s", e)
            return None
        except OSError as e:
            logger.error("OS error creating meeting tasks sheet: %s", e)
            return None

    def _create_meeting_tasks_sheet_with_title(self, sheet_title: str) -> Optional[str]:
        """Create a new Google Sheet with a specific title and standard structure."""
        try:
            service = self._get_service()
            if not service:
                logger.error("Sheets service not available")
                return None

            spreadsheet = {
                "properties": {
                    "title": sheet_title
                },
                "sheets": [
                    {
                        "properties": {
                            "title": "Meeting Tasks",
                            "gridProperties": {"rowCount": 1000, "columnCount": 12},
                        }
                    }
                ],
            }

            result = service.spreadsheets().create(body=spreadsheet).execute()
            sheet_id = result.get("spreadsheetId")

            if sheet_id:
                self._setup_sheet_structure(sheet_id)
                return sheet_id

            return None

        except HttpError as e:
            logger.error("HTTP error creating titled meeting tasks sheet: %s", e)
            return None
        except OSError as e:
            logger.error("OS error creating titled meeting tasks sheet: %s", e)
            return None

    def find_or_create_meeting_tasks_sheet(self, sheet_title: str, parent_folder_id: Optional[str] = None) -> Optional[str]:
        """Find existing spreadsheet by title (and optional parent) or create a new one.

        If created and a parent folder is specified, move the spreadsheet into that folder.
        """
        try:
            # Use Drive API to search for spreadsheets by name
            drive_service = self.auth.get_drive_service()
            if not drive_service:
                logger.error("Drive service not available for sheet discovery")
                return None

            query = f"name='{sheet_title}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
            if parent_folder_id:
                query += f" and '{parent_folder_id}' in parents"

            results = drive_service.files().list(q=query, fields="files(id,name,parents)").execute()
            files = results.get("files", [])

            if files:
                sheet_id = files[0]["id"]
                logger.info("Found existing spreadsheet: %s", sheet_title)
                # Persist for future use
                self._store_sheet_id(sheet_id)
                self.meeting_tasks_sheet_id = sheet_id
                return sheet_id

            # Not found: create
            sheet_id = self._create_meeting_tasks_sheet_with_title(sheet_title)
            if not sheet_id:
                return None

            # If parent_folder_id provided, move the sheet file into that folder
            if parent_folder_id:
                try:
                    # Get current parents, then move
                    file_meta = drive_service.files().get(fileId=sheet_id, fields="parents").execute()
                    previous_parents = ",".join(file_meta.get("parents", []))
                    drive_service.files().update(
                        fileId=sheet_id,
                        addParents=parent_folder_id,
                        removeParents=previous_parents,
                        fields="id, parents",
                    ).execute()
                    logger.info("Moved spreadsheet %s under parent folder %s", sheet_id, parent_folder_id)
                except Exception as move_err:
                    logger.warning("Failed to move spreadsheet %s to parent %s: %s", sheet_id, parent_folder_id, move_err)

            # Persist for future use
            self._store_sheet_id(sheet_id)
            self.meeting_tasks_sheet_id = sheet_id
            logger.info("Created new spreadsheet: %s", sheet_title)
            return sheet_id

        except Exception as e:
            logger.error("Error in find-or-create for spreadsheet '%s': %s", sheet_title, e, exc_info=True)
            return None

    def _setup_sheet_structure(self, sheet_id: str) -> bool:
        """Set up the initial structure of the meeting tasks sheet."""
        try:
            service = self._get_service()
            if not service:
                return False

            # Define headers (removed Task Hash, Similarity Score, Matched Text)
            headers = [
                "Task ID",
                "Task Text",
                "Meeting Title",
                "Assignees",
                "Priority Level",
                "Due Date",
                "Status",
                "Created Date",
            ]

            # Add headers to the sheet
            body = {"values": [headers]}

            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range="A1:H1", valueInputOption="RAW", body=body
            ).execute()

            # Get sheet info to find the correct sheet ID
            sheet_metadata = self.service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            sheets = sheet_metadata.get('sheets', [])
            if not sheets:
                logger.error(f"No sheets found in spreadsheet {sheet_id}")
                return False
            
            # Use the first sheet's ID
            first_sheet_id = sheets[0]['properties']['sheetId']
            logger.info(f"Using sheet ID: {first_sheet_id} for spreadsheet {sheet_id}")
            
            # Format headers (bold)
            requests = [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": first_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 8,
                        },
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            ]

            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id, body={"requests": requests}
            ).execute()

            logger.info("Meeting tasks sheet structure set up successfully")
            return True

        except HttpError as e:
            logger.error("HTTP error setting up sheet structure: %s", e)
            return False
        except OSError as e:
            logger.error("OS error setting up sheet structure: %s", e)
            return False

    def _store_sheet_id(self, sheet_id: str):
        """Store the sheet ID persistently for future use."""
        try:
            # Store in persistent configuration
            success = self.config_service.set_meeting_sheet_id(sheet_id)

            if success:
                # Also store in environment variable for backward compatibility
                os.environ["GOOGLE_SHEETS_MEETING_TASKS_ID"] = sheet_id
                logger.info("Stored meeting tasks sheet ID persistently: %s", sheet_id)
            else:
                logger.error("Failed to store sheet ID persistently: %s", sheet_id)

        except (HttpError, OSError) as e:
            logger.error("Error storing sheet ID: %s", e)

    def get_meeting_tasks_sheet_id(self) -> Optional[str]:
        """Get the meeting tasks sheet ID."""
        return self.meeting_tasks_sheet_id

    def append_task(self, task_data: Dict[str, Any]) -> bool:
        """Append a task to the meeting tasks sheet."""
        try:
            if not self.meeting_tasks_sheet_id:
                logger.error("No meeting tasks sheet ID available")
                return False

            service = self._get_service()
            if not service:
                logger.error("Sheets service not available")
                return False

            # Prepare row data (aligned with updated headers)
            row_data = [
                task_data.get("task_id", ""),
                task_data.get("task_text", ""),
                task_data.get("meeting_title", ""),
                ", ".join(task_data.get("assignees", [])),
                task_data.get("priority_level", "medium"),
                task_data.get("due_date", ""),
                task_data.get("status", "pending"),
                task_data.get("created_date", datetime.now().isoformat()),
            ]

            # Append to sheet
            body = {"values": [row_data]}

            service.spreadsheets().values().append(
                spreadsheetId=self.meeting_tasks_sheet_id,
                range="A:Z",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()

            logger.info(
                "Task appended to sheet: %s", task_data.get("task_text", "")[:50]
            )
            return True

        except (HttpError, OSError, ValueError, KeyError) as e:
            logger.error("Error appending task to sheet: %s", e)
            return False

    def get_existing_task_hashes(self) -> Set[str]:
        """Get existing task hashes from the sheet."""
        try:
            if not self.meeting_tasks_sheet_id:
                return set()

            service = self._get_service()
            if not service:
                return set()

            # Get all existing task texts (column B after header change)
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=self.meeting_tasks_sheet_id, range="B:B")
                .execute()
            )

            values = result.get("values", [])
            hashes = set()

            # Skip header row
            for row in values[1:]:
                if row and row[0]:
                    hashes.add(row[0])

            return hashes

        except (HttpError, OSError, ValueError, KeyError) as e:
            logger.error("Error getting existing task hashes: %s", e)
            return set()

    def find_similar_tasks(self) -> List[Dict[str, Any]]:
        """Find similar tasks in the sheet."""
        try:
            if not self.meeting_tasks_sheet_id:
                return []

            service = self._get_service()
            if not service:
                return []

            # Get all tasks (columns A through H after header change)
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=self.meeting_tasks_sheet_id, range="A:H")
                .execute()
            )

            values = result.get("values", [])
            if len(values) <= 1:  # Only headers or empty
                return []

            # Skip header row
            tasks = []
            for row in values[1:]:
                if len(row) >= 2:  # At least task_id and text
                    task = {
                        "task_id": row[0] if len(row) > 0 else "",
                        "task_text": row[1] if len(row) > 1 else "",
                        "meeting_title": row[2] if len(row) > 2 else "",
                        "assignees": (
                            row[3].split(", ") if len(row) > 3 and row[3] else []
                        ),
                        "priority_level": row[4] if len(row) > 4 else "",
                        "due_date": row[5] if len(row) > 5 else "",
                        "status": row[6] if len(row) > 6 else "",
                        "created_date": row[7] if len(row) > 7 else "",
                    }
                    tasks.append(task)

            return tasks

        except (HttpError, OSError, ValueError, KeyError) as e:
            logger.error("Error finding similar tasks: %s", e)
            return []

    def get_sheet_url(self) -> Optional[str]:
        """Get the URL of the meeting tasks sheet."""
        if self.meeting_tasks_sheet_id:
            return (
                "https://docs.google.com/spreadsheets/d/%s"
                % self.meeting_tasks_sheet_id
            )
        return None