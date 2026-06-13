# Claude Code Setup — Multi-laptop Configuration

Configure Claude Code on another laptop to use the same settings and project context.

---

## Global Claude Code Settings

**File location:** `~/.claude/settings.json`

Add or merge these settings:

```json
{
  "permissions": {
    "allow": [
      "Bash(ls /Users/sakthivel.sunder/.claude/projects/ 2>/dev/null)",
      "Read(//Users/sakthivel.sunder/.claude/projects/**)",
      "Bash(python3 -c ' *)",
      "Bash(python -m pytest tests/test_plugins_p2.py -v)",
      "Bash(python3 -m pytest tests/test_plugins_p2.py -v)",
      "Bash(python3 -m pytest --tb=short)",
      "Bash(python3 -m pytest tests/test_exp_search_prices.py -v -m \"not integration\")",
      "Bash(python3 -m pytest --tb=short -m \"not integration\")"
    ],
    "additionalDirectories": [
      "/Users/sakthivel.sunder/.claude/projects/-Users-sakthivel-sunder-officeWork-gitHub-GitHub-qaBackend-Enigma-supplier-mock-factory/memory"
    ]
  },
  "model": "opus",
  "switchModelsOnFlag": true
}
```

---

## Project-Specific Settings (in repo)

These files are **already committed** in the repo:

### 1. Codex Configuration
**File:** `.codex/config.toml`

Sets up project documentation loading and sandbox defaults.

```toml
project_doc_max_bytes = 65536
project_doc_fallback_filenames = ["PROGRESS.md"]
file_opener = "cursor"

[sandbox]
mode = "workspace-write"
```

**Trust the project in Codex:**

Add to `~/.codex/config.toml`:

```toml
[projects."/path/to/supplier-mock-factory"]
trust_level = "trusted"
```

### 2. Cursor Rules
**File:** `.cursor/rules/smf.mdc`

Always-on rules for Cursor agent. Applied automatically when opening project.

---

## Project Memory Files

Memory is stored **per project** in `~/.claude/projects/<project-path>/memory/`.

### Key memory files
- `MEMORY.md` — Index of all memories
- `project_overview.md` — What SMF does
- `tech_stack.md` — Backend + frontend stack
- `current_status.md` — Phase P8 status + how to resume

These files are **created automatically** the first time you open the project in Claude Code on the new laptop.

To **manually sync** (optional):

```bash
# Copy from current laptop
scp -r ~/.claude/projects/-Users-sakthivel-sunder-officeWork-gitHub-GitHub-supplier-mock-factory/memory \
  user@newlaptop:~/.claude/projects/-Users-sakthivel-sunder-officeWork-gitHub-GitHub-supplier-mock-factory/
```

---

## Setup checklist for new laptop

- [ ] Clone repo: `git clone https://github.com/sakthy1130/supplier-mock-factory.git`
- [ ] Add `~/.claude/settings.json` (see Global Settings above)
- [ ] Trust project in `~/.codex/config.toml`
- [ ] Install Claude Code CLI (if not already installed)
- [ ] Open project: `claude .` in repo root
- [ ] Let Claude Code create `.claude/projects/` directory automatically
- [ ] Memory files will be created on first run

---

## Resume workflow on new laptop

When you open the project on new laptop:

1. Claude Code will load `.cursor/rules/smf.mdc` (rules)
2. Agent will read `docs/PROGRESS.md` (current phase)
3. Start with "Next session" prompt from PROGRESS.md

**One-liner to resume:**

```
Resume Supplier Mock Factory (SMF).
Read: docs/ARCHITECTURE.md, docs/PROGRESS.md, .cursor/rules/smf.mdc
Continue "Next session" in PROGRESS.md only.
```

---

## Environment setup

### Backend
```bash
cd backend
cp .env.example .env
# Fill in staging values:
# - MOCK_SERVER_URL
# - BACKOFFICE_URL
# - MAPPING_SERVICE_URL
# - QUICKWIT_LOGS_API_URL
# - CRAWLA_API_URL, CRAWLA_API_KEY

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3 -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

---

## Model preference

Default model: **Opus** (best for complex tasks)

Switch models on flag:
```
/fast       # Faster Opus (optimized output)
/sonnet     # Sonnet 4.6 (fast)
/haiku      # Haiku 4.5 (quick answers)
```

---

## Tips

- **Always read PROGRESS.md first** — it has current phase + blockers
- **Update PROGRESS.md at session end** — enables seamless handoff
- **Use caveman mode** for terse responses: `/caveman lite`
- **Tests:** `pytest tests/` (51+ passing)
- **Type check frontend:** `npm run build`

---

## Troubleshooting

**Settings not loading?**

Check `~/.claude/settings.json` syntax:

```bash
python3 -m json.tool ~/.claude/settings.json
```

**Project not recognized?**

```bash
# List cached projects
ls ~/.claude/projects/
```

**Memory files missing?**

They'll be created automatically on first run. Or sync manually (see above).

---

## Questions?

See project docs:
- `AGENTS.md` — Agent rules + communication style
- `docs/ARCHITECTURE.md` — Full technical spec
- `docs/RESUME.md` — How to continue across sessions
