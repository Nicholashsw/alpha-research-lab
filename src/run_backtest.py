"""
Multi-Asset VRP Strategy — Main Runner

Usage:
    python run_backtest.py                    # all assets
    python run_backtest.py --asset USDCHF     # single asset
    python run_backtest.py --start 2005-01-01 # custom start date
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

from utils.data_loader import build_asset_panel
from strategies.vrp_signal import generate_signals
from engine.backtester import run_backtest, NOTIONAL
from utils.metrics import compute_metrics, print_tearsheet

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

ASSETS = ["USDCHF", "XAUUSD", "GBPUSD", "USDJPY"]


def run_asset(asset: str, start: str = "2005-01-01", vol_tenor: str = "1M") -> dict:
    print(f"Running {asset}...")

    panel = build_asset_panel(asset, vol_tenor)
    panel = panel[panel.index >= start]

    signals_df = generate_signals(panel["spot"], panel["iv"])
    merged = signals_df.join(panel[["iv"]], how="left", rsuffix="_raw")

    result = run_backtest(signals_df)
    metrics = compute_metrics(result["equity"], result["trades"])
    print_tearsheet(asset, metrics)

    return {
        "asset":   asset,
        "signals": signals_df,
        "equity":  result["equity"],
        "trades":  result["trades"],
        "metrics": metrics,
    }


def plot_tearsheet(results: list):
    n = len(results)
    fig = plt.figure(figsize=(18, 5 * n))
    fig.patch.set_facecolor("#0d0d0d")
    gs = gridspec.GridSpec(n, 3, figure=fig, hspace=0.5, wspace=0.35)

    for i, r in enumerate(results):
        asset   = r["asset"]
        sig_df  = r["signals"]
        equity  = r["equity"]
        metrics = r["metrics"]
        dd      = metrics["drawdown_series"]

        ax_price = fig.add_subplot(gs[i, 0])
        ax_eq    = fig.add_subplot(gs[i, 1])
        ax_dd    = fig.add_subplot(gs[i, 2])

        for ax in [ax_price, ax_eq, ax_dd]:
            ax.set_facecolor("#111111")
            ax.tick_params(colors="#aaaaaa", labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor("#333333")

        # Price + regime
        ax_price.plot(sig_df["spot"], color="#4a9eff", linewidth=0.8, label="Spot")
        bull = sig_df[sig_df["signal"] == 1]
        bear = sig_df[sig_df["signal"] == -1]
        ax_price.scatter(bull.index, bull["spot"], marker="^", s=15, color="#00cc66", zorder=3, label="Sell Put Spread")
        ax_price.scatter(bear.index, bear["spot"], marker="v", s=15, color="#ff4444", zorder=3, label="Sell Call Spread")
        ax_price.set_title(f"{asset} — Signals", color="white", fontsize=9, fontweight="bold")
        ax_price.legend(fontsize=6, facecolor="#1a1a1a", labelcolor="white", framealpha=0.8)

        # IV vs RV
        ax2 = ax_price.twinx()
        ax2.set_facecolor("#111111")
        ax2.plot(sig_df["iv"] * 100, color="#ffaa00", linewidth=0.6, alpha=0.6, label="IV")
        ax2.plot(sig_df["rv"] * 100, color="#cc66ff", linewidth=0.6, alpha=0.6, label="RV")
        ax2.tick_params(colors="#aaaaaa", labelsize=7)
        ax2.set_ylabel("Vol (%)", color="#aaaaaa", fontsize=7)

        # Equity
        ax_eq.plot(equity, color="#00cc66", linewidth=1)
        ax_eq.axhline(NOTIONAL, color="#555555", linewidth=0.5, linestyle="--")
        ax_eq.set_title(f"{asset} — Equity", color="white", fontsize=9, fontweight="bold")
        ax_eq.set_ylabel("Portfolio ($)", color="#aaaaaa", fontsize=8)
        ax_eq.yaxis.set_tick_params(labelsize=7)

        # Drawdown
        ax_dd.fill_between(dd.index, dd * 100, 0, color="#ff4444", alpha=0.5)
        ax_dd.plot(dd * 100, color="#ff6666", linewidth=0.7)
        ax_dd.set_title(f"{asset} — Drawdown", color="white", fontsize=9, fontweight="bold")
        ax_dd.set_ylabel("Drawdown (%)", color="#aaaaaa", fontsize=8)
        ax_dd.yaxis.set_tick_params(labelsize=7)

        # Metrics text box
        m = metrics
        txt = (
            f"CAGR: {m['cagr']:.1%}  Sharpe: {m['sharpe']:.2f}\n"
            f"MaxDD: {m['max_drawdown']:.1%}  WinRate: {m['win_rate']:.1%}\n"
            f"Trades: {m['n_trades']}  PF: {m['profit_factor']:.2f}"
        )
        ax_eq.text(0.02, 0.97, txt, transform=ax_eq.transAxes, fontsize=7,
                   verticalalignment="top", color="#cccccc",
                   bbox=dict(facecolor="#1a1a1a", alpha=0.8, edgecolor="#333333"))

    fig.suptitle("Multi-Asset Volatility Risk Premium Strategy", color="white",
                 fontsize=14, fontweight="bold", y=1.01)

    out_path = OUTPUT_DIR / "vrp_tearsheet.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"\nTearsheet saved → {out_path}")
    plt.show()


def plot_portfolio(results: list):
    """Combined equity curve across all assets (equal-weight)."""
    equities = pd.concat([r["equity"].rename(r["asset"]) for r in results], axis=1).dropna()
    portfolio = equities.sum(axis=1)

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), facecolor="#0d0d0d")
    for ax in axes:
        ax.set_facecolor("#111111")
        ax.tick_params(colors="#aaaaaa")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333333")

    axes[0].plot(portfolio, color="#4a9eff", linewidth=1.2)
    axes[0].set_title("Portfolio Equity — Equal Weight Multi-Asset VRP", color="white", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("Portfolio Value ($)", color="#aaaaaa")

    port_dd = (portfolio - portfolio.cummax()) / portfolio.cummax()
    axes[1].fill_between(port_dd.index, port_dd * 100, 0, color="#ff4444", alpha=0.5)
    axes[1].plot(port_dd * 100, color="#ff6666", linewidth=0.8)
    axes[1].set_title("Portfolio Drawdown", color="white", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Drawdown (%)", color="#aaaaaa")

    plt.tight_layout()
    out_path = OUTPUT_DIR / "vrp_portfolio.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Portfolio chart saved → {out_path}")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Multi-Asset VRP Backtester")
    parser.add_argument("--asset", type=str, default=None, help="Single asset (e.g. USDCHF)")
    parser.add_argument("--start", type=str, default="2005-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--tenor", type=str, default="1M", choices=["1M", "3M"], help="Vol tenor")
    args = parser.parse_args()

    assets = [args.asset] if args.asset else ASSETS
    results = [run_asset(a, start=args.start, vol_tenor=args.tenor) for a in assets]

    plot_tearsheet(results)
    if len(results) > 1:
        plot_portfolio(results)


if __name__ == "__main__":
    main()
