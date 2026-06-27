"""
vol_engine.py

Black-76 pricing, greeks, and implied vol for options on futures, with a
Cox-Ross-Rubinstein American pricer and a European-vs-American bias diagnostic.

Use the Black-76 path to build the historical greeks panel from a vendor
price panel (futures price + option settlement price per strike per day).
Use the CRR path to price the early-exercise premium on ITM or near-expiry
strikes, and run bias_report to decide whether the European approximation
is acceptable for the strikes you actually trade.

Conventions:
  F    futures price
  K    strike
  T    time to expiry, in years
  r    continuously compounded discount rate, applied to the premium only
  sig  annualized implied volatility
  cp   +1 for a call, -1 for a put

Black-76 prices options on a future. Cost of carry is already embedded in F
via covered interest parity, so r enters only through e^(-rT) discounting of
the premium. Do not add a carry term.

Units returned by the greeks:
  delta  per 1.00 move in F
  gamma  per 1.00 move in F, per 1.00 move in F
  vega   per 1.00 (100 vol points) change in sig. Divide by 100 for per point.
  theta  per year. Divide by 365 for per calendar day.
  rho    per 1.00 (100 bps) change in r. Divide by 100 for per bp.

Nicholas Hong | Built for educational and research purposes. Not financial advice.
"""

from __future__ import annotations

import numpy as np
from scipy.special import ndtr  # vectorized standard normal CDF

_SQRT_2PI = np.sqrt(2.0 * np.pi)


def _pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / _SQRT_2PI


# ----------------------------------------------------------------------
# Black-76 European pricing and greeks
# ----------------------------------------------------------------------
def black76_price(F, K, T, r, sig, cp):
    """European option on a future. Vectorized over any broadcastable inputs."""
    F, K, T, r, sig, cp = (np.asarray(x, float) for x in (F, K, T, r, sig, cp))
    disc = np.exp(-r * T)
    vol_t = sig * np.sqrt(T)
    safe = vol_t > 1e-12
    denom = np.where(safe, vol_t, 1.0)
    d1 = np.where(safe, (np.log(F / K) + 0.5 * sig * sig * T) / denom, 0.0)
    d2 = d1 - vol_t
    model = disc * cp * (F * ndtr(cp * d1) - K * ndtr(cp * d2))
    intrinsic = disc * np.maximum(cp * (F - K), 0.0)
    return np.where(safe, model, intrinsic)


def black76_greeks(F, K, T, r, sig, cp):
    """Closed-form Black-76 greeks. Returns a dict of arrays."""
    F, K, T, r, sig, cp = (np.asarray(x, float) for x in (F, K, T, r, sig, cp))
    disc = np.exp(-r * T)
    sqrt_t = np.sqrt(T)
    vol_t = sig * sqrt_t
    safe = vol_t > 1e-12
    denom = np.where(safe, vol_t, 1.0)
    d1 = np.where(safe, (np.log(F / K) + 0.5 * sig * sig * T) / denom, 0.0)
    d2 = d1 - vol_t
    pdf1 = _pdf(d1)

    price = disc * cp * (F * ndtr(cp * d1) - K * ndtr(cp * d2))
    delta = disc * cp * ndtr(cp * d1)
    gamma = np.where(safe, disc * pdf1 / (F * sig * sqrt_t), 0.0)
    vega = disc * F * pdf1 * sqrt_t
    theta = (
        -disc * F * pdf1 * sig / (2.0 * np.where(safe, sqrt_t, 1.0))
        + cp * r * disc * (F * ndtr(cp * d1) - K * ndtr(cp * d2))
    )
    # In Black-76 the only r dependence is the discount factor, so rho = -T * price.
    rho = -T * price

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
    }


