# How to Resume SMF in a New Cursor Agent Session

This project is designed for **multi-day builds**. Chat memory does not persist — **files do**.

## Quick start (new agent window)

1. Open workspace containing `supplier-mock-factory/`
2. Start a new **Agent** conversation
3. Paste:

```
Resume Supplier Mock Factory (SMF).

Read first:
@supplier-mock-factory/docs/ARCHITECTURE.md
@supplier-mock-factory/docs/PROGRESS.md
@supplier-mock-factory/.cursor/rules/smf.mdc

Continue only the "Next session" tasks in PROGRESS.md.
Do not re-scaffold. Do not change locked decisions.
Update PROGRESS.md when finished.
```

4. Agent continues from current phase in PROGRESS.md

## What persists automatically

| Artifact | Location |
|----------|----------|
| Full architecture spec | `docs/ARCHITECTURE.md` |
| Current phase + next tasks | `docs/PROGRESS.md` |
| Agent rules (always on) | `.cursor/rules/smf.mdc` |
| Design history | `docs/DESIGN-NOTES.md` |
| Code + git history | entire repo |

## End-of-session ritual (2 minutes)

1. Update `docs/PROGRESS.md`:
   - Phase checklist
   - "Next session" prompt block
   - Blockers table
2. Optional: fill `docs/HANDOFF.md` template
3. Commit: `git add -A && git commit -m "feat(pN): description"`

## Prerequisites before running backend

```bash
cd supplier-mock-factory/backend
cp .env.example .env
# Edit .env with staging URLs and credentials
pip install -e ".[dev]"
source .venv/bin/activate
PYTHONPATH=. python3 -m uvicorn app.main:app --reload --port 8000
```

## Prerequisites before P1 ingest

Create `reference-sids.json` at repo root (gitignored):

```json
{
  "HBS": "your-hbs-sid-here",
  "EXP": "your-exp-sid-here"
}
```

Then run (after P1 implemented):

```bash
python scripts/ingest_sids.py --input reference-sids.json
```
