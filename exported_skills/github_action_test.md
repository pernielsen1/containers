# github_action_test skill

Create a GitHub Action that watches a `todo/` directory and processes uploaded files using a Python script.

## What this skill does

When invoked, create the following files in the current working directory:

### 1. `handle_todo.py`
Python script that:
- Takes file paths as CLI arguments
- Reads each file as ASCII text
- Converts all content to uppercase
- Writes a copy to `next_step/` with a unique filename: `<basename>_CCYYMMDD.HH-MM-SS.<ext>`
- Creates `next_step/` if it doesn't exist

### 2. `handle_todo_workflow.yml`
GitHub Actions workflow definition:
- **Trigger:** `on: push: paths: ['todo/**']` — fires only when files are pushed to `todo/`
- Detects newly added files in the push via `git diff --diff-filter=A`
- Runs `python3 handle_todo.py <new_files>`
- Commits results back to `next_step/` with `[skip ci]` to prevent loops
- Uses `permissions: contents: write`

### 3. `setup_github_action.py`
Deployment script:
- Accepts `--repo REPO_NAME` (default: `todo-action-demo`)
- Prompts for GitHub username interactively
- Prompts for Personal Access Token via `getpass` (hidden input)
  - NOTE: GitHub dropped plain-password API auth in 2021; PAT with `repo` scope is required
- Verifies credentials via `/user` API endpoint
- Creates the GitHub repository if it doesn't exist (via POST `/user/repos`)
- Uploads all four files via GitHub Contents API (PUT `/repos/.../contents/...`)
- Handles existing files by fetching their SHA for updates

### 4. `todo/.gitkeep` and `next_step/.gitkeep`
Empty placeholder files to preserve directory structure in git.

## Usage

Run the skill, then deploy:
```bash
python3 setup_github_action.py [--repo my-repo-name]
```

The script will prompt for username and PAT, then create and configure the GitHub repository.

## Key design decisions
- Workflow is trigger-based: only runs on push to `todo/**`, never on a schedule
- Only newly added files (not pre-existing ones) are processed per push
- `[skip ci]` on the commit-back prevents infinite action loops
- PAT is read via `getpass` so it never appears in terminal history
- Uses only Python stdlib (`urllib`, `base64`, `getpass`, `pathlib`) — no dependencies
