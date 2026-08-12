# TerminalHelper

TerminalHelper turns a natural-language request into Linux Bash commands using
the Backboard SDK. It always displays the complete command text and asks for
confirmation before running anything.

## Setup

From this directory, create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set your Backboard API key in the environment. The key is never stored by the
application:

```bash
export BACKBOARD_API_KEY="your-api-key"
```

## Usage

Pass the prompt as one or more command-line arguments:

```bash
python terminal_helper.py "List all .jpeg files"
```

Review the full commands printed by the program. Enter `y` or `yes` to run
them; any other response cancels the request.

On the first run, the program creates the single Backboard assistant named
`TerminalHelper` and saves its ID in `terminalHelper.json`. Later runs reuse
that ID. Keep this file if you want to continue using the same assistant.
