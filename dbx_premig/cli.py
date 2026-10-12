"""Command line (typer). A skin over ``service.py``: no analysis logic lives here.

stdout carries only the path of the written workbook, so the command can be piped; progress,
the summary and errors go to stderr. Exit codes are listed in ``errors.py``.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from pydantic import SecretStr

from dbx_premig.config import ALL_COLLECTORS, Settings, load_settings
from dbx_premig.errors import DiscoveryError
from dbx_premig.logging import configure_logging, stderr_console
from dbx_premig.version import APP_NAME, APP_VERSION, DIST_NAME

__all__ = ["app", "main", "print_summary"]

app = typer.Typer(
    name=DIST_NAME,
    help=f"{APP_NAME}: inventory a Databricks workspace for a Microsoft Fabric migration.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

T = TypeVar("T")


def _handle(verbose: bool, fn: Callable[[], T]) -> T:
    """Run ``fn``; turn errors into a message on stderr and a fixed exit code."""
    try:
        return fn()
    except DiscoveryError as exc:
        stderr_console.print(f"[bold red]Error:[/] {exc.message}")
        if verbose and exc.detail:
            stderr_console.print(exc.detail, markup=False)
        raise typer.Exit(exc.exit_code) from None
    except KeyboardInterrupt:
        stderr_console.print("[yellow]Interrupted.[/]")
        raise typer.Exit(130) from None
    except Exception as exc:  # a bug: never show a traceback unless asked
        stderr_console.print(
            f"[bold red]Internal error[/] ({type(exc).__name__}). Re-run with --verbose "
            "and report it."
        )
        if verbose:
            stderr_console.print(traceback.format_exc(), markup=False)
        raise typer.Exit(1) from None


def _split(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    return tuple(v.strip() for v in value.split(",") if v.strip())


def print_summary(result: Any) -> None:
    from dbx_premig.estimation import summarise

    s = summarise(result.report)
    r = s.by_readiness
    stderr_console.print(
        f"[bold]{s.total_assets}[/] assessable objects  ·  "
        f"[green]{r['Compatible']} compatible[/]  ·  [yellow]{r['Partial']} partial[/]  ·  "
        f"[red]{r['Manual']} manual[/]  ·  [magenta]{r['Unsupported']} unsupported[/]  ·  "
        f"average readiness {s.average_readiness}  ·  {s.warnings} warning(s)"
    )
    if s.warnings:
        stderr_console.print("Read the [bold]Warnings[/] sheet: some objects could not be read.")
    if result.snapshot:
        stderr_console.print(f"Snapshot saved: {result.snapshot}")


@app.command()
def discover(
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            "-i",
            help="Offline mode: folder of exported notebooks, a .dbc/.zip export, or a "
            "snapshot .json. Omit for a live workspace scan.",
        ),
    ] = None,
    host: Annotated[str | None, typer.Option(help="Workspace URL (or DATABRICKS_HOST).")] = None,
    token: Annotated[
        str | None,
        typer.Option(help="Personal access token. Prefer the DATABRICKS_TOKEN variable."),
    ] = None,
    client_id: Annotated[
        str | None, typer.Option(help="Service principal client id (OAuth M2M).")
    ] = None,
    client_secret: Annotated[
        str | None, typer.Option(help="Service principal secret (or DATABRICKS_CLIENT_SECRET).")
    ] = None,
    profile: Annotated[str | None, typer.Option(help="Profile in ~/.databrickscfg.")] = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output folder.")] = Path("output"),
    name: Annotated[
        str | None, typer.Option(help="Workbook file name (default: generated).")
    ] = None,
    save_snapshot: Annotated[
        bool,
        typer.Option(
            "--save-snapshot",
            help="Also write the raw capture as JSON (re-run later with --input). It contains "
            "notebook source: treat it as client data.",
        ),
    ] = False,
    only: Annotated[
        str | None,
        typer.Option(help=f"Comma list of collectors to run: {', '.join(ALL_COLLECTORS)}."),
    ] = None,
    catalogs: Annotated[
        str | None, typer.Option(help="Comma list: only these Unity Catalog catalogs.")
    ] = None,
    skip_repos: Annotated[bool, typer.Option("--skip-repos", help="Skip /Repos.")] = False,
    no_columns: Annotated[
        bool, typer.Option("--no-columns", help="Leave out the Columns sheet.")
    ] = False,
    no_view_sql: Annotated[
        bool, typer.Option("--no-view-sql", help="Leave view SQL out of the Views sheet.")
    ] = False,
    max_notebooks: Annotated[
        int | None, typer.Option(help="Stop exporting notebooks after this many.")
    ] = None,
    insecure: Annotated[
        bool, typer.Option("--insecure", help="Do not verify TLS (lab proxies only).")
    ] = False,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Settings file (.yaml / .toml).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Progress and details.")] = False,
) -> None:
    """Discover a Databricks workspace (live) or an export (offline) and write the workbook."""

    def run() -> None:
        overrides: dict[str, Any] = {
            "host": host,
            "token": SecretStr(token) if token else None,
            "client_id": client_id,
            "client_secret": SecretStr(client_secret) if client_secret else None,
            "profile": profile,
            "collectors": _split(only),
            "catalogs": _split(catalogs),
            "max_notebooks": max_notebooks,
        }
        if skip_repos:
            overrides["skip_repos"] = True
        if no_columns:
            overrides["include_columns"] = False
        if no_view_sql:
            overrides["include_view_definitions"] = False
        if insecure:
            overrides["verify_tls"] = False
        settings = load_settings(config, **overrides)
        configure_logging(settings.log_level, verbose)
        result = execute(settings, input_path, out, name, save_snapshot)
        print_summary(result)
        typer.echo(str(result.workbook))

    _handle(verbose, run)


def execute(
    settings: Settings,
    input_path: Path | None,
    out: Path,
    name: str | None,
    save_snapshot: bool,
) -> Any:
    """Run a discovery with a progress spinner on stderr (shared with the prompts)."""
    from dbx_premig.service import run_discovery

    with stderr_console.status("Starting discovery...") as status:

        def progress(collector: str, state: str) -> None:
            if state == "start":
                status.update(f"Reading [bold]{collector}[/] ...")
            else:
                stderr_console.print(f"  {collector:<18} {state}")

        result = run_discovery(
            settings,
            input_path=input_path,
            output_dir=out,
            output_name=name,
            keep_snapshot=save_snapshot,
            progress=progress,
        )
        status.update("Writing the workbook ...")
    stderr_console.print(f"[green]Workbook written:[/] {result.workbook}")
    return result


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"{DIST_NAME} {APP_VERSION}")


@app.command("catalog-info")
def catalog_info(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate the bundled Databricks -> Fabric support catalog and print its size."""

    def run() -> None:
        from dbx_premig.catalog.loader import load_catalog

        cat = load_catalog()
        code = len(cat.code_patterns())
        typer.echo(
            f"catalog v{cat.version}: {len(cat.features)} features "
            f"({code} code patterns, {len(cat.features) - code} structural), "
            f"{len(cat.asset_targets)} asset targets, {len(cat.job_task_types)} job task types"
        )

    _handle(verbose, run)


@app.command()
def collectors() -> None:
    """List the live collectors (for --only)."""
    for name in ALL_COLLECTORS:
        typer.echo(name)


def main() -> None:
    """Console-script and frozen entry point: no arguments -> interactive prompts."""
    if len(sys.argv) <= 1:
        from dbx_premig.prompts import run_interactive

        sys.exit(run_interactive())
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
