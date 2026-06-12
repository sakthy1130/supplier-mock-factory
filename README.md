# Supplier Mock Factory (SMF)

Automate supplier mock creation for hotel connectivity QA: templates from SIDs → scenario mutations → MockServer → contracts → new apiKey.

## Quick start

### Backend

```bash
cd backend
cp .env.example .env   # fill staging values
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health: http://localhost:8000/health  
API docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker Compose

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Open:
- UI: http://localhost:5173
- API health: http://localhost:8000/health

The compose stack is tuned for local development:
- Backend runs with reload enabled
- Frontend runs Vite on `0.0.0.0:5173`
- Templates and field maps are mounted into the backend container

## Runbook

Use this flow for staging QA or a fresh local session:

1. Fill `backend/.env` with staging URLs and credentials from `backend/.env.example`.
2. Start the stack with `docker compose up --build` or run backend/frontend manually.
3. Confirm backend health at `/health` before creating scenarios.
4. Create a scenario from the UI with namespace, dates, hotel id, and supplier package data.
5. Wait for the bundle to reach `READY`, then copy the `apiKey` or inspect contracts/booking ids.
6. Use `refresh booking ids` when you need a fresh booking id for the same scenario.
7. Use `teardown` for one scenario or `Clear all data` to remove all active scenarios and leftover mocks.
8. Keep `docs/PROGRESS.md` updated at the end of each agent session.

## Resume after closing Cursor session

See **[docs/RESUME.md](docs/RESUME.md)** — read `PROGRESS.md` + `@` files in new agent.

## Project docs

| Doc | Purpose |
|-----|---------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full technical spec |
| [PROGRESS.md](docs/PROGRESS.md) | **Current phase — update every session** |
| [RESUME.md](docs/RESUME.md) | How to continue in new agent |
| [DESIGN-NOTES.md](docs/DESIGN-NOTES.md) | Design decisions history |

## Phases

P0 ✅ Bootstrap → P1 Template ingest → P2 Engine → P3 MockServer → P4 Orchestrator → P5 API → P6 UI → P7 Polish → P8 Crawla Mocks

Status in [docs/PROGRESS.md](docs/PROGRESS.md).

## Reference

Ports integration patterns from [qaBackend_Enigma](../) Java wrappers (read-only reference).
