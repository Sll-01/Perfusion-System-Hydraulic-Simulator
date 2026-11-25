# Test results

Software version 1.0.0 - run 2026-11-25 09:18 - Python 3.12.3

**158 passed, 0 failed, 158 total.**

| Module | Test | Result | Time [s] |
|---|---|---|---|
| test_components | test_tube_local_losses_added_without_double_counting | PASS | 0.00 |
| test_components | test_tube_area_change_K | PASS | 0.00 |
| test_components | test_tube_volume_and_wall | PASS | 0.00 |
| test_components | test_tube_reverse_flow_antisymmetric | PASS | 0.00 |
| test_components | test_constriction_diameter_vs_area_reduction | PASS | 0.00 |
| test_components | test_constriction_blocked_and_open | PASS | 0.00 |
| test_components | test_constriction_increases_loss_monotonically | PASS | 0.00 |
| test_components | test_elliptical_compression_perimeter_conserved | PASS | 0.00 |
| test_components | test_linear_taper_matches_analytic | PASS | 0.00 |
| test_components | test_kink_model_calibratable | PASS | 0.00 |
| test_components | test_throttle_characteristics[linear] | PASS | 0.00 |
| test_components | test_throttle_characteristics[equal_percentage] | PASS | 0.00 |
| test_components | test_throttle_characteristics[quick_opening] | PASS | 0.00 |
| test_components | test_throttle_characteristics[table] | PASS | 0.00 |
| test_components | test_throttle_models_monotonic_in_opening[resistance] | PASS | 0.00 |
| test_components | test_throttle_models_monotonic_in_opening[orifice_diameter] | PASS | 0.00 |
| test_components | test_throttle_models_monotonic_in_opening[orifice_area] | PASS | 0.00 |
| test_components | test_throttle_models_monotonic_in_opening[k_value] | PASS | 0.00 |
| test_components | test_throttle_models_monotonic_in_opening[kv] | PASS | 0.00 |
| test_components | test_throttle_cv_conversion | PASS | 0.00 |
| test_components | test_throttle_dp_curve_reproduces_measurements | PASS | 0.00 |
| test_components | test_throttle_calibration_factor | PASS | 0.00 |
| test_components | test_scaffold_quantities | PASS | 0.00 |
| test_components | test_reactor_states | PASS | 0.00 |
| test_components | test_reactor_scaffold_dp_reported | PASS | 0.00 |
| test_components | test_splitter_modes | PASS | 0.00 |
| test_hydraulics | test_unit_roundtrip | PASS | 0.00 |
| test_hydraulics | test_laminar_darcy_equals_hagen_poiseuille | PASS | 0.00 |
| test_hydraulics | test_friction_factor_continuity_at_regime_limits | PASS | 0.00 |
| test_hydraulics | test_friction_models_agree | PASS | 0.00 |
| test_hydraulics | test_regime | PASS | 0.00 |
| test_hydraulics | test_borda_carnot_and_contraction | PASS | 0.00 |
| test_hydraulics | test_series_parallel_helpers | PASS | 0.00 |
| test_hydraulics | test_forchheimer_reduces_to_darcy | PASS | 0.00 |
| test_hydraulics | test_kv_definition | PASS | 0.00 |
| test_hydraulics | test_orifice | PASS | 0.00 |
| test_hydraulics | test_water_properties_monotonic | PASS | 0.00 |
| test_hydraulics | test_fluid_presets[water] | PASS | 0.00 |
| test_hydraulics | test_fluid_presets[saline] | PASS | 0.00 |
| test_hydraulics | test_fluid_presets[culture_medium] | PASS | 0.00 |
| test_hydraulics | test_fluid_presets[custom] | PASS | 0.00 |
| test_hydraulics | test_fluid_overrides_and_warnings | PASS | 0.00 |
| test_network | test_default_system_converges_and_mass_balance | PASS | 0.01 |
| test_network | test_symmetric_distribution | PASS | 0.01 |
| test_network | test_asymmetric_distribution_follows_resistance | PASS | 0.01 |
| test_network | test_increasing_path_resistance_redistributes_flow | PASS | 0.03 |
| test_network | test_pressure_drop_non_negative_in_flow_direction | PASS | 0.02 |
| test_network | test_blocked_reactor_zero_flow | PASS | 0.01 |
| test_network | test_closed_throttle_zero_flow | PASS | 0.01 |
| test_network | test_isolated_section_reported | PASS | 0.01 |
| test_network | test_bypass_disabled_vs_enabled | PASS | 0.02 |
| test_network | test_bypass_tee_variant | PASS | 0.01 |
| test_network | test_bypass_opening_monotonic | PASS | 0.04 |
| test_network | test_throttle_half_open_is_not_half_flow | PASS | 0.02 |
| test_network | test_pump_modes[A_constant_flow] | PASS | 0.02 |
| test_network | test_pump_modes[B_constant_pressure] | PASS | 0.02 |
| test_network | test_pump_modes[C_pump_curve] | PASS | 0.04 |
| test_network | test_pump_modes[D_displacement] | PASS | 0.01 |
| test_network | test_mode_b_reproduces_mode_a | PASS | 0.03 |
| test_network | test_mode_c_operating_point_on_curve | PASS | 0.05 |
| test_network | test_mode_d_theoretical_flow_and_slip | PASS | 0.04 |
| test_network | test_impossible_configuration_detected | PASS | 0.03 |
| test_network | test_excess_pressure_warning | PASS | 0.09 |
| test_network | test_turbulent_regime_converges | PASS | 0.03 |
| test_network | test_variable_reactor_count | PASS | 0.05 |
| test_network | test_reverse_flow_possible_with_two_pumps | PASS | 0.00 |
| test_network | test_network_without_reference_raises | PASS | 0.00 |
| test_network | test_network_validation_errors | PASS | 0.00 |
| test_network | test_single_line_layout | PASS | 0.00 |
| test_network | test_system_volume_positive | PASS | 0.01 |
| test_network | test_hydrostatic_cancels_in_closed_loop | PASS | 0.02 |
| test_network | test_warm_start_same_result | PASS | 0.02 |
| test_reference_cases | test_reference_case[V01] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V02] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V03] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V04] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V05] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V06] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V07] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V08] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V09] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V10] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V11] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V12] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V13] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V14] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V15] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V16] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V17] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V18] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V19] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V20] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V21] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V22] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V23] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V24] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V25] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V26] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V27] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V28] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V29] | PASS | 0.00 |
| test_reference_cases | test_reference_case[V30] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[01_single_tube] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[02_tube_diameters] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[03_tube_lengths] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[04_partial_constriction] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[05_blocked_tube] | PASS | 0.00 |
| test_scenarios | test_scenario_runs[06_four_identical] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[07_different_lengths] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[08_different_diameters] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[09_different_permeability] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[10_individual_throttles] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[11_full_system_bypass] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[12_blocked_reactor] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[13_increasing_scaffold_resistance] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[14_optimize_throttles] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[15_with_without_bypass] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[16_manufacturing_tolerances] | PASS | 0.01 |
| test_scenarios | test_scenario_runs[17_splitter_variants] | PASS | 0.01 |
| test_scenarios | test_scenario_6_symmetric | PASS | 0.01 |
| test_scenarios | test_scenario_5_blocked_zero_flow | PASS | 0.00 |
| test_studies | test_wildcard_expansion | PASS | 0.00 |
| test_studies | test_sweep_1d_diameter_monotonic | PASS | 0.01 |
| test_studies | test_local_sensitivity_laminar_exponents | PASS | 0.01 |
| test_studies | test_grid_and_lhs | PASS | 0.15 |
| test_studies | test_monte_carlo_reproducible | PASS | 0.29 |
| test_studies | test_temperature_study_viscosity | PASS | 0.04 |
| test_studies | test_optimization_homogeneous | PASS | 14.18 |
| test_studies | test_optimization_individual_targets_feasible | PASS | 3.55 |
| test_studies | test_optimization_infeasible_explained | PASS | 4.32 |
| test_studies | test_optimization_min_pressure_opens_throttles | PASS | 6.42 |
| test_ui_smoke | test_page_renders[Dashboard] | PASS | 0.55 |
| test_ui_smoke | test_page_renders[System Diagram] | PASS | 0.33 |
| test_ui_smoke | test_page_renders[Fluid Properties] | PASS | 0.29 |
| test_ui_smoke | test_page_renders[Pump Configuration] | PASS | 0.46 |
| test_ui_smoke | test_page_renders[Tubing Configuration] | PASS | 0.33 |
| test_ui_smoke | test_page_renders[Splitter Configuration] | PASS | 0.28 |
| test_ui_smoke | test_page_renders[Bioreactor Configuration] | PASS | 0.36 |
| test_ui_smoke | test_page_renders[Throttle Configuration] | PASS | 0.41 |
| test_ui_smoke | test_page_renders[Bypass Configuration] | PASS | 0.35 |
| test_ui_smoke | test_page_renders[Simulation Results] | PASS | 0.69 |
| test_ui_smoke | test_page_renders[Parameter Studies] | PASS | 0.25 |
| test_ui_smoke | test_page_renders[Optimization] | PASS | 0.31 |
| test_ui_smoke | test_page_renders[Experimental Validation] | PASS | 0.28 |
| test_ui_smoke | test_page_renders[Scenarios & Projects] | PASS | 0.29 |
| test_ui_smoke | test_page_renders[Scientific Documentation] | PASS | 0.25 |
| test_ui_smoke | test_page_renders[Export] | PASS | 0.52 |
| test_ui_smoke | test_german_toggle | PASS | 0.37 |
| test_ui_smoke | test_throttle_change_recomputes | PASS | 0.55 |
| test_validation_project_export | test_comparison_perfect_agreement | PASS | 0.12 |
| test_validation_project_export | test_metrics_formulas | PASS | 0.00 |
| test_validation_project_export | test_calibration_recovers_factor_and_validates | PASS | 0.42 |
| test_validation_project_export | test_csv_excel_import | PASS | 0.05 |
| test_validation_project_export | test_pump_curve_import | PASS | 0.01 |
| test_validation_project_export | test_project_roundtrip[json] | PASS | 0.01 |
| test_validation_project_export | test_project_roundtrip[yaml] | PASS | 0.06 |
| test_validation_project_export | test_duplicate_and_compare | PASS | 0.01 |
| test_validation_project_export | test_save_run_and_exports | PASS | 0.17 |
