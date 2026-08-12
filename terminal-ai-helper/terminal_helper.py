#!/usr/bin/env python3
"""Translate a natural-language request into bash, then run it after approval."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from backboard import BackboardClient


ASSISTANT_NAME = "TerminalHelper"
ASSISTANT_FILE = Path(__file__).with_name("terminalHelper.json")
SYSTEM_PROMPT = """You translate the user's request into Linux bash commands.
Return ONLY the commands to execute, with no explanation, markdown, or commentary.
Commands must be complete and safe for the user's stated request. Use the current
working directory. Never use sudo, destructive commands (such as rm, rmdir,
mkfs, dd, shutdown, reboot, or a disk overwrite), or commands that download or
execute remote code. If the request is ambiguous or cannot safely be fulfilled,
return a single command that prints an explanation and does not change anything.
"""


def load_assistant_id() -> str | None:
    if not ASSISTANT_FILE.exists():
        return None
    try:
        data = json.loads(ASSISTANT_FILE.read_text(encoding="utf-8"))
        assistant_id = data.get("assistant_id")
        return assistant_id if isinstance(assistant_id, str) and assistant_id else None
    except (OSError, json.JSONDecodeError):
        return None


def save_assistant_id(assistant_id: str) -> None:
    ASSISTANT_FILE.write_text(
        json.dumps({"assistant_id": assistant_id}, indent=2) + "\n",
        encoding="utf-8",
    )


async def get_assistant_id(client: BackboardClient) -> str:
    assistant_id = load_assistant_id()
    if assistant_id:
        return assistant_id

    # Resolve by exact name before creating so a deleted/corrupt local ID does
    # not create a second TerminalHelper assistant.
    assistants = await client.list_assistants(limit=100)
    existing = next(
        (candidate for candidate in assistants if candidate.name == ASSISTANT_NAME),
        None,
    )
    if existing is not None:
        assistant = existing
    else:
        assistant = await client.create_assistant(
            name=ASSISTANT_NAME,
            system_prompt=SYSTEM_PROMPT,
        )
    # The SDK model exposes assistant_id as a UUID, while the persistence file
    # must contain plain JSON-compatible text.
    assistant_id = str(assistant.assistant_id)
    save_assistant_id(assistant_id)
    return assistant_id


def normalize_commands(content: str) -> str:
    """Remove accidental markdown wrappers while preserving every command byte."""
    content = content.strip()
    fenced = re.fullmatch(r"```(?:bash|sh|shell|linux)?\s*\n?(.*?)\n?```", content, re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1)
    return content.strip()


async def translate(prompt: str) -> str:
    api_key = os.environ.get("BACKBOARD_API_KEY")
    if not api_key:
        raise RuntimeError("BACKBOARD_API_KEY is not set.")

    client = BackboardClient(api_key=api_key)
    assistant_id = await get_assistant_id(client)
    response = await client.send_message(
        prompt,
        assistant_id=assistant_id,
        system_prompt=SYSTEM_PROMPT,
        json_output=False,
    )
    return normalize_commands(response.content)


def confirm_and_run(commands: str) -> int:
    if not commands:
        print("The assistant returned no commands.", file=sys.stderr)
        return 1

    print("Commands to run:")
    print("----------------------------------------")
    print(commands)
    print("----------------------------------------")
    try:
        answer = input("Run these commands? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0
    if answer.strip().lower() not in {"y", "yes"}:
        print("Cancelled.")
        return 0

    completed = subprocess.run(["bash", "-c", commands], check=False)
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate prompts into confirmed Linux commands.")
    parser.add_argument("prompt", nargs="+", help="Natural-language task for the terminal assistant")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        commands = asyncio.run(translate(" ".join(args.prompt)))
        return confirm_and_run(commands)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
