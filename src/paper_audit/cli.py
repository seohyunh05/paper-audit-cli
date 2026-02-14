from __future__ import annotations

from pathlib import Path
import typer
from rich import print

from .config import Paths, AuditPolicy
from .drive_client import DriveClient
from .runner import audit_folder

app = typer.Typer(add_completion=False, help="Paper audit CLI (Google Drive → checks → optional LLM).")


@app.command()
def auth():
    """
    Authenticate Google Drive access (OAuth). Stores token in ./.secrets/token.json
    """
    root = Path.cwd()
    paths = Paths(root=root)
    drive = DriveClient(paths=paths)
    drive.auth_interactive()
    print("[green]Authenticated successfully.[/green]")
    print(f"Token saved to: {paths.token_path}")


@app.command()
def scan(
    folder_id: str = typer.Option(..., "--folder-id", help="Google Drive folder ID"),
    recursive: bool = typer.Option(False, "--recursive", help="Scan subfolders recursively"),
    enable_llm: bool = typer.Option(True, "--enable-llm/--no-enable-llm", help="Enable LLM audit step"),
    max_files: int | None = typer.Option(None, "--max-files", help="Limit number of PDFs (testing)"),
    workers: int = typer.Option(6, "--workers", help="Download/basic-check workers"),
    llm_workers: int = typer.Option(2, "--llm-workers", help="LLM workers (keep small)"),
    min_pages: int = typer.Option(2, "--min-pages", help="Minimum pages required"),
    min_text_chars: int = typer.Option(500, "--min-text-chars", help="Minimum extracted text chars required"),
    llm_model: str = typer.Option("gpt-4.1-mini", "--llm-model", help="OpenAI model"),
    llm_reasoning_effort: str = typer.Option("low", "--llm-reasoning-effort", help="Reasoning effort"),
    llm_max_chars: int = typer.Option(120000, "--llm-max-chars", help="Max chars sent to LLM"),
):
    """
    Scan one Drive folder: downloads PDFs (cached), runs checks, optionally runs LLM audit.
    Writes reports/ and threads/ output.
    """
    root = Path.cwd()
    paths = Paths(root=root)

    policy = AuditPolicy(
        recursive=recursive,
        min_pages=min_pages,
        min_text_chars=min_text_chars,
        workers=workers,
        llm_workers=llm_workers,
        enable_llm=enable_llm,
        llm_model=llm_model,
        llm_reasoning_effort=llm_reasoning_effort,
        llm_max_chars=llm_max_chars,
        max_files=max_files,
    )

    drive = DriveClient(paths=paths)

    summary = audit_folder(paths=paths, drive=drive, folder_id=folder_id, policy=policy)

    print("\n[bold]Paper Audit Summary[/bold]")
    print(f"total_pdfs: {summary['total_pdfs']}")
    print(f"papers_with_issues: {summary['papers_with_issues']}")
    print(f"papers_no_issues: {summary['papers_no_issues']}")
    print(f"kept_threads: {summary['kept_threads']}")
    print(f"deleted_threads: {summary['deleted_threads']}")
    print(f"\nReport saved: {summary['dirs']['report_path']}")
    print(f"Threads dir: {summary['dirs']['threads_dir']}")
    print(f"Cache dir: {summary['dirs']['cache_dir']}")


if __name__ == "__main__":
    app()
