import pandas as pd
import numpy as np
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

DATA = '/mnt/user-data/uploads'

# ── helpers ──────────────────────────────────────────────────────────────────
def load_bbg(path, col_idx=1):
    df = pd.read_excel(path, header=None)
    # find first date row (row 3 onwards, col 0 is datetime)
    data_rows = df.iloc[3:].copy()
    data_rows.columns = range(len(data_rows.columns))
    data_rows = data_rows[[0, col_idx]].dropna()
    data_rows[0] = pd.to_datetime(data_rows[0], errors='coerce')
    data_rows = data_rows.dropna(subset=[0])
    data_rows = data_rows.set_index(0).sort_index()
    data_rows.index.name = 'date'
    data_rows.columns = ['value']
    data_rows['value'] = pd.to_numeric(data_rows['value'], errors='coerce')
    return data_rows['value'].dropna()

# ── load all series ───────────────────────────────────────────────────────────
pairs = ['AUDUSD', 'EURUSD', 'GBPUSD', 'USDCHF', 'USDJPY']

spot, iv1m, iv3m = {}, {}, {}
for p in pairs:
    spot[p]  = load_bbg(f'{DATA}/{p}_Curncy.xlsx')
    iv1m[p]  = load_bbg(f'{DATA}/{p}V1M.xlsx')
    iv3m[p]  = load_bbg(f'{DATA}/{p}V3M.xlsx')

spx    = load_bbg(f'{DATA}/SPX_INDEX.xlsx')
us2y   = load_bbg(f'{DATA}/USGG2YR_Index.xlsx')
# UK 10Y as risk-off proxy
uk10y  = load_bbg(f'{DATA}/GUKG10_Index.xlsx')
chf2y  = load_bbg(f'{DATA}/GSWISS02_Index.xlsx')

print("Data loaded.")
for p in pairs:
    print(f"  {p}: spot {spot[p].index[0].date()} to {spot[p].index[-1].date()} | iv1m {iv1m[p].index[0].date()} to {iv1m[p].index[-1].date()}")
print(f"  SPX: {spx.index[0].date()} to {spx.index[-1].date()}")