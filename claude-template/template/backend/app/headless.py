"""Headless agent runs — the second LLM seam, alongside app/llm.py.

app/llm.py wires *in-process* Claude API calls through the Anthropic
SDK. This module wires *agentic* runs: it shells out to the Claude
Code CLI in print mode —

    claude -p "<prompt>" --output-format text

— which gives the prompt tool access (read files, grep, git, ...)
inside a working directory. That is how slash-command workflows like
`/review` or `/security-review` execute against a repository, and the
prompt can just as well be free-form text ("summarize TODOs added
this week").

THE RULE (same spirit as llm.py): every `claude` subprocess in this
codebase is spawned by run_headless(). Auth is the same
ANTHROPIC_API_KEY the SDK uses — the CLI reads it from the env.

Permissions: print mode is non-interactive, so tools that would
normally prompt for approval are denied. Read-oriented workflows
(/review, /security-review) work out of the box. For workflows that
must edit files or run commands, grant capability explicitly per
workflow via `allowed_tools` (e.g. ["Edit", "Bash(git diff:*)"]) or
`extra_args` (e.g. ["--permission-mode", "acceptEdits"]). Never
default to bypassing permissions.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from app.config import settings

# Bound what a single run can store — review transcripts are big.
_MAX_CAPTURE = 200_000


async def run_headless(
    prompt: str,
    *,
    workdir: Optional[str] = None,
    output_format: str = "text",
    model: Optional[str] = None,
    allowed_tools: Optional[list[str]] = None,
    extra_args: Optional[list[str]] = None,
    timeout: float = 1800,
) -> dict:
    """Run one headless Claude Code invocation; return its outcome.

    Returns {"exit_code", "stdout", "stderr", "duration_s"}.
    Never raises on a failed run — the exit code tells the story —
    but does kill the subprocess on timeout.
    """
    cmd = [settings.claude_bin, "-p", prompt, "--output-format", output_format]
    if model:
        cmd += ["--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    cmd += list(extra_args or [])

    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workdir or settings.workflow_workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"timed out after {timeout:.0f}s",
            "duration_s": round(time.monotonic() - started, 1),
        }

    return {
        "exit_code": proc.returncode,
        "stdout": out.decode(errors="replace")[:_MAX_CAPTURE],
        "stderr": err.decode(errors="replace")[:_MAX_CAPTURE],
        "duration_s": round(time.monotonic() - started, 1),
    }
