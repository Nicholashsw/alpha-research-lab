# Bear Market Reversal — DCA Strategy Backtester

A systematic DCA screener and backtester built around one idea: **only buy when price is meaningfully below its 200-day SMA. Hold cash otherwise.**

---

## Strategy Logic

| Condition | Action |
|---|---|
| Price ≥ 10% below 200-day SMA | 🔴 **Buy aggressively** — deploy $500 per signal |
| Price within ±2% of 200-day SMA | 🟡 **Buy at fair value** — optional top-up |
| Price above 200-day SMA | 🟢 **Hold cash** — do not deploy |

The 200-day SMA acts as a proxy for long-run fair value. Buying below it concentrates capital into fear-driven dislocations — historically the highest-reward entry windows.

---

## Backtest Results (2015–2024, $500/signal)

| Ticker | Sector | BMR Return | 200-SMA Return | Monthly DCA | Trades |
|---|---|---|---|---|---|
| GRID | Energy | **+160.3%** | +134.2% | +133.4% | 195 |
| URA | Energy | **+144.6%** | +131.6% | +106.7% | 299 |
| PPA | Defense | **+132.5%** | +112.1% | +115.3% | 92 |
| HACK | Cybersecurity | **+126.4%** | +102.8% | +99.8% | 222 |
| XAR | Defense | **+114.8%** | +79.4% | +103.1% | 172 |
| QQQ | Benchmark | +106.6% | +258.6% | **+181.3%** | 150 |
| ITA | Defense | **+95.1%** | +78.8% | +75.2% | 139 |
| SPY | Benchmark | +89.0% | +121.5% | **+115.1%** | 76 |
| CIBR | Cybersecurity | +85.3% | +123.8% | **+132.5%** | 136 |
| AIQ | AI Infra | +82.9% | +84.7% | **+104.7%** | 193 |
| SMH | Memory | +261.4% | +453.1% | **+357.3%** | 180 |
| SOXX | Memory | +191.4% | +334.5% | **+259.6%** | 182 |

**Key finding:** BMR outperforms monthly DCA in 9/15 tickers. The edge is strongest in cyclical/volatile ETFs (Energy, Defense). It underperforms in structurally compounding growth ETFs (SMH, QQQ, SOXX) where staying invested beats waiting for dips.

---

## Project Structure

```
bear-market-reversal/
├── src/
│   ├── backtester.py       # Core backtest engine (BMR + 200-SMA strategies)
│   ├── screener.py         # Live signal scanner across full watchlist
│   └── run_backtest.py     # Batch runner — generates results JSON
├── results/
│   ├── backtest_results.json   # Full backtest output (auto-generated)
│   ├── dashboard_data.json     # Slim chart data for dashboard
│   └── latest_scan.json        # Latest daily screener output
├── .github/workflows/
│   └── daily_scan.yml          # GitHub Actions: auto-scan after US market close
├── requirements.txt
└── README.md
```

---

## Watchlist

Covers five high-conviction thematic sectors for 2026:

| Sector | Thesis | ETFs |
|---|---|---|
| **Energy** | AI grid demand + EV adoption | URA, ICLN, GRID |
| **Cybersecurity** | AI-driven threat surface expansion | CIBR, HACK, BUG |
| **Defense** | Record government spending + autonomous systems | ITA, PPA, XAR |
| **AI Infrastructure** | Neocloud + GPU cooling + networking | AIQ, SRVR |
| **Memory** | HBM supercycle as AI bottleneck | SMH, SOXX |

---

## Quickstart

```bash
git clone https://github.com/YOUR_USERNAME/bear-market-reversal
cd bear-market-reversal
pip install -r requirements.txt

# Run live screener — prints buy signals to terminal
python src/screener.py

# Run full backtest suite — generates results/backtest_results.json
python src/run_backtest.py
```

---

## Backtesting a Custom Ticker

```python
from src.backtester import BacktestConfig, run_bear_market_reversal

cfg = BacktestConfig(
    ticker="GEV",
    start="2020-01-01",
    end="2024-12-31",
    deploy_per_signal=500.0,
    bear_threshold=-0.10,   # -10% below SMA triggers buy
)

result = run_bear_market_reversal(cfg)
print(f"Total return: {result.total_return_pct:.1f}%")
print(f"Trades fired: {result.num_trades}")
print(f"Final value:  ${result.final_value:,.0f}")
```

---

## Limitations & Risk Disclosure

- Strategy performance is highly dependent on the underlying ETF recovering over time. ETFs that structurally decline will destroy capital.
- Signal frequency varies widely — some tickers fire 300+ signals over a decade; others fire fewer than 100. Capital requirements differ accordingly.
- No commissions or slippage modelled.
- The 10% threshold is a fixed heuristic. More volatile ETFs may warrant a wider threshold (e.g. -15%).
- Past backtest results do not guarantee future performance.

---

## Automated Daily Scanning

The `.github/workflows/daily_scan.yml` workflow runs the screener at 10pm UTC (6am SGT) every weekday — after the US market close. Results are committed to `results/latest_scan.json` automatically.

To enable: push to GitHub, then ensure Actions are enabled in your repository settings.

---

Nicholas Hong | Built for educational and research purposes. Not financial advice.
