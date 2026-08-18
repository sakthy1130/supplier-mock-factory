"""Health check endpoint with real backend dependency verification."""

import logging
from fastapi import APIRouter, Request

from app.config import get_settings
from app.db.database import get_database, ping
from app.db.repository import collection_names
from app.env_context import normalize_env

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def check_database() -> dict:
    """Verify MongoDB connectivity."""
    try:
        ping()
        return {
            "status": "ok",
            "message": "Database connected",
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "error",
            "message": f"Database connection failed: {str(e)}",
        }


def check_core_services() -> dict:
    """Verify the scenarios collection is queryable.

    Mongo creates collections lazily, so an empty/absent collection is healthy —
    what matters is that the query round-trips.
    """
    try:
        scenarios_name, _ = collection_names(get_settings().mongo_collection_prefix)
        get_database()[scenarios_name].estimated_document_count()
        return {
            "status": "ok",
            "message": "Core services operational",
        }
    except Exception as e:
        logger.error(f"Core services check failed: {e}")
        return {
            "status": "error",
            "message": f"Core services unavailable: {str(e)}",
        }


@router.get("/health")
def health(request: Request) -> dict:
    """
    Health check endpoint that verifies:
    - Database connectivity
    - Core services availability
    - Application readiness
    """
    env = normalize_env(request.headers.get("x-smf-env"))

    # Check database
    db_health = check_database()

    # Check core services
    services_health = check_core_services()

    # Overall status: all checks must pass
    all_ok = (
        db_health["status"] == "ok" and
        services_health["status"] == "ok"
    )

    overall_status = "ok" if all_ok else "degraded"

    return {
        "status": overall_status,
        "service": "supplier-mock-factory",
        "phase": "P8",
        "env": env,
        "checks": {
            "database": db_health,
            "core_services": services_health,
        },
        "message": (
            "All systems operational" if all_ok
            else "One or more services are unavailable"
        ),
    }
