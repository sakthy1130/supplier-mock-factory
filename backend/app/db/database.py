"""MongoDB client and store factory."""

from __future__ import annotations

import logging
from collections.abc import Generator

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db.repository import MongoStore, collection_names

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_client_url: str | None = None


class DatabaseNotConfigured(RuntimeError):
    pass


def get_client() -> MongoClient:
    """Process-wide client. pymongo pools connections internally and is fork-safe
    enough for our single-process uvicorn, so one client is reused."""
    global _client, _client_url
    settings = get_settings()
    if not settings.mongo_url:
        raise DatabaseNotConfigured(
            f"MONGO_URL is not set for env={settings.env or '<unknown>'}. "
            f"Set MONGO_URL (and optionally MONGO_DB_NAME) in backend/.env.{settings.env or '<env>'} "
            "or backend/.env.shared."
        )
    # Settings are per-env, so switching env can change the URL — rebuild the client
    # when it does rather than silently talking to the previous database.
    if _client is None or _client_url != settings.mongo_url:
        reset_client()
        _client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
        _client_url = settings.mongo_url
    return _client


def get_database():
    settings = get_settings()
    return get_client()[settings.mongo_db_name]


def get_store() -> MongoStore:
    return MongoStore(get_database(), get_settings().mongo_collection_prefix)


def init_db() -> None:
    """Create indexes. Mongo makes collections on first write, so there is nothing
    else to create — and no column migrations, unlike the previous SQLite schema."""
    database = get_database()
    scenarios_name, templates_name = collection_names(get_settings().mongo_collection_prefix)
    try:
        # namespace uniqueness used to be a SQLite UNIQUE constraint. create_pending
        # pre-checks and raises 409, but the index is what actually closes the race.
        database[scenarios_name].create_index(
            [("namespace", ASCENDING)], unique=True, name="uq_namespace"
        )
        database[scenarios_name].create_index([("env", ASCENDING)], name="ix_env")
        database[scenarios_name].create_index([("created_at", DESCENDING)], name="ix_created_at")
        database[templates_name].create_index([("created_at", DESCENDING)], name="ix_created_at")
    except PyMongoError:
        # A missing index degrades performance and the namespace race guard, but must
        # not stop the app from booting — surface it loudly instead.
        logger.exception("Failed to create MongoDB indexes on db=%s", database.name)


def ping() -> None:
    """Raise if the server is unreachable, with the URL host in the message."""
    settings = get_settings()
    try:
        get_client().admin.command("ping")
    except PyMongoError as exc:
        raise RuntimeError(
            f"MongoDB not reachable for env={settings.env or '<unknown>'} "
            f"(db={settings.mongo_db_name}): {exc}"
        ) from exc


def reset_client() -> None:
    """Close the client — for tests switching MONGO_URL / database name."""
    global _client, _client_url
    if _client is not None:
        _client.close()
    _client = None
    _client_url = None


def get_db() -> Generator[MongoStore, None, None]:
    """FastAPI dependency. Yields the store that replaced the SQLAlchemy Session;
    route signatures are unchanged."""
    yield get_store()
