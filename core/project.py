"""Project management: save / load / duplicate / compare / version configurations and
store simulation runs reproducibly (spec. chapter 19).

File format: JSON (default) or YAML. Every file contains the software name and version,
time stamps, a project version number and a change log together with the full system
configuration. Simulation runs are stored as a folder containing the configuration, the
results, the software version and a SHA-256 hash of the configuration.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, Field

from . import APP_NAME, SOFTWARE_VERSION
from .system import PerfusionSystemConfig


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class ChangeEntry(BaseModel):
    version: int
    timestamp: str = Field(default_factory=_now)
    author: str = ""
    note: str = ""


class ProjectFile(BaseModel):
    software: str = APP_NAME
    software_version: str = SOFTWARE_VERSION
    name: str = "Perfusion project"
    project_version: int = 1
    created: str = Field(default_factory=_now)
    modified: str = Field(default_factory=_now)
    changelog: list[ChangeEntry] = Field(default_factory=lambda: [ChangeEntry(version=1, note="created")])
    config: PerfusionSystemConfig = Field(default_factory=PerfusionSystemConfig)

    def new_version(self, note: str, author: str = "") -> None:
        self.project_version += 1
        self.modified = _now()
        self.software_version = SOFTWARE_VERSION
        self.changelog.append(ChangeEntry(version=self.project_version, note=note, author=author))


def config_hash(cfg: PerfusionSystemConfig) -> str:
    js = json.dumps(cfg.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(js.encode()).hexdigest()


def dumps_project(proj: ProjectFile, fmt: str = "json") -> str:
    data = proj.model_dump(mode="json")
    if fmt == "yaml":
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return json.dumps(data, indent=2, ensure_ascii=False)


def loads_project(text: str | bytes) -> ProjectFile:
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    text = text.strip()
    data = json.loads(text) if text.startswith("{") else yaml.safe_load(text)
    if "config" not in data:  # bare configuration file
        data = {"config": data, "name": data.get("name", "imported configuration")}
    return ProjectFile.model_validate(data)


def save_project(proj: ProjectFile, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fmt = "yaml" if p.suffix.lower() in (".yaml", ".yml") else "json"
    proj.modified = _now()
    p.write_text(dumps_project(proj, fmt), encoding="utf-8")
    return p


def load_project(path: str | Path) -> ProjectFile:
    return loads_project(Path(path).read_text(encoding="utf-8"))


def duplicate_project(proj: ProjectFile, new_name: str) -> ProjectFile:
    dup = proj.model_copy(deep=True)
    dup.name = new_name
    dup.config.name = new_name
    dup.project_version = 1
    dup.created = dup.modified = _now()
    dup.changelog = [ChangeEntry(version=1, note=f"duplicated from '{proj.name}' v{proj.project_version}")]
    return dup


def flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list) and d and isinstance(d[0], (dict, list)):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}.{i}"))
    else:
        out[prefix] = d
    return out


def compare_configs(a: PerfusionSystemConfig, b: PerfusionSystemConfig, name_a="A", name_b="B") -> pd.DataFrame:
    fa, fb = flatten(a.model_dump(mode="json")), flatten(b.model_dump(mode="json"))
    rows = []
    for k in sorted(set(fa) | set(fb)):
        va, vb = fa.get(k, "<missing>"), fb.get(k, "<missing>")
        if va != vb:
            rows.append({"parameter": k, name_a: str(va), name_b: str(vb)})
    return pd.DataFrame(rows, columns=["parameter", name_a, name_b])


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")[:60] or "run"


def save_simulation_run(result, directory: str | Path, label: str = "run", extra_tables: dict[str, pd.DataFrame] | None = None) -> Path:
    """Store a simulation result together with its configuration and software version."""
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(directory) / f"{ts}_{_safe(label)}"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"software": APP_NAME, "software_version": SOFTWARE_VERSION, "timestamp": _now(), "label": label,
            "config_sha256": config_hash(result.config)}
    (d / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (d / "config.json").write_text(json.dumps(result.config.model_dump(mode="json"), indent=2), encoding="utf-8")
    (d / "results.json").write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
    result.edges.to_csv(d / "segments.csv", index=False)
    result.reactors.to_csv(d / "reactors.csv", index=False)
    result.nodes.to_csv(d / "nodes.csv", index=False)
    for name, df in (extra_tables or {}).items():
        df.to_csv(d / f"{_safe(name)}.csv", index=False)
    return d


def save_study(df: pd.DataFrame, base: PerfusionSystemConfig, spec: dict, directory: str | Path, label: str = "study") -> Path:
    """Store a parameter study reproducibly: base config + study definition + results."""
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(directory) / f"{ts}_{_safe(label)}"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"software": APP_NAME, "software_version": SOFTWARE_VERSION, "timestamp": _now(), "study": spec,
            "config_sha256": config_hash(base)}
    (d / "study.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    (d / "base_config.json").write_text(json.dumps(base.model_dump(mode="json"), indent=2), encoding="utf-8")
    df.to_csv(d / "results.csv", index=False)
    return d
