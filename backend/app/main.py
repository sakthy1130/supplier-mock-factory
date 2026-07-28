"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    crawla,
    env as env_routes,
    health,
    hotels,
    logs,
    run_template,
    scenario_templates,
    scenarios,
    suppliers,
    test_run,
)
from app.config import get_settings
from app.db.database import init_db
from app.env_context import get_current_env, reset_current_env, set_current_env

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Supplier Mock Factory",
    description="Automate supplier mocks, contracts, and apiKeys for hotel connectivity QA",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def env_context_middleware(request: Request, call_next):
    """Resolve the active env (dev|stg) from X-SMF-Env for this request's contextvar.

    Downstream get_settings() calls made synchronously during the request (hotel
    mapping, suppliers, crawla anchors, quickwit search, ...) pick this up without
    needing the env threaded through every call. Scenario background jobs do NOT
    rely on this — they pin the env explicitly from the scenario's stored value
    (see scenario_service.py) so a dropdown change mid-run can't retarget them.
    """
    token = set_current_env(request.headers.get("x-smf-env"))
    try:
        response = await call_next(request)
    finally:
        resolved = get_current_env()
        reset_current_env(token)
    response.headers["X-SMF-Env-Resolved"] = resolved
    return response


app.include_router(health.router)
app.include_router(run_template.router)
app.include_router(env_routes.router, prefix="/api")
app.include_router(scenarios.router, prefix="/api")
app.include_router(scenario_templates.router, prefix="/api")
app.include_router(crawla.router, prefix="/api")
app.include_router(suppliers.router, prefix="/api")
app.include_router(hotels.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(test_run.router, prefix="/api")
