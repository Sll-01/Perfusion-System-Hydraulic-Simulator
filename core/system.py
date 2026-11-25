"""Configuration of the complete perfusion system and network builder (spec. chapters 2, 26).

Standard topology (layout ``full``), N reactor paths (default 4) plus optional bypass:

  reservoir -> suction tube -> PUMP -> pump outlet tube -> [T-piece] -> splitter 1 (hub)
     splitter 1 port k -> tube -> THROTTLE k -> tube -> BIOREACTOR k -> tube -> splitter 2 port k
     bypass: splitter 1 (or T-piece) -> tube -> BYPASS THROTTLE -> tube -> splitter 2 (or T-piece)
  splitter 2 (hub) -> [T-piece] -> return tube -> reservoir

Layout ``single_line`` (simplified experimental set-ups):

  reservoir -> suction tube -> PUMP -> pump outlet tube -> test tube
     -> [throttle] -> [bioreactor] -> return tube -> reservoir

The reservoir is an open vessel and acts as the pressure reference (gauge pressure =
``reservoir.gauge_pressure_pa`` at the liquid surface). Level differences are expressed
through the height differences of the tube segments.

All numeric defaults are clearly marked EXAMPLE parameters (no measured data yet).
"""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from . import SOFTWARE_VERSION
from .bioreactors import Bioreactor
from .bypass import BypassConfig, TeeChannel
from .fluids import FluidConfig
from .network import HydraulicNetwork
from .pumps import PumpConfig
from .scaffolds import Scaffold
from .solver import SolverSettings
from .splitters import Splitter, SplitterChannel, SplitterPort
from .throttles import Throttle
from .tubing import Fitting, Tube

EXAMPLE_NOTE = "EXAMPLE PARAMETERS - not based on measurements. Replace by real geometry / measured data."


class ReservoirConfig(BaseModel):
    name: str = "Medium reservoir"
    fill_volume_ml: float = Field(20.0, ge=0, description="Filled medium volume in the reservoir [mL]")
    gauge_pressure_pa: float = Field(0.0, description="Pressure at liquid surface relative to atmosphere [Pa]")


class ReactorPath(BaseModel):
    name: str = "Reactor path"
    tube_to_throttle: Tube = Field(default_factory=lambda: Tube(name="tube splitter -> throttle", length_m=0.10))
    throttle: Throttle = Field(default_factory=Throttle)
    tube_to_reactor: Tube = Field(default_factory=lambda: Tube(name="tube throttle -> reactor", length_m=0.15))
    reactor: Bioreactor = Field(default_factory=Bioreactor)
    tube_to_collector: Tube = Field(default_factory=lambda: Tube(name="tube reactor -> splitter", length_m=0.25))


class SingleLineConfig(BaseModel):
    test_tube: Tube = Field(default_factory=lambda: Tube(name="test tube", length_m=0.5))
    include_throttle: bool = False
    include_reactor: bool = False


class PerfusionSystemConfig(BaseModel):
    name: str = "Standard perfusion system (example)"
    description: str = EXAMPLE_NOTE
    layout: Literal["full", "single_line"] = "full"
    software_version: str = SOFTWARE_VERSION
    fluid: FluidConfig = Field(default_factory=FluidConfig)
    reservoir: ReservoirConfig = Field(default_factory=ReservoirConfig)
    pump: PumpConfig = Field(default_factory=PumpConfig)
    suction_tube: Tube = Field(default_factory=lambda: Tube(name="suction tube (reservoir -> pump)", length_m=0.25))
    pump_outlet_tube: Tube = Field(default_factory=lambda: Tube(name="pump outlet tube (pump -> splitter 1)", length_m=0.25))
    return_tube: Tube = Field(default_factory=lambda: Tube(name="return tube (splitter 2 -> reservoir)", length_m=0.30))
    splitter_in: Splitter = Field(default_factory=lambda: Splitter(name="Splitter 1 (distributor)", role="distributor"))
    splitter_out: Splitter = Field(default_factory=lambda: Splitter(name="Splitter 2 (collector)", role="collector"))
    reactor_paths: list[ReactorPath] = Field(default_factory=list)
    bypass: BypassConfig = Field(default_factory=BypassConfig)
    single_line: SingleLineConfig = Field(default_factory=SingleLineConfig)
    solver: SolverSettings = Field(default_factory=SolverSettings)

    @property
    def n_reactors(self) -> int:
        return len(self.reactor_paths)

    def copy_deep(self) -> "PerfusionSystemConfig":
        return self.model_copy(deep=True)


