# Verification report - analytical reference cases

Perfusion System Hydraulic Simulator V1.0.0 - generated 2026-11-25 09:14

Each case compares the software result with an analytical solution (or, where marked
*empirical*, with tabulated reference values / an alternative correlation). Tolerances are
relative unless marked otherwise. Regenerate with `python tools/generate_verification_report.py`.

**Result: 30 of 30 cases passed.**

| ID | Test case | Description | Expected | Actual | Deviation | Tolerance | Class | Result |
|---|---|---|---|---|---|---|---|---|
| V01 | Hagen-Poiseuille pressure drop | Tube L=1 m, d=1.6 mm, Q=5 mL/min, water 20 degC: dp = 128 mu L Q/(pi d^4) | 518.911 Pa | 518.911 Pa | 0.00e+00 (rel.) | 1e-10 (rel.) | analytical | PASS |
| V02 | Laminar resistance proportional to length | R(2L)/R(L) = 2 | 2 - | 2 - | 0.00e+00 (rel.) | 1e-10 (rel.) | analytical | PASS |
| V03 | Laminar resistance ~ d^-4 | R(d/2)/R(d) = 16 (laminar) | 16 - | 16 - | 0.00e+00 (rel.) | 1e-10 (rel.) | analytical | PASS |
| V04 | Reynolds number | Re = rho v d / mu | 66.0895 - | 66.0895 - | 0.00e+00 (rel.) | 1e-12 (rel.) | analytical | PASS |
| V05 | Laminar wall shear stress | tau_w = 32 mu Q / (pi d^3) | 0.207565 Pa | 0.207565 Pa | 2.67e-16 (rel.) | 1e-10 (rel.) | analytical | PASS |
| V06 | Colebrook-White residual | 1/sqrt(f) - RHS = 0 at Re=1e5, eps/d=1e-4 | 0 - | -1.87406e-13 - | 1.87e-13 | 1e-09 | numerical | PASS |
| V07 | Smooth turbulent friction vs. Blasius | f_Colebrook(Re=2e4, smooth) vs 0.3164 Re^-0.25 (empirical, 3 %) | 0.026606 - | 0.0258831 - | 2.72e-02 (rel.) | 3e-02 (rel.) | empirical | PASS |
| V08 | Darcy flow through scaffold | dp = mu H Q /(k A) | 49.8155 Pa | 49.8155 Pa | 1.43e-16 (rel.) | 1e-12 (rel.) | analytical | PASS |
| V09 | Elliptical duct, a=b | R_ellipse(a=b=d/2) = R_HP | 6.22694e+09 Pa s/m^3 | 6.22694e+09 Pa s/m^3 | 1.53e-16 (rel.) | 1e-12 (rel.) | analytical | PASS |
| V10 | Linear taper d1=d2 | R_taper(d,d) = R_HP | 6.22694e+09 Pa s/m^3 | 6.22694e+09 Pa s/m^3 | 1.53e-16 (rel.) | 1e-12 (rel.) | analytical | PASS |
| V11 | Series resistances | dp_pump = (R1+R2+R3) Q | 500 Pa | 500 Pa | 1.14e-16 (rel.) | 1e-09 (rel.) | numerical | PASS |
| V12 | Parallel resistances: flow share | Q1/Q = (1/R1)/sum(1/Ri) = 4/7 | 0.571429 - | 0.571429 - | 0.00e+00 (rel.) | 1e-09 (rel.) | numerical | PASS |
| V13 | Parallel resistances: pressure | dp = Q / sum(1/Ri) | 47.619 Pa | 47.619 Pa | 0.00e+00 (rel.) | 1e-09 (rel.) | numerical | PASS |
| V14 | Mass conservation at junction | Q_pump - sum(Q_i) = 0 | 0 - | 0 - | 0.00e+00 | 1e-10 | numerical | PASS |
| V15 | Blocked parallel path | Q_blocked = 0, others share Q/2 | 4.16667e-08 m^3/s | 4.16667e-08 m^3/s | 0.00e+00 (rel.) | 1e-09 (rel.) | numerical | PASS |
| V16 | Blocked parallel path: zero flow | Q_blocked == 0 exactly | 0 m^3/s | 0 m^3/s | 0.00e+00 | 0e+00 | numerical | PASS |
| V17 | Identical parallel paths | max |Q_i - Q/4| / (Q/4) = 0 | 0 - | 1.58819e-16 - | 1.59e-16 | 1e-10 | numerical | PASS |
| V18 | Pump mode B consistency | Mode B with dp from mode A gives Q = 5 mL/min | 8.33333e-08 m^3/s | 8.33333e-08 m^3/s | 2.06e-15 (rel.) | 1e-08 (rel.) | numerical | PASS |
| V19 | Pump curve operating point | Intersection of linear pump and system curve | 1.25e-07 m^3/s | 1.25e-07 m^3/s | 0.00e+00 (rel.) | 1e-08 (rel.) | numerical | PASS |
| V20 | Displacement pump with slip | Q = Q_th / (1 + C_slip R) | 9.23077e-08 m^3/s | 9.23077e-08 m^3/s | 0.00e+00 (rel.) | 1e-08 (rel.) | numerical | PASS |
| V21 | Hydrostatic head | p_in - p_out = dp_friction + rho g dz | 2217.26 Pa | 2217.26 Pa | 0.00e+00 (rel.) | 1e-09 (rel.) | numerical | PASS |
| V22 | Unit conversion mL/min -> m^3/s | 1 mL/min = 1/60e6 m^3/s | 1.66667e-08 m^3/s | 1.66667e-08 m^3/s | 0.00e+00 (rel.) | 1e-15 (rel.) | analytical | PASS |
| V23 | Unit conversion mmHg -> Pa | 1 mmHg = 133.322387415 Pa | 133.322 Pa | 133.322 Pa | 0.00e+00 (rel.) | 1e-15 (rel.) | analytical | PASS |
| V24 | Water viscosity 20 degC | Tabulated reference 1.0016 mPa s (1 %) | 0.0010016 Pa s | 0.00100175 Pa s | 1.49e-04 (rel.) | 1e-02 (rel.) | empirical | PASS |
| V25 | Water viscosity 37 degC | Tabulated reference 0.6913 mPa s (1.5 %) | 0.0006913 Pa s | 0.000690398 Pa s | 1.31e-03 (rel.) | 1e-02 (rel.) | empirical | PASS |
| V26 | Water density 20 degC | Tabulated reference 998.21 kg/m^3 (0.01 %) | 998.21 kg/m^3 | 998.207 kg/m^3 | 3.26e-06 (rel.) | 1e-04 (rel.) | empirical | PASS |
| V27 | Water density 37 degC | Tabulated reference 993.33 kg/m^3 (0.02 %) | 993.33 kg/m^3 | 993.329 kg/m^3 | 1.05e-06 (rel.) | 2e-04 (rel.) | empirical | PASS |
| V28 | Uniform constriction (laminar) | 50 % diameter reduction over 0.1 m: R = R(0.9 m, d) + R(0.1 m, d/2) | 1297.28 Pa | 1297.28 Pa | 0.00e+00 (rel.) | 1e-09 (rel.) | analytical | PASS |
| V29 | Area vs. diameter reduction | 75 % area reduction = 50 % diameter reduction | 0.0008 m | 0.0008 m | 0.00e+00 (rel.) | 1e-12 (rel.) | analytical | PASS |
| V30 | Medium viscosity from user ratio | mu = 1.1 mu_water(37 degC) | 0.000759437 Pa s | 0.000759437 Pa s | 0.00e+00 (rel.) | 1e-12 (rel.) | analytical | PASS |
