import numpy as np
import pytest

from core.simulation import run_simulation
from scenarios import SCENARIOS


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s.key for s in SCENARIOS])
def test_scenario_runs(sc):
    cfg = sc.build()
    res = run_simulation(cfg)
    assert res.ok, [w.message for w in res.warnings if w.level == "error"]
    assert "EXAMPLE" in cfg.description


def test_scenario_6_symmetric():
    res = run_simulation(SCENARIOS[5].build())
    q = res.reactor_flows()
    assert np.ptp(q) / q.mean() < 1e-10


def test_scenario_5_blocked_zero_flow():
    res = run_simulation(SCENARIOS[4].build())
    assert res.pump["Q"] == 0.0
