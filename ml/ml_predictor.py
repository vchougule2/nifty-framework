"""
ml/ml_predictor.py - ML Predictor (Blocks ML4-ML6)  [HARD-DISABLED]
===================================================================
WHAT:   Loads a trained model, produces an ML probability for each setup, and
        formats it for the pipeline / S19 (ML Signal Output).
WHY:    Adds a data-driven edge ON TOP of the rule engine - but only once we have
        120+ labelled days. Until then every entry point is a guarded no-op.
IMPACT: All three blocks check config.ML_ENABLED first. With ML off they return a
        clear DISABLED payload so the pipeline behaves identically to today.

Block map: ML4 load_model | ML5 predict | ML6 format_output
GUARD: nothing here trains or predicts unless config.ML_ENABLED is True.
"""

from __future__ import annotations

import os

try:
    from .. import config
    from . import ml_optimizer
except ImportError:
    import config
    from ml import ml_optimizer


MODEL_PATH = lambda: os.path.join(config.ML_DIR, "model.joblib")  # noqa: E731

_DISABLED = {"enabled": False, "status": "ML_DISABLED",
             "note": "Set config.ML_ENABLED=True after 120+ labelled days (see ml_optimizer.readiness())."}


# =============================================================================
# BLOCK ML4 - MODEL LOADER
# =============================================================================
def load_model():
    if not config.ML_ENABLED:
        return None
    rdy = ml_optimizer.readiness()
    if not rdy["ready"]:
        return None
    try:
        import joblib
        if os.path.exists(MODEL_PATH()):
            return joblib.load(MODEL_PATH())
    except Exception:
        return None
    return None


# =============================================================================
# BLOCK ML5 - PREDICT
# =============================================================================
def predict(decisions: list[dict]) -> dict:
    if not config.ML_ENABLED:
        return dict(_DISABLED)
    model = load_model()
    if model is None:
        return {"enabled": True, "status": "NO_MODEL",
                "note": "ML enabled but no trained model / insufficient labelled data."}
    try:
        feats = ml_optimizer.engineer_features()
        if feats.empty:
            return {"enabled": True, "status": "NO_FEATURES"}
        feat_cols = [c for c in feats.columns if c.startswith("f_")] + ["tier2_sum", "tier3_sum"]
        X = feats[feat_cols].fillna(0).tail(len(decisions))
        proba = model.predict_proba(X)[:, 1] if hasattr(model, "predict_proba") else model.predict(X)
        return {"enabled": True, "status": "OK",
                "predictions": {d.get("symbol"): float(p) for d, p in zip(decisions, proba)}}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "status": "ERROR", "error": str(exc)}


# =============================================================================
# BLOCK ML6 - OUTPUT FORMATTER (feeds S19 ML Signal Output)
# =============================================================================
def format_output(prediction: dict) -> str:
    if not prediction.get("enabled"):
        return "[S19/ML] disabled - rule engine only."
    if prediction.get("status") != "OK":
        return f"[S19/ML] {prediction.get('status')}: {prediction.get('note', prediction.get('error',''))}"
    lines = ["[S19/ML] probability of positive 5d move:"]
    for sym, p in sorted(prediction.get("predictions", {}).items(),
                         key=lambda kv: kv[1], reverse=True)[:10]:
        lines.append(f"   {sym}: {p*100:.1f}%")
    return "\n".join(lines)
