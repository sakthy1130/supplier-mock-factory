from app.plugins.base import SupplierMockPlugin
from app.plugins.exp import ExpMockPlugin
from app.plugins.hbs import HbsMockPlugin
from app.plugins.rhk import RhkMockPlugin

PLUGINS: dict[str, SupplierMockPlugin] = {
    "HBS": HbsMockPlugin(),
    "EXP": ExpMockPlugin(),
    "RHK": RhkMockPlugin(),
}

__all__ = ["PLUGINS", "SupplierMockPlugin", "HbsMockPlugin", "ExpMockPlugin", "RhkMockPlugin"]
