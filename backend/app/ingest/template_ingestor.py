"""SID → templates on disk. Port AdapterSidLogToMockExpectationUtil."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ingest.expectation_builder import (
    OPTIONAL_TEMPLATE_LOG_TYPES,
    PendingExpectation,
    apply_aligned_derby_res_ids_for_booking_and_get_order,
    build_diagnostic_json,
    build_expectation,
    canonical_log_type,
    extract_request_payload_for_mock,
    extract_response_body_payload,
    extract_response_headers,
    is_get_order_response_row,
    is_outbound_get_order_row,
    is_target_log_type,
    resolve_http_path_and_method,
    resolve_http_status_code,
    row_timestamp,
)
from app.ingest.field_map_generator import FieldMapGenerator
from app.integrations.logs_api import LogsApiClient
from app.plugins import resolve_plugin_or_none
from app.plugins.base import SupplierMockPlugin

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "templates"
FIELD_MAPS_DIR = REPO_ROOT / "field-maps"


@dataclass
class LogRowCandidate:
    row: dict
    canonical_type: str
    raw_log_type: str
    timestamp: str


@dataclass
class IngestResult:
    """What one SID ingest produced — enough for the Suppliers screen to explain itself."""

    supplier_code: str
    sid: str
    # Log types written to templates/{CODE}/{LogType}/v1.json.
    written: list[str]
    # Required log types the SID's logs had nothing usable for.
    missing: list[str]
    # Rows whose HTTP path couldn't be resolved; dumped to _diagnostics/.
    unresolved: int
    # log type -> the httpRequest.path the mock will match on.
    paths: dict[str, str]
    # How many field-map paths were inferred from the ingested templates.
    field_map_paths: int
    # Adapter log sources seen for this SID, whether or not they matched.
    sources_seen: list[str]


class TemplateIngestor:
    def __init__(
        self,
        logs_client: LogsApiClient | None = None,
        templates_dir: Path | None = None,
        field_maps_dir: Path | None = None,
    ) -> None:
        self.logs = logs_client or LogsApiClient()
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.field_maps_dir = field_maps_dir or FIELD_MAPS_DIR
        self.field_map_generator = FieldMapGenerator()

    async def ingest_from_sids(self, sids: dict[str, str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self.logs:
            for supplier_code, sid in sids.items():
                result = await self._ingest_one(supplier_code, sid)
                counts[supplier_code] = len(result.written)
        return counts

    async def ingest_sid(self, supplier_code: str, sid: str) -> IngestResult:
        """Build one supplier's templates from a single SID's adapter logs."""
        async with self.logs:
            return await self._ingest_one(supplier_code, sid)

    async def _ingest_one(self, supplier_code: str, sid: str) -> IngestResult:
        plugin = resolve_plugin_or_none(supplier_code)
        if plugin is None:
            raise ValueError(f"Unknown supplier code: {supplier_code}")
        list_json = await self.logs.list_logs(sid)
        details = list_json.get("details") or []
        return await self._ingest_supplier(
            plugin, sid, details, fetch_detail=self.logs.get_log_detail
        )

    async def ingest_from_list_json(
        self,
        supplier_code: str,
        sid: str,
        list_json: dict,
        fetch_detail: Any,
    ) -> int:
        """Ingest from pre-loaded list payload — used by tests."""
        plugin = resolve_plugin_or_none(supplier_code)
        if plugin is None:
            raise ValueError(f"Unknown supplier code: {supplier_code}")
        details = list_json.get("details") or []
        result = await self._ingest_supplier(plugin, sid, details, fetch_detail=fetch_detail)
        return len(result.written)

    def _collect_candidates(self, plugin: SupplierMockPlugin, details: list[dict]) -> dict[str, list[LogRowCandidate]]:
        buckets: dict[str, list[LogRowCandidate]] = {}
        for row in details:
            if not isinstance(row, dict):
                continue
            raw_log_type = str(row.get("logType", ""))
            canonical = canonical_log_type(raw_log_type)
            if not is_target_log_type(raw_log_type) or canonical is None:
                continue
            source = str(row.get("source", ""))
            if not plugin.matches_adapter_source(source):
                continue
            log_url = row.get("logUrl", "")
            if not log_url:
                continue
            buckets.setdefault(canonical, []).append(
                LogRowCandidate(
                    row=row,
                    canonical_type=canonical,
                    raw_log_type=raw_log_type,
                    timestamp=row_timestamp(row),
                )
            )
        return buckets

    def _select_candidate(
        self,
        canonical_type: str,
        candidates: list[LogRowCandidate],
    ) -> LogRowCandidate | None:
        if not candidates:
            return None
        if canonical_type == "GetOrder":
            return self._select_get_order_candidate(candidates)
        if canonical_type == "CancelOrder":
            return max(candidates, key=lambda c: c.timestamp)
        return candidates[0]

    def _select_get_order_candidate(self, candidates: list[LogRowCandidate]) -> LogRowCandidate | None:
        """Latest GetOrderResponse wins; pair with nearest outbound GetOrder for supplier HTTP mock."""
        response_rows = [c for c in candidates if is_get_order_response_row(c.raw_log_type)]
        outbound_rows = [c for c in candidates if is_outbound_get_order_row(c.raw_log_type)]

        if response_rows:
            latest_response = max(response_rows, key=lambda c: c.timestamp)
            if outbound_rows:
                return min(
                    outbound_rows,
                    key=lambda c: _timestamp_distance_seconds(
                        c.timestamp, latest_response.timestamp
                    ),
                )
            return latest_response
        if outbound_rows:
            return max(outbound_rows, key=lambda c: c.timestamp)
        return None

    async def _attribute_by_payload(
        self,
        plugin: SupplierMockPlugin,
        buckets: dict[str, list[LogRowCandidate]],
        detail_for: Any,
    ) -> dict[str, list[LogRowCandidate]]:
        """Drop source-matched rows whose payload belongs to a sibling on the same adapter.

        CHC and HIL share ``hotels-derby-bts-adapter``, so ``matches_adapter_source``
        cannot tell their rows apart and a single search SID contains both. Filtering here
        rather than after ``_select_candidate`` means the selection rules (latest
        CancelOrder, GetOrder response/outbound pairing) still choose from this supplier's
        own rows instead of picking a sibling's row and losing the log type.
        """
        filtered: dict[str, list[LogRowCandidate]] = {}
        for canonical_type, candidates in buckets.items():
            kept: list[LogRowCandidate] = []
            for candidate in candidates:
                log_url = candidate.row.get("logUrl", "")
                if not log_url:
                    continue
                try:
                    full_log = await detail_for(log_url)
                except Exception:  # noqa: BLE001 - one unreadable row must not fail the ingest
                    logger.warning(
                        "%s ingest could not read %s for attribution; skipping row",
                        plugin.code,
                        log_url,
                    )
                    continue
                if plugin.claims_log_payload(full_log):
                    kept.append(candidate)
            dropped = len(candidates) - len(kept)
            if dropped:
                logger.info(
                    "%s ingest dropped %d %s row(s) belonging to another supplier on the "
                    "same adapter",
                    plugin.code,
                    dropped,
                    canonical_type,
                )
            if kept:
                filtered[canonical_type] = kept
        return filtered

    async def _ingest_supplier(
        self,
        plugin: SupplierMockPlugin,
        sid: str,
        details: list[dict],
        fetch_detail: Any,
    ) -> IngestResult:
        if not details:
            raise ValueError(f"No log details for sid={sid} supplier={plugin.code}")

        buckets = self._collect_candidates(plugin, details)
        pending_by_type: dict[str, PendingExpectation] = {}
        diagnostics: list[dict] = []

        # Details are fetched once per log url: shared-adapter attribution below reads the
        # same payloads the expectations are then built from.
        detail_cache: dict[str, dict] = {}

        async def detail_for(log_url: str) -> dict:
            if log_url not in detail_cache:
                detail_cache[log_url] = await fetch_detail(log_url)
            return detail_cache[log_url]

        if plugin.disambiguate_by_payload:
            buckets = await self._attribute_by_payload(plugin, buckets, detail_for)

        for canonical_type, candidates in buckets.items():
            selected = self._select_candidate(canonical_type, candidates)
            if selected is None:
                continue

            row = selected.row
            log_url = row.get("logUrl", "")
            full_log = await detail_for(log_url)

            http = resolve_http_path_and_method(row, full_log)
            if not http.path:
                diagnostics.append(build_diagnostic_json(sid, row, log_url, full_log))
                continue

            response_body = extract_response_body_payload(full_log)
            response_headers = extract_response_headers(full_log)
            request_payload = extract_request_payload_for_mock(full_log)
            status_code = resolve_http_status_code(row, full_log)
            expectation = build_expectation(
                http.path,
                http.method,
                request_payload,
                response_body,
                status_code,
                response_headers,
            )
            pending_by_type[canonical_type] = PendingExpectation(
                expectation=expectation,
                log_type=canonical_type,
            )

        pending = list(pending_by_type.values())
        apply_aligned_derby_res_ids_for_booking_and_get_order(pending)

        templates: dict[str, dict] = {}
        supplier_dir = self.templates_dir / plugin.code
        supplier_dir.mkdir(parents=True, exist_ok=True)

        for item in pending:
            log_dir = supplier_dir / item.log_type
            log_dir.mkdir(parents=True, exist_ok=True)
            out_path = log_dir / "v1.json"
            out_path.write_text(json.dumps(item.expectation, indent=2), encoding="utf-8")
            templates[item.log_type] = item.expectation

        if diagnostics:
            diag_dir = supplier_dir / "_diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            for index, diag in enumerate(diagnostics):
                diag_path = diag_dir / f"unresolved_{index:03d}.json"
                diag_path.write_text(json.dumps(diag, indent=2), encoding="utf-8")

        required_types = set(plugin.log_types) - OPTIONAL_TEMPLATE_LOG_TYPES
        missing = required_types - set(templates.keys())
        if missing:
            logger.warning(
                "%s ingest for sid=%s missing log types: %s",
                plugin.code,
                sid,
                sorted(missing),
            )

        # Generate the field map from the supplier's own configured key names, so a
        # supplier added from the UI gets a real map instead of an empty one (the old
        # SUPPLIER_MUTABLE_KEYS table only knew the five built-ins).
        field_map = self.field_map_generator.generate(
            plugin.code, templates, _mutation_config(plugin.code)
        )
        self.field_maps_dir.mkdir(parents=True, exist_ok=True)
        field_map_path = self.field_maps_dir / f"{plugin.code}.json"
        field_map_path.write_text(json.dumps(field_map, indent=2), encoding="utf-8")

        return IngestResult(
            supplier_code=plugin.code,
            sid=sid,
            written=sorted(templates.keys()),
            missing=sorted(missing),
            unresolved=len(diagnostics),
            paths={
                log_type: expectation.get("httpRequest", {}).get("path", "")
                for log_type, expectation in templates.items()
            },
            field_map_paths=sum(len(v) for v in field_map.get("paths", {}).values()),
            sources_seen=sorted(
                {
                    str(row.get("source", ""))
                    for row in details
                    if isinstance(row, dict) and row.get("source")
                }
            ),
        )


def _mutation_config(supplier_code: str):
    """The supplier's configured key names, or None to fall back to SUPPLIER_MUTABLE_KEYS."""
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    try:
        return get_supplier_config(supplier_code).mutation_config
    except UnknownSupplierError:
        return None


def _parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min
    normalized = value.replace("Z", "+00:00")
    if normalized.endswith("+00:00") and "T" in normalized:
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(normalized.split(".")[0])
    except ValueError:
        return datetime.min


def _timestamp_distance_seconds(left: str, right: str) -> float:
    delta = _parse_timestamp(left) - _parse_timestamp(right)
    return abs(delta.total_seconds())
