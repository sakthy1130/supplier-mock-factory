import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.ingest.template_ingestor import REPO_ROOT, TemplateIngestor

router = APIRouter(prefix="/admin", tags=["admin"])

REFERENCE_SIDS_PATH = REPO_ROOT / "reference-sids.json"


@router.post("/ingest")
async def ingest_templates() -> dict:
    """Run SID ingest from reference-sids.json at repo root."""
    if not REFERENCE_SIDS_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Missing {REFERENCE_SIDS_PATH.name}. Copy reference-sids.json.example and add SIDs.",
        )

    sids = json.loads(REFERENCE_SIDS_PATH.read_text(encoding="utf-8"))
    ingestor = TemplateIngestor()
    counts = await ingestor.ingest_from_sids(sids)
    return {"status": "ok", "templates_written": counts}
