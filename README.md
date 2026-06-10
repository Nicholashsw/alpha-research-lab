# Multi-Asset Volatility Risk Premium Strategy

A systematic, event-driven backtesting framework for harvesting the **Volatility Risk Premium (VRP)** across FX and commodity markets using delta-structured options spreads with macro regime filtering.

---

## Strategy Overview

Options markets consistently price implied volatility (IV) above realised volatility (RV). This persistent gap — the VRP — represents the risk premium sellers earn for providing insurance. This framework captures that premium systematically through defined-risk spreads, filtered by trend regime and VRP sign.

**Core logic:**

| Condition | Action |
|---|---|
| Spot > 200MA & IV > RV | Sell Bull Put Spread (20Δ / 10Δ) |
| Spot < 200MA & IV > RV | Sell Bear Call Spread (20Δ / 10Δ) |
| IV ≤ RV | No trade |

**Trade lifecycle:** Enter at 45 DTE → Exit at 50% profit, 2× stop, or 21 DTE force-close.

---

## Asset Universe

| Asset | Description | Data |
|---|---|---|
| USDCHF | USD/CHF FX spot + 1M/3M IV | Bloomberg BGN |
| XAUUSD | Gold spot + 1M/3M IV | Bloomberg BGN |
| GBPUSD | GBP/USD FX spot + 1M/3M IV | Bloomberg BGN |
| USDJPY | USD/JPY FX spot + 1M/3M IV | Bloomberg BGN |

Macro context series also loaded: VIX, SPX, US/UK/CH yield curves.

---

## Results (2005–2026, 5% risk-per-trade sizing)

| Asset | CAGR | Sharpe (Trade) | Max DD | Win Rate | Profit Factor | Trades |
|---|---|---|---|---|---|---|
| USDCHF | -0.12% | -0.03 | -17.8% | 69.2% | 0.99 | 487 |
| XAUUSD | +1.62% | **0.41** | -10.9% | 73.4% | 1.21 | 496 |
| GBPUSD | -0.10% | -0.02 | -13.9% | 68.1% | 0.99 | 524 |
| USDJPY | +1.65% | **0.40** | -6.3% | 73.0% | 1.22 | 518 |

> **Sharpe (Trade)** is annualised at the trade-level — a more honest measure for options strategies where daily mark-to-market volatility inflates apparent risk.

**Key observation:** XAUUSD and USDJPY consistently exceed the ~70.1% win rate required to break even at a 2.35× loss-to-win ratio. USDCHF and GBPUSD sit just below this threshold, reflecting structurally lower VRP in EUR-correlated pairs over this period.

---

## Architecture

```
vrp_strategy/
├── run_backtest.py              # Entry point: single or multi-asset run
├── requirements.txt
│
├── strategies/
│   └── vrp_signal.py           # 200MA regime filter + IV/RV VRP signal
│
├── engine/
│   └── backtester.py           # Event-driven backtester (45/21 DTE lifecycle)
│
├── options/
│   └── black_scholes.py        # BS pricing, Greeks, delta-based strike inversion
│
├── utils/
│   ├── data_loader.py          # Bloomberg Excel loader (BGN format)
│   └── metrics.py              # Performance metrics + tearsheet printer
│
├── data/                       # Bloomberg XLSX files (not committed)
└── output/                     # Generated charts
```

---

## Key Design Decisions

**Why spreads, not naked options?**
Defined risk — max loss is bounded by the spread width, enabling proper position sizing and survival through drawdowns. Critical for both real trading and honest backtesting.

**Why 20Δ / 10Δ strikes?**
~75–85% probability of profit at entry. Strike selection via Black-Scholes delta inversion rather than fixed OTM percentage — accounts for the actual volatility surface at each entry.

**Why 45 DTE entry, 21 DTE exit?**
45 DTE captures the steepest portion of the theta decay curve while limiting gamma exposure. The 21 DTE force-close avoids the non-linear gamma risk that accelerates near expiry.

**Why risk-based sizing?**
Contracts are sized so max loss = 5% of current portfolio value, not a fixed notional. This prevents a single tail event from destroying capital and makes the strategy self-scaling as equity grows.

**Why trade-level Sharpe?**
Daily mark-to-market equity for an options spread fluctuates heavily with IV changes even when directional P&L is positive. Trade-level Sharpe — annualised at the average hold frequency — is a more honest representation of the strategy's risk-adjusted edge.

---

## Limitations (Acknowledged)

- **No real options chain data** — strikes and premiums are derived from Black-Scholes using ATM implied vol. A real implementation requires surface data (smile/skew adjustment).
- **Constant volatility assumption** — BS assumes flat vol; FX surfaces have meaningful skew especially around risk events.
- **No transaction costs or slippage** — bid-ask on FX options can be 1–3 vol points, which would compress edge on lower-VRP assets.
- **One trade per asset** — no pyramiding or concurrent spread management across expiries.
- **Simulated IV** — Bloomberg BGN ATM vol used as IV proxy; actual tradable IV (e.g. from IBKR options chain) may differ.

---

## Setup

```bash
git clone https://github.com/Nicholashsw/algorithmic-trading-bot
cd algorithmic-trading-bot
pip install -r requirements.txt
```

Place Bloomberg XLSX data files in `data/`. Then:

```bash
# All assets
python run_backtest.py

# Single asset
python run_backtest.py --asset XAUUSD

# Custom date range and vol tenor
python run_backtest.py --asset USDJPY --start 2010-01-01 --tenor 3M
```

---

## Roadmap

- [ ] Vol surface skew adjustment (25Δ risk reversal + butterfly)
- [ ] IV regime filter: only sell when IV percentile > 50th
- [ ] Multi-leg portfolio allocation with correlation-adjusted sizing
- [ ] IBKR live options chain integration via `ib_insync`
- [ ] C++ execution engine for latency-sensitive deployment

---

*Nicholas Hong | Built for educational and research purposes. Not financial advice.*
