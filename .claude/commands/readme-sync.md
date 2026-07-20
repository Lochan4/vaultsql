# readme-sync

Scan the current project, write or update README.md with current codebase capabilities, then push only if this repo has a single contributor (you + Claude).

## Steps to follow

### 1. Detect the project root
Find the git root: run `git rev-parse --show-toplevel`. All paths below are relative to that.

### 2. Check for existing README
Check if `README.md` exists at the project root.

- **If it does not exist**: Create a new README from scratch (see "README structure" below).
- **If it exists**: Read it, then update any sections that are stale based on what you find in the codebase. Preserve sections you cannot verify (e.g., "License", "Contributing") exactly as-is.

### 3. Scan the codebase for current capabilities
Read enough of the codebase to accurately describe what is *actually implemented* — not planned or aspirational. Key things to look for:
- `api/routes/` or equivalent — list every HTTP endpoint that exists
- `core/` or `src/` — list every module and what it does
- `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` — extract tech stack and versions
- `frontend/` or `client/` — list UI components and their purpose
- `docker-compose.yml` or `Dockerfile` — note deployment options
- `README.md` (if it exists) — note which sections are already accurate vs. stale

Only write about things that are implemented and can be verified in the code. If a feature is partially implemented, describe what portion exists.

### 4. README structure
Follow this structure for a professional GitHub README:

```
# Project Name

One-sentence description.

---

## What It Does
2–3 sentence overview of the core value proposition.

## Key Capabilities
Bullet list of implemented features. Group by theme if there are many.

## Architecture
Directory tree with one-line descriptions per folder/file (important files only).
Include a pipeline/flow diagram if the system has a clear sequential flow.

## API Reference (if applicable)
Table per resource group: Method | Endpoint | Description

## Tech Stack
Table: Component | Technology | Version

## Getting Started
Prerequisites → Install → Configure → Run. Actual commands, no placeholders.

## Configuration
Describe the main config file(s) with a real example snippet.

## Design Principles (optional)
Key architectural decisions and why.

## License
```

### 5. Check contributors before pushing
Run:
```bash
git log --format='%ae' | sort -u
```

Parse the output. Emails to treat as "owner/Claude" (not external contributors):
- Any email matching the pattern of the primary committer (the most frequent email in the log)
- Any email containing `noreply@anthropic.com` (Claude Co-Author commits)

**Decision logic:**
- If the unique email list contains **only** the primary committer's email and/or `noreply@anthropic.com` → this is a **sole-contributor repo** → proceed to push
- If there are **any other unique emails** → **do NOT push**. Instead, output a message:
  > "README updated locally. Skipping push — this repo has multiple contributors. Please review and push manually."

### 6. Commit and push (sole-contributor repos only)
```bash
git add README.md
git commit -m "docs: update README with current capabilities

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
```

If the push fails (e.g. no upstream set), run `git push -u origin HEAD` and report the result.

### 7. Report back
Tell the user:
- Whether the README was created or updated
- Which sections changed
- Whether it was pushed or left local (and why)
