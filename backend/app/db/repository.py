"""MongoDB repositories for scenarios and templates.

The only module that touches pymongo. Everything above it works with the dataclass
records in app.db.models, so swapping storage again would land here alone.

Queries mirror exactly what the service layer used to ask SQLAlchemy for:
get-by-id, get-by-namespace, and list-with-optional-filter ordered by created_at
descending. There are no joins and no cross-collection transactions.
"""

from __future__ import annotations

from typing import Iterable, Optional

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.db.models import ScenarioRecord, ScenarioTemplateRecord

SCENARIOS_COLLECTION = "scenarios"
TEMPLATES_COLLECTION = "scenario_templates"


def collection_names(prefix: str = "") -> tuple[str, str]:
    """(scenarios, templates) collection names for a prefix.

    The prefix exists for test isolation: the app database user is usually granted
    rights on exactly one database, so a per-run *database* is not creatable, while
    per-run *collections* are.
    """
    return f"{prefix}{SCENARIOS_COLLECTION}", f"{prefix}{TEMPLATES_COLLECTION}"


class ScenarioRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, scenario_id: str) -> Optional[ScenarioRecord]:
        doc = self._collection.find_one({"_id": scenario_id})
        return ScenarioRecord.from_doc(doc) if doc else None

    def get_by_namespace(self, namespace: str) -> Optional[ScenarioRecord]:
        doc = self._collection.find_one({"namespace": namespace})
        return ScenarioRecord.from_doc(doc) if doc else None

    def list(
        self,
        env: Optional[str] = None,
        statuses: Optional[Iterable[str]] = None,
    ) -> list[ScenarioRecord]:
        query: dict = {}
        if env:
            query["env"] = env
        if statuses is not None:
            query["status"] = {"$in": list(statuses)}
        cursor = self._collection.find(query).sort("created_at", DESCENDING)
        return [ScenarioRecord.from_doc(doc) for doc in cursor]

    def save(self, record: ScenarioRecord) -> ScenarioRecord:
        """Insert or replace the whole document.

        Replacing wholesale (rather than diffing fields) matches how callers use the
        record: mutate several attributes, then persist once — the shape the old
        `session.commit()` had.
        """
        self._collection.replace_one({"_id": record.id}, record.to_doc(), upsert=True)
        return record

    def delete(self, record: ScenarioRecord) -> None:
        self._collection.delete_one({"_id": record.id})


class TemplateRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, template_id: str) -> Optional[ScenarioTemplateRecord]:
        doc = self._collection.find_one({"_id": template_id})
        return ScenarioTemplateRecord.from_doc(doc) if doc else None

    def list(self) -> list[ScenarioTemplateRecord]:
        cursor = self._collection.find({}).sort("created_at", DESCENDING)
        return [ScenarioTemplateRecord.from_doc(doc) for doc in cursor]

    def save(self, record: ScenarioTemplateRecord) -> ScenarioTemplateRecord:
        self._collection.replace_one({"_id": record.id}, record.to_doc(), upsert=True)
        return record

    def delete(self, record: ScenarioTemplateRecord) -> None:
        self._collection.delete_one({"_id": record.id})


class MongoStore:
    """What `get_db()` yields, in place of a SQLAlchemy Session.

    Service functions keep their `db` first parameter and reach `db.scenarios` /
    `db.templates`, so route signatures did not change.
    """

    def __init__(self, database, collection_prefix: str = "") -> None:
        self.database = database
        scenarios_name, templates_name = collection_names(collection_prefix)
        self.scenarios = ScenarioRepository(database[scenarios_name])
        self.templates = TemplateRepository(database[templates_name])
