"""
Pairs Trading Backtest Engine
==============================
Engle-Granger cointegration + OLS hedge ratio + rolling z-score
Walk-forward validated, cost-adjusted P&L

Usage:
    python backtest_engine.py

Expects CSVs in ../data/ named: KO.csv, PEP.csv, XOM.csv, CVX.csv,
GS.csv, MS.csv, AMZN.csv, TGT.csv

Bloomberg HP export format: two columns — Date, PX_LAST
"""

import pandas as pd
import numpy as np
import json
import os
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
import warnings
warnings.filterwarnings("ignore")

# ── Configuration ─────────────────────────────────────────────────────────────

PAIRS = [
    ("KO",   "PEP",  "Consumer Staples"),
    ("XOM",  "CVX",  "Energy Majors"),
    ("GS",   "MS",   "Investment Banks"),
    ("AMZN", "TGT",  "Retail / Consumer"),
]

CONFIG = {
    "start_date":       "2010-01-01",
    "end_date":         "2024-12-31",
    "train_years":      5,          # walk-forward training window (years)
    "test_years":       1,          # walk-forward test window (years)
    "z_window":         60,         # rolling mean/std lookback (trading days)
    "entry_z":          2.0,        # default entry threshold
    "exit_z":           0.5,        # default exit threshold
    "cost_bps":         10,         # round-trip transaction cost (basis points)
    "initial_capital":  10_000,     # per pair
    "max_holding_days": 30,         # force-exit after this many days
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ── Data Loading ───────────────────────────────────────────────────────────────

def load_prices(ticker: str) -> pd.Series:
    """
    Load Bloomberg HP CSV export.
    Handles Bloomberg's typical format with optional metadata header rows.
    Expects columns: Date, PX_LAST
    """
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Missing data file: {path}\n"
            f"Export from Bloomberg HP: ticker '{ticker} US Equity', "
            f"field PX_LAST, daily, 2010-01-01 to today."
        )

    # Try to read, skip metadata rows Bloomberg sometimes prepends
    for skip in [0, 1, 2, 3, 4, 5]:
        try:
            df = pd.read_csv(path, skiprows=skip, parse_dates=[0], index_col=0)
            df.index.name = "Date"
            # Find PX_LAST column (Bloomberg may name it differently)
            col = next(
                (c for c in df.columns if "PX_LAST" in c.upper() or "LAST" in c.upper() or "CLOSE" in c.upper()),
                df.columns[0]
            )
            series = df[col].dropna().astype(float)
            series.name = ticker
            return series
        except Exception:
            continue

    raise ValueError(f"Could not parse {path}. Check Bloomberg export format.")


def load_all_prices() -> pd.DataFrame:
    """Load all tickers and align to common dates."""
    tickers = list({t for pair in PAIRS for t in pair[:2]})
    series  = {t: load_prices(t) for t in tickers}
    df = pd.DataFrame(series).dropna()
    df = df.loc[CONFIG["start_date"]:CONFIG["end_date"]]
    print(f"Loaded {len(df)} trading days — {df.index[0].date()} to {df.index[-1].date()}")
    return df


# ── Statistical Tests ──────────────────────────────────────────────────────────

def engle_granger_coint(pA: pd.Series, pB: pd.Series) -> dict:
    """Full cointegration diagnostics for a pair."""
    _, pvalue, _ = coint(pA, pB)

    # OLS hedge ratio: pA = α + β*pB + ε
    X    = add_constant(pB.values)
    model = OLS(pA.values, X).fit()
    alpha, beta = model.params
    spread = pA - beta * pB - alpha

    # ADF on spread
    adf_stat, adf_p, _, _, adf_crit, _ = adfuller(spread.dropna(), autolag="AIC")

    # Half-life via AR(1) on spread changes
    lag_spread  = spread.shift(1).dropna()
    delta_spread = spread.diff().dropna()
    aligned      = pd.concat([delta_spread, lag_spread], axis=1).dropna()
    ar_model     = OLS(aligned.iloc[:, 0], add_constant(aligned.iloc[:, 1])).fit()
    kappa        = -ar_model.params[1]
    half_life    = int(np.log(2) / kappa) if kappa > 0 else 999

    return {
        "eg_pvalue":   round(pvalue, 4),
        "cointegrated": pvalue < 0.05,
        "beta":        round(beta, 4),
        "alpha":       round(alpha, 4),
        "spread":      spread,
        "adf_stat":    round(adf_stat, 4),
        "adf_pvalue":  round(adf_p, 4),
        "half_life":   half_life,
        "r_squared":   round(model.rsquared, 4),
    }


