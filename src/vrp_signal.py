"""
VRP Signal Engine.

Regime filter  : 200-day MA on spot price.
VRP filter     : Enter only when IV > RV (vol risk premium positive).
Signal output  : +1 = bull (sell put spread), -1 = bear (sell call spread).
"""

import numpy as np
import pandas as pd


def compute_realized_vol(spot: pd.Series, window: int = 21) -> pd.Series:
    """Annualised close-to-close RV over rolling window."""
    log_ret = np.log(spot / spot.shift(1))
    return log_ret.rolling(window).std() * np.sqrt(252)


def compute_regime(spot: pd.Series, ma_window: int = 200) -> pd.Series:
    """
    +1 if spot > 200MA (bullish), -1 if below (bearish).
    """
    ma = spot.rolling(ma_window).mean()
    return np.sign(spot - ma).replace(0, np.nan).ffill()


def compute_vrp(iv: pd.Series, rv: pd.Series) -> pd.Series:
    """
    VRP = IV - RV. Positive means IV > RV → option selling is attractive.
    """
    return iv - rv


def generate_signals(
    spot: pd.Series,
    iv: pd.Series,
    ma_window: int = 200,
    rv_window: int = 21,
    vrp_threshold: float = 0.0,
) -> pd.DataFrame:
    """
    Returns DataFrame with: spot, iv, rv, vrp, regime, signal.

    signal = regime direction, BUT only when VRP > threshold.
    No signal (0) if VRP not positive or insufficient history.
    """
    rv = compute_realized_vol(spot, rv_window)
    regime = compute_regime(spot, ma_window)
    vrp = compute_vrp(iv, rv)

    signal = pd.Series(0, index=spot.index, name="signal")
    vrp_positive = vrp > vrp_threshold
    signal[vrp_positive & (regime == 1)]  = 1   # bull → sell put spread
    signal[vrp_positive & (regime == -1)] = -1  # bear → sell call spread
    signal[vrp_positive & (regime == 1)]  = 1
    signal[vrp_positive & (regime == -1)] = -1

    df = pd.DataFrame({
        "spot":   spot,
        "iv":     iv,
        "rv":     rv,
        "vrp":    vrp,
        "regime": regime,
        "signal": signal,
    })
    return df.dropna(subset=["rv", "regime"])
