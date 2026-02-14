# src/paper_audit/drive_client.py
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .config import Paths
from .models import DriveFile

# Read-only Drive access is enough for scanning + downloading
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _parse_rfc3339(ts: str | None) -> Optional[datetime]:
    if not ts:
        return None
    # Google returns e.g. "2026-02-13T12:34:56.789Z"
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


class DriveClient:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.service = None  # created after auth

    # ---------- Auth ----------
    def auth_interactive(self) -> None:
        """
        Creates/updates token at ./.secrets/token.json using OAuth Desktop client in credentials.json
        """
        self.paths.secrets_dir.mkdir(parents=True, exist_ok=True)

        if not self.paths.credentials_path.exists():
            raise FileNotFoundError(
                f"Missing {self.paths.credentials_path}. Put your Google OAuth client JSON there."
            )

        creds: Credentials | None = None
        if self.paths.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.paths.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.paths.credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token
        self.paths.token_path.write_text(creds.to_json(), encoding="utf-8")

        self.service = build("drive", "v3", credentials=creds)

    def _ensure_service(self) -> None:
        if self.service is not None:
            return
        # Try to load saved token automatically
        if not self.paths.token_path.exists():
            raise RuntimeError("Not authenticated. Run: paper-audit auth")

        creds = Credentials.from_authorized_user_file(str(self.paths.token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        self.service = build("drive", "v3", credentials=creds)

    # ---------- Listing PDFs ----------
    def list_pdfs_in_folder(self, folder_id: str, recursive: bool = False) -> list[DriveFile]:
        self._ensure_service()

        out: list[DriveFile] = []

        if not recursive:
            out.extend(self._list_pdfs_direct(folder_id))
            return out

        # BFS over folders
        queue = [folder_id]
        seen = set(queue)

        while queue:
            fid = queue.pop(0)

            # PDFs in this folder
            out.extend(self._list_pdfs_direct(fid))

            # child folders
            for sub in self._list_subfolders_direct(fid):
                if sub.id not in seen:
                    seen.add(sub.id)
                    queue.append(sub.id)

        return out

    def _list_pdfs_direct(self, folder_id: str) -> list[DriveFile]:
        self._ensure_service()

        q = (
            f"'{folder_id}' in parents and "
            "mimeType='application/pdf' and "
            "trashed=false"
        )

        files: list[DriveFile] = []
        page_token = None

        while True:
            resp = (
                self.service.files()
                .list(
                    q=q,
                    fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                    pageToken=page_token,
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )

            for f in resp.get("files", []):
                files.append(
                    DriveFile(
                        id=f["id"],
                        name=f["name"],
                        mime_type=f.get("mimeType", "application/pdf"),
                        modified_time=f.get("modifiedTime"),
                    )
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return files

    def _list_subfolders_direct(self, folder_id: str) -> list[DriveFile]:
        self._ensure_service()
        q = (
            f"'{folder_id}' in parents and "
            "mimeType='application/vnd.google-apps.folder' and "
            "trashed=false"
        )

        files: list[DriveFile] = []
        page_token = None

        while True:
            resp = (
                self.service.files()
                .list(
                    q=q,
                    fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                    pageToken=page_token,
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )

            for f in resp.get("files", []):
                files.append(
                    DriveFile(
                        id=f["id"],
                        name=f["name"],
                        mime_type=f.get("mimeType", "application/vnd.google-apps.folder"),
                        modified_time=f.get("modifiedTime"),
                    )
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return files

    # ---------- Download ----------
    def download_pdf(self, file_id: str, local_path: Path) -> None:
        self._ensure_service()
        local_path.parent.mkdir(parents=True, exist_ok=True)

        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)

        fh = io.FileIO(str(local_path), "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.close()

    # ---------- Cache freshness ----------
    @staticmethod
    def local_is_fresh(local_path: Path, drive_modified_time: str | None) -> bool:
        if not local_path.exists():
            return False
        if not drive_modified_time:
            return True

        remote_dt = _parse_rfc3339(drive_modified_time)
        if remote_dt is None:
            return True

        local_dt = datetime.fromtimestamp(local_path.stat().st_mtime, tz=timezone.utc)
        return local_dt >= remote_dt
