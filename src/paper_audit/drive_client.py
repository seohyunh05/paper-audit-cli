from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .models import DriveFile


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@dataclass(frozen=True)
class DrivePaths:
    credentials_path: Path
    token_path: Path


class DriveClient:
    def __init__(self, service):
        self._service = service

    @staticmethod
    def auth_interactive(paths: DrivePaths) -> Credentials:
        if not paths.credentials_path.exists():
            raise FileNotFoundError(f"Missing {paths.credentials_path}. Put your Google OAuth client JSON there.")

        creds: Credentials | None = None
        if paths.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(paths.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(paths.credentials_path), SCOPES)
                creds = flow.run_local_server(port=0)

            paths.token_path.parent.mkdir(parents=True, exist_ok=True)
            paths.token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    @staticmethod
    def from_credentials(creds: Credentials):
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return DriveClient(service)

    def list_pdfs_in_folder(self, folder_id: str, recursive: bool) -> list[DriveFile]:
        # If recursive, we BFS into subfolders.
        if not recursive:
            return self._list_pdfs_non_recursive(folder_id)

        pdfs: list[DriveFile] = []
        queue: list[str] = [folder_id]

        while queue:
            fid = queue.pop(0)
            pdfs.extend(self._list_pdfs_non_recursive(fid))
            queue.extend(self._list_subfolders(fid))

        return pdfs

    def _list_pdfs_non_recursive(self, folder_id: str) -> list[DriveFile]:
        q = f"'{folder_id}' in parents and trashed=false and mimeType='application/pdf'"
        fields = "nextPageToken, files(id, name, modifiedTime, size)"
        out: list[DriveFile] = []
        token = None

        while True:
            resp = (
                self._service.files()
                .list(q=q, fields=fields, pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True)
                .execute()
            )
            for f in resp.get("files", []):
                out.append(
                    DriveFile(
                        id=f["id"],
                        name=f.get("name", f["id"]),
                        modified_time=f.get("modifiedTime"),
                        size=int(f["size"]) if f.get("size") else None,
                    )
                )
            token = resp.get("nextPageToken")
            if not token:
                break
        return out

    def _list_subfolders(self, folder_id: str) -> list[str]:
        q = f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'"
        fields = "nextPageToken, files(id)"
        out: list[str] = []
        token = None

        while True:
            resp = (
                self._service.files()
                .list(q=q, fields=fields, pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True)
                .execute()
            )
            for f in resp.get("files", []):
                out.append(f["id"])
            token = resp.get("nextPageToken")
            if not token:
                break
        return out

    def download_pdf(self, file_id: str, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with target_path.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)  # 1MB
            done = False
            while not done:
                _, done = downloader.next_chunk()

    @staticmethod
    def drive_time_to_epoch(modified_time: str | None) -> float | None:
        if not modified_time:
            return None
        # RFC3339 e.g. "2026-02-13T12:05:15.123Z"
        dt = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
        return dt.timestamp()

    @staticmethod
    def local_is_fresh(local_path: Path, modified_time: str | None) -> bool:
        if not local_path.exists():
            return False
        drive_epoch = DriveClient.drive_time_to_epoch(modified_time)
        if drive_epoch is None:
            return True
        local_epoch = local_path.stat().st_mtime
        return local_epoch >= drive_epoch - 2  # small tolerance