def rolling_zscore(spread: pd.Series, window: int) -> pd.Series:
    """
    Rolling z-score — uses only past data (no look-ahead).
    Each z[t] = (spread[t] - mean(spread[t-window:t])) / std(spread[t-window:t])
    """
    mu  = spread.rolling(window=window, min_periods=window // 2).mean()
    sig = spread.rolling(window=window, min_periods=window // 2).std()
    return (spread - mu) / sig


# ── Backtest ───────────────────────────────────────────────────────────────────

def backtest_pair(
    pA: pd.Series,
    pB: pd.Series,
    beta: float,
    alpha: float,
    entry_z: float  = CONFIG["entry_z"],
    exit_z: float   = CONFIG["exit_z"],
    z_window: int   = CONFIG["z_window"],
    cost_bps: float = CONFIG["cost_bps"],
    capital: float  = CONFIG["initial_capital"],
    max_hold: int   = CONFIG["max_holding_days"],
) -> dict:
    """
    Vectorised backtest on a single pair.
    Returns equity curve, trade log, and performance metrics.
    """
    spread   = pA - beta * pB - alpha
    zscore   = rolling_zscore(spread, z_window)
    cost_pct = cost_bps / 10_000

    equity   = [capital]
    trades   = []
    position = None   # None | {"dir": "long"|"short", "entry_i": int, "entry_z": float}

    idx = zscore.index

    for i in range(1, len(zscore)):
        z   = zscore.iloc[i]
        if pd.isna(z):
            equity.append(equity[-1])
            continue

        # Mark-to-market P&L if in position
        mtm = 0.0
        if position is not None:
            dz = zscore.iloc[i] - zscore.iloc[i - 1]
            mtm = (-dz if position["dir"] == "short" else dz) * capital * 0.01

        # Exit conditions
        if position is not None:
            days_held = i - position["entry_i"]
            exit_cond = (
                (position["dir"] == "short" and z <= exit_z)  or
                (position["dir"] == "long"  and z >= -exit_z) or
                days_held >= max_hold
            )
            if exit_cond:
                gross_pnl = (equity[-1] + mtm) - position["entry_capital"]
                net_pnl   = gross_pnl - cost_pct * capital  # exit leg cost
                trades.append({
                    "entry_date":    idx[position["entry_i"]].strftime("%Y-%m-%d"),
                    "exit_date":     idx[i].strftime("%Y-%m-%d"),
                    "direction":     position["dir"],
                    "entry_z":       round(position["entry_z"], 3),
                    "exit_z":        round(float(z), 3),
                    "days_held":     days_held,
                    "gross_pnl":     round(gross_pnl, 2),
                    "net_pnl":       round(net_pnl, 2),
                    "net_pnl_pct":   round(net_pnl / capital * 100, 3),
                    "forced_exit":   days_held >= max_hold,
                })
                equity.append(equity[-1] + mtm + net_pnl - gross_pnl)
                position = None
                continue

        # Entry conditions (only when flat)
        if position is None:
            if z >= entry_z:    # spread too wide → short spread
                entry_capital = equity[-1]
                position = {"dir": "short", "entry_i": i, "entry_z": float(z), "entry_capital": entry_capital}
                equity.append(equity[-1] - cost_pct * capital)  # entry cost
            elif z <= -entry_z: # spread too narrow → long spread
                entry_capital = equity[-1]
                position = {"dir": "long",  "entry_i": i, "entry_z": float(z), "entry_capital": entry_capital}
                equity.append(equity[-1] - cost_pct * capital)
            else:
                equity.append(equity[-1] + mtm)
        else:
            equity.append(equity[-1] + mtm)

    equity_s   = pd.Series(equity, index=idx)
    returns    = equity_s.pct_change().dropna()
    total_ret  = (equity_s.iloc[-1] / equity_s.iloc[0]) - 1
    n_years    = len(equity_s) / 252
    cagr       = (1 + total_ret) ** (1 / n_years) - 1
    sharpe     = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    max_dd     = ((equity_s / equity_s.cummax()) - 1).min()
    wins       = [t for t in trades if t["net_pnl"] > 0]
    win_rate   = len(wins) / len(trades) if trades else 0
    gross_pnl  = sum(t["gross_pnl"] for t in trades)
    gross_loss = abs(sum(t["gross_pnl"] for t in trades if t["gross_pnl"] < 0)) or 1
    profit_factor = sum(t["gross_pnl"] for t in trades if t["gross_pnl"] > 0) / gross_loss

    return {
        "equity":        equity_s,
        "trades":        trades,
        "n_trades":      len(trades),
        "total_return":  round(total_ret * 100, 2),
        "cagr":          round(cagr * 100, 2),
        "sharpe":        round(sharpe, 3),
        "max_drawdown":  round(max_dd * 100, 2),
        "win_rate":      round(win_rate * 100, 1),
        "profit_factor": round(profit_factor, 3),
        "avg_hold":      round(np.mean([t["days_held"] for t in trades]), 1) if trades else 0,
    }


# ── Walk-Forward Optimisation ──────────────────────────────────────────────────

def walk_forward(pA, pB, beta, alpha, param_grid: dict) -> dict:
    """
    Walk-forward parameter search.
    Splits data into train/test windows, finds best params on train,
    evaluates on held-out test. Returns OOS combined performance.
    """
    results = []
    n = len(pA)
    train_days = CONFIG["train_years"] * 252
    test_days  = CONFIG["test_years"]  * 252

    start = 0
    while start + train_days + test_days <= n:
        train_pA = pA.iloc[start : start + train_days]
        train_pB = pB.iloc[start : start + train_days]
        test_pA  = pA.iloc[start + train_days : start + train_days + test_days]
        test_pB  = pB.iloc[start + train_days : start + train_days + test_days]

        # Find best params on training window
        best_sharpe = -np.inf
        best_params = {}
        for ez in param_grid["entry_z"]:
            for xz in param_grid["exit_z"]:
                for w in param_grid["z_window"]:
                    if xz >= ez:
                        continue
                    r = backtest_pair(train_pA, train_pB, beta, alpha,
                                      entry_z=ez, exit_z=xz, z_window=w)
                    if r["sharpe"] > best_sharpe and r["n_trades"] >= 5:
                        best_sharpe = r["sharpe"]
                        best_params = {"entry_z": ez, "exit_z": xz, "z_window": w}

        # Evaluate best params on test window
        if best_params:
            r_test = backtest_pair(test_pA, test_pB, beta, alpha, **best_params)
            results.append({
                "period_start": pA.index[start + train_days].strftime("%Y-%m-%d"),
                "period_end":   pA.index[min(start + train_days + test_days - 1, n-1)].strftime("%Y-%m-%d"),
                "best_params":  best_params,
                "train_sharpe": round(best_sharpe, 3),
                "oos_sharpe":   r_test["sharpe"],
                "oos_return":   r_test["total_return"],
                "oos_trades":   r_test["n_trades"],
            })

        start += test_days

    return results


# ── Main Runner ────────────────────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("PAIRS TRADING BACKTEST ENGINE")
    print("=" * 60)

    try:
        prices = load_all_prices()
    except FileNotFoundError as e:
        print(f"\n[DATA MISSING] {e}")
        print("\nGenerate synthetic data for testing? (y/n): ", end="")
        if input().strip().lower() == "y":
            prices = generate_synthetic(CONFIG["start_date"], CONFIG["end_date"])
        else:
            return

    param_grid = {
        "entry_z":  [1.5, 1.75, 2.0, 2.25, 2.5],
        "exit_z":   [0.25, 0.5, 0.75],
        "z_window": [40, 60, 90],
    }

    all_results = {}

    for tickA, tickB, label in PAIRS:
        print(f"\n── {tickA}/{tickB} · {label} ──")
        pA = prices[tickA]
        pB = prices[tickB]

        # Cointegration tests
        coint_res = engle_granger_coint(pA, pB)
        print(f"   EG p-value:  {coint_res['eg_pvalue']}  {'✓ cointegrated' if coint_res['cointegrated'] else '✗ weak'}")
        print(f"   Hedge ratio β: {coint_res['beta']}   Half-life: {coint_res['half_life']}d")

        # Default backtest
        bt = backtest_pair(pA, pB, coint_res["beta"], coint_res["alpha"])
        print(f"   CAGR: {bt['cagr']}%  |  Sharpe: {bt['sharpe']}  |  MaxDD: {bt['max_drawdown']}%")
        print(f"   Trades: {bt['n_trades']}  |  Win rate: {bt['win_rate']}%  |  PF: {bt['profit_factor']}")

        # Walk-forward
        print(f"   Running walk-forward optimisation...")
        wf = walk_forward(pA, pB, coint_res["beta"], coint_res["alpha"], param_grid)
        if wf:
            avg_oos = np.mean([w["oos_sharpe"] for w in wf])
            print(f"   Avg OOS Sharpe: {avg_oos:.3f}  ({len(wf)} windows)")

        # Save equity curve
        eq_path = os.path.join(os.path.dirname(__file__), f"equity_{tickA}_{tickB}.csv")
        bt["equity"].to_csv(eq_path, header=["portfolio_value"])

        all_results[f"{tickA}/{tickB}"] = {
            "label":       label,
            "cointegration": {k: v for k, v in coint_res.items() if k != "spread"},
            "backtest":    {k: v for k, v in bt.items()    if k not in ["equity", "trades"]},
            "trades":      bt["trades"][-10:],   # last 10 trades
            "walk_forward": wf,
        }

    # Export JSON summary
    out_path = os.path.join(os.path.dirname(__file__), "results_summary.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n✓ Results saved to {out_path}")
    print("✓ Equity curves saved as equity_TICKER1_TICKER2.csv")
    return all_results


def generate_synthetic(start, end):
    """Synthetic OU data for testing without Bloomberg data."""
    import datetime
    dates = pd.date_range(start, end, freq="B")
    rng   = np.random.default_rng(42)
    tickers = list({t for pair in PAIRS for t in pair[:2]})
    data  = {}
    for i, t in enumerate(tickers):
        base = 100 + i * 25
        ret  = rng.normal(0.0003, 0.012, len(dates))
        data[t] = pd.Series(base * np.exp(np.cumsum(ret)), index=dates, name=t)
    return pd.DataFrame(data).dropna()


if __name__ == "__main__":
    run_all()
