"""Black-Scholes-Merton option Greeks, vectorized over an options-chain DataFrame.

yfinance returns implied volatility but not the Greeks, so we compute them here
from the Black-Scholes-Merton model (European options with a continuous dividend
yield q).

Scaling conventions (broker-style), so the numbers read the way traders expect:
- ``delta``, ``gamma``: raw, per $1 move of the underlying.
- ``vega``:  per **1%** change in implied volatility (raw vega / 100).
- ``theta``: per **calendar day** (raw annual theta / 365).
- ``rho``:   per **1%** change in the risk-free rate (raw rho / 100).

Greeks are returned as NaN (never an exception) for rows where they are not
well defined: non-positive time to expiry, non-positive/missing volatility,
missing spot, or non-positive strike.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

# Used by theta/rho day/percent scaling.
DAYS_PER_YEAR = 365.0

# Fallback if the live T-bill fetch fails.
DEFAULT_RISK_FREE_RATE = 0.04

# Columns added to the chain by compute_greeks().
GREEK_COLUMNS = ["delta", "gamma", "theta", "vega", "rho"]
TRACE_COLUMNS = ["underlyingPrice", "timeToExpiry"]


def get_risk_free_rate(fallback: float = DEFAULT_RISK_FREE_RATE) -> float:
    """Return the current risk-free rate as a fraction (e.g. 0.0521 for 5.21%).

    Uses the 13-week US Treasury bill yield (``^IRX``), which Yahoo quotes in
    percent. Returns ``fallback`` on any failure so a network hiccup never
    aborts a run.
    """
    try:
        irx = yf.Ticker("^IRX")
        rate_pct: float | None = None

        # fast_info is cheap; fall back to a 1-day history close.
        try:
            rate_pct = float(irx.fast_info["last_price"])
        except Exception:  # noqa: BLE001 - try the history path next
            rate_pct = None

        if rate_pct is None or not np.isfinite(rate_pct):
            hist = irx.history(period="5d")
            if hist is not None and not hist.empty:
                rate_pct = float(hist["Close"].dropna().iloc[-1])

        if rate_pct is None or not np.isfinite(rate_pct):
            return fallback
        return rate_pct / 100.0
    except Exception:  # noqa: BLE001 - any failure -> fallback
        return fallback


def _bsm_greeks(
    spot: float,
    strike: np.ndarray,
    t: np.ndarray,
    r: float,
    q: float,
    sigma: np.ndarray,
    is_call: np.ndarray,
) -> dict[str, np.ndarray]:
    """Vectorized Black-Scholes-Merton Greeks. Inputs are numpy arrays (broadcast).

    Returns a dict of raw, unscaled Greeks (per-year theta/rho/vega). Invalid
    rows are set to NaN. Scaling to broker conventions happens in the caller.
    """
    strike = np.asarray(strike, dtype=float)
    t = np.asarray(t, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)

    valid = (
        np.isfinite(strike)
        & (strike > 0)
        & np.isfinite(t)
        & (t > 0)
        & np.isfinite(sigma)
        & (sigma > 0)
        & np.isfinite(spot)
        & (spot > 0)
    )

    # Compute on safe substitutes where invalid, then mask to NaN at the end.
    safe_k = np.where(valid, strike, 1.0)
    safe_t = np.where(valid, t, 1.0)
    safe_sigma = np.where(valid, sigma, 1.0)

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        sqrt_t = np.sqrt(safe_t)
        d1 = (np.log(spot / safe_k) + (r - q + 0.5 * safe_sigma**2) * safe_t) / (
            safe_sigma * sqrt_t
        )
        d2 = d1 - safe_sigma * sqrt_t

        disc_q = np.exp(-q * safe_t)  # dividend discount
        disc_r = np.exp(-r * safe_t)  # rate discount
        pdf_d1 = norm.pdf(d1)
        cdf_d1 = norm.cdf(d1)
        cdf_d2 = norm.cdf(d2)
        cdf_neg_d1 = norm.cdf(-d1)
        cdf_neg_d2 = norm.cdf(-d2)

        # Delta
        delta = np.where(is_call, disc_q * cdf_d1, disc_q * (cdf_d1 - 1.0))

        # Gamma (same for calls and puts)
        gamma = disc_q * pdf_d1 / (spot * safe_sigma * sqrt_t)

        # Vega (per 1.00 change in vol; same for calls and puts)
        vega = spot * disc_q * pdf_d1 * sqrt_t

        # Theta (per year)
        common_theta = -(spot * pdf_d1 * safe_sigma * disc_q) / (2.0 * sqrt_t)
        theta_call = (
            common_theta - r * safe_k * disc_r * cdf_d2 + q * spot * disc_q * cdf_d1
        )
        theta_put = (
            common_theta
            + r * safe_k * disc_r * cdf_neg_d2
            - q * spot * disc_q * cdf_neg_d1
        )
        theta = np.where(is_call, theta_call, theta_put)

        # Rho (per 1.00 change in rate)
        rho = np.where(
            is_call,
            safe_k * safe_t * disc_r * cdf_d2,
            -safe_k * safe_t * disc_r * cdf_neg_d2,
        )

    nan = np.full_like(strike, np.nan, dtype=float)
    return {
        "delta": np.where(valid, delta, nan),
        "gamma": np.where(valid, gamma, nan),
        "theta": np.where(valid, theta, nan),
        "vega": np.where(valid, vega, nan),
        "rho": np.where(valid, rho, nan),
    }


def compute_greeks(
    df: pd.DataFrame, spot: float, r: float, q: float
) -> pd.DataFrame:
    """Append Greek columns to a per-ticker options-chain DataFrame.

    Expects columns ``strike``, ``impliedVolatility``, ``type`` ('call'/'put'),
    and ``timeToExpiry`` (years). Adds ``delta``, ``gamma``, ``theta``, ``vega``,
    ``rho`` plus traceability columns ``underlyingPrice`` and ``timeToExpiry``
    (the latter is left as provided). Returns the same DataFrame, mutated.
    """
    spot = float(spot) if spot is not None else float("nan")
    q = float(q) if q is not None and np.isfinite(q) else 0.0

    strike = df["strike"].to_numpy(dtype=float)
    sigma = df["impliedVolatility"].to_numpy(dtype=float)
    t = df["timeToExpiry"].to_numpy(dtype=float)
    is_call = (df["type"].astype(str).str.lower() == "call").to_numpy()

    raw = _bsm_greeks(spot, strike, t, r, q, sigma, is_call)

    df["delta"] = raw["delta"]
    df["gamma"] = raw["gamma"]
    df["theta"] = raw["theta"] / DAYS_PER_YEAR  # per calendar day
    df["vega"] = raw["vega"] / 100.0  # per 1% vol
    df["rho"] = raw["rho"] / 100.0  # per 1% rate
    df["underlyingPrice"] = spot
    return df
