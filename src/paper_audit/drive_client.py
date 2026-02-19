from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import io
import json
import threading

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from paper_audit.config import Paths
from paper_audit.models import DriveFile

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _load_token(token_path: Path) -> Optional[Credentials]:
    if not token_path.exists():
        return None
    data = json.loads(token_path.read_text(encoding="utf-8"))
    return Credentials.from_authorized_user_info(data, SCOPES)


def _save_token(token_path: Path, creds: Credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def auth_interactive(paths: Paths) -> Credentials:
    """
    OAuth flow for desktop app.
    Stores token in ./.secrets/token.json
    Requires credentials.json at project root.
    """
    token_path = paths.token_path
    creds = _load_token(token_path)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        # Let google-auth refresh automatically via discovery client as needed.
        pass

    if not paths.credentials_path.exists():
        raise FileNotFoundError(f"Missing {paths.credentials_path}. Put your Google OAuth client JSON there.")

    flow = InstalledAppFlow.from_client_secrets_file(str(paths.credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(token_path, creds)
    return creds


def _get_service(paths: Paths):
    """
    Building the Drive service is expensive.
    Cache one per thread (googleapiclient clients are not guaranteed thread-safe).
    """
    creds = _load_token(paths.token_path)
    if not creds or not creds.valid:
        raise RuntimeError("Not authenticated. Run: python -m paper_audit.cli auth")

    tl = getattr(_get_service, "_thread_local", None)
    if tl is None:
        tl = threading.local()
        setattr(_get_service, "_thread_local", tl)

    svc = getattr(tl, "service", None)
    if svc is None:
        tl.service = build("drive", "v3", credentials=creds)
        svc = tl.service
    return svc


def _iter_folder_pdfs(paths: Paths, folder_id: str) -> Iterable[DriveFile]:
    service = _get_service(paths)
    q = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"

    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        for f in resp.get("files", []):
            size_val = f.get("size")
            try:
                size_int = int(size_val) if size_val is not None else None
            except Exception:
                size_int = None

            yield DriveFile(
                id=f["id"],
                name=f.get("name", ""),
                mime_type=f.get("mimeType", ""),
                modified_time=f.get("modifiedTime"),
                size=size_int,
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _iter_subfolders(paths: Paths, folder_id: str) -> Iterable[str]:
    service = _get_service(paths)
    q = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"

    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        for f in resp.get("files", []):
            yield f["id"]

        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def list_pdfs_in_folder(paths: Paths, folder_id: str, recursive: bool = False) -> List[DriveFile]:
    out: List[DriveFile] = []
    queue = [folder_id]
    seen = set()

    while queue:
        fid = queue.pop(0)
        if fid in seen:
            continue
        seen.add(fid)

        out.extend(list(_iter_folder_pdfs(paths, fid)))

        if recursive:
            for child in _iter_subfolders(paths, fid):
                if child not in seen:
                    queue.append(child)

    out.sort(key=lambda x: (x.name or "").lower())
    return out


def download_file(paths: Paths, file_id: str, dest_path: Path) -> None:
    service = _get_service(paths)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(dest_path, "wb")
    downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)

    done = False
    while not done:
        _status, done = downloader.next_chunk()
