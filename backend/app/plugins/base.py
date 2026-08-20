"""Supplier plugin interface."""

from abc import ABC, abstractmethod

from app.models.scenario import PackageSpec


class SupplierMockPlugin(ABC):
    code: str

    # True when ``matches_adapter_source`` alone cannot attribute a log row, because
    # this supplier shares its adapter with another one (CHC and HIL both log as
    # hotels-derby-bts-adapter). The ingestor then fetches each source-matched row's
    # detail and asks ``claims_log_payload`` before using it. Left False for suppliers
    # with an adapter of their own, so ingest costs no extra log fetches.
    disambiguate_by_payload: bool = False

    @abstractmethod
    def matches_adapter_source(self, source: str) -> bool:
        """True if log list row source belongs to this supplier adapter."""

    def claims_log_payload(self, full_log: dict) -> bool:
        """True if this fetched log detail is this supplier's, not a shared-adapter sibling's.

        Only consulted when ``disambiguate_by_payload`` is set. Returning False drops the
        row, so an implementation should refuse anything it cannot positively identify —
        writing a sibling supplier's payload into these templates is worse than a
        missing log type, which ingest reports.
        """
        return True

    @abstractmethod
    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        ...

    @abstractmethod
    def mutate_packages(
        self,
        expectation: dict,
        spec: PackageSpec,
        hotel_id: str,
        check_in: str,
        check_out: str,
        log_type: str,
    ) -> dict:
        ...

    def propagate_package_linkage(
        self,
        expectations_by_type: dict[str, dict],
        spec: PackageSpec,
    ) -> None:
        """Sync package identifiers into prebook/book flows."""

    @property
    @abstractmethod
    def log_types(self) -> list[str]:
        ...
