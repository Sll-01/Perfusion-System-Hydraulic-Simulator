"""Nonlinear hydraulic network solver (spec. chapter 12).

Formulation (mixed nodal-pressure / branch-flow formulation)
------------------------------------------------------------
Unknowns:   p_i  for every node without prescribed pressure (in solvable parts)
            Q_j  for every open edge (passive components and pumps)

Equations:
  (1) mass conservation at every node with unknown pressure
          sum_{j in(i)} Q_j - sum_{j out(i)} Q_j = 0
  (2) passive branch j (from a to b):
          p_a - p_b - rho g dz_j - dp_j(Q_j) = 0
  (3) pump branch:  r_pump(Q, p_out - p_in) = 0   (mode dependent, see core.pumps)

Closed components (fully blocked tube, closed throttle, blocked reactor) are removed from
the unknowns with Q = 0 *exactly*; no artificial "very large resistance" is used, which
keeps the Jacobian well conditioned. Network parts that are cut off from every
fixed-pressure node (e.g. a section closed at both ends) have an undefined pressure; they
are reported as isolated (pressure NaN, Q = 0).

Scaling: flows are scaled by Q_s (characteristic flow), pressures by P_s (1 kPa); all
residuals are dimensionless. Solution: damped Newton-Raphson with backtracking line search
and an analytical incidence structure; element derivatives d(dp)/dQ by central differences.
Fallback: scipy.optimize.root (MINPACK hybrd / Levenberg-Marquardt).

Convergence criteria (documented, configurable):
  max |mass residual|     <= tol_mass_rel * Q_s          [m^3/s]
  max |pressure residual| <= tol_pressure_pa             [Pa]
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from pydantic import BaseModel, Field
from scipy import optimize

from .fluids import FluidState
from .hydraulics import FrictionSettings
from .network import HydraulicNetwork


class SolverSettings(BaseModel):
    tol_mass_rel: float = Field(1e-10, description="Mass residual tolerance relative to Q_s")
    tol_pressure_pa: float = Field(1e-6, description="Pressure-equation residual tolerance [Pa]")
    max_iterations: int = 100
    pressure_scale_pa: float = 1000.0
    flow_scale_m3s: float | None = None
    use_fallback: bool = True
    turbulent_model: str = "colebrook"
    re_laminar: float = 2000.0
    re_turbulent: float = 4000.0
    allow_backflow: bool = True

    def friction(self) -> FrictionSettings:
        return FrictionSettings(self.turbulent_model, self.re_laminar, self.re_turbulent)


class SolverError(RuntimeError):
    pass


@dataclass
class SolverResult:
    converged: bool
    node_pressures: dict[str, float]
    edge_flows: dict[str, float]
    iterations: int = 0
    method: str = ""
    max_mass_residual: float = math.nan  # m^3/s
    max_pressure_residual: float = math.nan  # Pa
    mass_residuals: dict[str, float] = field(default_factory=dict)
    pressure_residuals: dict[str, float] = field(default_factory=dict)
    residual_history: list[float] = field(default_factory=list)
    condition_number: float = math.nan
    isolated_nodes: list[str] = field(default_factory=list)
    closed_edges: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    q_scale: float = math.nan
    p_scale: float = math.nan


def _estimate_q_scale(net: HydraulicNetwork) -> float:
    for e in net.pumps:
        p = e.element
        kind, a, _ = p.linear_guess()
        if kind == "flow" and a > 0:
            return a
    return 1e-8  # 0.6 mL/min


def solve_network(net: HydraulicNetwork, fluid: FluidState, settings: SolverSettings | None = None,
                  initial: SolverResult | None = None) -> SolverResult:
    """Solve the steady-state flow and pressure distribution of a hydraulic network."""
    st = settings or SolverSettings()
    fs = st.friction()
    errors = net.validate()
    if any("No node with fixed pressure" in e for e in errors):
        raise SolverError(errors[0])

    P_s = st.pressure_scale_pa
    Q_s = st.flow_scale_m3s or _estimate_q_scale(net)

    edges = list(net.edges.values())
    closed = [e.id for e in edges if e.is_closed()]
    open_edges = [e for e in edges if not e.is_closed()]

    # ---- connectivity analysis (open edges only) --------------------------------
    g = nx.MultiGraph()
    g.add_nodes_from(net.nodes)
    for e in open_edges:
        g.add_edge(e.from_node, e.to_node, key=e.id)
    active_nodes: set[str] = set()
    isolated: list[str] = []
    errs: list[str] = []
    msgs: list[str] = []
    for comp in nx.connected_components(g):
        if any(net.nodes[n].fixed_pressure is not None for n in comp):
            active_nodes |= comp
        else:
            isolated.extend(sorted(comp))
            comp_pumps = [e for e in open_edges if e.is_pump and e.from_node in comp]
            for pe in comp_pumps:
                errs.append(f"Pump '{pe.id}' lies in a section without pressure reference (closed suction/return).")
    if isolated:
        msgs.append(
            "Isolated sections (closed at both ends, pressure undefined, Q = 0): " + ", ".join(isolated)
        )

    act_edges = [e for e in open_edges if e.from_node in active_nodes]

    # ---- physical feasibility pre-checks -----------------------------------
    for pe in [e for e in act_edges if e.is_pump]:
        pump = pe.element
        g2 = g.copy()
        g2.remove_edge(pe.from_node, pe.to_node, key=pe.id)
        connected = nx.has_path(g2, pe.from_node, pe.to_node)
        if not connected:
            # also connected through fixed-pressure nodes (open system)?
            fixed = {n for n in active_nodes if net.nodes[n].fixed_pressure is not None}
            reach_a = nx.node_connected_component(g2, pe.from_node) & fixed
            reach_b = nx.node_connected_component(g2, pe.to_node) & fixed
            connected = bool(reach_a and reach_b)
        if not connected:
            kind, a, b = pump.linear_guess()
            if pump.mode == "A_constant_flow" and a > 0:
                errs.append(
                    "Physically impossible: constant-flow pump (mode A) works against a completely closed circuit "
                    "(all flow paths blocked). The required pressure would be infinite."
                )
            if pump.mode == "D_displacement" and a > 0 and b == 0:
                errs.append(
                    "Physically impossible: displacement pump (mode D) without slip is dead-headed (all flow paths "
                    "blocked); pressure would rise until the maximum permissible pressure / tube failure."
                )
    if errs:
        return SolverResult(False, {n: math.nan for n in net.nodes}, {e.id: math.nan for e in edges},
                            method="pre-check", errors=errs, messages=msgs, isolated_nodes=isolated,
                            closed_edges=closed, q_scale=Q_s, p_scale=P_s)

    p_nodes = [n for n in net.nodes if n in active_nodes and net.nodes[n].fixed_pressure is None]
    p_idx = {n: i for i, n in enumerate(p_nodes)}
    q_idx = {e.id: len(p_nodes) + j for j, e in enumerate(act_edges)}
    nP, nQ = len(p_nodes), len(act_edges)
    N = nP + nQ
    fixed_p = {n.id: n.fixed_pressure for n in net.nodes.values() if n.fixed_pressure is not None}

    # incidence for mass balance
    inc_rows: list[list[tuple[int, float]]] = [[] for _ in range(nP)]
    for e in act_edges:
        if e.to_node in p_idx:
            inc_rows[p_idx[e.to_node]].append((q_idx[e.id], 1.0))
        if e.from_node in p_idx:
            inc_rows[p_idx[e.from_node]].append((q_idx[e.id], -1.0))

    hydro = {e.id: (0.0 if e.is_pump else e.element.hydrostatic(fluid)) for e in act_edges}

    def pressure(x, node):
        if node in p_idx:
            return x[p_idx[node]] * P_s
        return fixed_p.get(node, math.nan)

    def residual(x):
        F = np.zeros(N)
        for i in range(nP):
            F[i] = sum(s * x[k] for k, s in inc_rows[i])
        for j, e in enumerate(act_edges):
            Q = x[nP + j] * Q_s
            pa, pb = pressure(x, e.from_node), pressure(x, e.to_node)
            if e.is_pump:
                F[nP + j] = e.element.residual(Q, pb - pa, P_s, Q_s)
            else:
                F[nP + j] = (pa - pb - hydro[e.id] - e.element.pressure_drop(Q, fluid, fs)) / P_s
        return F

    def jacobian(x):
        J = np.zeros((N, N))
        for i in range(nP):
            for k, s in inc_rows[i]:
                J[i, k] += s
        for j, e in enumerate(act_edges):
            row = nP + j
            Q = x[nP + j] * Q_s
            a, b = e.from_node, e.to_node
            if e.is_pump:
                pa, pb = pressure(x, a), pressure(x, b)
                hq = 1e-7 * max(abs(Q), Q_s)
                hp = 1e-7 * max(abs(pb - pa), P_s)
                r0 = e.element.residual(Q, pb - pa, P_s, Q_s)
                dr_dQ = (e.element.residual(Q + hq, pb - pa, P_s, Q_s) - r0) / hq
                dr_ddp = (e.element.residual(Q, pb - pa + hp, P_s, Q_s) - r0) / hp
                J[row, nP + j] = dr_dQ * Q_s
                if b in p_idx:
                    J[row, p_idx[b]] += dr_ddp * P_s
                if a in p_idx:
                    J[row, p_idx[a]] -= dr_ddp * P_s
            else:
                if a in p_idx:
                    J[row, p_idx[a]] += 1.0
                if b in p_idx:
                    J[row, p_idx[b]] -= 1.0
                Rd = e.element.resistance_differential(Q, fluid, fs, q_scale=Q_s)
                Rd = max(Rd, 1e-12 * P_s / Q_s)  # regularisation of the Jacobian only
                J[row, nP + j] = -Rd * Q_s / P_s
        return J

    # ---- initial guess: linearised network --------------------------------------
    x0 = np.zeros(N)
    if initial is not None and initial.converged:
        for n, i in p_idx.items():
            v = initial.node_pressures.get(n, 0.0)
            x0[i] = 0.0 if not np.isfinite(v) else v / P_s
        for e in act_edges:
            v = initial.edge_flows.get(e.id, 0.0)
            x0[q_idx[e.id]] = 0.0 if not np.isfinite(v) else v / Q_s
    else:
        A = np.zeros((N, N))
        rhs = np.zeros(N)
        for i in range(nP):
            for k, s in inc_rows[i]:
                A[i, k] += s
        q_ref = Q_s / max(1, sum(1 for e in act_edges if e.kind == "reactor") + 1)
        for j, e in enumerate(act_edges):
            row = nP + j
            a, b = e.from_node, e.to_node
            if e.is_pump:
                kind, c0, c1 = e.element.linear_guess()
                if kind == "flow":  # Q + c1 (pb - pa) = c0
                    A[row, nP + j] = Q_s
                    for node, sgn in ((b, 1.0), (a, -1.0)):
                        if node in p_idx:
                            A[row, p_idx[node]] += sgn * c1 * P_s
                        else:
                            rhs[row] -= sgn * c1 * fixed_p.get(node, 0.0)
                    rhs[row] += c0
                else:  # (pb - pa) + c1 Q = c0
                    A[row, nP + j] = c1 * Q_s
                    for node, sgn in ((b, 1.0), (a, -1.0)):
                        if node in p_idx:
                            A[row, p_idx[node]] += sgn * P_s
                        else:
                            rhs[row] -= sgn * fixed_p.get(node, 0.0)
                    rhs[row] += c0
            else:
                R = e.element.pressure_drop(q_ref, fluid, fs) / q_ref
                R = max(R, 1e-6 * P_s / Q_s)
                for node, sgn in ((a, 1.0), (b, -1.0)):
                    if node in p_idx:
                        A[row, p_idx[node]] += sgn * P_s
                    else:
                        rhs[row] -= sgn * fixed_p.get(node, 0.0)
                A[row, nP + j] = -R * Q_s
                rhs[row] += hydro[e.id]
        try:
            x0 = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            x0 = np.linalg.lstsq(A, rhs, rcond=None)[0]

    # ---- damped Newton ------------------------------------------------------------
    x = x0.copy()
    history = []
    converged = False
    method = "Newton-Raphson (damped, line search)"
    it = 0
    tol_mass = st.tol_mass_rel  # scaled mass residual is Q/Q_s
    tol_p = st.tol_pressure_pa / P_s

    def is_conv(F):
        m = np.max(np.abs(F[:nP])) if nP else 0.0
        pr = np.max(np.abs(F[nP:])) if nQ else 0.0
        return m <= tol_mass and pr <= tol_p

    cond = math.nan
    F = residual(x)
    for it in range(1, st.max_iterations + 1):
        nrm = float(np.linalg.norm(F, np.inf))
        history.append(nrm)
        if is_conv(F):
            converged = True
            it -= 1
            break
        J = jacobian(x)
        try:
            dx = np.linalg.solve(J, -F)
        except np.linalg.LinAlgError:
            msgs.append("Singular Jacobian in Newton iteration.")
            break
        lam = 1.0
        f0 = float(np.dot(F, F))
        while lam > 1e-6:
            x_new = x + lam * dx
            F_new = residual(x_new)
            if np.all(np.isfinite(F_new)) and float(np.dot(F_new, F_new)) <= (1 - 1e-4 * lam) * f0:
                break
            lam *= 0.5
        x, F = x_new, F_new
    else:
        if is_conv(F):
            converged = True

    if not converged and st.use_fallback and N > 0:
        for meth in ("hybr", "lm"):
            sol = optimize.root(lambda y: residual(y), x, jac=jacobian, method=meth,
                                options={"xtol": 1e-14} if meth == "hybr" else {"xtol": 1e-14, "ftol": 1e-14})
            F_try = residual(sol.x)
            if np.all(np.isfinite(F_try)) and is_conv(F_try):
                x, F = sol.x, F_try
                converged = True
                method = f"scipy.optimize.root ({meth}) after Newton"
                break
        if not converged:
            msgs.append("Solver did not converge to the requested tolerance.")

    try:
        if N > 0:
            cond = float(np.linalg.cond(jacobian(x)))
    except Exception:  # pragma: no cover
        cond = math.nan
    if cond > 1e14:
        msgs.append(f"Jacobian is badly conditioned (cond = {cond:.2e}); results may be inaccurate.")

    # ---- assemble results ----------------------------------------------------------
    pressures = {}
    for n in net.nodes:
        if n in fixed_p:
            pressures[n] = fixed_p[n]
        elif n in p_idx:
            pressures[n] = float(x[p_idx[n]] * P_s)
        else:
            pressures[n] = math.nan
    flows = {e.id: 0.0 for e in edges}
    for e in act_edges:
        flows[e.id] = float(x[q_idx[e.id]] * Q_s)

    mass_res = {n: float(F[i] * Q_s) for n, i in p_idx.items()}
    pres_res = {}
    for j, e in enumerate(act_edges):
        pres_res[e.id] = float(F[nP + j] * (P_s if not (e.is_pump and e.element.mode in ("A_constant_flow", "D_displacement")) else 1.0))
        if e.is_pump and e.element.mode in ("A_constant_flow", "D_displacement"):
            mass_res[f"pump:{e.id}"] = float(F[nP + j] * Q_s)
            pres_res.pop(e.id)
    res = SolverResult(
        converged=converged,
        node_pressures=pressures,
        edge_flows=flows,
        iterations=it,
        method=method,
        max_mass_residual=max((abs(v) for v in mass_res.values()), default=0.0),
        max_pressure_residual=max((abs(v) for v in pres_res.values()), default=0.0),
        mass_residuals=mass_res,
        pressure_residuals=pres_res,
        residual_history=history,
        condition_number=cond,
        isolated_nodes=isolated,
        closed_edges=closed,
        messages=msgs,
        errors=[] if converged else ["Solution not converged."],
        q_scale=Q_s,
        p_scale=P_s,
    )
    if not all(np.isfinite(list(flows.values()))):
        res.converged = False
        res.errors.append("Non-finite values in the solution (numerical error).")
    return res
