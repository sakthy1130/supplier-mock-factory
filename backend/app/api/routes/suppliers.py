from fastapi import APIRouter

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]


@router.get("")
def list_suppliers() -> list[dict]:
    return [
        {"code": "HBS", "name": "Hotelbeds", "log_types": LOG_TYPES, "status": "v1"},
        {"code": "EXP", "name": "Expedia", "log_types": LOG_TYPES, "status": "v1"},
        {"code": "RHK", "name": "RateHawk", "log_types": LOG_TYPES, "status": "v1"},
        {"code": "CHC", "name": "Choice", "log_types": LOG_TYPES, "status": "v1"},
    ]
