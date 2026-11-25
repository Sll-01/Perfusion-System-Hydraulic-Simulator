"""Smoke test of all Streamlit pages (headless, streamlit.testing.AppTest)."""
import pytest

pytest.importorskip("streamlit")
from pathlib import Path  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")

PAGES = ["Dashboard", "System Diagram", "Fluid Properties", "Pump Configuration", "Tubing Configuration", "Splitter Configuration",
         "Bioreactor Configuration", "Throttle Configuration", "Bypass Configuration", "Simulation Results", "Parameter Studies",
         "Optimization", "Experimental Validation", "Scenarios & Projects", "Scientific Documentation", "Export"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    at.sidebar.radio(key="nav").set_value(page).run()
    assert not at.exception, [e.message for e in at.exception]


def test_german_toggle():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio(key="lang_radio").set_value("DE").run()
    assert not at.exception
    assert any("Gesamtvolumenstrom" in m.label for m in at.metric)


def test_throttle_change_recomputes():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio(key="nav").set_value("Throttle Configuration").run()
    before = at.session_state["last_result"].reactor_flows()[0]
    sl = [s for s in at.slider if s.key and "reactor_paths.0.throttle" in s.key][0]
    sl.set_value(20.0).run()
    after = at.session_state["last_result"].reactor_flows()[0]
    assert after < before
