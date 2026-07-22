"""Environment metadata — lets the UI render the dev/stg toggle."""

from fastapi import APIRouter, Request

from app.env_context import DEFAULT_ENV, SUPPORTED_ENVS, normalize_env

router = APIRouter(tags=["env"])


@router.get("/env")
def get_env(request: Request) -> dict:
    return {
        "available": list(SUPPORTED_ENVS),
        "default": DEFAULT_ENV,
        "current": normalize_env(request.headers.get("x-smf-env")),
    }
