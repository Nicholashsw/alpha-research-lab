"""
Performance metrics for VRP strategy tearsheet.
"""

import numpy as np
import pandas as pd
from typing import List
from engine.backtester import Trade


def compute_metrics(equity: pd.Series, trades: List[Trade], rf: float = 0.04) -> dict:
    ret = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    excess = ret - rf / 252
    sharpe = excess.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan
    sortino_denom = ret[ret < 0].std()
    sortino = excess.mean() / sortino_denom * np.sqrt(252) if sortino_denom > 0 else np.nan
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan

    closed = [t for t in trades if t.exit_pnl is not None]
    wins   = [t for t in closed if t.exit_pnl > 0]
    win_rate = len(wins) / len(closed) if closed else np.nan
    avg_win  = np.mean([t.exit_pnl for t in wins]) if wins else 0
    losers   = [t for t in closed if t.exit_pnl <= 0]
    avg_loss = np.mean([t.exit_pnl for t in losers]) if losers else 0
    profit_factor = (avg_win * len(wins)) / abs(avg_loss * len(losers)) if losers and avg_loss != 0 else np.nan

    exit_counts = {}
    for t in closed:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "total_return":   total_return,
        "cagr":           cagr,
        "sharpe":         sharpe,
        "sortino":        sortino,
        "calmar":         calmar,
        "max_drawdown":   max_dd,
        "win_rate":       win_rate,
        "profit_factor":  profit_factor,
        "n_trades":       len(closed),
        "avg_win":        avg_win,
        "avg_loss":       avg_loss,
        "exit_breakdown": exit_counts,
        "drawdown_series": drawdown,
    }


def print_tearsheet(asset: str, metrics: dict):
    print(f"\n{'='*50}")
    print(f"  VRP Strategy — {asset}")
    print(f"{'='*50}")
    print(f"  Total Return   : {metrics['total_return']:.2%}")
    print(f"  CAGR           : {metrics['cagr']:.2%}")
    print(f"  Sharpe Ratio   : {metrics['sharpe']:.2f}")
    print(f"  Sortino Ratio  : {metrics['sortino']:.2f}")
    print(f"  Calmar Ratio   : {metrics['calmar']:.2f}")
    print(f"  Max Drawdown   : {metrics['max_drawdown']:.2%}")
    print(f"  Win Rate       : {metrics['win_rate']:.2%}")
    print(f"  Profit Factor  : {metrics['profit_factor']:.2f}")
    print(f"  Total Trades   : {metrics['n_trades']}")
    print(f"  Exit Breakdown : {metrics['exit_breakdown']}")
    print(f"{'='*50}\n")
