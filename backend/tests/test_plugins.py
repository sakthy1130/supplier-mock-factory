from app.plugins.exp import ExpMockPlugin
from app.plugins.hbs import HbsMockPlugin
from app.plugins.rhk import RhkMockPlugin


def test_hbs_matches_adapter_source():
    plugin = HbsMockPlugin()
    assert plugin.matches_adapter_source("hotel-connectivity-hbs-adapter")
    assert not plugin.matches_adapter_source("hotels-exp-adapter-service-staging")


def test_exp_matches_adapter_source():
    plugin = ExpMockPlugin()
    assert plugin.matches_adapter_source("hotels-exp-adapter-service-staging")
    assert not plugin.matches_adapter_source("hotel-connectivity-hbs-adapter")


def test_rhk_matches_adapter_source():
    plugin = RhkMockPlugin()
    assert plugin.matches_adapter_source("hotels-rhk-adapter-service-staging")
    assert not plugin.matches_adapter_source("hotel-connectivity-hbs-adapter")
