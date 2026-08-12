#!/usr/bin/env python3
"""Generate a conventional commit message from a local Git diff."""

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from backboard import BackboardClient


ASSISTANT_FILE = Path(__file__).with_name("GitHelper.json")
ASSISTANT_NAME = "GitHelper"
SYSTEM_PROMPT = """You are GitHelper, an expert at writing concise Conventional Commits.
Given a git diff, return a JSON object with exactly one key, `message`.
The value must be a single conventional commit subject in the form
<type>[optional scope]: <imperative description>. Use a type such as feat, fix,
refactor, docs, test, chore, or build. Keep it under 72 characters,
do not add a body, markdown, quotes, or explanation. Describe only changes shown
in the diff; do not invent details."""


def run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=check
    )


def get_diff(project: Path) -> str:
    """Return staged, unstaged, and untracked project changes."""
    try:
        run_git(["rev-parse", "--show-toplevel"], project)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(f"{project} is not inside a Git repository") from None

    repo_root = Path(run_git(["rev-parse", "--show-toplevel"], project).stdout.strip())
    project_path = project.relative_to(repo_root)
    diff = run_git(["diff", "HEAD", "--", str(project_path)], repo_root).stdout
    untracked = run_git(["ls-files", "--others", "--exclude-standard"], repo_root).stdout
    for name in filter(None, untracked.splitlines()):
        path = repo_root / name
        if path.is_file() and (path == project or project in path.parents):
            diff += f"\n--- Untracked file: {name} ---\n{path.read_text(errors='replace')}\n"
    if not diff.strip():
        raise RuntimeError("No changes found in the Git working tree")
    return diff


async def load_or_create_assistant(client: BackboardClient) -> str:
    """Reuse the persisted assistant; create GitHelper only when needed."""
    if ASSISTANT_FILE.exists():
        try:
            data = json.loads(ASSISTANT_FILE.read_text())
            assistant_id = data.get("assistant_id")
            if assistant_id:
                return assistant_id
        except (OSError, json.JSONDecodeError):
            pass

    # Older backboard-sdk releases do not support the newer ``name`` filter.
    # Listing and filtering locally keeps the CLI compatible with both APIs.
    assistants = await client.list_assistants(limit=100)
    matching = [assistant for assistant in assistants if assistant.name == ASSISTANT_NAME]
    if matching:
        assistant_id = str(matching[0].assistant_id)
    else:
        assistant = await client.create_assistant(name=ASSISTANT_NAME, system_prompt=SYSTEM_PROMPT)
        # The SDK exposes assistant_id as a UUID; persist its string form so
        # GitHelper.json remains valid JSON and can be reused on later runs.
        assistant_id = str(assistant.assistant_id)
    ASSISTANT_FILE.write_text(json.dumps({"assistant_id": assistant_id}, indent=2) + "\n")
    return assistant_id


async def generate_message(client: BackboardClient, assistant_id: str, diff: str) -> str:
    response = await client.send_message(
        "Create the commit subject for this diff:\n\n" + diff,
        assistant_id=assistant_id,
        system_prompt=SYSTEM_PROMPT,
        json_output=True,
    )
    content = response.content
    if isinstance(content, dict):
        message = content.get("message", "")
    else:
        raw = str(content).strip()
        try:
            message = json.loads(raw).get("message", "")
        except (json.JSONDecodeError, AttributeError):
            message = raw.strip("` ").removeprefix("message:").strip()
    message = " ".join(message.splitlines()).strip().strip('"')
    conventional_commit = re.compile(
        r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
        r"(?:\([^)]+\))?!?: .+"
    )
    if not message or len(message) > 72 or not conventional_commit.fullmatch(message):
        raise RuntimeError(f"Assistant returned an invalid commit message: {message!r}")
    return message


def commit(project: Path, message: str) -> None:
    run_git(["add", "-A"], project)
    run_git(["commit", "-m", message], project)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and optionally run a Git commit message.")
    parser.add_argument("project", nargs="?", default=".", help="Git project directory (default: current directory)")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    api_key = os.environ.get("BACKBOARD_API_KEY")
    if not api_key:
        print("Error: BACKBOARD_API_KEY is not set.", file=sys.stderr)
        return 1
    try:
        diff = get_diff(project)
        client = BackboardClient(api_key=api_key)
        assistant_id = await load_or_create_assistant(client)
        message = await generate_message(client, assistant_id, diff)
        command = f"git add -A && git commit -m {shlex.quote(message)}"
        print(f"\nGenerated commit message: {message}")
        print(f"Command: (cd {shlex.quote(str(project))} && {command})")
        answer = input("Execute this command? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Commit cancelled.")
            return 0
        commit(project, message)
        print("Commit created successfully.")
        return 0
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        print(f"Error: {detail.strip()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
