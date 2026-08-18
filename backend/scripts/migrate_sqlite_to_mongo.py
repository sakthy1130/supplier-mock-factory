"""One-off migration: copy scenarios and scenario_templates from SQLite into MongoDB.

Read-only against the SQLite file (never written, never deleted) and idempotent —
documents are upserted by `_id`, so re-running converges instead of duplicating.

    python3 scripts/migrate_sqlite_to_mongo.py                    # dry run, prints counts
    python3 scripts/migrate_sqlite_to_mongo.py --commit           # actually write
    python3 scripts/migrate_sqlite_to_mongo.py --commit --db smf_dev --sqlite ./smf.db

JSON columns come back as TEXT from SQLite and are decoded here. Datetimes are
stored by SQLite as strings; they are parsed and made UTC-aware so they match what
the app writes natively (see app/db/models.py — BSON has no timezone).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.repository import SCENARIOS_COLLECTION, TEMPLATES_COLLECTION  # noqa: E402

# column -> how to decode it. Anything not listed is copied verbatim.
_JSON_COLUMNS = {"request_json", "contracts_json", "booking_ids_json", "suppliers_json", "packages_json"}
_DATE_COLUMNS = {"created_at", "updated_at", "expires_at"}


def _decode_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _decode_date(value):
    if value is None or isinstance(value, datetime):
        return _as_utc(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _as_utc(datetime.strptime(str(value).replace("+00:00", ""), fmt))
        except ValueError:
            continue
    print(f"  ! could not parse datetime {value!r} — storing as-is")
    return value


def _as_utc(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _row_to_doc(row: sqlite3.Row) -> dict:
    doc: dict = {}
    for key in row.keys():
        value = row[key]
        if key in _JSON_COLUMNS:
            # suppliers_json/packages_json are lists; the rest are objects.
            value = _decode_json(value, [] if key.startswith(("suppliers", "packages")) else {})
        elif key in _DATE_COLUMNS:
            value = _decode_date(value)
        doc[key] = value
    doc["_id"] = doc.pop("id")
    return doc


def _read_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.OperationalError as exc:
        print(f"  ! skipping {table}: {exc}")
        return []
    return [_row_to_doc(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=str(BACKEND_DIR / "smf.db"), help="path to smf.db")
    parser.add_argument("--db", default=None, help="target Mongo database (default: MONGO_DB_NAME)")
    parser.add_argument("--env", default=None, help="which .env to read MONGO_URL from (dev|stg)")
    parser.add_argument("--commit", action="store_true", help="write; omit for a dry run")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"SQLite file not found: {sqlite_path}")
        return 1

    from app.config import get_settings
    from app.db.database import get_client

    settings = get_settings(args.env) if args.env else get_settings()
    if not settings.mongo_url:
        print("MONGO_URL is not set — nothing to migrate into.")
        return 1
    target_db = args.db or settings.mongo_db_name

    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        scenarios = _read_table(conn, "scenarios")
        templates = _read_table(conn, "scenario_templates")
    finally:
        conn.close()

    print(f"source : {sqlite_path}")
    print(f"target : {target_db} (env={settings.env or 'default'})")
    print(f"  scenarios         in sqlite: {len(scenarios)}")
    print(f"  scenario_templates in sqlite: {len(templates)}")

    database = get_client()[target_db]
    before = {
        SCENARIOS_COLLECTION: database[SCENARIOS_COLLECTION].count_documents({}),
        TEMPLATES_COLLECTION: database[TEMPLATES_COLLECTION].count_documents({}),
    }
    print(f"  mongo before: {before}")

    if not args.commit:
        print("\nDry run — nothing written. Re-run with --commit to migrate.")
        return 0

    for collection_name, docs in (
        (SCENARIOS_COLLECTION, scenarios),
        (TEMPLATES_COLLECTION, templates),
    ):
        collection = database[collection_name]
        for doc in docs:
            collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"  upserted {len(docs)} -> {collection_name}")

    after = {
        SCENARIOS_COLLECTION: database[SCENARIOS_COLLECTION].count_documents({}),
        TEMPLATES_COLLECTION: database[TEMPLATES_COLLECTION].count_documents({}),
    }
    print(f"  mongo after : {after}")
    print("\nDone. Re-running this script will not duplicate anything (upsert by _id).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
