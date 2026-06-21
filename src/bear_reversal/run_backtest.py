"""
run_backtest.py  —  Run Bear Market Reversal backtests across entire watchlist.
Exports results/backtest_results.json for the interactive dashboard.
"""

import json
import os
import sys
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from backtester import BacktestConfig, run_bear_market_reversal, run_sma_accumulation
from screener import WATCHLIST

START = "2015-01-01"
END   = "2024-12-31"
DEPLOY_PER_SIGNAL = 500.0

# Flatten watchlist — ETFs only for reliable backtesting (index-like recovery)
BACKTEST_TICKERS = {
    "Energy":          ["URA", "ICLN", "GRID"],
    "Cybersecurity":   ["CIBR", "HACK", "BUG"],
    "Defense":         ["ITA", "PPA", "XAR"],
    "AI Infra":        ["AIQ", "SRVR"],
    "Memory":          ["SMH", "SOXX"],
    "Benchmark":       ["SPY", "QQQ"],
}


def serialise_result(r) -> dict:
    trades_list = []
    if not r.trades.empty:
        for _, row in r.trades.iterrows():
            trades_list.append({
                "date": str(row["date"])[:10],
                "price": round(float(row["price"]), 2),
                "sma200": round(float(row["sma200"]), 2),
                "pct_vs_sma": round(float(row["pct_vs_sma"]) * 100, 2),
                "cost": float(row["cost"]),
                "shares_bought": round(float(row["shares_bought"]), 4),
                "total_invested": round(float(row["total_invested"]), 2),
            })

    # Downsample price + equity to monthly for chart performance
    monthly_idx = r.price_series.resample("ME").last()
    price_chart = [{"date": str(d)[:10], "price": round(float(v), 2)}
                   for d, v in monthly_idx.items() if not np.isnan(v)]

    sma_chart = [{"date": str(d)[:10], "sma200": round(float(v), 2)}
                 for d, v in r.sma_series.resample("ME").last().items() if not np.isnan(v)]

    eq_chart = [{"date": str(d)[:10], "equity": round(float(v), 2)}
                for d, v in r.equity_curve.resample("ME").last().items() if not np.isnan(v)]

    return {
        "ticker": r.ticker,
        "strategy": r.strategy,
        "total_invested": round(r.total_invested, 2),
        "final_value": round(r.final_value, 2),
        "profit": round(r.final_value - r.total_invested, 2),
        "total_return_pct": round(r.total_return_pct, 2),
        "benchmark_dca_return_pct": round(r.benchmark_return_pct, 2),
        "effective_buy_price": round(r.effective_buy_price, 2) if not np.isnan(r.effective_buy_price) else None,
        "num_trades": r.num_trades,
        "start": r.config.start,
        "end": r.config.end,
        "trades": trades_list,
        "price_chart": price_chart,
        "sma_chart": sma_chart,
        "equity_chart": eq_chart,
    }


def main():
    os.makedirs("results", exist_ok=True)
    output = {"generated_at": datetime.now().isoformat(), "results": {}}

    for sector, tickers in BACKTEST_TICKERS.items():
        output["results"][sector] = []
        for ticker in tickers:
            print(f"  Backtesting {ticker} ({sector})...")
            try:
                cfg = BacktestConfig(
                    ticker=ticker,
                    start=START,
                    end=END,
                    deploy_per_signal=DEPLOY_PER_SIGNAL,
                )
                bmr = run_bear_market_reversal(cfg)
                sma = run_sma_accumulation(cfg)

                output["results"][sector].append({
                    "ticker": ticker,
                    "bear_market_reversal": serialise_result(bmr),
                    "sma_accumulation": serialise_result(sma),
                })
                print(f"    BMR return: {bmr.total_return_pct:.1f}%  "
                      f"({bmr.num_trades} trades)  |  "
                      f"Monthly DCA: {bmr.benchmark_return_pct:.1f}%")
            except Exception as e:
                print(f"    ERROR on {ticker}: {e}")
                output["results"][sector].append({"ticker": ticker, "error": str(e)})

    with open("results/backtest_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved → results/backtest_results.json")


if __name__ == "__main__":
    main()
