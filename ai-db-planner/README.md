# AI DB Planner

AI DB Planner is a Flask single-page app that uses four persistent Backboard assistants to turn a product idea into business requirements, a reviewed database plan, and a Mermaid ER diagram.

## Run locally

1. Create and activate a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Set the key (never put it in source): `export BACKBOARD_API_KEY="your-key"`
4. Start: `python app.py`
5. Open http://127.0.0.1:5000 and enter a project description.

The first run creates the four assistants and writes their IDs to `agents.json`. Pipeline state is saved to `progress.json`. Both files are local runtime state and are reused on subsequent runs.

## Troubleshooting

The API returns actionable errors in the UI and logs the full exception server-side. If the key is missing, install dependencies or set `BACKBOARD_API_KEY`; if an AI response is not valid JSON, the response preview identifies the responsible agent.
