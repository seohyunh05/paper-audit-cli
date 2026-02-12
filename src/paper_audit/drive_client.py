from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from .config import Paths
from .models import DriveFile

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def ensure_dirs(paths: Paths) -> None:
    paths.secrets_dir.mkdir(parents=True, exist_ok=True)

def load_credentials(paths: Paths) -> Optional[Credentials]:
    if paths.token_path.exists():
        return Credentials.from_authorized_user_file(str(paths.token_path), SCOPES)
    return None

def save_credentials(paths: Paths, creds: Credentials) -> None:
    ensure_dirs(paths)
    paths.token_path.write_text(creds.to_json(), encoding="utf-8")

def auth_interactive(paths: Paths) -> Credentials:
    if not paths.credentials_path.exists():
        raise FileNotFoundError(f"Missing {paths.credentials_path}. Put your Google OAuth client JSON there.")

    creds = load_credentials(paths)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(paths, creds)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(paths.credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    save_credentials(paths, creds)
    return creds

def get_drive_service(paths: Paths):
    creds = load_credentials(paths)
    if not creds:
        raise RuntimeError("Not authenticated. Run: paper-audit auth")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(paths, creds)
    return build("drive", "v3", credentials=creds)

def list_pdfs_in_folder(paths: Paths, folder_id: str, recursive: bool = True) -> List[DriveFile]:
    service = get_drive_service(paths)

    files: List[DriveFile] = []
    to_visit = [folder_id]

    while to_visit:
        current = to_visit.pop()
        q = f"'{current}' in parents and trashed=false"
        page_token = None

        while True:
            resp = service.files().list(
                q=q,
                fields="nextPageToken, files(id,name,mimeType,modifiedTime,size)",
                pageToken=page_token,
                pageSize=1000
            ).execute()

            for f in resp.get("files", []):
                df = DriveFile(**f)
                if df.mimeType == "application/pdf":
                    files.append(df)
                elif recursive and df.mimeType == "application/vnd.google-apps.folder":
                    to_visit.append(df.id)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    return files

def download_file(paths: Paths, file_id: str, out_path: Path) -> None:
    service = get_drive_service(paths)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    request = service.files().get_media(fileId=file_id)
    with open(out_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
