"""Google Drive Service for Meeting Intelligence Workflow."""

import logging
import io
import time
from typing import List, Dict, Any, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """
    Google Drive service for file operations.
    """

    def __init__(self, auth):
        """
        Initialize Drive service.

        Args:
            auth: GoogleAuthenticator instance
        """
        self.auth = auth
        self.service = None

    def _get_service(self):
        """Get Google Drive service."""
        if not self.service:
            self.service = self.auth.get_drive_service()
        return self.service

    def search_files(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search for files in Google Drive.

        Args:
            query: Search query string
            max_results: Maximum number of results

        Returns:
            List of file metadata dictionaries
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                service = self._get_service()
                if not service:
                    logger.error("Drive service not available")
                    return []

                logger.info("Searching Drive with query: %s (attempt %d/%d)", query, attempt + 1, max_retries)

                results = (
                    service.files()
                    .list(
                        q=query,
                        pageSize=max_results,
                        fields="nextPageToken, files(id, name, mimeType, size, "
                        "modifiedTime, webViewLink, parents)",
                    )
                    .execute()
                )
                break  # Success, exit retry loop
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning("Drive search attempt %d failed: %s. Retrying in 2 seconds...", attempt + 1, str(e))
                    time.sleep(2)
                    continue
                else:
                    logger.error("Drive search failed after %d attempts: %s", max_retries, str(e))
                    return []

        files = results.get("files", [])
        logger.info("Found %d files matching query", len(files))

        for file in files:
            if self._is_text_file(file.get("mimeType", "")):
                try:
                    content = self.download_file_content(file["id"])
                    file["content"] = content
                except Exception:  # pylint: disable=broad-except
                    logger.debug(
                        "Could not download content for %s",
                        file.get("name", "unknown"),
                    )
                    file["content"] = ""

        return files

    def download_file_content(self, file_id: str) -> str:
        """
        Download file content as text.

        Args:
            file_id: Google Drive file ID

        Returns:
            File content as string
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                service = self._get_service()
                if not service:
                    return ""

                file_metadata = service.files().get(fileId=file_id).execute()
                mime_type = file_metadata.get("mimeType", "")

                if mime_type == "application/vnd.google-apps.document":
                    return self._download_google_doc_content(file_id)

                request = service.files().get_media(fileId=file_id)
                file_content = io.BytesIO()
                downloader = MediaIoBaseDownload(file_content, request)

                done = False
                while not done:
                    _, done = downloader.next_chunk()

                content = file_content.getvalue()
                break  # Success, exit retry loop
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning("File download attempt %d failed for %s: %s. Retrying in 2 seconds...", attempt + 1, file_id, str(e))
                    time.sleep(2)
                    continue
                else:
                    logger.error("File download failed after %d attempts for %s: %s", max_retries, file_id, str(e))
                    return ""

        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return content.decode("latin-1")
                except UnicodeDecodeError:
                    return content.decode("utf-8", errors="ignore")

        return str(content)

    def _download_google_doc_content(self, file_id: str) -> str:
        """Download content from Google Docs with retry logic and better error handling."""
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                service = self._get_service()
                if not service:
                    logger.warning("Google Drive service not available")
                    return ""

                # First, check if file exists and get its metadata
                try:
                    file_metadata = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
                    logger.info(f"File metadata retrieved: {file_metadata.get('name', 'Unknown')} ({file_metadata.get('mimeType', 'Unknown')})")
                except Exception as meta_error:
                    logger.warning(f"Could not retrieve file metadata for {file_id}: {meta_error}")
                    if "notFound" in str(meta_error):
                        logger.error(f"File not found: {file_id}")
                        return ""
                    # Continue with download attempt even if metadata fails

                # Try to download the file
                request = service.files().export_media(
                    fileId=file_id, mimeType="text/plain"
                )
                file_content = io.BytesIO()
                downloader = MediaIoBaseDownload(file_content, request)

                done = False
                while not done:
                    _, done = downloader.next_chunk()

                content = file_content.getvalue().decode("utf-8")
                logger.info(f"Successfully downloaded content from {file_id} ({len(content)} characters)")
                return content

            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for file {file_id}: {error_msg}")
                
                # Check for specific error types
                if "notFound" in error_msg or "File not found" in error_msg:
                    logger.error(f"File not found: {file_id}")
                    return ""
                elif "500" in error_msg or "Internal Error" in error_msg:
                    logger.warning(f"Google API internal error for file {file_id}, retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue
                elif "403" in error_msg or "Forbidden" in error_msg:
                    logger.error(f"Access forbidden for file {file_id}")
                    return ""
                elif "401" in error_msg or "Unauthorized" in error_msg:
                    logger.error(f"Unauthorized access to file {file_id}")
                    return ""
                
                # For other errors, retry with backoff
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay * (attempt + 1)} seconds...")
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    logger.error(f"All retry attempts failed for file {file_id}: {error_msg}")
                    return ""
        
        return ""

    def read_file_content(self, file_id: str) -> str:
        """Alias for download_file_content for compatibility."""
        return self.download_file_content(file_id)

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Get file metadata.

        Args:
            file_id: Google Drive file ID

        Returns:
            File metadata dictionary or None
        """
        try:
            service = self._get_service()
            if not service:
                return None

            return service.files().get(fileId=file_id).execute()

        except Exception:  # pylint: disable=broad-except
            logger.error("Error getting file metadata %s", file_id, exc_info=True)
            return None

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """
        Export file in specified MIME type.

        Args:
            file_id: Google Drive file ID
            mime_type: Target MIME type

        Returns:
            File content as bytes
        """
        try:
            service = self._get_service()
            if not service:
                return b""

            request = service.files().export_media(fileId=file_id, mimeType=mime_type)
            file_content = io.BytesIO()
            downloader = MediaIoBaseDownload(file_content, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            return file_content.getvalue()

        except Exception:  # pylint: disable=broad-except
            logger.error("Error exporting file %s", file_id, exc_info=True)
            return b""

    def upload_file(
        self,
        file_name: str,
        content: bytes,
        mime_type: str,
        parent_folder_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Upload a file to Google Drive.

        Args:
            file_name: Name of the file
            content: File content as bytes
            mime_type: MIME type of the file
            parent_folder_id: Parent folder ID (optional)

        Returns:
            Uploaded file metadata or None
        """
        try:
            service = self._get_service()
            if not service:
                return None

            file_metadata = {"name": file_name, "mimeType": mime_type}

            if parent_folder_id:
                file_metadata["parents"] = [parent_folder_id]

            media = io.BytesIO(content)
            media_upload = MediaIoBaseUpload(media, mimetype=mime_type, resumable=True)
            file = (
                service.files()
                .create(
                    body=file_metadata, media_body=media_upload, fields="id,name,webViewLink"
                )
                .execute()
            )

            logger.info("Uploaded file: %s", file_name)
            return file

        except Exception:  # pylint: disable=broad-except
            logger.error("Error uploading file %s", file_name, exc_info=True)
            return None

    def find_or_create_folder(
        self, folder_name: str, parent_folder_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Find existing folder or create new one.

        Args:
            folder_name: Name of the folder
            parent_folder_id: Parent folder ID (optional)

        Returns:
            Folder ID or None
        """
        try:
            service = self._get_service()
            if not service:
                return None

            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            if parent_folder_id:
                query += f" and '{parent_folder_id}' in parents"

            results = service.files().list(q=query).execute()
            files = results.get("files", [])

            if files:
                folder_id = files[0]["id"]
                logger.info("Found existing folder: %s", folder_name)
                return folder_id

            folder_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if parent_folder_id:
                folder_metadata["parents"] = [parent_folder_id]

            folder = service.files().create(body=folder_metadata, fields="id").execute()

            folder_id = folder.get("id")
            logger.info("Created new folder: %s", folder_name)
            return folder_id

        except Exception:  # pylint: disable=broad-except
            logger.error("Error finding/creating folder %s", folder_name, exc_info=True)
            return None

    def _is_text_file(self, mime_type: str) -> bool:
        """Check if file type is likely to contain text content."""
        text_types = [
            "text/plain",
            "text/csv",
            "application/json",
            "text/html",
            "text/markdown",
            "application/rtf",
            "application/vnd.google-apps.document",
        ]
        return mime_type in text_types