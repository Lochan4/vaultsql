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

from core import token_counter

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
    chat_id: str | None = None,
    db_alias: str | None = None,
) -> str:
    """
    Call `claude -p <prompt> --output-format json` as a subprocess and return
    the result text. Token usage and cost are recorded to the usage log.

    Args:
        prompt:    The user prompt to send.
        task:      Task name — used to pick the default model tier.
        model:     Override the model (ignores task default).
        system:    Optional system prompt (inlined before prompt).
        timeout:   Max seconds to wait for the subprocess.
        chat_id:   Optional — tags the usage record to a session.
        db_alias:  Optional — tags the usage record to a connection.

    Returns:
        Text output from Claude.

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
        "--output-format", "json",
        "--model", resolved_model,
        full_prompt,
    ]

    try:
        proc = subprocess.run(
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

    if proc.returncode != 0:
        raise ClaudeRunnerError(
            f"claude CLI exited with code {proc.returncode}.\n"
            f"stderr: {proc.stderr.strip()}"
        )

    raw = proc.stdout.strip()

    # Parse the JSON envelope returned by --output-format json
    # Expected shape: { "result": "...", "total_cost_usd": 0.001,
    #                   "usage": { "input_tokens": N, "output_tokens": M } }
    try:
        envelope = json.loads(raw)
        text_out = envelope.get("result", raw)

        # Extract usage for accounting (best-effort — never raise)
        try:
            usage     = envelope.get("usage") or {}
            cost_usd  = envelope.get("total_cost_usd") or envelope.get("cost_usd")
            token_counter.record(
                task_type=task,
                model=resolved_model,
                cost_usd=cost_usd,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                chat_id=chat_id,
                db_alias=db_alias,
            )
        except Exception:
            pass

        return str(text_out).strip()

    except json.JSONDecodeError:
        # CLI didn't return JSON (older version or flag unsupported) — use raw text
        return raw


def run_json(
    prompt: str,
    task: str = "sql_medium",
    model: ModelTier | None = None,
    system: str | None = None,
    timeout: int = 60,
    chat_id: str | None = None,
    db_alias: str | None = None,
) -> Any:
    """
    Same as run() but parses stdout as JSON.

    Use this for structured outputs (anchor extraction, joinability, etc.)
    The prompt should instruct Claude to return valid JSON only.

    Raises:
        ClaudeRunnerError: if output is not valid JSON.
    """
    raw = run(
        prompt=prompt, task=task, model=model, system=system,
        timeout=timeout, chat_id=chat_id, db_alias=db_alias,
    )

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