# ----------------------------------------------------------------------
# Implied vol: Newton-Raphson with a vectorized bisection backstop
# ----------------------------------------------------------------------
def implied_vol(price, F, K, T, r, cp, tol=1e-8, max_iter=100):
    """
    Invert Black-76 for implied vol. Newton-Raphson primary, bisection backstop
    for elements where vega collapses or Newton stalls. Returns NaN where the
    price violates the no-arbitrage bounds.
    """
    arrs = np.broadcast_arrays(*[np.asarray(x, float) for x in (price, F, K, T, r, cp)])
    shape = arrs[0].shape
    price, F, K, T, r, cp = (a.ravel().astype(float) for a in arrs)

    disc = np.exp(-r * T)
    intrinsic = disc * np.maximum(cp * (F - K), 0.0)
    upper = np.where(cp > 0, disc * F, disc * K)
    valid = (price > intrinsic + 1e-12) & (price < upper - 1e-12) & (T > 0)

    # Manaster-Koltun style seed, clamped. Placeholder 1.0 where invalid so the
    # arithmetic stays finite; masked out at the end.
    seed = np.sqrt(np.maximum(2.0 * np.abs(np.log(F / K)) / np.maximum(T, 1e-12), 1e-6))
    sig = np.where(valid, np.clip(seed, 0.05, 3.0), 1.0)

    active = valid.copy()
    for _ in range(max_iter):
        model = black76_price(F, K, T, r, sig, cp)
        sqrt_t = np.sqrt(T)
        vol_t = sig * sqrt_t
        d1 = np.where(vol_t > 1e-12,
                      (np.log(F / K) + 0.5 * sig * sig * T) / np.where(vol_t > 1e-12, vol_t, 1.0),
                      0.0)
        vega = disc * F * _pdf(d1) * sqrt_t
        diff = model - price
        conv = np.abs(diff) < tol
        step = np.where(vega > 1e-12, diff / vega, 0.0)
        sig_new = np.clip(sig - step, 1e-6, 5.0)
        sig = np.where(active, sig_new, sig)
        active = active & ~conv & (vega > 1e-10)
        if not active.any():
            break

    # Bisection backstop. Price is monotone increasing in sig for valid options.
    resid = np.abs(black76_price(F, K, T, r, sig, cp) - price)
    need = valid & (resid > tol)
    if need.any():
        lo = np.full_like(price, 1e-6)
        hi = np.full_like(price, 5.0)
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            pm = black76_price(F, K, T, r, mid, cp)
            below = pm < price
            lo = np.where(need & below, mid, lo)
            hi = np.where(need & ~below, mid, hi)
        sig = np.where(need, 0.5 * (lo + hi), sig)

    sig = np.where(valid, sig, np.nan)
    return sig.reshape(shape)


# ----------------------------------------------------------------------
# Cox-Ross-Rubinstein binomial on a future (American or European)
# ----------------------------------------------------------------------
def crr_price(F, K, T, r, sig, cp, steps=400, american=True):
    """
    CRR binomial price for an option on a future. Scalar inputs.

    The future is a martingale under the pricing measure, so the up
    probability is (1 - d) / (u - d) with no drift term. The premium is
    discounted at r each step.
    """
    F = float(F); K = float(K); T = float(T); r = float(r); sig = float(sig); cp = float(cp)
    if T <= 0.0:
        return max(cp * (F - K), 0.0)

    dt = T / steps
    u = np.exp(sig * np.sqrt(dt))
    d = 1.0 / u
    p = (1.0 - d) / (u - d)
    disc = np.exp(-r * dt)

    k = np.arange(steps + 1)
    F_term = F * u ** k * d ** (steps - k)
    v = np.maximum(cp * (F_term - K), 0.0)

    for i in range(steps - 1, -1, -1):
        k = np.arange(i + 1)
        cont = disc * (p * v[1 : i + 2] + (1.0 - p) * v[0 : i + 1])
        if american:
            F_node = F * u ** k * d ** (i - k)
            exer = np.maximum(cp * (F_node - K), 0.0)
            v = np.maximum(cont, exer)
        else:
            v = cont
    return float(v[0])


