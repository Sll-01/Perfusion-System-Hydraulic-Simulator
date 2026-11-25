"""Perfusion System Hydraulic Simulator V1.0 -- Streamlit user interface.

Start with:   streamlit run app.py      (or double-click start.bat on Windows)

The user interface only *uses* the calculation library in ``core``; all physics,
solvers, studies and statistics are implemented there and can be scripted without
Streamlit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core import APP_NAME, SOFTWARE_VERSION  # noqa: E402

st.set_page_config(page_title=f"{APP_NAME} V{SOFTWARE_VERSION}", page_icon="💧", layout="wide")

from ui import pages_analysis, pages_config, pages_misc, pages_results  # noqa: E402
from ui.i18n import t  # noqa: E402
from ui.state import cfg, init_state  # noqa: E402

PAGES = {
    "Dashboard": pages_results.page_dashboard,
    "System Diagram": pages_results.page_diagram,
    "Fluid Properties": pages_config.page_fluid,
    "Pump Configuration": pages_config.page_pump,
    "Tubing Configuration": pages_config.page_tubing,
    "Splitter Configuration": pages_config.page_splitters,
    "Bioreactor Configuration": pages_config.page_reactors,
    "Throttle Configuration": pages_config.page_throttles,
    "Bypass Configuration": pages_config.page_bypass,
    "Simulation Results": pages_results.page_results,
    "Parameter Studies": pages_analysis.page_studies,
    "Optimization": pages_analysis.page_optimization,
    "Experimental Validation": pages_analysis.page_validation,
    "Scenarios & Projects": pages_misc.page_scenarios_projects,
    "Scientific Documentation": pages_misc.page_documentation,
    "Export": pages_misc.page_export,
}


def main() -> None:
    init_state()
    with st.sidebar:
        st.markdown(f"### {APP_NAME}\nV{SOFTWARE_VERSION}")
        lang = st.radio(t("Language"), ["EN", "DE"], index=["EN", "DE"].index(st.session_state.lang), horizontal=True, key="lang_radio")
        if lang != st.session_state.lang:
            st.session_state.lang = lang
            st.rerun()
        page = st.radio(t("Navigation"), list(PAGES), format_func=t, key="nav")
        st.divider()
        c = cfg()
        st.caption(f"Configuration: **{c.name}**")
        st.caption(f"Layout: {c.layout} | reactors: {c.n_reactors} | bypass: {'on' if c.bypass.enabled else 'off'} | pump: {c.pump.mode[0]}")
        st.caption("1D hydraulic network model - not a substitute for 3D CFD or biological validation.")
    PAGES[page]()


main()
