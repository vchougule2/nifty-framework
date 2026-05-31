"""
nifty_framework.ml - Machine Learning sub-package
=================================================
WHAT:   Package init for the ml/ folder. Enables `from nifty_framework.ml import ...`.
WHY:    Keeps the ML layer cleanly separated from the rule-based core.
IMPACT: ml_optimizer (ML1-ML3) ALWAYS collects training data; ml_predictor
        (ML4-ML6) stays hard-disabled until config.ML_ENABLED becomes True
        (needs 120+ days of collected data - see blueprint Part 8 / config B18).
"""

__all__ = ["ml_optimizer", "ml_predictor"]
