"""
claude_runner.py

Subprocess wrapper for `claude -p` (Claude Code CLI print mode).
This is how VaultSQL calls Claude without requiring a separate API key —
it uses the Claude Code session the user already has authenticated.

All LLM calls in VaultSQL go through this module.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Literal

ModelTier = Literal[
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

# Default models per task — can be overridden via enrichment.yaml
TASK_MODELS: dict[str, ModelTier] = {
    "anchor_extraction":   "claude-haiku-4-5-20251001",
    "joinability":         "claude-haiku-4-5-20251001",
    "sql_simple":          "claude-haiku-4-5-20251001",
    "sql_medium":          "claude-sonnet-4-6",
    "sql_complex":         "claude-sonnet-4-6",
    "synthesis":           "claude-sonnet-4-6",
    "summarization":       "claude-haiku-4-5-20251001",
    "knowledge_extraction": "claude-haiku-4-5-20251001",
    "reference_detection":  "claude-haiku-4-5-20251001",
}


class ClaudeRunnerError(Exception):
    pass


def run(
    prompt: str,
    task: str = "sql_medium",
    model: ModelTier | None = None,
    system: str | None = None,
    timeout: int = 60,
) -> str:
    """
    Call `claude -p <prompt>` as a subprocess and return stdout as a string.

    Args:
        prompt:  The user prompt to send.
        task:    Task name — used to pick the default model tier.
        model:   Override the model (ignores task default).
        system:  Optional system prompt (prepended to prompt if claude -p
                 doesn't support --system, we inline it).
        timeout: Max seconds to wait for the subprocess.

    Returns:
        Raw stdout string from claude CLI.

    Raises:
        ClaudeRunnerError: if the subprocess fails or times out.
    """
    resolved_model = model or TASK_MODELS.get(task, "claude-sonnet-4-6")

    full_prompt = prompt
    if system:
        full_prompt = f"<system>\n{system}\n</system>\n\n{prompt}"

    cmd = [
        "claude",
        "--print",
        "--model", resolved_model,
        full_prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeRunnerError(
            f"claude CLI timed out after {timeout}s for task '{task}'"
        ) from e
    except FileNotFoundError as e:
        raise ClaudeRunnerError(
            "claude CLI not found. Make sure Claude Code is installed and in PATH."
        ) from e

    if result.returncode != 0:
        raise ClaudeRunnerError(
            f"claude CLI exited with code {result.returncode}.\n"
            f"stderr: {result.stderr.strip()}"
        )

    return result.stdout.strip()


def run_json(
    prompt: str,
    task: str = "sql_medium",
    model: ModelTier | None = None,
    system: str | None = None,
    timeout: int = 60,
) -> Any:
    """
    Same as run() but parses stdout as JSON.

    Use this for structured outputs (anchor extraction, joinability, etc.)
    The prompt should instruct Claude to return valid JSON only.

    Raises:
        ClaudeRunnerError: if output is not valid JSON.
    """
    raw = run(prompt=prompt, task=task, model=model, system=system, timeout=timeout)

    # Strip markdown code fences if Claude wraps output in ```json ... ```
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        cleaned = "\n".join(inner)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ClaudeRunnerError(
            f"Claude returned non-JSON output for task '{task}'.\n"
            f"Raw output: {raw[:500]}"
        ) from e
