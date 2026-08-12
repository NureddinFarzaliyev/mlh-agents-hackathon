import asyncio
import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request

try:
    from backboard import BackboardClient
except ImportError:  # Helpful error is returned by the API instead of a cryptic import crash.
    BackboardClient = None

BASE_DIR = Path(__file__).resolve().parent
AGENTS_FILE = BASE_DIR / "agents.json"
PROGRESS_FILE = BASE_DIR / "progress.json"
app = Flask(__name__)

AGENT_SPECS = [
    ("business_requirements_decider", "Business Requirements Decider", "You turn a product idea into a complete business requirements JSON. Ask only essential questions, maximum three, and return strict JSON with business_requirements and optionally questions. If answers are supplied, incorporate them and omit questions and answers."),
    ("initial_database_planner", "Initial Database Planner", "You design a database from business requirements. Return strict JSON with initial_plan as plain English covering entities, properties, relationships, primary keys, constraints, and indexes. If initial_plan_revise exists, apply it and omit that field."),
    ("initial_reviewer", "Initial Reviewer", "You audit the complete JSON and initial_plan against the business requirements. Return strict JSON. If changes are needed, provide initial_plan_revise with at most three concise, actionable revision requests; otherwise set review_status to approved. Do not invent requirements."),
    ("mermaid_writer", "Mermaid Writer", "Convert initial_plan into valid Mermaid ER diagram syntax. Return strict JSON with mermaid containing only the Mermaid text (starting with erDiagram). Keep entity and relationship names Mermaid-safe."),
]


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc


def write_json(path, value):
    try:
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        raise RuntimeError(f"Could not save {path.name}: {exc}") from exc


async def ensure_agents():
    if BackboardClient is None:
        raise RuntimeError("The backboard-sdk package is not installed. Run: pip install -r requirements.txt")
    key = os.environ.get("BACKBOARD_API_KEY")
    if not key:
        raise RuntimeError("BACKBOARD_API_KEY is not set. Export your Backboard API key before starting the app.")
    agents = read_json(AGENTS_FILE, {})
    client = BackboardClient(api_key=key)
    for key_name, name, prompt in AGENT_SPECS:
        if key_name not in agents:
            assistant = await client.create_assistant(name=name, system_prompt=prompt)
            assistant_id = getattr(assistant, "assistant_id", None) or assistant.get("assistant_id")
            agents[key_name] = str(assistant_id)
    write_json(AGENTS_FILE, agents)
    return agents


def parse_response(content, agent_name):
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    candidate = fenced.group(1).strip() if fenced else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"{agent_name} returned invalid JSON. Raw response: {text[:500]}")


async def ask(client, assistant_id, agent_name, payload):
    instruction = (
        "Work on this workflow state. Return ONLY a valid JSON object, with no markdown. "
        "Preserve useful existing fields and update only your assigned fields.\n\n" +
        json.dumps(payload, indent=2, ensure_ascii=False)
    )
    response = await client.send_message(instruction, assistant_id=assistant_id, json_output=True)
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    return parse_response(content, agent_name)


async def run_pipeline(topic, answers=None):
    agents = await ensure_agents()
    client = BackboardClient(api_key=os.environ["BACKBOARD_API_KEY"])
    state = {"project": topic, "workflow": {"step": 1, "description": "Business requirements"}}
    if answers:
        state["answers"] = answers
    state.update(await ask(client, agents["business_requirements_decider"], "Business Requirements Decider", state))
    # Questions are deliberately bounded even if a model ignores its instruction.
    if isinstance(state.get("questions"), list):
        state["questions"] = state["questions"][:3]
    write_json(PROGRESS_FILE, state)
    if state.get("questions"):
        return state
    state.pop("questions", None)
    state.pop("answers", None)

    state["workflow"] = {"step": 2, "description": "Initial database plan"}
    state.update(await ask(client, agents["initial_database_planner"], "Initial Database Planner", state))
    write_json(PROGRESS_FILE, state)
    for revision_number in range(3):
        state["workflow"] = {"step": 3, "description": "Reviewing database plan", "revision": revision_number}
        review = await ask(client, agents["initial_reviewer"], "Initial Reviewer", state)
        if isinstance(review.get("initial_plan_revise"), list):
            review["initial_plan_revise"] = review["initial_plan_revise"][:3]
        state.update(review)
        write_json(PROGRESS_FILE, state)
        if not state.get("initial_plan_revise"):
            state["review_status"] = "approved"
            state.pop("initial_plan_revise", None)
            break
        state = {k: v for k, v in state.items() if k != "review_status"}
        state["workflow"] = {"step": 2, "description": "Revising database plan", "revision": revision_number + 1}
        state.update(await ask(client, agents["initial_database_planner"], "Initial Database Planner", state))
        state.pop("initial_plan_revise", None)
        write_json(PROGRESS_FILE, state)
    state["workflow"] = {"step": 4, "description": "Writing Mermaid schema"}
    state.update(await ask(client, agents["mermaid_writer"], "Mermaid Writer", state))
    state["status"] = "complete"
    state["workflow"] = {"step": 4, "description": "Complete"}
    write_json(PROGRESS_FILE, state)
    return state


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/progress")
def progress():
    return jsonify(read_json(PROGRESS_FILE, {}))


@app.post("/api/run")
def run():
    body = request.get_json(silent=True) or {}
    topic = str(body.get("topic", "")).strip()
    if not topic:
        return jsonify(error="Please enter a project or feature description."), 400
    try:
        return jsonify(asyncio.run(run_pipeline(topic)))
    except Exception as exc:
        app.logger.exception("Pipeline failed")
        return jsonify(error=str(exc)), 500


@app.post("/api/answers")
def answers():
    body = request.get_json(silent=True) or {}
    topic, values = str(body.get("topic", "")).strip(), body.get("answers", {})
    if not topic or not isinstance(values, dict):
        return jsonify(error="A topic and an answers object are required."), 400
    try:
        return jsonify(asyncio.run(run_pipeline(topic, values)))
    except Exception as exc:
        app.logger.exception("Pipeline continuation failed")
        return jsonify(error=str(exc)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
