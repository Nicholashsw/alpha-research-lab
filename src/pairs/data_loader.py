"""
Bloomberg Data Loader
=====================
Handles Bloomberg HP CSV export format quirks and normalises
all tickers to a clean DataFrame.

Bloomberg HP export format (typical):
    Row 0-3:  Metadata (ticker name, currency, source, etc.)
    Row 4+:   Date, PX_LAST

This script:
1. Reads all CSVs from the data/ folder
2. Strips Bloomberg metadata rows automatically
3. Aligns all series to common trading dates
4. Outputs a single clean master CSV: data/prices_master.csv

Usage:
    python data_loader.py

Then point backtest_engine.py at prices_master.csv instead of individual files.
"""

import pandas as pd
import numpy as np
import os
import glob

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# Map Bloomberg ticker suffix to clean name
TICKER_MAP = {
    "KO":   "KO US Equity",
    "PEP":  "PEP US Equity",
    "XOM":  "XOM US Equity",
    "CVX":  "CVX US Equity",
    "GS":   "GS US Equity",
    "MS":   "MS US Equity",
    "AMZN": "AMZN US Equity",
    "TGT":  "TGT US Equity",
    "SHEL": "SHEL US Equity",
    "TTE":  "TTE US Equity",
}

def read_bloomberg_csv(path: str, ticker: str) -> pd.Series:
    """
    Robustly reads a Bloomberg HP CSV export.
    Tries skipping 0–6 header rows, detects Date + PX_LAST columns.
    Returns a clean daily price Series.
    """
    for skip in range(7):
        try:
            df = pd.read_csv(path, skiprows=skip)

            # Find date column
            date_col = next(
                (c for c in df.columns if any(k in str(c).upper() for k in ["DATE", "Unnamed: 0", ""])),
                df.columns[0]
            )

            # Find price column
            price_col = next(
                (c for c in df.columns if any(k in str(c).upper() for k in ["PX_LAST", "LAST", "CLOSE", "PRICE"])),
                None
            )
            if price_col is None and len(df.columns) >= 2:
                price_col = df.columns[1]

            if price_col is None:
                continue

            df[date_col]  = pd.to_datetime(df[date_col], errors="coerce")
            df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
            df = df.dropna(subset=[date_col, price_col])

            if len(df) < 100:   # too few rows → probably still in header
                continue

            series = df.set_index(date_col)[price_col]
            series.index.name = "Date"
            series.name = ticker
            series = series.sort_index()

            print(f"  ✓ {ticker:6s}  {len(series):5d} obs  "
                  f"{series.index[0].date()} – {series.index[-1].date()}  "
                  f"(skipped {skip} header rows)")
            return series

        except Exception:
            continue

    raise ValueError(
        f"Could not parse {path}.\n"
        f"Check Bloomberg HP export: should have Date and PX_LAST columns.\n"
        f"Try opening the CSV and removing any rows above the column headers."
    )


def load_master(
    tickers: list = None,
    start: str = "2010-01-01",
    end:   str = "2024-12-31",
    dropna: bool = True,
) -> pd.DataFrame:
    """
    Load all available CSVs from data/ folder and return aligned DataFrame.
    """
    if tickers is None:
        csvs   = glob.glob(os.path.join(DATA_DIR, "*.csv"))
        tickers = [os.path.splitext(os.path.basename(f))[0].upper() for f in csvs
                   if "master" not in f.lower() and "equity" not in f.lower()]

    print(f"\nLoading {len(tickers)} tickers from {DATA_DIR}:")
    series = {}
    missing = []

    for t in tickers:
        path = os.path.join(DATA_DIR, f"{t}.csv")
        if not os.path.exists(path):
            # Try lowercase
            path_lower = os.path.join(DATA_DIR, f"{t.lower()}.csv")
            if os.path.exists(path_lower):
                path = path_lower
            else:
                missing.append(t)
                continue
        series[t] = read_bloomberg_csv(path, t)

    if missing:
        print(f"\n⚠ Missing CSVs: {', '.join(missing)}")
        print(f"  Export from Bloomberg HP and save to {DATA_DIR}/")

    df = pd.DataFrame(series)
    df = df.sort_index()
    df = df.loc[start:end]

    if dropna:
        before = len(df)
        df = df.dropna()
        if before - len(df) > 0:
            print(f"\n  Dropped {before - len(df)} rows with NaN (non-overlapping dates)")

    print(f"\n✓ Master DataFrame: {df.shape[0]} rows × {df.shape[1]} cols")
    print(f"  Date range: {df.index[0].date()} – {df.index[-1].date()}")

    return df


def save_master(df: pd.DataFrame):
    out = os.path.join(DATA_DIR, "prices_master.csv")
    df.to_csv(out)
    print(f"✓ Saved: {out}")
    return out


def check_data_quality(df: pd.DataFrame):
    """Flag suspicious price series (large gaps, outlier returns)."""
    print("\nData Quality Check:")
    returns = df.pct_change().dropna()
    issues = []

    for col in df.columns:
        s = df[col]
        r = returns[col]

        # Missing data
        nan_pct = s.isna().mean() * 100
        if nan_pct > 1:
            issues.append(f"  {col}: {nan_pct:.1f}% missing")

        # Extreme daily moves (>30% in a single day — likely adjustment error)
        big_moves = (r.abs() > 0.30).sum()
        if big_moves > 0:
            dates = r[r.abs() > 0.30].index.strftime("%Y-%m-%d").tolist()
            issues.append(f"  {col}: {big_moves} daily move(s) >30% — check adj. {dates}")

        # Zero prices
        zeros = (s == 0).sum()
        if zeros > 0:
            issues.append(f"  {col}: {zeros} zero price(s)")

    if issues:
        print("  ⚠ Issues found:")
        for i in issues:
            print(i)
    else:
        print("  ✓ No data quality issues detected")


if __name__ == "__main__":
    TICKERS = ["KO", "PEP", "XOM", "CVX", "GS", "MS", "AMZN", "TGT"]

    df = load_master(tickers=TICKERS, start="2010-01-01", end="2024-12-31")
    check_data_quality(df)
    save_master(df)

    print("\nNext step: run backtest_engine.py")
