"""
Bear Market Reversal DCA Backtester
Strategy: Buy aggressively when price drops 10%+ below 200-day SMA. Hold cash otherwise.
Based on: https://samueljuanp.medium.com/demystifying-dollar-cost-averaging-19b706657a0b
"""

import yfinance as yf
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import warnings
warnings.filterwarnings("ignore")


@dataclass
class BacktestConfig:
    ticker: str
    start: str = "2010-01-01"
    end: str = "2024-12-31"
    deploy_per_signal: float = 500.0   # $ deployed each time signal triggers
    sma_window: int = 200
    bear_threshold: float = -0.10      # -10% below SMA = buy signal
    sma_threshold: float = 0.00        # 0% = at SMA (optional 200-SMA strategy)


@dataclass
class BacktestResult:
    ticker: str
    strategy: str
    trades: pd.DataFrame
    equity_curve: pd.Series
    price_series: pd.Series
    sma_series: pd.Series
    effective_buy_price: float
    total_invested: float
    final_value: float
    total_return_pct: float
    num_trades: int
    benchmark_return_pct: float       # monthly DCA comparison
    config: BacktestConfig


def fetch_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df.columns = ["close"]
    df["sma200"] = df["close"].rolling(window=200).mean()
    df["pct_vs_sma"] = (df["close"] / df["sma200"]) - 1
    return df.dropna()


def run_bear_market_reversal(cfg: BacktestConfig) -> BacktestResult:
    df = fetch_data(cfg.ticker, cfg.start, cfg.end)

    trades = []
    shares_held = 0.0
    total_invested = 0.0

    for date, row in df.iterrows():
        if row["pct_vs_sma"] <= cfg.bear_threshold:
            shares_bought = cfg.deploy_per_signal / row["close"]
            shares_held += shares_bought
            total_invested += cfg.deploy_per_signal
            trades.append({
                "date": date,
                "price": row["close"],
                "sma200": row["sma200"],
                "pct_vs_sma": row["pct_vs_sma"],
                "shares_bought": shares_bought,
                "cost": cfg.deploy_per_signal,
                "shares_held": shares_held,
                "total_invested": total_invested,
            })

    trades_df = pd.DataFrame(trades)

    # Build equity curve
    equity = pd.Series(index=df.index, dtype=float)
    running_shares = 0.0
    running_invested = 0.0
    trade_dates = set(trades_df["date"]) if not trades_df.empty else set()

    for date, row in df.iterrows():
        if date in trade_dates:
            t = trades_df[trades_df["date"] == date].iloc[-1]
            running_shares = t["shares_held"]
            running_invested = t["total_invested"]
        equity[date] = running_shares * row["close"]

    final_value = shares_held * df["close"].iloc[-1]
    eff_price = total_invested / shares_held if shares_held > 0 else np.nan

    # Monthly DCA benchmark
    monthly_dates = pd.date_range(cfg.start, cfg.end, freq="MS")
    monthly_dca_shares = 0.0
    monthly_dca_invested = 0.0
    for d in monthly_dates:
        nearest = df.index[df.index.searchsorted(d)]
        if nearest in df.index:
            monthly_dca_shares += cfg.deploy_per_signal / df.loc[nearest, "close"]
            monthly_dca_invested += cfg.deploy_per_signal
    monthly_dca_final = monthly_dca_shares * df["close"].iloc[-1]
    benchmark_return = ((monthly_dca_final - monthly_dca_invested) / monthly_dca_invested * 100
                        if monthly_dca_invested > 0 else 0)

    total_return = ((final_value - total_invested) / total_invested * 100
                    if total_invested > 0 else 0)

    return BacktestResult(
        ticker=cfg.ticker,
        strategy="Bear Market Reversal",
        trades=trades_df,
        equity_curve=equity,
        price_series=df["close"],
        sma_series=df["sma200"],
        effective_buy_price=eff_price,
        total_invested=total_invested,
        final_value=final_value,
        total_return_pct=total_return,
        num_trades=len(trades_df),
        benchmark_return_pct=benchmark_return,
        config=cfg,
    )


def run_sma_accumulation(cfg: BacktestConfig) -> BacktestResult:
    """Buy only when price touches the 200-day SMA (within ±2%)."""
    df = fetch_data(cfg.ticker, cfg.start, cfg.end)

    trades = []
    shares_held = 0.0
    total_invested = 0.0

    for date, row in df.iterrows():
        if abs(row["pct_vs_sma"]) <= 0.02:  # within 2% of SMA
            shares_bought = cfg.deploy_per_signal / row["close"]
            shares_held += shares_bought
            total_invested += cfg.deploy_per_signal
            trades.append({
                "date": date,
                "price": row["close"],
                "sma200": row["sma200"],
                "pct_vs_sma": row["pct_vs_sma"],
                "shares_bought": shares_bought,
                "cost": cfg.deploy_per_signal,
                "shares_held": shares_held,
                "total_invested": total_invested,
            })

    trades_df = pd.DataFrame(trades)
    final_value = shares_held * df["close"].iloc[-1]
    eff_price = total_invested / shares_held if shares_held > 0 else np.nan

    monthly_dates = pd.date_range(cfg.start, cfg.end, freq="MS")
    monthly_dca_shares = 0.0
    monthly_dca_invested = 0.0
    for d in monthly_dates:
        nearest = df.index[df.index.searchsorted(d)]
        if nearest in df.index:
            monthly_dca_shares += cfg.deploy_per_signal / df.loc[nearest, "close"]
            monthly_dca_invested += cfg.deploy_per_signal

    monthly_dca_final = monthly_dca_shares * df["close"].iloc[-1]
    benchmark_return = ((monthly_dca_final - monthly_dca_invested) / monthly_dca_invested * 100
                        if monthly_dca_invested > 0 else 0)
    total_return = ((final_value - total_invested) / total_invested * 100
                    if total_invested > 0 else 0)

    equity = pd.Series(index=df.index, dtype=float)
    running_shares = 0.0
    trade_dates = set(trades_df["date"]) if not trades_df.empty else set()
    for date, row in df.iterrows():
        if date in trade_dates:
            t = trades_df[trades_df["date"] == date].iloc[-1]
            running_shares = t["shares_held"]
        equity[date] = running_shares * row["close"]

    return BacktestResult(
        ticker=cfg.ticker,
        strategy="200-SMA Accumulation",
        trades=trades_df,
        equity_curve=equity,
        price_series=df["close"],
        sma_series=df["sma200"],
        effective_buy_price=eff_price,
        total_invested=total_invested,
        final_value=final_value,
        total_return_pct=total_return,
        num_trades=len(trades_df),
        benchmark_return_pct=benchmark_return,
        config=cfg,
    )
