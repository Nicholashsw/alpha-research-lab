"""
Black-Scholes pricing, Greeks, and delta-based strike inversion.
All inputs annualised; sigma as decimal (e.g. 0.12 = 12%).
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


def _d1d2(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return d1, d2


def bs_price(S, K, T, r, sigma, option_type="call") -> float:
    d1, d2 = _d1d2(S, K, T, r, sigma)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(S, K, T, r, sigma, option_type="call") -> float:
    d1, _ = _d1d2(S, K, T, r, sigma)
    if option_type == "call":
        return norm.cdf(d1)
    return norm.cdf(d1) - 1


def strike_from_delta(S, target_delta, T, r, sigma, option_type="call") -> float:
    """
    Invert BS to find strike K that gives target_delta.
    target_delta: positive value (e.g. 0.20 for 20-delta).
    """
    def objective(K):
        return abs(bs_delta(S, K, T, r, sigma, option_type)) - target_delta

    lo, hi = S * 0.1, S * 3.0
    try:
        return brentq(objective, lo, hi, xtol=1e-6)
    except ValueError:
        return np.nan


def bs_theta(S, K, T, r, sigma, option_type="call") -> float:
    d1, d2 = _d1d2(S, K, T, r, sigma)
    theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)
    if option_type == "put":
        theta += r * K * np.exp(-r * T)
    return theta / 365  # per calendar day


def bs_vega(S, K, T, r, sigma) -> float:
    d1, _ = _d1d2(S, K, T, r, sigma)
    return S * norm.pdf(d1) * np.sqrt(T) / 100  # per 1 vol point
