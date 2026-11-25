import io
import json

import numpy as np
import pandas as pd
import pytest

from core.export import to_csv_zip_bytes, to_excel_bytes, to_json_str
from core.project import ProjectFile, compare_configs, config_hash, duplicate_project, dumps_project, load_project, loads_project, save_project, save_simulation_run
from core.pumps import import_pump_curve
from core.sensitivity import evaluate
from core.simulation import run_simulation
from core.validation import CalibrationParameter, apply_inputs, calibrate, compare, comparison_metrics, load_experimental_data, write_templates


def _synthetic_data(cfg, n=6, factor=None):
    rows = []
    truth = cfg.model_copy(deep=True)
    if factor:
        for p in truth.reactor_paths:
            p.throttle.calibration_factor = factor
    for i, (q, op) in enumerate(zip(np.linspace(2, 8, n), np.linspace(30, 100, n))):
        row = {"point_id": i, "dataset": "calibration" if i % 2 == 0 else "validation", "pump_flow_ml_min": q,
               "throttle_1_opening_percent": op}
        o, sol = evaluate(apply_inputs(truth, pd.Series(row)))
        row.update({f"Q_reactor_{k}_ml_min": o[f"Q_reactor_{k}_ml_min"] for k in range(1, 5)})
        row["pump_dp_pa"] = o["pump_dp_pa"]
        row["p_rx1_in_pa"] = sol.node_pressures["rx1_in"]
        row["u_pump_dp_pa"] = 5.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_comparison_perfect_agreement(cfg):
    df = _synthetic_data(cfg)
    sim, metrics = compare(cfg, df)
    assert (metrics.RMSE.abs() < 1e-6).all()
    assert set(metrics.quantity) >= {"Q_reactor_1_ml_min", "pump_dp_pa", "p_rx1_in_pa"}


def test_metrics_formulas():
    m = comparison_metrics(np.array([1.0, 2.0, 3.0, 5.0]), np.array([1.0, 2.0, 2.0, 4.0]), u=np.array([1, 1, 1, 0.1]))
    assert m["MAE"] == pytest.approx(0.5)
    assert m["RMSE"] == pytest.approx(np.sqrt(0.5))
    assert m["bias"] == pytest.approx(0.5)
    assert m["bias_CI_low"] < m["bias"] < m["bias_CI_high"]
    assert "R2" in m
    assert m["fraction_within_2u_percent"] == pytest.approx(75.0)


def test_calibration_recovers_factor_and_validates(cfg):
    df = _synthetic_data(cfg, factor=3.0)
    cal_cfg, info = calibrate(cfg, df, [CalibrationParameter(path="reactor_paths.*.throttle.calibration_factor", low=0.1, high=20)])
    assert info["parameters"][0]["value"] == pytest.approx(3.0, rel=1e-3)
    val = df[df.dataset == "validation"]
    _, metrics = compare(cal_cfg, val)
    assert (metrics.RMSE < 1e-3 * np.abs(val[metrics.quantity].values).max()).all()


def test_csv_excel_import(cfg, tmp_path):
    df = _synthetic_data(cfg, n=3)
    p = tmp_path / "x.csv"
    df.to_csv(p, index=False)
    assert len(load_experimental_data(p)) == 3
    px = tmp_path / "x.xlsx"
    df.to_excel(px, index=False)
    assert len(load_experimental_data(px)) == 3
    files = write_templates(tmp_path / "tpl")
    assert len(files) == 10
    assert all(f.read_text().startswith("#") for f in files)


def test_pump_curve_import(tmp_path):
    p = tmp_path / "curve.csv"
    p.write_text("Speed_rpm;Flow_ml_min;dp_mbar;Power_W\n30;0;80;0.5\n30;5;50;0.6\n30;10;0;0.7\n")
    pts = import_pump_curve(p)
    assert len(pts) == 3 and pts[0].dp_pa == pytest.approx(8000)
    with pytest.raises(ValueError):
        q = tmp_path / "bad.csv"
        q.write_text("a,b\n1,2\n")
        import_pump_curve(q)


@pytest.mark.parametrize("ext", ["json", "yaml"])
def test_project_roundtrip(cfg, tmp_path, ext):
    proj = ProjectFile(name="test", config=cfg)
    proj.new_version("changed throttle")
    p = save_project(proj, tmp_path / f"p.{ext}")
    back = load_project(p)
    assert back.project_version == 2 and len(back.changelog) == 2
    assert config_hash(back.config) == config_hash(cfg)
    assert compare_configs(cfg, back.config).empty


def test_duplicate_and_compare(cfg):
    proj = ProjectFile(name="a", config=cfg)
    dup = duplicate_project(proj, "b")
    dup.config.reactor_paths[0].throttle.opening_percent = 42
    diff = compare_configs(proj.config, dup.config)
    assert "reactor_paths.0.throttle.opening_percent" in set(diff.parameter)
    assert loads_project(dumps_project(dup)).name == "b"


def test_save_run_and_exports(cfg, tmp_path):
    res = run_simulation(cfg)
    d = save_simulation_run(res, tmp_path, "unit test")
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["software_version"] == "1.0.0"
    assert (d / "config.json").exists() and (d / "segments.csv").exists()
    xl = to_excel_bytes(res)
    sheets = pd.read_excel(io.BytesIO(xl), sheet_name=None)
    assert {"Summary", "Segments", "Reactors", "Convergence", "Warnings", "Configuration"} <= set(sheets)
    js = json.loads(to_json_str(res))
    assert js["software_version"] == "1.0.0" and "configuration" in js
    assert len(to_csv_zip_bytes(res)) > 1000