def crr_greeks(F, K, T, r, sig, cp, steps=400, american=True):
    """American greeks by finite difference on the CRR pricer. Scalar inputs."""
    def px(F_=F, K_=K, T_=T, r_=r, s_=sig):
        return crr_price(F_, K_, T_, r_, s_, cp, steps, american)

    base = px()
    hF = max(F * 1e-4, 1e-6)
    up, dn = px(F_=F + hF), px(F_=F - hF)
    delta = (up - dn) / (2.0 * hF)
    gamma = (up - 2.0 * base + dn) / (hF * hF)

    hs = 1e-4
    vega = (px(s_=sig + hs) - px(s_=sig - hs)) / (2.0 * hs)

    hT = min(1e-3, T * 0.5)
    theta = (px(T_=T - hT) - base) / hT  # per year, decay as calendar time advances

    hr = 1e-4
    rho = (px(r_=r + hr) - px(r_=r - hr)) / (2.0 * hr)

    return {"price": base, "delta": delta, "gamma": gamma,
            "vega": vega, "theta": theta, "rho": rho}


def american_implied_vol(price, F, K, T, r, cp, steps=400, tol=1e-6, max_iter=80):
    """Invert the CRR American price for implied vol via bisection. Scalar inputs."""
    price = float(price)
    disc = np.exp(-r * T)
    intrinsic = disc * max(cp * (F - K), 0.0)
    if not (price > intrinsic and T > 0):
        return float("nan")
    lo, hi = 1e-4, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        pm = crr_price(F, K, T, r, mid, cp, steps, american=True)
        if abs(pm - price) < tol:
            return mid
        if pm < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ----------------------------------------------------------------------
# European-vs-American bias diagnostic
# ----------------------------------------------------------------------
def bias_report(F, strikes, T, r, market_prices, cp, steps=600):
    """
    For each strike, fit IV under Black-76 (European) and CRR (American) to the
    same market price, then compare the implied deltas. The European model
    ignores early exercise, so it overstates IV and the gap widens in the money.

    Returns a list of dicts, one per strike.
    """
    out = []
    strikes = np.atleast_1d(strikes).astype(float)
    market_prices = np.atleast_1d(market_prices).astype(float)
    cp_arr = np.broadcast_to(np.atleast_1d(cp).astype(float), strikes.shape)

    for K, mkt, c in zip(strikes, market_prices, cp_arr):
        iv_e = float(implied_vol(mkt, F, K, T, r, c))
        iv_a = american_implied_vol(mkt, F, K, T, r, c, steps)
        delta_e = float(black76_greeks(F, K, T, r, iv_e, c)["delta"]) if iv_e == iv_e else float("nan")
        delta_a = crr_greeks(F, K, T, r, iv_a, c, steps)["delta"] if iv_a == iv_a else float("nan")
        moneyness = (F - K) / F if c > 0 else (K - F) / F  # positive means in the money
        out.append({
            "strike": K,
            "cp": "C" if c > 0 else "P",
            "moneyness_itm": moneyness,
            "market": mkt,
            "iv_euro": iv_e,
            "iv_amer": iv_a,
            "iv_gap_bps": (iv_e - iv_a) * 1e4 if (iv_e == iv_e and iv_a == iv_a) else float("nan"),
            "delta_euro": delta_e,
            "delta_amer": delta_a,
            "delta_gap": delta_e - delta_a if (delta_e == delta_e and delta_a == delta_a) else float("nan"),
        })
    return out


