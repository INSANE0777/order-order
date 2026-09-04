"""Command line for OrderOrder.

orderorder doctor                       check the environment
orderorder init-db                      create tables
orderorder corpus years                 list years available in the open-data bucket
orderorder corpus fetch 2019 2020       download parquet metadata for those years
orderorder ingest metadata 2019         import a year into judgment + citation_alias
orderorder cite parse "..."             show what the citation grammar finds in a string
orderorder resolve "(2019) 4 SCC 1"     resolve a citation against the knowledge base
orderorder stats                        row counts
"""

from __future__ import annotations

import os
import sys

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from orderorder import __version__
from orderorder.citations.grammar import extract_citations
from orderorder.config import get_settings
from orderorder.db.models import CitationAlias, Judgment, JudgmentTextVersion, Paragraph
from orderorder.db.session import get_session, init_db
from orderorder.engine.locator import locate as locate_claim
from orderorder.ingest import corpus as corpus_mod
from orderorder.ingest import pdf as pdf_mod
from orderorder.ingest.metadata import import_parquet
from orderorder.ingest.store import load_paragraphs, store_extracted
from orderorder.resolver import resolve as resolve_citation

app = typer.Typer(help="Citation-integrity engine for Indian case law.", no_args_is_help=True)
corpus_app = typer.Typer(help="Download judgments from the AWS Open Data bucket.", no_args_is_help=True)
ingest_app = typer.Typer(help="Import downloaded data into the knowledge base.", no_args_is_help=True)
cite_app = typer.Typer(help="Citation grammar tools.", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")
app.add_typer(ingest_app, name="ingest")
app.add_typer(cite_app, name="cite")

console = Console()


@app.callback()
def _root(version: bool = typer.Option(False, "--version", help="Print the version and exit.")) -> None:
    if version:
        console.print(f"orderorder {__version__}")
        raise typer.Exit()


@app.command()
def doctor() -> None:
    """Check Python, the data directory, the database and which model providers have keys."""
    settings = get_settings()
    table = Table(title="OrderOrder environment", show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Value")
    table.add_column("Status")

    table.add_row("python", sys.version.split()[0], "ok" if sys.version_info >= (3, 12) else "needs 3.12+")
    data_dir = settings.orderorder_data_dir
    table.add_row("data dir", str(data_dir), "ok" if data_dir.exists() else "missing")
    table.add_row(
        "database", settings.db_url.split("://")[0], "postgres" if settings.is_postgres else "sqlite"
    )

    for name, env in [
        ("GOOGLE_API_KEY", "GOOGLE_API_KEY"),
        ("GROQ_API_KEY", "GROQ_API_KEY"),
        ("CEREBRAS_API_KEY", "CEREBRAS_API_KEY"),
        ("INDIANKANOON_TOKEN", "INDIANKANOON_TOKEN"),
    ]:
        table.add_row(name, "set" if os.environ.get(env) else "-", "ok" if os.environ.get(env) else "not set")

    table.add_row("llm primary", settings.llm_primary, "")
    table.add_row("llm fallbacks", ", ".join(settings.fallback_models) or "-", "")
    console.print(table)

    try:
        with get_session() as session:
            judgments = session.scalar(select(func.count()).select_from(Judgment)) or 0
        console.print(f"[green]database reachable[/green], {judgments} judgments")
    except Exception as exc:  # noqa: BLE001 - the point is to report any failure
        console.print(f"[yellow]database not ready:[/yellow] {exc}")
        console.print("run [bold]orderorder init-db[/bold]")


@app.command("init-db")
def init_db_command() -> None:
    """Create tables in the configured database."""
    settings = get_settings()
    init_db()
    console.print(f"[green]tables created[/green] in {settings.db_url}")


@corpus_app.command("years")
def corpus_years() -> None:
    """List the years available in the open-data bucket."""
    years = corpus_mod.available_years()
    console.print(f"{len(years)} years: {years[0]}-{years[-1]}")
    console.print(f"[dim]{corpus_mod.ATTRIBUTION}[/dim]")


@corpus_app.command("fetch")
def corpus_fetch(
    years: list[int] = typer.Argument(..., help="Years to download, e.g. 2019 2020 2021."),
) -> None:
    """Download parquet metadata for the given years."""
    settings = get_settings()
    for year in years:
        path = corpus_mod.download_metadata(year, settings.corpus_dir)
        size_mb = path.stat().st_size / 1e6
        console.print(f"[green]{year}[/green] {path.name} ({size_mb:.1f} MB)")
    console.print(f"[dim]{corpus_mod.ATTRIBUTION}[/dim]")


@ingest_app.command("metadata")
def ingest_metadata(
    years: list[int] = typer.Argument(..., help="Years to import; download them first."),
    limit: int | None = typer.Option(None, help="Import only the first N rows of each year."),
) -> None:
    """Import parquet metadata into judgment and citation_alias."""
    settings = get_settings()
    init_db()
    totals: dict[str, int] = {}
    for year in years:
        path = settings.corpus_dir / "metadata" / f"year={year}_metadata.parquet"
        if not path.exists():
            path = corpus_mod.download_metadata(year, settings.corpus_dir)
        with get_session() as session:
            stats = import_parquet(session, path, limit=limit)
        console.print(f"[green]{year}[/green] {stats.as_dict()}")
        for key, value in stats.as_dict().items():
            totals[key] = totals.get(key, 0) + value
    if len(years) > 1:
        console.print(f"[bold]total[/bold] {totals}")


@ingest_app.command("text")
def ingest_text(
    keys: list[str] = typer.Argument(..., help="Canonical keys, e.g. INSC:2019:770."),
    version_key: str = typer.Option("scr_pdf", help="Name for this text version."),
) -> None:
    """Fetch each judgment's official PDF, clean it, segment it and store the paragraphs."""
    settings = get_settings()
    init_db()
    for key in keys:
        with get_session() as session:
            judgment = session.scalars(select(Judgment).where(Judgment.canonical_key == key)).first()
            if judgment is None:
                console.print(f"[red]{key}[/red] not in the knowledge base; import its year first")
                continue
            if not judgment.source_id:
                console.print(f"[red]{key}[/red] has no source path, cannot locate a PDF")
                continue
            year = (judgment.extra or {}).get("year") or (
                judgment.decided_on.year if judgment.decided_on else None
            )
            try:
                path = pdf_mod.fetch_pdf(judgment.source_id, year, settings.corpus_dir)
                extracted = pdf_mod.extract(path, judgment.source_id)
            except Exception as exc:  # noqa: BLE001 - report and continue with the next key
                console.print(f"[red]{key}[/red] {type(exc).__name__}: {exc}")
                continue
            if not extracted.has_judgment:
                console.print(f"[yellow]{key}[/yellow] no judgment text found after cleaning")
                continue
            result = store_extracted(
                session,
                judgment,
                extracted,
                version_key=version_key,
                source_url=pdf_mod.pdf_url(judgment.source_id, year),
            )
            bench = f"bench {extracted.bench_strength}" if extracted.bench_strength else "bench ?"
            console.print(
                f"[green]{key}[/green] {extracted.page_count}p "
                f"{len(extracted.judgment):,}ch {result.paragraphs} paras, "
                f"{bench}, author {extracted.author or '-'}"
                + (" [yellow](bench corrected)[/yellow]" if result.bench_corrected else "")
                + (" [dim](replaced)[/dim]" if result.replaced else "")
            )


@app.command("locate")
def locate_command(
    key: str = typer.Argument(..., help="Canonical key of the judgment, e.g. INSC:2019:770."),
    proposition: str = typer.Argument(..., help="The proposition the brief attributes to the judgment."),
    pinpoint: str | None = typer.Option(None, help="The paragraph the brief cited, e.g. 5.1."),
    top: int = typer.Option(5, help="How many candidate paragraphs to show."),
) -> None:
    """Rank a judgment's paragraphs against a proposition and check the pinpoint."""
    with get_session() as session:
        judgment = session.scalars(select(Judgment).where(Judgment.canonical_key == key)).first()
        if judgment is None:
            console.print(f"[red]{key}[/red] not in the knowledge base")
            raise typer.Exit(1)
        paragraphs = load_paragraphs(session, judgment.id)
        if not paragraphs:
            console.print(f"[yellow]{key}[/yellow] has no text; run [bold]orderorder ingest text {key}[/bold]")
            raise typer.Exit(1)

        result = locate_claim(paragraphs, proposition, claimed_pinpoint=pinpoint, top_k=top)
        console.print(f"[bold]{judgment.title[:80]}[/bold]")
        console.print(f"[dim]{len(paragraphs)} paragraphs; query terms: {', '.join(result.query_terms[:12])}[/dim]\n")

        check = result.pinpoint
        if check.status == "ok":
            console.print(f"[green]pinpoint ok[/green] paragraph {check.claimed} exists")
        elif check.is_problem:
            console.print(f"[red]pinpoint problem[/red] {check.note}")
        elif check.status == "none_claimed":
            console.print(f"[dim]no pinpoint claimed; numbering runs to {check.highest_label}[/dim]")

        table = Table(show_header=True, header_style="bold")
        table.add_column("para")
        table.add_column("score", justify="right")
        table.add_column("terms")
        table.add_column("text")
        for candidate in result.candidates[:top]:
            label = candidate.printed_label or f"#{candidate.seq}"
            if candidate.is_claimed_pinpoint:
                label = f"{label} (cited)"
            if candidate.likely_quoted:
                label = f"[red]{label} quoted?[/red]"
            table.add_row(label, f"{candidate.score:.2f}", ", ".join(candidate.matched_terms[:4]), candidate.preview)
        console.print(table)
        if any(c.likely_quoted for c in result.candidates[:top]):
            console.print(
                "[red]warning[/red] a candidate's paragraph number breaks the judgment's sequence, "
                "so it is probably quoted from another judgment rather than this court's own words"
            )


@cite_app.command("parse")
def cite_parse(text: str = typer.Argument(..., help="Text to scan for citations.")) -> None:
    """Show every citation the grammar finds, with its normalised key and pinpoint."""
    found = extract_citations(text)
    if not found:
        console.print("[yellow]no citations found[/yellow]")
        raise typer.Exit(1)
    table = Table(show_header=True, header_style="bold")
    for column in ("raw", "reporter", "normalized", "pinpoint", "parties"):
        table.add_column(column)
    for citation in found:
        table.add_row(
            citation.raw,
            citation.reporter,
            citation.normalized,
            citation.pinpoint.label if citation.pinpoint else "-",
            citation.party_names or "-",
        )
    console.print(table)


@app.command("resolve")
def resolve_command(text: str = typer.Argument(..., help="A citation, optionally with party names.")) -> None:
    """Resolve every citation in the text against the knowledge base."""
    found = extract_citations(text)
    if not found:
        console.print("[yellow]no citations found[/yellow]")
        raise typer.Exit(1)
    with get_session() as session:
        for citation in found:
            result = resolve_citation(session, citation)
            colour = {"found": "green", "ambiguous": "yellow"}.get(result.status, "red")
            console.print(
                f"[{colour}]{result.status}[/{colour}] {citation.raw} "
                f"-> {result.canonical_key or '-'} via {result.method} ({result.score:.0f})"
            )
            if result.note:
                console.print(f"  [dim]{result.note}[/dim]")
            for candidate in result.candidates[:3]:
                console.print(
                    f"  [dim]{candidate.score:5.1f} {candidate.canonical_key} {candidate.title[:70]}[/dim]"
                )


@app.command()
def stats() -> None:
    """Row counts for the knowledge base."""
    with get_session() as session:
        table = Table(show_header=True, header_style="bold")
        table.add_column("table")
        table.add_column("rows", justify="right")
        for name, model in [
            ("judgment", Judgment),
            ("citation_alias", CitationAlias),
            ("judgment_text_version", JudgmentTextVersion),
            ("paragraph", Paragraph),
        ]:
            count = session.scalar(select(func.count()).select_from(model)) or 0
            table.add_row(name, f"{count:,}")
        console.print(table)
        earliest, latest = session.execute(
            select(func.min(Judgment.decided_on), func.max(Judgment.decided_on))
        ).first() or (None, None)
        if earliest:
            console.print(f"date range: {earliest} to {latest}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
