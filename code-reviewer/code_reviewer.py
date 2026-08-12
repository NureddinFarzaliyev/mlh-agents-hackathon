"""Human-approved code review CLI backed by Backboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ASSISTANT_NAME = "CodeReviewer"
ASSISTANT_FILE = Path("codeReviewer.json")
ISSUES_FILE = Path("issues.json")
SYSTEM_PROMPT = """You are CodeReviewer, a careful senior software engineer.
Review only the supplied git diff. Find concrete bugs, vulnerabilities, and worthwhile
improvements. Do not invent issues. Return valid JSON only in this shape:
{"issues": [{"title": str, "severity": "low|medium|high|critical", "file": str,
"line": str, "description": str, "solution": str}]}
Solutions must be actionable and limited to the supplied changes.
"""


def response_content(response: Any) -> str:
    """Get response text from either SDK objects or test doubles."""
    if isinstance(response, dict):
        return str(response.get("content", ""))
    return str(getattr(response, "content", response))


def response_value(response: Any, name: str) -> str | None:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)


def identifier_value(response: Any, name: str) -> str | None:
    """Return SDK identifiers as strings so they can be persisted and reused."""
    value = response_value(response, name)
    return str(value) if value is not None else None


def parse_json_response(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1])
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Backboard returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("issues"), list):
        raise ValueError("Backboard response must contain an 'issues' list")
    return value


def run_git_diff() -> str:
    result = subprocess.run(
        ["git", "diff"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


async def load_or_create_assistant(client: Any, assistant_file: Path, printer: Callable[[str], None]) -> str:
    if assistant_file.exists():
        data = json.loads(assistant_file.read_text(encoding="utf-8"))
        assistant_id = data.get("assistant_id")
        if assistant_id:
            printer(f"[assistant] Reusing CodeReviewer ({assistant_id})")
            return assistant_id
        raise ValueError(f"{assistant_file} does not contain assistant_id")

    # Resolve by exact name first as a guard against a deleted local metadata file.
    # Older SDK releases do not accept a name filter, so filter the returned page
    # locally rather than relying on a version-specific keyword argument.
    assistants = await client.list_assistants(limit=200)
    existing = next(
        (assistant for assistant in assistants if response_value(assistant, "name") == ASSISTANT_NAME),
        None,
    )
    if existing:
        assistant_id = identifier_value(existing, "assistant_id")
        if assistant_id:
            save_json(assistant_file, {"assistant_id": assistant_id, "name": ASSISTANT_NAME})
            printer(f"[assistant] Found and saved existing CodeReviewer ({assistant_id})")
            return assistant_id

    printer("[assistant] Creating CodeReviewer...")
    assistant = await client.create_assistant(name=ASSISTANT_NAME, system_prompt=SYSTEM_PROMPT)
    assistant_id = identifier_value(assistant, "assistant_id")
    if not assistant_id:
        raise RuntimeError("Backboard did not return an assistant_id")
    save_json(assistant_file, {"assistant_id": assistant_id, "name": ASSISTANT_NAME})
    printer(f"[assistant] Saved assistant ID to {assistant_file}")
    return assistant_id


def apply_patch(patch: str, printer: Callable[[str], None]) -> None:
    patch = patch.strip()
    if patch.startswith("```") and patch.endswith("```"):
        patch = "\n".join(patch.splitlines()[1:-1]).strip()
    if not patch.strip():
        raise ValueError("The proposed solution did not contain a patch")
    patch += "\n"
    check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=error"],
        input=patch, text=True, capture_output=True, check=False,
    )
    if check.returncode:
        raise RuntimeError(f"Proposed patch failed validation: {check.stderr.strip()}")
    subprocess.run(
        ["git", "apply", "--whitespace=error"], input=patch, text=True, check=True
    )
    printer("[fix] Patch applied successfully")


async def review(diff: str, client: Any, assistant_id: str) -> tuple[dict[str, Any], str | None]:
    prompt = f"Review this current git diff and return the requested JSON.\n\n```diff\n{diff}\n```"
    response = await client.send_message(prompt, assistant_id=assistant_id, json_output=True)
    return parse_json_response(response_content(response)), response_value(response, "thread_id")


async def request_fix(client: Any, assistant_id: str, thread_id: str | None, issue: dict[str, Any]) -> str:
    prompt = f"""The human approved this issue:
{json.dumps(issue, indent=2)}

Return only a valid unified git diff patch that fixes this issue. Do not include markdown fences,
explanations, or changes unrelated to the issue. The patch must apply from the repository root."""
    response = await client.send_message(
        prompt, assistant_id=assistant_id, thread_id=thread_id, json_output=False
    )
    return response_content(response)


def ask_user(issue: dict[str, Any], index: int, total: int, input_fn: Callable[[str], str]) -> bool:
    print(f"\n[issue {index}/{total}] {issue.get('title', 'Untitled')} ({issue.get('severity', 'unknown')})")
    print(f"Location: {issue.get('file', 'unknown')}:{issue.get('line', 'unknown')}")
    print(f"Problem: {issue.get('description', '')}")
    print(f"Possible solution: {issue.get('solution', '')}")
    while True:
        choice = input_fn("Apply this fix? [y]es/[n]o: ").strip().lower()
        if choice in {"y", "yes"}:
            return True
        if choice in {"n", "no", ""}:
            return False
        print("Please enter y or n.")


async def run_app(args: argparse.Namespace) -> int:
    print("[start] CodeReviewer is starting")
    if not os.environ.get("BACKBOARD_API_KEY"):
        print("[error] BACKBOARD_API_KEY is not set", file=sys.stderr)
        return 1
    diff = run_git_diff()
    print(f"[diff] Collected {len(diff)} characters")
    if not diff.strip():
        print("[done] No current changes to review")
        save_json(args.issues_file, {"issues": []})
        return 0

    try:
        from backboard import BackboardClient

        client = BackboardClient(api_key=os.environ["BACKBOARD_API_KEY"])
        assistant_id = await load_or_create_assistant(client, args.assistant_file, print)
        print("[review] Asking CodeReviewer to analyze the diff...")
        review_result, thread_id = await review(diff, client, assistant_id)
        save_json(args.issues_file, review_result)
        issues = review_result["issues"]
        print(f"[review] Saved {len(issues)} issue(s) to {args.issues_file}")
        for index, issue in enumerate(issues, 1):
            if not ask_user(issue, index, len(issues), input):
                print("[skip] Issue ignored")
                continue
            print("[fix] Requesting an exact patch from CodeReviewer...")
            patch = await request_fix(client, assistant_id, thread_id, issue)
            apply_patch(patch, print)
        print("[done] Review complete")
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Review current git changes with human-approved fixes.")
    parser.add_argument("--assistant-file", type=Path, default=ASSISTANT_FILE)
    parser.add_argument("--issues-file", type=Path, default=ISSUES_FILE)
    return asyncio.run(run_app(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
