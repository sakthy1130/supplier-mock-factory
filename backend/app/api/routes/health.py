from fastapi import APIRouter, Request

from app.env_context import normalize_env

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": "supplier-mock-factory",
        "phase": "P8",
        "env": normalize_env(request.headers.get("x-smf-env")),
    }