def default_reactor_path(i: int) -> ReactorPath:
    k = i + 1
    return ReactorPath(
        name=f"Reactor path {k}",
        tube_to_throttle=Tube(name=f"R{k} tube splitter1 -> throttle", length_m=0.10, fittings=[Fitting(name="Luer connector", count=1, K=0.2)]),
        throttle=Throttle(name=f"Throttle {k}", opening_percent=100.0),
        tube_to_reactor=Tube(name=f"R{k} tube throttle -> reactor", length_m=0.15, fittings=[Fitting(name="Luer connector", count=1, K=0.2)]),
        reactor=Bioreactor(name=f"Bioreactor {k}", scaffold=Scaffold(name=f"Scaffold {k}")),
        tube_to_collector=Tube(name=f"R{k} tube reactor -> splitter2", length_m=0.25, fittings=[Fitting(name="Luer connector", count=1, K=0.2)]),
    )


def default_system(n_reactors: int = 4, bypass: bool = True) -> PerfusionSystemConfig:
    """Standard example system: reservoir, pump, 2 splitters, N throttles+reactors, bypass."""
    cfg = PerfusionSystemConfig(reactor_paths=[default_reactor_path(i) for i in range(n_reactors)])
    cfg.bypass.enabled = bypass
    cfg.splitter_in.ensure_ports(n_reactors)
    cfg.splitter_out.ensure_ports(n_reactors)
    return cfg


def set_reactor_count(cfg: PerfusionSystemConfig, n: int) -> None:
    """Change the number of reactor paths (copies the last path's parameters)."""
    n = max(0, int(n))
    while len(cfg.reactor_paths) > n:
        cfg.reactor_paths.pop()
    while len(cfg.reactor_paths) < n:
        if cfg.reactor_paths:
            p = copy.deepcopy(cfg.reactor_paths[-1])
            k = len(cfg.reactor_paths) + 1
            p.name = f"Reactor path {k}"
            p.throttle.name = f"Throttle {k}"
            p.reactor.name = f"Bioreactor {k}"
            cfg.reactor_paths.append(p)
        else:
            cfg.reactor_paths.append(default_reactor_path(0))
    cfg.splitter_in.ensure_ports(n)
    cfg.splitter_out.ensure_ports(n)


