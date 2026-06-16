"""Crawla anchors and Crawla-driven scenario API."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.integrations.crawla import CrawlaApiError, CrawlaClient
from app.integrations.core_app import CoreAppClient
from app.models.crawla import (
    CrawlaAnchorPackagesResponse,
    CrawlaAnchorRequest,
    CrawlaAnchorSearchResponse,
    CrawlaBucket,
    CrawlaPackagePriceMode,
    CrawlaRunScenarioResponse,
    CrawlaScenarioExport,
    CrawlaScenarioRequest,
)
from app.models.scenario import PackageSpec, ScenarioBundle, ScenarioRequest, ScenarioStatus, SupplierCode, SupplierMutation, SupplierScenario
from app.services import scenario_service
from app.services.hotel_mapping_service import resolve_scenario_hotel_ids

router = APIRouter(prefix="/crawla", tags=["crawla"])


@router.post("/anchor/search", response_model=CrawlaAnchorSearchResponse)
async def anchor_search(request: CrawlaAnchorRequest) -> CrawlaAnchorSearchResponse:
    async with CrawlaClient() as client:
        try:
            return await client.search_anchor(request)
        except CrawlaApiError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/anchor/packages", response_model=CrawlaAnchorPackagesResponse)
async def anchor_packages(request: CrawlaAnchorRequest) -> CrawlaAnchorPackagesResponse:
    async with CrawlaClient() as client:
        try:
            return await client.packages_anchor(request)
        except CrawlaApiError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scenarios", response_model=ScenarioBundle, status_code=202)
async def create_crawla_scenario(
    request: CrawlaScenarioRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScenarioBundle:
    base_request = _build_scenario_request(request)
    resolved = await resolve_scenario_hotel_ids(base_request)
    record = scenario_service.create_pending(db, resolved)
    background_tasks.add_task(scenario_service.run_create_scenario, record.id)
    return scenario_service.record_to_bundle(record)


@router.post("/scenarios/{scenario_id}/run", response_model=CrawlaRunScenarioResponse)
async def run_crawla_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
) -> CrawlaRunScenarioResponse:
    record = scenario_service.get_record(db, scenario_id)
    bundle = scenario_service.record_to_bundle(record)
    if bundle.status != ScenarioStatus.READY:
        raise HTTPException(status_code=409, detail="Scenario must be READY before running")
    if not bundle.api_key:
        raise HTTPException(status_code=409, detail="Scenario has no apiKey")
    if not bundle.crawla_export:
        raise HTTPException(status_code=409, detail="Scenario has no Crawla export payload")

    async with CoreAppClient() as client:
        result = await client.run_search_and_packages(
            api_key=bundle.api_key,
            check_in=bundle.check_in,
            check_out=bundle.check_out,
            hotel_id=bundle.atg_hotel_id,
        )

    result.scenario_id = scenario_id
    return result


def _build_scenario_request(request: CrawlaScenarioRequest) -> ScenarioRequest:
    search_price = request.search
    package_price = request.packages
    package_count = package_price.package_count
    hbs_prices = _build_price_series(
        package_price.hbs_price,
        package_count,
        package_price.package_price_mode,
        package_price.package_price_step,
    )
    exp_prices = _build_price_series(
        package_price.exp_price,
        package_count,
        package_price.package_price_mode,
        package_price.package_price_step,
    )
    refundable = [package_price.refundability.upper() == "YES"] * package_count
    export = CrawlaScenarioExport(
        bucket=request.bucket,
        namespace=request.namespace,
        atg_hotel_id=request.atg_hotel_id,
        check_in=request.check_in,
        check_out=request.check_out,
        search=search_price,
        packages=package_price,
    )
    is_l2 = request.bucket == CrawlaBucket.CHEAPEST_L2_GROSS
    raw_room_basis = package_price.room_basis or package_price.meal or "RO"
    pkg_room_basis = "RO" if is_l2 else raw_room_basis

    suppliers = [
        SupplierScenario(
            code=SupplierCode.HBS,
            packages=PackageSpec(
                count=package_count,
                room_basis=pkg_room_basis,
                prices=hbs_prices,
                refundable=refundable,
            ),
        ),
        SupplierScenario(
            code=SupplierCode.EXP,
            packages=PackageSpec(
                count=package_count,
                room_basis=pkg_room_basis,
                prices=exp_prices,
                refundable=refundable,
            ),
        ),
    ]
    # CHEAPEST_L2_GROSS room-basis rule:
    #   - Enigma's verifyRoomBasisIsROorBBAndReturnRoomBasisAsList() hard-asserts RO.
    #   - Hardcode RO (not just normalise) so L2 eligibility is guaranteed.
    effective_room_basis = "RO" if is_l2 else raw_room_basis

    # CHEAPEST_L2_GROSS room-name rule:
    #   - HBS room_name  == Crawla room_name  (same — Crawla anchor drives HBS)
    #   - EXP room_name  != HBS room_name     (different — forces separate similar-package group)
    #   When HBS and EXP are in *different* groups, Enigma fires L2 independently:
    #   if EXP gross < Crawla anchor and L2 is enabled on the API key,
    #   CHEAPEST_L2_GROSS_PARTICIPATING_PACKAGES_IDS is populated { HBS_id -> EXP_id }.
    hbs_room_name = package_price.crawla_room_name
    exp_room_name = ("Single " + package_price.crawla_room_name) if is_l2 else package_price.crawla_room_name

    # CHEAPEST_L2_GROSS Search room-name rule:
    #   Both HBS and EXP Search use the same room_name, which differs from the
    #   Crawla anchor. This ensures they appear in the same group in Search
    #   but are separated in Packages (HBS = crawla_room_name, EXP = "Single " + crawla_room_name).
    l2_search_room_name = ("Double " + package_price.crawla_room_name) if is_l2 else None

    supplier_mutations = {
        "HBS": SupplierMutation(
            search_price=search_price.hbs_price,
            package_price=package_price.hbs_price,
            room_name=hbs_room_name,
            search_room_name=l2_search_room_name,
            room_basis=effective_room_basis,
        ),
        "EXP": SupplierMutation(
            search_price=search_price.exp_price,
            package_price=package_price.exp_price,
            room_name=exp_room_name,
            search_room_name=l2_search_room_name,
            # For L2: hardcoded RO (both suppliers must be RO for L2 eligibility).
            # For other buckets: preserve original meal/room_basis order.
            room_basis=effective_room_basis if is_l2 else (package_price.meal or package_price.room_basis),
            bed_groups_description="3 Bed" if request.bucket == CrawlaBucket.ONLY_CRAWLA else None,
        ),
    }
    return ScenarioRequest(
        namespace=request.namespace,
        check_in=request.check_in,
        check_out=request.check_out,
        atg_hotel_id=request.atg_hotel_id,
        suppliers=suppliers,
        supplier_mutations=supplier_mutations,
        crawla_export=export.model_dump(mode="json"),
    )


def _build_price_series(
    base_price: float,
    count: int,
    mode: CrawlaPackagePriceMode,
    step: float,
) -> list[float]:
    prices: list[float] = []
    for index in range(count):
        if mode == CrawlaPackagePriceMode.INCREASE:
            price = base_price + (step * index)
        elif mode == CrawlaPackagePriceMode.DECREASE:
            price = max(base_price - (step * index), 0.01)
        else:
            price = base_price
        prices.append(round(price, 2))
    return prices
