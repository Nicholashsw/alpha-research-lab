"""
Event-Driven VRP Options Backtester.

Trade lifecycle:
  Entry  : 45 DTE, on signal day
  Exit   : Take profit (50% premium), stop loss (2x premium), or 21 DTE force close
  Spreads: Bull Put (signal=+1), Bear Call (signal=-1)
  Strikes: 20-delta short leg, 10-delta long leg (width = defined risk)

One open trade per asset at a time.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from options.black_scholes import bs_price, strike_from_delta, bs_delta


# ── Config ────────────────────────────────────────────────────────────────────

ENTRY_DTE    = 45
EXIT_DTE     = 21
SHORT_DELTA  = 0.20
LONG_DELTA   = 0.10
TP_PCT       = 0.50   # Close at 50% of max profit
SL_MULT      = 2.0    # Stop if spread value = 2x premium received
NOTIONAL     = 10_000 # USD notional per trade
RISK_FREE    = 0.04   # Annualised


# ── Trade record ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_date: pd.Timestamp
    expiry_date: pd.Timestamp
    direction: str          # "bull_put" or "bear_call"
    spot_entry: float
    K_short: float          # Strike sold (20-delta)
    K_long: float           # Strike bought (10-delta)
    premium_received: float # Net credit per unit
    contracts: float        # Notional / spread width
    max_profit: float
    max_loss: float
    exit_date: Optional[pd.Timestamp] = None
    exit_pnl: Optional[float] = None
    exit_reason: Optional[str] = None


# ── Spread pricing ────────────────────────────────────────────────────────────

def _spread_value(spot, K_short, K_long, T, r, sigma, direction):
    """Current mark-to-market value of spread (cost to close)."""
    if direction == "bull_put":
        short_val = bs_price(spot, K_short, T, r, sigma, "put")
        long_val  = bs_price(spot, K_long,  T, r, sigma, "put")
    else:  # bear_call
        short_val = bs_price(spot, K_short, T, r, sigma, "call")
        long_val  = bs_price(spot, K_long,  T, r, sigma, "call")
    return short_val - long_val  # debit to close (positive = we owe)


def _open_trade(date, spot, sigma, signal) -> Optional[Trade]:
    T = ENTRY_DTE / 365
    r = RISK_FREE

    if signal == 1:   # Bull Put: sell lower put, buy even lower put
        K_short = strike_from_delta(spot, SHORT_DELTA, T, r, sigma, "put")
        K_long  = strike_from_delta(spot, LONG_DELTA,  T, r, sigma, "put")
        direction = "bull_put"
        short_p = bs_price(spot, K_short, T, r, sigma, "put")
        long_p  = bs_price(spot, K_long,  T, r, sigma, "put")
    else:             # Bear Call: sell higher call, buy even higher call
        K_short = strike_from_delta(spot, SHORT_DELTA, T, r, sigma, "call")
        K_long  = strike_from_delta(spot, LONG_DELTA,  T, r, sigma, "call")
        direction = "bear_call"
        short_p = bs_price(spot, K_short, T, r, sigma, "call")
        long_p  = bs_price(spot, K_long,  T, r, sigma, "call")

    if np.isnan(K_short) or np.isnan(K_long):
        return None

    premium = short_p - long_p  # net credit received
    if premium <= 0:
        return None

    spread_width = abs(K_short - K_long)
    contracts    = NOTIONAL / spread_width if spread_width > 0 else 0
    max_profit   = premium * contracts
    max_loss     = (spread_width - premium) * contracts
    expiry_date  = date + pd.Timedelta(days=ENTRY_DTE)

    return Trade(
        entry_date=date,
        expiry_date=expiry_date,
        direction=direction,
        spot_entry=spot,
        K_short=K_short,
        K_long=K_long,
        premium_received=premium,
        contracts=contracts,
        max_profit=max_profit,
        max_loss=max_loss,
    )


# ── Main backtester ───────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, r: float = RISK_FREE) -> dict:
    """
    df must have columns: spot, iv, signal.
    Returns dict with trades list and daily equity series.
    """
    trades = []
    equity = []
    cash   = NOTIONAL  # starting capital
    open_trade: Optional[Trade] = None

    for date, row in df.iterrows():
        spot   = row["spot"]
        sigma  = row["iv"]
        signal = row["signal"]

        # ── Check open trade for exit ──────────────────────────────────────
        if open_trade is not None:
            dte = (open_trade.expiry_date - date).days
            T   = max(dte / 365, 1e-6)
            current_val = _spread_value(spot, open_trade.K_short, open_trade.K_long, T, r, sigma, open_trade.direction)
            current_val = max(current_val, 0)

            pnl_pct = (open_trade.premium_received - current_val) / open_trade.premium_received

            close = False
            reason = None

            if pnl_pct >= TP_PCT:
                close  = True
                reason = "take_profit"
            elif current_val >= open_trade.premium_received * SL_MULT:
                close  = True
                reason = "stop_loss"
            elif dte <= EXIT_DTE:
                close  = True
                reason = "dte_exit"

            if close:
                realized_pnl = (open_trade.premium_received - current_val) * open_trade.contracts
                cash += realized_pnl
                open_trade.exit_date   = date
                open_trade.exit_pnl    = realized_pnl
                open_trade.exit_reason = reason
                trades.append(open_trade)
                open_trade = None

        # ── Try to open new trade ──────────────────────────────────────────
        if open_trade is None and signal != 0:
            t = _open_trade(date, spot, sigma, signal)
            if t is not None:
                open_trade = t

        # ── Mark-to-market equity ──────────────────────────────────────────
        mtm = 0.0
        if open_trade is not None:
            dte = max((open_trade.expiry_date - date).days, 1)
            T   = dte / 365
            curr_val = _spread_value(spot, open_trade.K_short, open_trade.K_long, T, r, sigma, open_trade.direction)
            mtm = (open_trade.premium_received - max(curr_val, 0)) * open_trade.contracts

        equity.append({"date": date, "equity": cash + mtm})

    # Force-close any open trade at end
    if open_trade is not None:
        open_trade.exit_date   = df.index[-1]
        open_trade.exit_pnl    = 0.0
        open_trade.exit_reason = "end_of_data"
        trades.append(open_trade)

    equity_df = pd.DataFrame(equity).set_index("date")["equity"]
    return {"trades": trades, "equity": equity_df}
