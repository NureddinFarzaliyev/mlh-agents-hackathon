# GitHelper

GitHelper reads the current Git project's staged, unstaged, and untracked changes,
asks a Backboard assistant for a concise [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/)
subject, and offers to execute the commit.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export BACKBOARD_API_KEY="your-api-key"
```

The key is read only from `BACKBOARD_API_KEY`. On its first run the program creates
one Backboard assistant named `GitHelper` and stores its ID in `GitHelper.json`.
Later runs reuse that ID.

## Usage

Run from the project you want to commit:

```bash
python /path/to/git_helper.py
```

Or pass a project directory explicitly:

```bash
python git_helper.py /path/to/project
```

The proposed message and the exact command are printed before confirmation. Answer
`y` or `yes` to stage all changes and commit; any other answer cancels without
creating a commit.
