"""Environment metadata — lets the UI render the env switcher."""

from fastapi import APIRouter, Request

from app.env_context import DEFAULT_ENV, ENV_LABELS, SUPPORTED_ENVS, normalize_env

router = APIRouter(tags=["env"])


@router.get("/env")
def get_env(request: Request) -> dict:
    return {
        "available": list(SUPPORTED_ENVS),
        # Code + display name, so adding an env does not mean editing the UI's
        # option list as well. `available` stays for existing callers.
        "options": [{"code": code, "label": ENV_LABELS.get(code, code)} for code in SUPPORTED_ENVS],
        "default": DEFAULT_ENV,
        "current": normalize_env(request.headers.get("x-smf-env")),
    }
