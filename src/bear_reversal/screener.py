"""
Bear Market Reversal Screener
Scans watchlist tickers vs their 200-day SMA and flags buy signals.
Run daily or on-demand.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import json
import os

# ── Watchlist ────────────────────────────────────────────────────────────────
WATCHLIST = {
    "Energy": {
        "stocks": ["LEU", "GEV", "BE", "FSLR", "VST", "NEE", "CCJ"],
        "etfs":   ["URA", "NLR", "ICLN", "GRID", "OIH"],
    },
    "Cybersecurity": {
        "stocks": ["PANW", "CRWD", "FTNT", "NET", "CYBR"],
        "etfs":   ["CIBR", "HACK", "BUG", "IHAK", "WCBR"],
    },
    "Defense": {
        "stocks": ["ONDS", "LMT", "RCAT", "RTX", "NOC"],
        "etfs":   ["ITA", "PPA", "XAR", "SHLD", "ARKX"],
    },
    "AI Infrastructure": {
        "stocks": ["NBIS", "CRWV", "ANET", "VRT", "ALAB"],
        "etfs":   ["DTCR", "AIQ", "SRVR", "BAI"],
    },
    "Memory": {
        "stocks": ["MU", "AMAT", "WDC", "LRCX"],
        "etfs":   ["SMH", "SOXX", "XSD", "FTXL", "PSI"],
    },
}

BEAR_THRESHOLD = -0.10   # -10% below SMA triggers buy
SMA_WINDOW = 200


def get_ticker_signal(ticker: str) -> Optional[dict]:
    """Fetch latest data and compute signal for a single ticker."""
    try:
        df = yf.download(ticker, period="300d", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Close"]].dropna()
        df.columns = ["close"]
        if len(df) < SMA_WINDOW:
            return None
        df["sma200"] = df["close"].rolling(SMA_WINDOW).mean()
        df = df.dropna()
        latest = df.iloc[-1]
        pct = (latest["close"] / latest["sma200"]) - 1
        price_52w_high = df["close"].tail(252).max()
        drawdown = (latest["close"] / price_52w_high) - 1
        return {
            "ticker": ticker,
            "price": round(float(latest["close"]), 2),
            "sma200": round(float(latest["sma200"]), 2),
            "pct_vs_sma": round(float(pct), 4),
            "drawdown_52w": round(float(drawdown), 4),
            "signal": pct <= BEAR_THRESHOLD,
            "near_sma": abs(pct) <= 0.02,
            "as_of": df.index[-1].strftime("%Y-%m-%d"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def scan_watchlist(save_json: bool = True) -> pd.DataFrame:
    """Scan all tickers and return signal DataFrame."""
    rows = []
    for sector, items in WATCHLIST.items():
        for category, tickers in items.items():
            for t in tickers:
                sig = get_ticker_signal(t)
                if sig and "error" not in sig:
                    sig["sector"] = sector
                    sig["category"] = category
                    rows.append(sig)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.sort_values("pct_vs_sma")

    if save_json:
        os.makedirs("results", exist_ok=True)
        out = df.to_dict(orient="records")
        with open("results/latest_scan.json", "w") as f:
            json.dump({"scanned_at": datetime.now().isoformat(), "signals": out}, f, indent=2)

    return df


def print_report(df: pd.DataFrame) -> None:
    """Pretty-print the screener report to terminal."""
    if df.empty:
        print("No data available.")
        return

    buy_signals = df[df["signal"] == True]
    near_sma = df[df["near_sma"] == True]

    print("\n" + "═" * 65)
    print("  BEAR MARKET REVERSAL SCREENER")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("═" * 65)

    if not buy_signals.empty:
        print(f"\n🔴  BUY SIGNALS — price ≥10% below 200-SMA ({len(buy_signals)} tickers)\n")
        for _, row in buy_signals.iterrows():
            print(f"  {row['ticker']:<8} ${row['price']:<8.2f}  "
                  f"vs SMA: {row['pct_vs_sma']*100:+.1f}%  "
                  f"52w DD: {row['drawdown_52w']*100:+.1f}%  "
                  f"[{row['sector']}]")
    else:
        print("\n  No active bear signals today.")

    if not near_sma.empty:
        print(f"\n🟡  NEAR SMA — within ±2% of 200-SMA ({len(near_sma)} tickers)\n")
        for _, row in near_sma.iterrows():
            print(f"  {row['ticker']:<8} ${row['price']:<8.2f}  "
                  f"vs SMA: {row['pct_vs_sma']*100:+.1f}%  [{row['sector']}]")

    above = df[df["pct_vs_sma"] > 0.02]
    print(f"\n🟢  ABOVE SMA — hold cash, do not buy ({len(above)} tickers)\n")
    print("═" * 65 + "\n")


if __name__ == "__main__":
    print("Scanning watchlist...")
    df = scan_watchlist(save_json=True)
    print_report(df)
