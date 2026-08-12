"""Health check endpoint with real backend dependency verification."""

import logging
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.db.database import get_engine
from app.env_context import normalize_env

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def check_database() -> dict:
    """Verify database connectivity and basic functionality."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Execute simple query to verify connection
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
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
    """Verify core application services are functioning."""
    try:
        # Check if scenario-related tables exist
        engine = get_engine()
        with engine.connect() as conn:
            # Query to check if scenarios table has data (optional)
            result = conn.execute(text("SELECT COUNT(*) FROM scenarios LIMIT 1"))
            result.fetchone()
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
