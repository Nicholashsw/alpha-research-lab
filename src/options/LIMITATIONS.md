# LIMITATIONS

Scope of `vol_engine.py` and the assumptions you are accepting when you use it.

## Model assumptions

- **Black-76 is European.** The closed-form pricing, greeks, and `implied_vol`
  assume no early exercise. Standard CME FX options (6E, 6B, 6J, 6C, 6A, 6S) are
  American. Fitting a European model to an American market price overstates
  implied vol and biases delta. The error is negligible OTM and short dated, and
  grows sharply in the money and near expiry. Quantify it on your own strikes
  with `bias_report` before trusting the European greeks. In the bundled demo
  the gap is under 1 bp at the money and reaches roughly 120 bps at 5.6 percent
  in the money.

- **CRR is the reference, not ground truth.** The binomial American pricer
  converges to the true price as steps increase, at order 1/steps. Default steps
  are tuned for the demo. Raise steps for production and confirm convergence on a
  few representative strikes. American greeks come from finite differences on the
  tree, so they inherit both discretization and bump noise. They are a diagnostic,
  not a hedging-grade greek.

- **No carry term, by design.** Black-76 takes the futures price F directly.
  Cost of carry is already in F via covered interest parity. The rate r enters
  only through e^(-rT) discounting of the premium. Do not add a carry adjustment.
  If you feed a spot rate instead of a futures price you will double count carry.

- **Discount rate is an input, not a curve.** A single continuously compounded r
  is used. For a real panel, supply the OIS or SOFR rate at each option's tenor.
  Black-76 rho equals minus T times price, so the premium is not very sensitive
  to r, but the convention still matters for consistency between IV inversion and
  greek calculation.

- **Time is calendar years.** T is expected in years and should use the same day
  count for IV inversion and greeks. Mixing calendar and trading-day conventions
  corrupts the implied vol.

- **One vol per strike.** Inversion is per strike, which preserves the smile.
  There is no surface fit, no interpolation, and no arbitrage repair across
  strikes or expiries. Crossed or stale quotes will produce NaN or noisy IV.

## Data dependencies, not provided here

- This module computes greeks from prices. It does not supply prices. The
  historical greeks panel still requires a historical option price panel,
  futures price plus option settlement price per strike per day. Source that
  from Databento GLBX or equivalent. Recomputation removes the need for a vendor
  greeks feed, not the need for a vendor price feed.

- Settlement price quality drives everything downstream. Illiquid wings, wide
  settlement marks, and roll boundaries will dominate any modeling error.

## Numerical notes

- `implied_vol` returns NaN when the price violates the no-arbitrage bounds
  (below discounted intrinsic, above the discounted upper bound, or non-positive
  time). Check for NaN before using the output.

- Newton-Raphson is the primary solver, with a vectorized bisection backstop for
  elements where vega collapses. Bisection is bounded to vol in [1e-6, 5.0].
  Vols outside that range are not recoverable and indicate bad input.

Nicholas Hong | Built for educational and research purposes. Not financial advice.
