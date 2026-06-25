from app.plugins.base import SupplierMockPlugin
from app.plugins.chc import ChcMockPlugin
from app.plugins.exp import ExpMockPlugin
from app.plugins.hbs import HbsMockPlugin
from app.plugins.rhk import RhkMockPlugin

PLUGINS: dict[str, SupplierMockPlugin] = {
    "HBS": HbsMockPlugin(),
    "EXP": ExpMockPlugin(),
    "RHK": RhkMockPlugin(),
    "CHC": ChcMockPlugin(),
}

__all__ = [
    "PLUGINS",
    "SupplierMockPlugin",
    "HbsMockPlugin",
    "ExpMockPlugin",
    "RhkMockPlugin",
    "ChcMockPlugin",
]
