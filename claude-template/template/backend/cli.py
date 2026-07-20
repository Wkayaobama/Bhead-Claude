#!/usr/bin/env python3
"""Ad-hoc CLI — the third entry point over the same two LLM seams.

No FastAPI, no server, no scheduler: this is for one-off invocations
from a terminal, a cron job, or a CI step, equivalent to
`bun run headless/claude-chat.ts "..."` setups:

    python backend/cli.py chat  "Summarize RFC 9110 in three bullets"
    python backend/cli.py agent "List all TypeScript errors in src/"
    python backend/cli.py agent "/review" --workdir ~/code/other-repo
    python backend/cli.py workflow "Code review"

`chat` goes through seam #1 (app/llm.py — Anthropic SDK, streams to
stdout). `agent` goes through seam #2 (app/headless.py — Claude Code
CLI with tool access in --workdir, default: current directory).
`workflow` runs a registered workflow definition once, in the
foreground, without the server (ad-hoc runs are not written to the
run history — only server-triggered runs are).

Auth is the same ANTHROPIC_API_KEY as everywhere else; run from the
project root so pydantic-settings finds `.env`, or export the var.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Allow running from anywhere: `python backend/cli.py ...`
sys.path.insert(0, str(Path(__file__).resolve().parent))

import click


@click.group()
def cli():
    """__app_name__ — ad-hoc Claude invocations (no server needed)."""


@cli.command()
@click.argument("message")
@click.option("--system", default=None, help="System prompt.")
@click.option("--model", default=None, help="Override AI_MODEL for this call.")
def chat(message: str, system: str | None, model: str | None):
    """One streamed chat turn via the Anthropic SDK (seam #1)."""
    from app.llm import stream_chat

    async def run():
        async for chunk in stream_chat(
            user_message=message, system_prompt=system, model=model
        ):
            print(chunk, end="", flush=True)
        print()

    asyncio.run(run())


@cli.command()
@click.argument("prompt")
@click.option(
    "--workdir",
    default=".",
    show_default=True,
    help="Directory the agent works in (it can read files, grep, run git there).",
)
@click.option(
    "--output-format",
    default="text",
    show_default=True,
    type=click.Choice(["text", "json", "stream-json"]),
)
@click.option("--timeout", default=1800.0, show_default=True, help="Seconds before the run is killed.")
def agent(prompt: str, workdir: str, output_format: str, timeout: float):
    """One headless agent run via the Claude Code CLI (seam #2).

    PROMPT is a slash command (/review, /security-review) or free-form
    text. Exit code mirrors the run's exit code.
    """
    from app.headless import run_headless

    result = asyncio.run(
        run_headless(
            prompt, workdir=workdir, output_format=output_format, timeout=timeout
        )
    )
    print(result["stdout"], end="")
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr)
    sys.exit(0 if result["exit_code"] == 0 else 1)


@cli.command()
@click.argument("name_or_id")
@click.option(
    "--workdir",
    default=".",
    show_default=True,
    help="Directory to run in (the server uses WORKFLOW_WORKDIR instead).",
)
@click.option("--as-json", is_flag=True, help="Print the full run result as JSON.")
def workflow(name_or_id: str, workdir: str, as_json: bool):
    """Run a registered workflow once, in the foreground."""
    from app import workflows as wf
    from app.headless import run_headless

    record = wf.find_workflow(name_or_id)
    if not record:
        known = ", ".join(w["name"] for w in wf.load_workflows())
        raise click.ClickException(f"no workflow {name_or_id!r} (known: {known})")

    result = asyncio.run(
        run_headless(
            record["prompt"],
            workdir=workdir,
            model=record.get("model"),
            allowed_tools=record.get("allowed_tools"),
            extra_args=record.get("extra_args"),
        )
    )
    if as_json:
        print(json.dumps({"workflow": record["name"], **result}, indent=2))
    else:
        print(result["stdout"], end="")
        if result["stderr"]:
            print(result["stderr"], file=sys.stderr)
    sys.exit(0 if result["exit_code"] == 0 else 1)


if __name__ == "__main__":
    cli()
