"""
setup_github_action.py
======================
Creates (or updates) a GitHub repository with the todo-handler GitHub Action.

What it does
------------
1. Prompts for your GitHub username and Personal Access Token (PAT).
   NOTE: GitHub dropped plain-password API auth in 2021.
         You need a PAT with the 'repo' scope.
         Create one at: https://github.com/settings/tokens
2. Creates the target repository if it does not exist yet.
3. Pushes the required files:
     handle_todo.py
     todo/.gitkeep
     next_step/.gitkeep
     .github/workflows/handle_todo.yml
4. Prints the repository URL when done.

Usage
-----
    python3 setup_github_action.py [--repo REPO_NAME]

    --repo   Repository name to create/update (default: todo-action-demo)
"""

import argparse
import base64
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WORKFLOW_FILE = Path(__file__).parent / "handle_todo_workflow.yml"
SCRIPT_FILE   = Path(__file__).parent / "handle_todo.py"

GITKEEP = ""  # empty placeholder


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, username: str, token: str) -> None:
        self.username = username
        creds = base64.b64encode(f"{username}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type":  "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url  = self.BASE + path
        data = json.dumps(body).encode() if body else None
        req  = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err = json.loads(exc.read())
            raise RuntimeError(f"GitHub API {exc.code}: {err.get('message', exc.reason)}") from exc

    def get_repo(self, repo: str) -> dict | None:
        try:
            return self._request("GET", f"/repos/{self.username}/{repo}")
        except RuntimeError as exc:
            if "404" in str(exc):
                return None
            raise

    def create_repo(self, repo: str, description: str = "") -> dict:
        return self._request("POST", "/user/repos", {
            "name":        repo,
            "description": description,
            "private":     False,
            "auto_init":   True,          # creates main branch with README
        })

    def get_file_sha(self, repo: str, path: str) -> str | None:
        """Return the blob SHA of an existing file (needed for updates)."""
        try:
            info = self._request("GET", f"/repos/{self.username}/{repo}/contents/{path}")
            return info.get("sha")
        except RuntimeError:
            return None

    def put_file(self, repo: str, path: str, content: str, message: str) -> None:
        sha = self.get_file_sha(repo, path)
        body: dict = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        self._request("PUT", f"/repos/{self.username}/{repo}/contents/{path}", body)
        print(f"  uploaded: {path}")


# ---------------------------------------------------------------------------
# Main setup logic
# ---------------------------------------------------------------------------

def setup(repo_name: str) -> None:
    print("=== GitHub Action setup ===\n")

    # --- credentials --------------------------------------------------------
    username = input("GitHub username: ").strip()
    if not username:
        sys.exit("Username is required.")

    print("\nNOTE: GitHub requires a Personal Access Token (PAT) instead of your")
    print("      account password for API access.")
    print("      Create a PAT with 'repo' scope at: https://github.com/settings/tokens\n")
    token = getpass.getpass("Personal Access Token (input hidden): ").strip()
    if not token:
        sys.exit("Token is required.")

    client = GitHubClient(username, token)

    # --- verify credentials -------------------------------------------------
    print("\nVerifying credentials …")
    try:
        me = client._request("GET", "/user")
        print(f"  Authenticated as: {me['login']}")
    except RuntimeError as exc:
        sys.exit(f"Authentication failed: {exc}")

    # --- create repo if needed ----------------------------------------------
    print(f"\nChecking repository '{repo_name}' …")
    repo_info = client.get_repo(repo_name)
    if repo_info is None:
        print(f"  Repository not found — creating '{repo_name}' …")
        repo_info = client.create_repo(
            repo_name,
            description="Todo-handler GitHub Action demo",
        )
        print(f"  Created: {repo_info['html_url']}")
    else:
        print(f"  Found: {repo_info['html_url']}")

    # --- upload files -------------------------------------------------------
    print("\nUploading files …")

    client.put_file(
        repo_name,
        "handle_todo.py",
        SCRIPT_FILE.read_text(encoding="utf-8"),
        "chore: add handle_todo.py processor",
    )

    client.put_file(
        repo_name,
        "todo/.gitkeep",
        GITKEEP,
        "chore: add todo/ directory",
    )

    client.put_file(
        repo_name,
        "next_step/.gitkeep",
        GITKEEP,
        "chore: add next_step/ directory",
    )

    client.put_file(
        repo_name,
        ".github/workflows/handle_todo.yml",
        WORKFLOW_FILE.read_text(encoding="utf-8"),
        "ci: add handle_todo GitHub Action workflow",
    )

    # --- done ---------------------------------------------------------------
    print(f"\nDone!  Repository: {repo_info['html_url']}")
    print("Upload any .txt file to the todo/ directory to trigger the action.")


# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default="todo-action-demo", help="Repository name (default: todo-action-demo)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup(args.repo)
