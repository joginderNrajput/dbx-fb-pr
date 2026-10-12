"""Interactive front end: what a double-clicked executable or ``python discovery.py`` runs.

Asks for the minimum (where to read from, how to sign in, where to write) and calls the same
``cli.execute`` -> ``service.run_discovery`` path as the command line. Without a terminal only
the input question is asked; every other question takes its default.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from pydantic import SecretStr
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from dbx_premig.errors import DiscoveryError
from dbx_premig.logging import configure_logging, stderr_console
from dbx_premig.version import APP_NAME, APP_VERSION

__all__ = ["run_interactive"]


def _tty() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def _ask(question: str, default: str = "", *, password: bool = False) -> str:
    if not _tty():
        return default
    if password:
        value = getpass.getpass(f"{question}: ")
        return value.strip() or default
    return Prompt.ask(question, default=default or None, console=stderr_console) or ""


def _pause() -> None:
    """Keep a double-clicked console window open until the user has read the result."""
    if getattr(sys, "frozen", False) and _tty() and os.name == "nt":
        input("\nPress Enter to close...")


def run_interactive() -> int:
    from dbx_premig.cli import execute, print_summary
    from dbx_premig.config import load_settings

    stderr_console.print(
        Panel.fit(
            f"[bold]{APP_NAME}[/] {APP_VERSION}\n"
            "Reads a Databricks workspace (read-only) and writes a discovery workbook for a "
            "Microsoft Fabric migration.",
            border_style="green",
        )
    )
    try:
        if not _tty():
            # Only the input question may be asked without a terminal: read it from stdin.
            line = sys.stdin.readline().strip() if sys.stdin else ""
            mode, source = ("offline", line) if line else ("live", "")
        else:
            choice = Prompt.ask(
                "Scan a [bold]live[/] workspace or an [bold]offline[/] export?",
                choices=["live", "offline"],
                default="live",
                console=stderr_console,
            )
            mode, source = choice, ""
        overrides: dict[str, object] = {}
        input_path: Path | None = None
        if mode == "offline":
            source = source or _ask(
                "Folder / .dbc / .zip export or snapshot .json to read", "exports"
            )
            input_path = Path(source).expanduser()
        else:
            overrides["host"] = (
                _ask(
                    "Workspace URL (e.g. https://adb-123.4.azuredatabricks.net)",
                    os.environ.get("DATABRICKS_HOST", ""),
                )
                or None
            )
            use_sp = _tty() and Confirm.ask(
                "Sign in with a service principal (OAuth) instead of a personal access token?",
                default=False,
                console=stderr_console,
            )
            if use_sp:
                overrides["client_id"] = _ask(
                    "Client id", os.environ.get("DATABRICKS_CLIENT_ID", "")
                )
                secret = _ask("Client secret (hidden)", password=True)
                overrides["client_secret"] = SecretStr(secret) if secret else None
            else:
                token = _ask("Personal access token (hidden)", password=True)
                overrides["token"] = SecretStr(token) if token else None
        out = Path(_ask("Output folder", "output")).expanduser()
        keep = (
            mode == "live"
            and _tty()
            and Confirm.ask(
                "Also save the raw snapshot JSON (contains notebook source)?",
                default=False,
                console=stderr_console,
            )
        )
        settings = load_settings(None, **overrides)
        configure_logging(settings.log_level, verbose=False)
        result = execute(settings, input_path, out, None, keep)
        print_summary(result)
        print(result.workbook)
        assess = not _tty() or Confirm.ask(
            "Also run the assessment (complexity, automation, hours)?",
            default=True,
            console=stderr_console,
        )
        if assess:
            from dbx_premig.cli import print_assessment
            from dbx_premig.service import run_assessment

            assessed = run_assessment(settings, discovery_workbook=result.workbook, output_dir=out)
            print_assessment(assessed)
            print(assessed.workbook)
        _pause()
        return 0
    except DiscoveryError as exc:
        stderr_console.print(f"[bold red]Error:[/] {exc.message}")
        _pause()
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        stderr_console.print("[yellow]Cancelled.[/]")
        return 130
    except Exception as exc:  # a bug: say so plainly, never dump client data
        stderr_console.print(
            f"[bold red]Internal error[/] ({type(exc).__name__}). Run "
            "'discovery discover --verbose ...' for details and report it."
        )
        _pause()
        return 1
