# who_am_i skill

Restore full user context in a new container session.

## What this skill does

When invoked, run the following steps:

### Step 1 — Run the identity script

Execute:
```bash
python3 ~/containers/who_am_i/who_am_i.py
```

This prints the user's identity, environment, preferences, and active project context.

### Step 2 — Ask about seeding memory

Ask the user: "Do you want me to seed the memory files into this project?"

If yes, run:
```bash
python3 ~/containers/who_am_i/who_am_i.py --seed
```

This writes all memory files (`user_environment.md`, `feedback_csv_encoding.md`,
`project_anacredit.md`, `MEMORY.md`) into `~/.claude/projects/<encoded-cwd>/memory/`
so Claude Code picks them up in the next session opened from this directory.

### Step 3 — Confirm

Tell the user which directory the memory was seeded into and remind them to
restart the Claude Code session for the new context to take effect.

## Usage

```
/who_am_i
```

Run this at the start of a new container session.
To export the script to a new machine, copy `~/containers/who_am_i/who_am_i.py` —
it is self-contained and requires only Python 3 stdlib.
