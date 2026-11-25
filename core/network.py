"""Generic hydraulic network: nodes and components (edges).

The network is a directed multigraph. Each edge carries a hydraulic component (passive
element or pump). The edge direction defines the positive flow direction; negative
solutions mean reverse flow. Any topology (series, parallel, loops, several pumps,
several fixed-pressure nodes) can be represented -- the standard perfusion system is just
one particular network built in :mod:`core.system`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx


@dataclass
class Node:
    id: str
    label: str = ""
    kind: str = "junction"  # reservoir | junction | splitter_hub | port | tee | pump_port ...
    fixed_pressure: float | None = None  # Pa (gauge) -- boundary condition
    pos: tuple[float, float] = (0.0, 0.0)
    elevation_m: float = 0.0


@dataclass
class Edge:
    id: str
    from_node: str
    to_node: str
    element: Any
    kind: str = "tube"  # tube | throttle | reactor | splitter_channel | tee | pump | resistor
    label: str = ""
    group: str = ""  # flow path the edge belongs to, e.g. 'reactor_1', 'bypass', 'feed', 'return'
    config_path: str = ""  # dotted path to the configuration object (for UI editing)

    @property
    def is_pump(self) -> bool:
        return self.kind == "pump"

    def is_closed(self) -> bool:
        if self.is_pump:
            return False
        return bool(self.element.is_closed())


@dataclass
class HydraulicNetwork:
    name: str = "network"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)

    # --- construction -------------------------------------------------------
    def add_node(self, id: str, label: str = "", kind: str = "junction", fixed_pressure: float | None = None,
                 pos=(0.0, 0.0)) -> Node:
        if id in self.nodes:
            raise ValueError(f"Duplicate node id '{id}'")
        n = Node(id=id, label=label or id, kind=kind, fixed_pressure=fixed_pressure, pos=pos)
        self.nodes[id] = n
        return n

    def add_edge(self, id: str, from_node: str, to_node: str, element, kind: str = "tube", label: str = "",
                 group: str = "", config_path: str = "") -> Edge:
        if id in self.edges:
            raise ValueError(f"Duplicate edge id '{id}'")
        for n in (from_node, to_node):
            if n not in self.nodes:
                raise ValueError(f"Edge '{id}' references unknown node '{n}'")
        if from_node == to_node:
            raise ValueError(f"Edge '{id}' is a self-loop")
        e = Edge(id=id, from_node=from_node, to_node=to_node, element=element, kind=kind,
                 label=label or getattr(element, "name", id), group=group, config_path=config_path)
        self.edges[id] = e
        return e

    def add_series(self, prefix: str, from_node: str, to_node: str, elements: list, kinds: list[str],
                   group: str = "") -> list[Edge]:
        """Convenience: connect several elements in series with automatically created nodes."""
        edges = []
        current = from_node
        for i, (el, k) in enumerate(zip(elements, kinds)):
            nxt = to_node if i == len(elements) - 1 else f"{prefix}_n{i+1}"
            if nxt not in self.nodes:
                self.add_node(nxt)
            edges.append(self.add_edge(f"{prefix}_{i+1}", current, nxt, el, kind=k, group=group))
            current = nxt
        return edges

    # --- queries ----------------------------------------------------------------
    @property
    def pumps(self) -> list[Edge]:
        return [e for e in self.edges.values() if e.is_pump]

    def fixed_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.fixed_pressure is not None]

    def to_networkx(self, open_only: bool = False) -> nx.MultiGraph:
        g = nx.MultiGraph()
        g.add_nodes_from(self.nodes)
        for e in self.edges.values():
            if open_only and e.is_closed():
                continue
            g.add_edge(e.from_node, e.to_node, key=e.id)
        return g

    def to_digraph(self) -> nx.MultiDiGraph:
        g = nx.MultiDiGraph()
        for n in self.nodes.values():
            g.add_node(n.id, label=n.label, kind=n.kind, pos=n.pos)
        for e in self.edges.values():
            g.add_edge(e.from_node, e.to_node, key=e.id, kind=e.kind, label=e.label)
        return g

    def validate(self) -> list[str]:
        """Topological plausibility checks; returns a list of error messages."""
        errors = []
        if not self.fixed_nodes():
            errors.append("No node with fixed pressure (reference / reservoir) defined.")
        g = self.to_networkx()
        if g.number_of_nodes() and not nx.is_connected(g):
            comps = list(nx.connected_components(g))
            errors.append(f"Network is not connected ({len(comps)} separate parts).")
        for n in self.nodes.values():
            if g.degree(n.id) == 0:
                errors.append(f"Node '{n.id}' has no connections.")
        return errors

    def total_volume_m3(self) -> float:
        return sum(e.element.volume_m3() for e in self.edges.values() if not e.is_pump)
