"""Session state handling for the Streamlit UI."""
from __future__ import annotations

import streamlit as st

from core.project import ProjectFile
from core.simulation import SimulationResult, run_simulation
from core.system import PerfusionSystemConfig, default_system


def init_state() -> None:
    ss = st.session_state
    if "project" not in ss:
        ss.project = ProjectFile(name="Example perfusion project", config=default_system())
    ss.setdefault("rev", 0)
    ss.setdefault("lang", "EN")
    ss.setdefault("selected_edge", None)
    ss.setdefault("prev_solution", None)


def cfg() -> PerfusionSystemConfig:
    return st.session_state.project.config


def set_config(new: PerfusionSystemConfig, note: str | None = None) -> None:
    """Replace the whole configuration (new widget keys via revision counter)."""
    st.session_state.project.config = new
    st.session_state.rev += 1
    st.session_state.prev_solution = None
    if note:
        st.session_state.project.new_version(note)


def key(*parts) -> str:
    return f"r{st.session_state.rev}:" + ":".join(str(p) for p in parts)


def simulate() -> SimulationResult:
    """Run the steady-state simulation for the current configuration (every rerun:
    any parameter change triggers a complete recomputation of all flows/pressures)."""
    prev = st.session_state.get("prev_solution")
    try:
        res = run_simulation(cfg(), initial=prev)
    except Exception:
        res = run_simulation(cfg())
    st.session_state.prev_solution = res.solver if res.ok else None
    st.session_state.last_result = res
    return res
