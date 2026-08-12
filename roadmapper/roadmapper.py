#!/usr/bin/env python3
"""Generate a learning roadmap in one Backboard thread."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from backboard import BackboardClient


ROOT = Path(__file__).resolve().parent
ASSISTANT_FILE = ROOT / "roadmapper.json"

SYSTEM_PROMPT = """You are Roadmapper, an expert learning-roadmap researcher and editor.
Build practical, accurate, step-by-step learning roadmaps. Prefer authoritative,
current sources and include direct URLs. Follow each stage's instructions exactly.
Do not invent links. Keep the user's requested scope in mind."""

STAGES = [
    ("🔎 RESEARCH", "The browser has put on its tiny detective hat.", "research"),
    ("🧭 ANGLE", "We are throwing out the knowledge-shaped potatoes.", "angle"),
    ("✍️ WRITE", "The keyboard is warming up its storytelling muscles.", "write"),
    ("🪜 ORDER", "The skills are lining up like ducks with a curriculum.", "order"),
    ("💾 SAVE", "The roadmap is packing its bags for Markdown town.", "save"),
]


def load_or_create_assistant_id(client: BackboardClient) -> str:
    if ASSISTANT_FILE.exists():
        try:
            data = json.loads(ASSISTANT_FILE.read_text())
            assistant_id = data.get("assistant_id")
            if assistant_id:
                return assistant_id
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read {ASSISTANT_FILE}: {exc}") from exc

    async def create():
        return await client.create_assistant(
            name="Roadmapper",
            system_prompt=SYSTEM_PROMPT,
            tok_k=25,
        )

    assistant = run_with_retry(create, "creating the Roadmapper assistant")
    assistant_id = getattr(assistant, "assistant_id", None)
    if not assistant_id:
        raise RuntimeError("Backboard created an assistant but returned no assistant_id.")
    assistant_id = str(assistant_id)
    ASSISTANT_FILE.write_text(json.dumps({"assistant_id": assistant_id}, indent=2) + "\n")
    return assistant_id


def run_with_retry(operation, description):
    last_error = None
    for attempt in (1, 2):
        try:
            return asyncio.run(operation())
        except Exception as exc:  # SDK errors vary by provider and version.
            last_error = exc
            # if attempt == 1:
                # print(f"⚠️ {description} failed; retrying once...", file=sys.stderr)
    raise RuntimeError(
        f"Backboard API error while {description}. Tried twice. "
        f"Technical detail: {type(last_error).__name__}: {last_error}"
    ) from last_error


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug or "topic"


def stage_prompt(stage: str, topic: str) -> str:
    if stage == "research":
        return f"""RESEARCH stage for the user's topic: {topic!r}.
Use web search and identify 10 to 25 of the most important things to learn.
For every item, include its name, why it matters, and all relevant direct links
to documentation, articles, or courses. Return a clearly numbered research list.
This is research material for the next stages, not the final roadmap."""
    if stage == "angle":
        return """ANGLE stage. Review the research you just produced for relevance,
importance, accuracy, and suitability for the user's exact request. Discard items
that are highly irrelevant, misleading, duplicates, or too advanced for the path.
Keep useful links and explain any important pruning decisions. Return the curated
list, preserving useful source URLs."""
    if stage == "write":
        return """WRITE stage. Turn the curated list into roadmap step material.
For each skill, write: the skill name, a brief explanation, why it is necessary,
then all relevant source links. Be concrete and learner-friendly. Do not reorder
or number the items yet."""
    if stage == "order":
        return """ORDER stage. Sort the written skills into a natural, step-by-step
learning progression, from prerequisites to advanced application. Add numbers
before every step (1., 2., etc.). Preserve each step's explanation, rationale,
and source links. Return only the complete ordered roadmap."""
    return f"""SAVE stage for topic {topic!r}. Using the ordered roadmap in the
conversation, produce the final Markdown file contents. Include a title and a
short overview, followed by every numbered step with its explanation, why it is
necessary, and source links. Output ONLY Markdown—no preamble, no code fences,
no discussion of this instruction."""


def main(topic: str) -> None:
    if not os.environ.get("BACKBOARD_API_KEY"):
        raise RuntimeError("BACKBOARD_API_KEY is not set. Export your Backboard API key and retry.")

    client = BackboardClient(api_key=os.environ["BACKBOARD_API_KEY"])
    assistant_id = load_or_create_assistant_id(client)
    thread_id = None
    final_markdown = None

    for label, joke, stage in STAGES:
        print(f"{label}: {joke}")

        async def send():
            kwargs = {
                "assistant_id": assistant_id,
                "web_search": "Auto" if stage == "research" else "off",
                "memory": "off",
            }
            if thread_id:
                kwargs["thread_id"] = thread_id
            return await client.send_message(stage_prompt(stage, topic), **kwargs)

        response = run_with_retry(send, f"running {stage} stage")
        thread_id = getattr(response, "thread_id", None) or thread_id
        content = getattr(response, "content", None)
        if not content:
            raise RuntimeError(f"Backboard returned no content for the {stage} stage.")
        if stage == "save":
            final_markdown = content.strip()

    output_path = ROOT / f"roadmap-{slugify(topic)}.md"
    output_path.write_text(final_markdown + "\n", encoding="utf-8")
    lines = [line for line in final_markdown.splitlines() if line.strip()]
    steps = sum(bool(re.match(r"^\s*\d+[.)]\s+", line)) for line in lines)
    print(f"✅ Roadmap saved to: {output_path}")
    print(f"Summary: {steps} ordered learning steps for {topic}; {len(lines)} non-empty Markdown lines.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: python roadmapper.py "topic and other details here"', file=sys.stderr)
        raise SystemExit(2)
    try:
        main(sys.argv[1].strip())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
