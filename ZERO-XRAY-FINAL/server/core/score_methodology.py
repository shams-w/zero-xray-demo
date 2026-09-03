"""Shared, additive machine-readable marker for every confidence /
likelihood / impact / risk score produced by Predict, Future
Simulation, and Challenge (Steps 1-3 of the ZERO X-RAY -> Government
Future Engine evolution).

Added per the Step 3 audit finding: field names like "confidence",
"likelihood", and "risk_score" read as calibrated statistical
probabilities. The values behind them are deterministic evidence-
derived ratios (e.g. Predict's occurrence-count confidence, Simulate's
affected-step ratios) or named engineering default constants (e.g.
DEFAULT_MANUAL_LIKELIHOOD, SPOF_RATIO_THRESHOLD) -- never a
statistically fitted or calibrated model. This marker makes that
distinction visible in the API response itself, not only in code
comments or docstrings, WITHOUT changing any existing field name,
formula, or numeric value anywhere -- it is purely an additive new
key on each capability's top-level result dict.
"""

SCORE_METHODOLOGY_MARKER = {
    "kind": "ZERO_XRAY_ENGINEERING_HEURISTIC",
    "statistically_validated": False,
    "note": (
        "confidence/likelihood/impact/risk values in this result are "
        "deterministic evidence-derived ratios or named engineering "
        "default constants, not calibrated statistical probabilities."
    ),
}
