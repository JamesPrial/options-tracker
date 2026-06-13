"""Tests for the Black-Scholes-Merton Greeks in greeks.py.

Reference values are the textbook case S=100, K=100, T=1, r=0.05, q=0, sigma=0.2,
which yields d1=0.35, d2=0.15. No network access is used.
"""

import math

import numpy as np
import pandas as pd
import pytest

import greeks


def _chain(rows):
    """Build a minimal chain DataFrame from (strike, iv, type, T) tuples."""
    return pd.DataFrame(
        rows, columns=["strike", "impliedVolatility", "type", "timeToExpiry"]
    )


def test_reference_call_and_put():
    df = _chain(
        [
            (100.0, 0.2, "call", 1.0),
            (100.0, 0.2, "put", 1.0),
        ]
    )
    out = greeks.compute_greeks(df, spot=100.0, r=0.05, q=0.0)
    call, put = out.iloc[0], out.iloc[1]

    # Delta
    assert call["delta"] == pytest.approx(0.63683, abs=1e-4)
    assert put["delta"] == pytest.approx(-0.36317, abs=1e-4)

    # Gamma (identical for call/put)
    assert call["gamma"] == pytest.approx(0.018762, abs=1e-5)
    assert put["gamma"] == pytest.approx(0.018762, abs=1e-5)

    # Vega per 1% (identical for call/put)
    assert call["vega"] == pytest.approx(0.37524, abs=1e-4)
    assert put["vega"] == pytest.approx(0.37524, abs=1e-4)

    # Theta per calendar day
    assert call["theta"] == pytest.approx(-0.017573, abs=1e-5)
    assert put["theta"] == pytest.approx(-0.0045423, abs=1e-5)

    # Rho per 1%
    assert call["rho"] == pytest.approx(0.53234, abs=1e-4)
    assert put["rho"] == pytest.approx(-0.41889, abs=1e-4)

    # Traceability column
    assert call["underlyingPrice"] == 100.0


def test_put_call_parity_delta():
    """call delta - put delta == e^(-qT) for matching strike/expiry/vol."""
    q = 0.03
    df = _chain([(120.0, 0.25, "call", 0.5), (120.0, 0.25, "put", 0.5)])
    out = greeks.compute_greeks(df, spot=100.0, r=0.04, q=q)
    diff = out.iloc[0]["delta"] - out.iloc[1]["delta"]
    assert diff == pytest.approx(math.exp(-q * 0.5), abs=1e-9)


def test_dividend_yield_lowers_call_delta():
    base = greeks.compute_greeks(
        _chain([(100.0, 0.2, "call", 1.0)]), spot=100.0, r=0.05, q=0.0
    ).iloc[0]["delta"]
    with_div = greeks.compute_greeks(
        _chain([(100.0, 0.2, "call", 1.0)]), spot=100.0, r=0.05, q=0.05
    ).iloc[0]["delta"]
    assert with_div < base


@pytest.mark.parametrize(
    "rows, spot",
    [
        ([(100.0, 0.2, "call", 0.0)], 100.0),  # expired
        ([(100.0, 0.0, "call", 1.0)], 100.0),  # zero vol
        ([(100.0, float("nan"), "call", 1.0)], 100.0),  # missing IV
        ([(100.0, 0.2, "call", 1.0)], float("nan")),  # missing spot
        ([(-100.0, 0.2, "call", 1.0)], 100.0),  # bad strike
        ([(100.0, 0.2, "call", -0.5)], 100.0),  # negative time
    ],
)
def test_invalid_rows_return_nan(rows, spot):
    out = greeks.compute_greeks(_chain(rows), spot=spot, r=0.05, q=0.0)
    row = out.iloc[0]
    for col in greeks.GREEK_COLUMNS:
        assert np.isnan(row[col]), f"{col} should be NaN for invalid input"


def test_valid_and_invalid_mixed():
    """A bad row must not poison the good rows in the same chain."""
    df = _chain(
        [
            (100.0, 0.2, "call", 1.0),  # valid
            (100.0, 0.0, "put", 1.0),  # invalid (zero vol)
        ]
    )
    out = greeks.compute_greeks(df, spot=100.0, r=0.05, q=0.0)
    assert not np.isnan(out.iloc[0]["delta"])
    assert np.isnan(out.iloc[1]["delta"])
