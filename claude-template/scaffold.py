#!/usr/bin/env python3
"""Stamp out a new Claude-mediated app from the template/ directory.

Single-file Click CLI in the spirit of Simon Willison's `click-app`
cookiecutter: one command, sensible defaults, ready to run.

Usage:
    pip install click
    python scaffold.py new my-app
    python scaffold.py new my-api --no-frontend
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import click

TEMPLATE = Path(__file__).resolve().parent / "template"
TOKEN = "__app_name__"
FRONTEND_BLOCK = re.compile(
    r"^\s*# --frontend-start.*?# --frontend-end\n", re.DOTALL | re.MULTILINE
)


@click.group()
def cli():
    """Scaffold Claude-mediated applications."""


@cli.command()
@click.argument("name")
@click.option(
    "--dir",
    "target_dir",
    default=".",
    show_default=True,
    help="Parent directory to create the project in.",
)
@click.option(
    "--no-frontend",
    is_flag=True,
    help="Backend-only scaffold (drops the React frontend).",
)
def new(name: str, target_dir: str, no_frontend: bool):
    """Create a new project NAME from the template."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not slug:
        raise click.ClickException(f"Cannot derive a project slug from {name!r}")

    dest = Path(target_dir) / slug
    if dest.exists():
        raise click.ClickException(f"{dest} already exists — refusing to overwrite")

    shutil.copytree(TEMPLATE, dest)

    if no_frontend:
        shutil.rmtree(dest / "frontend")
        compose = dest / "docker-compose.yml"
        compose.write_text(FRONTEND_BLOCK.sub("", compose.read_text()))

    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue  # binary file — nothing to substitute
        if TOKEN in text:
            path.write_text(text.replace(TOKEN, slug))

    click.secho(f"Created {dest}/", fg="green")
    click.echo("Next steps:")
    click.echo(f"  cd {dest}")
    click.echo("  cp .env.example .env    # paste your ANTHROPIC_API_KEY")
    click.echo("  docker compose up --build")


if __name__ == "__main__":
    cli()
