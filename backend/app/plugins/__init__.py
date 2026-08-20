from app.plugins.base import SupplierMockPlugin
from app.plugins.chc import ChcMockPlugin
from app.plugins.derby_bts import DerbyBtsMockPlugin
from app.plugins.exp import ExpMockPlugin
from app.plugins.ext import ExtMockPlugin
from app.plugins.generic import GenericMockPlugin
from app.plugins.hbs import HbsMockPlugin
from app.plugins.hil import HilMockPlugin
from app.plugins.rhk import RhkMockPlugin

# Hand-written plugins. These are overrides, not the source of truth for which
# suppliers exist — that's the suppliers table. A supplier with an entry here gets it;
# anything else is mutated by GenericMockPlugin from its own mutation_config.
PLUGINS: dict[str, SupplierMockPlugin] = {
    "HBS": HbsMockPlugin(),
    "EXP": ExpMockPlugin(),
    "RHK": RhkMockPlugin(),
    "CHC": ChcMockPlugin(),
    "HIL": HilMockPlugin(),
    "EXT": ExtMockPlugin(),
}


def resolve_plugin(supplier_code: str) -> SupplierMockPlugin:
    """The plugin that will mutate this supplier's templates.

    Raises ``UnknownSupplierError`` for a code with neither a plugin nor a config, so
    the failure names the supplier and points at the Suppliers screen instead of
    surfacing as a KeyError deep in the engine.
    """
    from app.services.supplier_service import get_supplier_config

    code = supplier_code.upper()
    plugin = PLUGINS.get(code)
    if plugin is not None:
        return plugin
    config = get_supplier_config(code)
    return GenericMockPlugin(code, config.mutation_config, config.log_types)


def resolve_plugin_or_none(supplier_code: str) -> SupplierMockPlugin | None:
    """``resolve_plugin`` but returns None for an unconfigured code."""
    from app.services.supplier_service import UnknownSupplierError

    try:
        return resolve_plugin(supplier_code)
    except UnknownSupplierError:
        return None


def plugins_for_ingest(codes: list[str] | None = None) -> list[SupplierMockPlugin]:
    """Plugins to try when attributing an Enigma adapter log to a supplier.

    Walks every configured supplier, not just the hand-written ones, so a UI-added
    supplier can be ingested by SID as long as its adapter_source_match is set.
    """
    from app.services.supplier_service import UnknownSupplierError, configured_codes

    resolved = codes if codes is not None else configured_codes()
    plugins: list[SupplierMockPlugin] = []
    for code in resolved:
        try:
            plugins.append(resolve_plugin(code))
        except UnknownSupplierError:
            continue
    return plugins


__all__ = [
    "PLUGINS",
    "SupplierMockPlugin",
    "resolve_plugin",
    "resolve_plugin_or_none",
    "plugins_for_ingest",
    "GenericMockPlugin",
    "HbsMockPlugin",
    "ExpMockPlugin",
    "RhkMockPlugin",
    "ChcMockPlugin",
    "HilMockPlugin",
    "DerbyBtsMockPlugin",
    "ExtMockPlugin",
]