# ---------------------------------------------------------------------------
# Network builder
# ---------------------------------------------------------------------------
def build_network(cfg: PerfusionSystemConfig) -> HydraulicNetwork:
    net = HydraulicNetwork(name=cfg.name)
    p_ref = cfg.reservoir.gauge_pressure_pa
    net.add_node("reservoir", "Reservoir", "reservoir", fixed_pressure=p_ref, pos=(0.0, 0.0))
    net.add_node("pump_in", "Pump inlet", "pump_port", pos=(1.0, 0.0))
    net.add_node("pump_out", "Pump outlet", "pump_port", pos=(2.0, 0.0))
    net.add_edge("suction_tube", "reservoir", "pump_in", cfg.suction_tube, "tube", group="feed", config_path="suction_tube")
    net.add_edge("pump", "pump_in", "pump_out", cfg.pump, "pump", label="Pump", group="feed", config_path="pump")

    if cfg.layout == "single_line":
        sl = cfg.single_line
        net.add_node("test_in", "Test section inlet", pos=(3.0, 0.0))
        net.add_edge("pump_outlet_tube", "pump_out", "test_in", cfg.pump_outlet_tube, "tube", group="feed",
                     config_path="pump_outlet_tube")
        cur = "test_in"
        net.add_node("test_out", "Test tube outlet", pos=(4.0, 0.0))
        net.add_edge("test_tube", cur, "test_out", sl.test_tube, "tube", group="test", config_path="single_line.test_tube")
        cur = "test_out"
        x = 5.0
        if sl.include_throttle and cfg.reactor_paths:
            net.add_node("thr_out", "Throttle outlet", pos=(x, 0.0))
            net.add_edge("throttle_1", cur, "thr_out", cfg.reactor_paths[0].throttle, "throttle", group="test",
                         config_path="reactor_paths.0.throttle")
            cur, x = "thr_out", x + 1
        if sl.include_reactor and cfg.reactor_paths:
            net.add_node("rx_out", "Reactor outlet", pos=(x, 0.0))
            net.add_edge("reactor_1", cur, "rx_out", cfg.reactor_paths[0].reactor, "reactor", group="test",
                         config_path="reactor_paths.0.reactor")
            cur, x = "rx_out", x + 1
        net.add_edge("return_tube", cur, "reservoir", cfg.return_tube, "tube", group="return", config_path="return_tube")
        return net

    n = cfg.n_reactors
    if n == 0 and not cfg.bypass.enabled:
        raise ValueError("Full layout needs at least one reactor path or an enabled bypass.")
    cfg.splitter_in.ensure_ports(n)
    cfg.splitter_out.ensure_ports(n)
    y_span = max(n, 1) + (1 if cfg.bypass.enabled else 0)
    y_mid = (y_span - 1) / 2.0

    use_tee = cfg.bypass.enabled and cfg.bypass.integration == "tee_pieces"
    net.add_node("s1_in", "Splitter 1 inlet", "port", pos=(3.0, -y_mid))
    if use_tee:
        net.add_node("tee1", "T-piece (feed)", "tee", pos=(2.6, -y_mid))
        net.add_edge("pump_outlet_tube", "pump_out", "tee1", cfg.pump_outlet_tube, "tube", group="feed", config_path="pump_outlet_tube")
        net.add_edge("tee1_run", "tee1", "s1_in", TeeChannel(name="T-piece feed (run)", tee=cfg.bypass.tee_in, branch=False),
                     "tee", group="feed", config_path="bypass.tee_in")
    else:
        net.add_edge("pump_outlet_tube", "pump_out", "s1_in", cfg.pump_outlet_tube, "tube", group="feed", config_path="pump_outlet_tube")
    net.add_node("S1", cfg.splitter_in.name, "splitter_hub", pos=(3.5, -y_mid))
    net.add_edge("s1_common", "s1_in", "S1", cfg.splitter_in.channel(None), "splitter_channel", group="feed",
                 config_path="splitter_in")
    net.add_node("S2", cfg.splitter_out.name, "splitter_hub", pos=(9.5, -y_mid))
    net.add_node("s2_out", "Splitter 2 outlet", "port", pos=(10.0, -y_mid))
    net.add_edge("s2_common", "S2", "s2_out", cfg.splitter_out.channel(None), "splitter_channel", group="return",
                 config_path="splitter_out")
    if use_tee:
        net.add_node("tee2", "T-piece (return)", "tee", pos=(10.4, -y_mid))
        net.add_edge("tee2_run", "s2_out", "tee2", TeeChannel(name="T-piece return (run)", tee=cfg.bypass.tee_out, branch=False),
                     "tee", group="return", config_path="bypass.tee_out")
        net.add_edge("return_tube", "tee2", "reservoir", cfg.return_tube, "tube", group="return", config_path="return_tube")
    else:
        net.add_edge("return_tube", "s2_out", "reservoir", cfg.return_tube, "tube", group="return", config_path="return_tube")

    for i, path in enumerate(cfg.reactor_paths):
        k = i + 1
        y = -float(i)
        grp = f"reactor_{k}"
        base = f"reactor_paths.{i}"
        net.add_node(f"s1_p{k}", f"Splitter 1 port {k}", "port", pos=(4.0, y))
        net.add_node(f"thr{k}_in", f"Throttle {k} inlet", pos=(5.0, y))
        net.add_node(f"thr{k}_out", f"Throttle {k} outlet", pos=(5.8, y))
        net.add_node(f"rx{k}_in", f"Reactor {k} inlet", pos=(6.8, y))
        net.add_node(f"rx{k}_out", f"Reactor {k} outlet", pos=(7.8, y))
        net.add_node(f"s2_p{k}", f"Splitter 2 port {k}", "port", pos=(9.0, y))
        net.add_edge(f"s1_ch{k}", "S1", f"s1_p{k}", cfg.splitter_in.channel(i), "splitter_channel", group=grp,
                     config_path=f"splitter_in.branch_ports.{i}")
        net.add_edge(f"tube_s1_thr{k}", f"s1_p{k}", f"thr{k}_in", path.tube_to_throttle, "tube", group=grp,
                     config_path=f"{base}.tube_to_throttle")
        net.add_edge(f"throttle_{k}", f"thr{k}_in", f"thr{k}_out", path.throttle, "throttle", group=grp,
                     config_path=f"{base}.throttle")
        net.add_edge(f"tube_thr_rx{k}", f"thr{k}_out", f"rx{k}_in", path.tube_to_reactor, "tube", group=grp,
                     config_path=f"{base}.tube_to_reactor")
        net.add_edge(f"reactor_{k}", f"rx{k}_in", f"rx{k}_out", path.reactor, "reactor", group=grp,
                     config_path=f"{base}.reactor")
        net.add_edge(f"tube_rx_s2{k}", f"rx{k}_out", f"s2_p{k}", path.tube_to_collector, "tube", group=grp,
                     config_path=f"{base}.tube_to_collector")
        net.add_edge(f"s2_ch{k}", f"s2_p{k}", "S2", cfg.splitter_out.channel(i), "splitter_channel", group=grp,
                     config_path=f"splitter_out.branch_ports.{i}")

    if cfg.bypass.enabled:
        bp = cfg.bypass
        y = -float(n)
        net.add_node("bp_a", "Bypass inlet", "port", pos=(4.0, y))
        net.add_node("bp_thr_in", "Bypass throttle inlet", pos=(5.6, y))
        net.add_node("bp_thr_out", "Bypass throttle outlet", pos=(6.6, y))
        net.add_node("bp_b", "Bypass outlet", "port", pos=(9.0, y))
        if use_tee:
            net.add_edge("tee1_branch", "tee1", "bp_a", TeeChannel(name="T-piece feed (branch)", tee=bp.tee_in, branch=True),
                         "tee", group="bypass", config_path="bypass.tee_in")
        else:
            port_mode = "ideal" if cfg.splitter_in.mode == "ideal" else ("individual_resistances" if cfg.splitter_in.mode == "individual_resistances" else "asymmetric")
            net.add_edge("s1_bypass", "S1", "bp_a", SplitterChannel(name="Splitter 1 bypass port", port=bp.splitter_port_in, mode=port_mode),
                         "splitter_channel", group="bypass", config_path="bypass.splitter_port_in")
        net.add_edge("bypass_tube_up", "bp_a", "bp_thr_in", bp.tube_upstream, "tube", group="bypass", config_path="bypass.tube_upstream")
        net.add_edge("bypass_throttle", "bp_thr_in", "bp_thr_out", bp.throttle, "throttle", group="bypass", config_path="bypass.throttle")
        if bp.extra_resistance > 0:
            from .elements import LinearResistor

            net.add_node("bp_res", "Bypass extra resistance", pos=(7.6, y))
            net.add_edge("bypass_resistor", "bp_thr_out", "bp_res", LinearResistor(name="bypass extra resistance", resistance=bp.extra_resistance),
                         "resistor", group="bypass", config_path="bypass")
            down_from = "bp_res"
        else:
            down_from = "bp_thr_out"
        net.add_edge("bypass_tube_down", down_from, "bp_b", bp.tube_downstream, "tube", group="bypass", config_path="bypass.tube_downstream")
        if use_tee:
            net.add_edge("tee2_branch", "bp_b", "tee2", TeeChannel(name="T-piece return (branch)", tee=bp.tee_out, branch=True),
                         "tee", group="bypass", config_path="bypass.tee_out")
        else:
            port_mode = "ideal" if cfg.splitter_out.mode == "ideal" else ("individual_resistances" if cfg.splitter_out.mode == "individual_resistances" else "asymmetric")
            net.add_edge("s2_bypass", "bp_b", "S2", SplitterChannel(name="Splitter 2 bypass port", port=bp.splitter_port_out, mode=port_mode),
                         "splitter_channel", group="bypass", config_path="bypass.splitter_port_out")
    return net