# ----------------------------------------------------------------------
# Self tests and demo
# ----------------------------------------------------------------------
def _run_tests():
    rng = np.random.default_rng(0)
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    # 1. Put-call parity: C - P = e^{-rT}(F - K)
    F, K, T, r, sig = 1.08, 1.10, 45 / 365, 0.04, 0.085
    c = black76_price(F, K, T, r, sig, +1)
    p = black76_price(F, K, T, r, sig, -1)
    parity = np.exp(-r * T) * (F - K)
    check("put-call parity", abs((c - p) - parity) < 1e-12)

    # 2. Analytic greeks vs finite difference on the Black-76 price
    g = black76_greeks(F, K, T, r, sig, +1)
    hF = 1e-5
    fd_delta = (black76_price(F + hF, K, T, r, sig, +1) - black76_price(F - hF, K, T, r, sig, +1)) / (2 * hF)
    fd_gamma = (black76_price(F + hF, K, T, r, sig, +1) - 2 * c + black76_price(F - hF, K, T, r, sig, +1)) / hF ** 2
    hs = 1e-5
    fd_vega = (black76_price(F, K, T, r, sig + hs, +1) - black76_price(F, K, T, r, sig - hs, +1)) / (2 * hs)
    hT = 1e-5
    fd_theta = (black76_price(F, K, T - hT, r, sig, +1) - black76_price(F, K, T, r, sig, +1)) / hT
    check("delta vs FD", abs(float(g["delta"]) - fd_delta) < 1e-5)
    check("gamma vs FD", abs(float(g["gamma"]) - fd_gamma) < 1e-3)
    check("vega vs FD", abs(float(g["vega"]) - fd_vega) < 1e-5)
    check("theta vs FD", abs(float(g["theta"]) - fd_theta) < 1e-4)

    # 3. IV round trip across a vector of strikes and both sides
    Ks = np.array([1.03, 1.06, 1.08, 1.10, 1.13])
    cps = np.array([+1, +1, +1, -1, -1])
    sig_true = np.array([0.090, 0.082, 0.080, 0.083, 0.091])
    px = black76_price(F, Ks, T, r, sig_true, cps)
    iv = implied_vol(px, F, Ks, T, r, cps)
    check("IV round trip", np.nanmax(np.abs(iv - sig_true)) < 1e-6)

    # 4. European CRR converges to Black-76
    euro_tree = crr_price(F, K, T, r, sig, +1, steps=4000, american=False)
    check("CRR European -> Black-76", abs(euro_tree - float(c)) < 5e-4)

    # 5. American premium is non-negative for both sides
    am_put = crr_price(F, 1.12, T, r, sig, -1, steps=800, american=True)
    eu_put = crr_price(F, 1.12, T, r, sig, -1, steps=800, american=False)
    am_call = crr_price(F, 1.04, T, r, sig, +1, steps=800, american=True)
    eu_call = crr_price(F, 1.04, T, r, sig, +1, steps=800, american=False)
    check("American put >= European put", am_put >= eu_put - 1e-10)
    check("American call >= European call", am_call >= eu_call - 1e-10)

    # 6. Fitting an American price with a European model overstates IV
    mkt = crr_price(F, 1.13, T, r, 0.080, -1, steps=800, american=True)
    iv_e = float(implied_vol(mkt, F, 1.13, T, r, -1))
    iv_a = american_implied_vol(mkt, F, 1.13, T, r, -1, steps=800)
    check("American IV recovers truth", abs(iv_a - 0.080) < 2e-3)
    check("European IV > American IV (ITM)", iv_e > iv_a)

    print(f"\n  ALL TESTS {'PASSED' if ok else 'FAILED'}")
    return ok


def _demo():
    print("\nBias demo, 6E style chain. Market prices generated American at 8.0 vol,\n"
          "then inverted both ways. European overstates vol, worst in the money.\n")
    F, T, r = 1.08, 30 / 365, 0.04
    sig_true = 0.080
    strikes = np.array([1.02, 1.04, 1.06, 1.08, 1.10, 1.12, 1.14])
    cp = -1  # puts
    market = np.array([crr_price(F, K, T, r, sig_true, cp, steps=800, american=True) for K in strikes])

    rows = bias_report(F, strikes, T, r, market, cp, steps=800)
    hdr = f"{'K':>6} {'side':>4} {'itm%':>7} {'mkt':>9} {'iv_eu':>7} {'iv_am':>7} {'gap_bps':>8} {'d_eu':>8} {'d_am':>8}"
    print(hdr)
    print("-" * len(hdr))
    for x in rows:
        print(f"{x['strike']:>6.2f} {x['cp']:>4} {x['moneyness_itm']*100:>7.1f} "
              f"{x['market']:>9.5f} {x['iv_euro']:>7.4f} {x['iv_amer']:>7.4f} "
              f"{x['iv_gap_bps']:>8.1f} {x['delta_euro']:>8.4f} {x['delta_amer']:>8.4f}")


if __name__ == "__main__":
    print("vol_engine self tests")
    _run_tests()
    _demo()
