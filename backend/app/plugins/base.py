"""Supplier plugin interface."""

from abc import ABC, abstractmethod

from app.models.scenario import PackageSpec


class SupplierMockPlugin(ABC):
    code: str

    @abstractmethod
    def matches_adapter_source(self, source: str) -> bool:
        """True if log list row source belongs to this supplier adapter."""

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
