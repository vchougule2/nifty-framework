"""
nifty_framework - Institutional Trading Framework v2.0
=====================================================
WHAT:   Root package init. Makes the project importable as a Python package.
WHY:    Lets every module use clean intra-package imports and exposes version.
IMPACT: Lightweight on purpose - NO heavy imports here (keeps CLI start-up fast).

Module map (see PART 7 of the blueprint):
    config                -> B1-B22  all thresholds / constants
    smart_data_fetcher    -> A1-A12  raw NSE + intermarket downloads
    data_fetcher          -> C1-C10  load CSV -> clean DataFrames
    rule_engine_stock     -> D1-D12  S1-S11 scoring + composite + universe
    rule_engine_options   -> J1-J13  S12-S15 scoring
    rule_engine_macro     -> K1-K9   S16-S18 + precedence engine
    chart_generator       -> F1-F7   daily dashboard PNGs
    chart_plotter         -> E1-E7   deep-dive inspection charts
    alerts                -> G1-G4   Telegram / Sheets / shadow logger
    main_pipeline         -> H1-H9   orchestrator
    ml.ml_optimizer       -> ML1-ML3 data collector (always ON)
    ml.ml_predictor       -> ML4-ML6 predictor (OFF until ML_ENABLED)
"""

__version__ = "2.0.0"
__author__ = "Vikram Chougule"

__all__ = ["__version__", "__author__"]
