from __future__ import annotations
import typer
from rich import print
from rich.table import Table

from .config import Paths, AuditPolicy

from .drive_client import auth_interactive
from .runner import audit_folder

app = typer.Typer(add_completion=False)
paths = Paths()

DEFAULT_FOLDER_ID = "1fTHQEJvEr2_9UX0c3f_72SUcMiSYcm2p"

@app.command()
def auth():
    """
    Authenticate Google Drive access (OAuth). Stores token in ./.secrets/token.json
    """
    auth_interactive(paths)
    print("[green]Authenticated successfully.[/green]")
    print(f"Token saved to: {paths.token_path}")

@app.command()
def scan(
    folder_id: str = typer.Option(DEFAULT_FOLDER_ID, "--folder-id", help="Google Drive folder ID (default: professor's folder)"),
    recursive: bool = typer.Option(True, help="Scan folders recursively"),
    min_pages: int = typer.Option(2, help="Warn if PDF has fewer pages than this"),
    min_text_chars: int = typer.Option(300, help="Warn if extracted text chars less than this"),

    enable_llm: bool = typer.Option(True, help="Enable LLM-based logical audit (requires OPENAI_API_KEY env var)"),
    llm_model: str = typer.Option("gpt-5", help="OpenAI model name"),
    llm_reasoning_effort: str = typer.Option("low", help="Reasoning effort (if supported): low|medium|high"),
    llm_max_chars: int = typer.Option(120000, help="Cap extracted text characters sent to LLM"),
    llm_chunk_chars: int = typer.Option(18000, help="Chunk size for long papers"),
    llm_chunk_overlap: int = typer.Option(800, help="Chunk overlap"),

    keep_all_threads: bool = typer.Option(False, help="If set, do NOT auto-delete threads when no issues"),
    delete_cached_pdf_if_no_errors: bool = typer.Option(False, help="Also delete cached PDFs when no issues"),
):
    policy = AuditPolicy(
        recursive=recursive,
        min_pages=min_pages,
        min_text_chars=min_text_chars,

        enable_llm=enable_llm,
        llm_model=llm_model,
        llm_reasoning_effort=llm_reasoning_effort,
        llm_max_chars=llm_max_chars,
        llm_chunk_chars=llm_chunk_chars,
        llm_chunk_overlap=llm_chunk_overlap,

        delete_thread_if_no_errors=(not keep_all_threads),
        delete_cached_pdf_if_no_errors=delete_cached_pdf_if_no_errors,
    )

    summary = audit_folder(paths, folder_id, policy)

    table = Table(title="Paper Audit Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    for k in ["total_pdfs", "papers_with_issues", "papers_no_issues", "kept_threads", "deleted_threads"]:
        table.add_row(k, str(summary[k]))

    print(table)
    print(f"[cyan]Report saved:[/cyan] {paths.reports_dir / 'summary.json'}")
    print(f"[cyan]Threads dir:[/cyan] {paths.threads_dir}")
    print(f"[cyan]Cache dir:[/cyan] {paths.cache_dir}")

if __name__ == "__main__":
    app()
