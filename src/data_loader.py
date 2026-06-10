"""
Bloomberg Excel data loader.
Handles BGN Curncy / Index format with 6-row metadata header.
"""

import pandas as pd
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"

# Spot price files: 6-row skip, 2 columns
SPOT_FILES = {
    "USDCHF": "USDCHF_Curncy.xlsx",
    "XAUUSD": "XAUUSD_Curncy.xlsx",
    "GBPUSD": "GBPUSD_Curncy.xlsx",
    "USDJPY": "USDJPY_Curncy.xlsx",
}

# Implied vol files (annualised %, BGN): 6-row skip, 2 columns
VOL_FILES = {
    "USDCHF_1M": "USDCHFV1M.xlsx",
    "USDCHF_3M": "USDCHFV3M.xlsx",
    "XAUUSD_1M": "XAUUSDV1M.xlsx",
    "XAUUSD_3M": "XAUUSDV3M.xlsx",
    "GBPUSD_1M": "GBPUSDV1M.xlsx",
    "GBPUSD_3M": "GBPUSDV3M.xlsx",
    "USDJPY_1M": "USDJPYV1M.xlsx",
    "USDJPY_3M": "USDJPYV3M.xlsx",
    "EURUSD_3M": "EURUSDV3M.xlsx",
}

# Macro / index files: 6-row skip, 3 columns (extra unnamed col)
INDEX_FILES = {
    "VIX":     ("VIX_Index.xlsx",      2),
    "SPX":     ("SPX_INDEX.xlsx",      2),
    "US2Y":    ("USGG2YR_Index.xlsx",  3),
    "US10Y":   ("USGG10YR_Index.xlsx", 3),
    "CH2Y":    ("GSWISS02_Index.xlsx", 3),
    "UK2Y":    ("GUKG2_Index.xlsx",    3),
    "UK10Y":   ("GUKG10_Index.xlsx",   3),
}


def _load_bbg(filepath: Path, n_cols: int = 2) -> pd.Series:
    cols = ["date", "value"] if n_cols == 2 else ["date", "value", "_extra"]
    df = pd.read_excel(filepath, skiprows=6, header=None, names=cols)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).set_index("date")["value"]
    df.index = df.index.normalize()
    return df.sort_index()


def load_spot(asset: str) -> pd.Series:
    if asset not in SPOT_FILES:
        raise ValueError(f"Unknown asset '{asset}'. Available: {list(SPOT_FILES)}")
    return _load_bbg(DATA_DIR / SPOT_FILES[asset], n_cols=2)


def load_iv(series: str) -> pd.Series:
    if series not in VOL_FILES:
        raise ValueError(f"Unknown vol series '{series}'. Available: {list(VOL_FILES)}")
    s = _load_bbg(DATA_DIR / VOL_FILES[series], n_cols=2)
    return s / 100  # convert % to decimal


def load_index(name: str) -> pd.Series:
    if name not in INDEX_FILES:
        raise ValueError(f"Unknown index '{name}'. Available: {list(INDEX_FILES)}")
    fname, n_cols = INDEX_FILES[name]
    return _load_bbg(DATA_DIR / fname, n_cols=n_cols)


def build_asset_panel(asset: str, vol_tenor: str = "1M") -> pd.DataFrame:
    """
    Merge spot + implied vol into a single aligned DataFrame.
    vol_tenor: '1M' or '3M'
    """
    spot = load_spot(asset).rename("spot")
    iv_key = f"{asset}_{vol_tenor}"
    iv = load_iv(iv_key).rename("iv")
    df = pd.concat([spot, iv], axis=1).dropna()
    df.index.name = "date"
    return df
