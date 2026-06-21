"""
Johansen / VECM Multi-Asset Cointegration
==========================================
Extends the two-asset Engle-Granger model to an n-asset basket.
Designed for the energy basket: XOM, CVX, SHEL, TTE (USD ADRs).

Usage:
    python johansen_vecm.py

Expects CSVs in ../data/ named: XOM.csv, CVX.csv, SHEL.csv, TTE.csv
(Bloomberg HP export, PX_LAST, daily, USD ADRs on NYSE)

Key concepts:
    - Johansen trace / max-eigenvalue tests select rank r (# cointegrating vectors)
    - VECM models speed of adjustment (alpha) and long-run equilibrium (beta)
    - Each cointegrating vector is an independently tradeable stationary spread
    - Half-life estimated from error correction coefficient
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings("ignore")

from statsmodels.tsa.vector_ar.vecm import VECM, select_coint_rank, select_order

# ── Configuration ─────────────────────────────────────────────────────────────

BASKET = ["XOM", "CVX", "SHEL", "TTE"]
BASKET_LABELS = {
    "XOM":  "ExxonMobil (NYSE)",
    "CVX":  "Chevron (NYSE)",
    "SHEL": "Shell ADR (NYSE)",
    "TTE":  "TotalEnergies ADR (NYSE)",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

CONFIG = {
    "start_date":   "2010-01-01",
    "end_date":     "2024-12-31",
    "z_window":     60,
    "entry_z":      2.0,
    "exit_z":       0.5,
    "cost_bps":     12,     # slightly higher for 4-leg execution
    "capital":      10_000,
    "max_hold":     30,
    "vecm_lags":    5,      # VAR lag order (auto-selected if None)
    "sig_level":    "5%",   # Johansen significance level
}

# ── Data ──────────────────────────────────────────────────────────────────────

def load_prices() -> pd.DataFrame:
    frames = {}
    for t in BASKET:
        path = os.path.join(DATA_DIR, f"{t}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing: {path}\n"
                f"Export from Bloomberg HP: '{t} US Equity', PX_LAST, daily, USD."
            )
        for skip in range(6):
            try:
                df = pd.read_csv(path, skiprows=skip, parse_dates=[0], index_col=0)
                col = next(c for c in df.columns if any(k in c.upper() for k in ["PX_LAST","LAST","CLOSE"]))
                frames[t] = df[col].dropna().astype(float)
                break
            except Exception:
                continue

    prices = pd.DataFrame(frames).dropna()
    prices = prices.loc[CONFIG["start_date"]:CONFIG["end_date"]]
    print(f"Loaded {len(prices)} days: {prices.index[0].date()} – {prices.index[-1].date()}")
    return prices


# ── Johansen Tests ─────────────────────────────────────────────────────────────

def run_johansen(prices: pd.DataFrame) -> dict:
    """
    Johansen cointegration rank selection.
    Returns trace test, max-eigenvalue test, and selected rank r.
    """
    log_prices = np.log(prices)

    # Auto-select VAR lag order
    if CONFIG["vecm_lags"] is None:
        lag_order = select_order(log_prices, maxlags=10, deterministic="ci").aic
    else:
        lag_order = CONFIG["vecm_lags"]

    # Trace test
    rank_trace = select_coint_rank(
        log_prices, det_order=0, k_ar_diff=lag_order,
        method="trace", signif=0.05
    )
    # Max-eigenvalue test
    rank_maxeig = select_coint_rank(
        log_prices, det_order=0, k_ar_diff=lag_order,
        method="maxeig", signif=0.05
    )

    r = rank_trace.rank   # selected cointegrating rank
    print(f"\nJohansen Results · {' / '.join(BASKET)}")
    print(f"  Trace test rank:      r = {rank_trace.rank}")
    print(f"  Max-eigenvalue rank:  r = {rank_maxeig.rank}")
    print(f"  Selected rank:        r = {r}  ({r} cointegrating vector{'s' if r!=1 else ''})")

    return {
        "log_prices":  log_prices,
        "lag_order":   lag_order,
        "rank":        r,
        "rank_trace":  rank_trace.rank,
        "rank_maxeig": rank_maxeig.rank,
    }


# ── VECM Estimation ────────────────────────────────────────────────────────────

def fit_vecm(log_prices: pd.DataFrame, rank: int, lag_order: int) -> dict:
    """
    Fit VECM with selected rank.
    Returns:
        - beta:       cointegrating vectors (n_assets × rank)
        - alpha:      adjustment speeds (n_assets × rank)
        - spreads:    r stationary spread series
        - half_lives: mean-reversion speed per cointegrating vector
    """
    model = VECM(log_prices, k_ar_diff=lag_order, coint_rank=rank, deterministic="ci")
    result = model.fit()

    print(f"\nVECM Estimation:")
    print(f"  Cointegrating vectors β (normalised):")
    beta = result.beta                     # shape: (n_assets, rank)
    for j in range(rank):
        vec = beta[:, j]
        print(f"  CV{j+1}: " + "  ".join(f"{BASKET[i]}={vec[i]:.4f}" for i in range(len(BASKET))))

    alpha = result.alpha                   # adjustment speeds
    print(f"\n  Adjustment speeds α (error correction):")
    for i, t in enumerate(BASKET):
        print(f"  {t}: " + "  ".join(f"CV{j+1}={alpha[i,j]:.4f}" for j in range(rank)))

    # Compute spread series for each cointegrating vector
    X = log_prices.values                  # (T, n)
    spreads = {}
    half_lives = {}

    for j in range(rank):
        bvec   = beta[:, j]
        spread = pd.Series(X @ bvec, index=log_prices.index, name=f"CV{j+1}")
        spreads[f"CV{j+1}"] = spread

        # Half-life from dominant adjustment speed
        kappa = -alpha[:, j].mean()
        hl    = int(np.log(2) / kappa) if kappa > 0 else 999
        half_lives[f"CV{j+1}"] = hl
        print(f"  CV{j+1} half-life: {hl} days")

    return {
        "beta":        beta,
        "alpha":       alpha,
        "spreads":     spreads,
        "half_lives":  half_lives,
        "result":      result,
    }


# ── Z-score + Backtest ─────────────────────────────────────────────────────────

def rolling_zscore(spread: pd.Series, window: int) -> pd.Series:
    mu  = spread.rolling(window, min_periods=window // 2).mean()
    sig = spread.rolling(window, min_periods=window // 2).std()
    return (spread - mu) / sig


def backtest_spread(spread: pd.Series, cv_name: str) -> dict:
    """Backtest a single cointegrating spread series."""
    from backtest_engine import backtest_pair
    # For VECM spreads we use a simplified version (spread is already computed)
    ez = CONFIG["entry_z"]
    xz = CONFIG["exit_z"]
    w  = CONFIG["z_window"]
    cap = CONFIG["capital"]
    cost = CONFIG["cost_bps"] / 10_000
    max_hold = CONFIG["max_hold"]

    zscore  = rolling_zscore(spread, w)
    equity  = [cap]
    trades  = []
    position = None

    for i in range(1, len(zscore)):
        z = zscore.iloc[i]
        if pd.isna(z):
            equity.append(equity[-1])
            continue

        mtm = 0.0
        if position is not None:
            dz  = zscore.iloc[i] - zscore.iloc[i-1]
            mtm = (-dz if position["dir"] == "short" else dz) * cap * 0.01

        if position is not None:
            days = i - position["entry_i"]
            if (position["dir"] == "short" and z <= xz) or \
               (position["dir"] == "long"  and z >= -xz) or days >= max_hold:
                net = equity[-1] + mtm - position["entry_cap"] - cost * cap
                trades.append({"days": days, "net_pnl": round(net, 2), "dir": position["dir"]})
                equity.append(equity[-1] + mtm - cost * cap)
                position = None
                continue

        if position is None:
            if z >= ez:
                position = {"dir": "short", "entry_i": i, "entry_cap": equity[-1]}
                equity.append(equity[-1] - cost * cap)
            elif z <= -ez:
                position = {"dir": "long",  "entry_i": i, "entry_cap": equity[-1]}
                equity.append(equity[-1] - cost * cap)
            else:
                equity.append(equity[-1] + mtm)
        else:
            equity.append(equity[-1] + mtm)

    eq = pd.Series(equity, index=spread.index)
    ret = eq.pct_change().dropna()
    tr  = (eq.iloc[-1] / eq.iloc[0]) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
    dd = ((eq / eq.cummax()) - 1).min()

    print(f"\n  {cv_name} backtest:")
    print(f"    Return: {tr*100:.1f}%  |  Sharpe: {sharpe:.3f}  |  MaxDD: {dd*100:.1f}%  |  Trades: {len(trades)}")
    return {"equity": eq, "sharpe": round(sharpe,3), "total_return": round(tr*100,2), "trades": len(trades)}


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("JOHANSEN / VECM MULTI-ASSET COINTEGRATION")
    print(f"Basket: {' · '.join(BASKET)}")
    print("=" * 60)

    try:
        prices = load_prices()
    except FileNotFoundError as e:
        print(f"\n[DATA MISSING] {e}")
        print("Add SHEL.csv and TTE.csv exports from Bloomberg to run this module.")
        return

    joh = run_johansen(prices)

    if joh["rank"] == 0:
        print("\n⚠ No cointegrating vectors found at 5% level.")
        print("  The basket may not be cointegrated in this sample period.")
        print("  Options: (1) extend sample, (2) strip oil price factor first, (3) revisit pair selection.")
        return

    vecm = fit_vecm(joh["log_prices"], joh["rank"], joh["lag_order"])

    print("\nBacktest — each cointegrating vector:")
    for cv_name, spread in vecm["spreads"].items():
        backtest_spread(spread, cv_name)

    # Save spread series
    spreads_df = pd.DataFrame(vecm["spreads"])
    out = os.path.join(os.path.dirname(__file__), "vecm_spreads.csv")
    spreads_df.to_csv(out)
    print(f"\n✓ Spread series saved: {out}")


if __name__ == "__main__":
    run()