def internal_volume_breakdown(cfg: PerfusionSystemConfig) -> dict[str, float]:
    """Medium volume per group [m^3] (tubing, splitters, reactors, throttles, reservoir)."""
    net = build_network(cfg)
    out = {"tubing": 0.0, "splitters": 0.0, "throttles": 0.0, "bioreactors": 0.0, "T-pieces": 0.0}
    for e in net.edges.values():
        if e.is_pump:
            continue
        v = e.element.volume_m3()
        key = {"tube": "tubing", "splitter_channel": "splitters", "throttle": "throttles", "reactor": "bioreactors",
               "tee": "T-pieces"}.get(e.kind, "tubing")
        out[key] += v
    if cfg.layout == "full":
        out["splitters"] += cfg.splitter_in.hub_volume() + cfg.splitter_out.hub_volume()
    out["reservoir (fill)"] = cfg.reservoir.fill_volume_ml * 1e-6
    return out


def get_by_path(obj, path: str):
    """Access a nested configuration attribute by dotted path ('reactor_paths.0.throttle')."""
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, (list, tuple)):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            cur = getattr(cur, part)
    return cur


def set_by_path(obj, path: str, value) -> None:
    parts = path.split(".")
    parent = get_by_path(obj, ".".join(parts[:-1])) if len(parts) > 1 else obj
    last = parts[-1]
    if isinstance(parent, list):
        parent[int(last)] = value
    elif isinstance(parent, dict):
        parent[last] = value
    else:
        if not hasattr(parent, last):
            raise AttributeError(f"Parameter path '{path}' does not exist")
        setattr(parent, last, value)


__all__ = [
    "PerfusionSystemConfig", "ReactorPath", "ReservoirConfig", "SingleLineConfig", "default_system", "build_network",
    "set_reactor_count", "get_by_path", "set_by_path", "internal_volume_breakdown", "SplitterPort", "EXAMPLE_NOTE",
]
