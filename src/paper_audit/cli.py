from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from paper_audit.config import Paths, AuditPolicy
from paper_audit.drive_client import auth_interactive
from paper_audit.runner import audit_folder

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def auth():
    """
    Authenticate Google Drive access (OAuth).
    Saves token to ./.secrets/token.json
    """
    paths = Paths.from_cwd()
    auth_interactive(paths)
    console.print("[green]Authenticated successfully.[/green]")
    console.print(f"Token saved to: {paths.token_path}")


@app.command()
def scan(
    folder_id: str = typer.Option(..., "--folder-id", help="Google Drive folder ID"),
    max_files: Optional[int] = typer.Option(None, "--max-files", help="Limit number of PDFs scanned"),
    recursive: bool = typer.Option(False, "--recursive", help="Also scan PDFs in subfolders"),
    enable_llm: bool = typer.Option(True, "--enable-llm/--no-enable-llm", help="Enable or disable LLM auditing"),
    workers: int = typer.Option(6, "--workers", help="Parallel workers for basic checks"),
    download_workers: int = typer.Option(4, "--download-workers", help="Parallel workers for downloading PDFs"),
    llm_workers: int = typer.Option(1, "--llm-workers", help="Parallel workers for LLM calls (increase carefully)"),
    min_pages: int = typer.Option(1, "--min-pages", help="Fail if PDF has fewer pages than this"),
    min_text_chars: int = typer.Option(200, "--min-text-chars", help="Fail if extracted text too short"),
    llm_model: str = typer.Option("gpt-4.1-mini", "--llm-model", help="OpenAI model name"),
    skip_unchanged: bool = typer.Option(True, "--skip-unchanged/--no-skip-unchanged", help="Skip PDFs unchanged since last scan"),
    force_redownload: bool = typer.Option(False, "--force-redownload", help="Force re-download PDFs even if cached"),
    force_recheck: bool = typer.Option(False, "--force-recheck", help="Force re-check even if unchanged"),
    llm_max_chars: int = typer.Option(120000, "--llm-max-chars", help="Max chars sent to LLM per paper"),
    llm_chunk_chars: int = typer.Option(20000, "--llm-chunk-chars", help="Chunk size for LLM"),
    llm_chunk_overlap: int = typer.Option(1000, "--llm-chunk-overlap", help="Overlap between chunks"),
):
    """
    Scan a Google Drive folder for PDFs and run checks.
    Writes:
      - cache/  (downloaded PDFs)
      - threads/ (issue threads for PDFs with issues only)
      - reports/summary.json
    """
    paths = Paths.from_cwd()

    policy = AuditPolicy(
        recursive=recursive,
        enable_llm=enable_llm,
        max_files=max_files,
        workers=workers,
        download_workers=download_workers,
        llm_workers=llm_workers,
        min_pages=min_pages,
        min_text_chars=min_text_chars,
        llm_model=llm_model,
        skip_unchanged=skip_unchanged,
        force_redownload=force_redownload,
        force_recheck=force_recheck,
        llm_max_chars=llm_max_chars,
        llm_chunk_chars=llm_chunk_chars,
        llm_chunk_overlap=llm_chunk_overlap,
    )

    summary = audit_folder(paths=paths, folder_id=folder_id, policy=policy)

    table = Table(title="Paper Audit Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k in [
        "total_pdfs",
        "skipped_unchanged",
        "papers_with_issues",
        "papers_no_issues",
        "kept_threads",
        "deleted_threads",
    ]:
        table.add_row(k, str(summary.get(k, "")))
    console.print(table)

    out_path = paths.reports_dir / "summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[cyan]Report saved:[/cyan] {out_path}")
    console.print(f"[cyan]Threads dir:[/cyan] {paths.threads_dir}")
    console.print(f"[cyan]Cache dir:[/cyan] {paths.cache_dir}")


if __name__ == "__main__":
    app()
