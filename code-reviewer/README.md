# CodeReviewer

`CodeReviewer` is a Python CLI that sends the current `git diff` to one persistent
Backboard assistant, writes the findings to `issues.json`, and asks for human approval
before applying each proposed fix.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
export BACKBOARD_API_KEY="your-api-key"
```

The key is read only from `BACKBOARD_API_KEY`; it is never stored in the repository.

## Run

Run from the root of the repository whose changes should be reviewed:

```bash
python code_reviewer.py
```

On the first run the app creates exactly one assistant named `CodeReviewer` and saves
its ID in `codeReviewer.json`. Later runs reuse that ID. The current `git diff` is
reviewed and the complete result is saved in `issues.json`. Each issue displays its
severity, location, explanation, and proposed solution. Enter `y` to request and
apply a validated unified diff, or `n` to leave the code unchanged.

The app validates every generated patch with `git apply --check` before applying it.
It prints progress for diff collection, assistant setup, analysis, each decision, and
each patch result.

## Tests

The fake scenario tests JSON review parsing and a human-approved secret-removal patch
without calling Backboard:

```bash
python -m unittest discover -s tests -v
```
