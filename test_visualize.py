"""Tests for visualize.py's pure data-prep helpers.

These exercise the helpers against both synthetic frames and the committed
sample snapshots under ``data/`` (skipped if those files are absent).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import visualize
from greeks import GREEK_COLUMNS

DATA_DIR = Path(__file__).parent / "data"
SAMPLE = DATA_DIR / "SPY_2026-06-13.csv"


def _frame() -> pd.DataFrame:
    """A small two-ticker chain with deliberate NaN/zero edge cases."""
    return pd.DataFrame(
        {
            "ticker": ["SPY", "SPY", "SPY", "SPY", "AAPL"],
            "snapshot": ["2026-06-13T15:00:00"] * 5,
            "expiration": ["2026-06-20", "2026-06-20", "2026-06-27", "2026-06-20", "2026-06-20"],
            "type": ["call", "put", "call", "call", "call"],
            "strike": [100.0, 100.0, 110.0, 90.0, 200.0],
            "volume": [10.0, np.nan, 5.0, 0.0, 7.0],
            "openInterest": [100.0, 50.0, np.nan, 20.0, 30.0],
            "impliedVolatility": [0.25, 0.30, 0.0, np.nan, 0.40],
            "delta": [0.55, -0.45, 0.20, np.nan, 0.60],
            "underlyingPrice": [105.0, 105.0, 105.0, 105.0, 210.0],
        }
    )


def test_tickers_in_preserves_first_seen_order():
    assert visualize.tickers_in(_frame()) == ["SPY", "AAPL"]


def test_expirations_for_is_sorted_and_ticker_scoped():
    assert visualize.expirations_for(_frame(), "SPY") == ["2026-06-20", "2026-06-27"]
    assert visualize.expirations_for(_frame(), "AAPL") == ["2026-06-20"]


def test_spot_price():
    assert visualize.spot_price(_frame(), "SPY") == 105.0
    assert visualize.spot_price(_frame(), "AAPL") == 210.0


def test_prep_smile_drops_nonpositive_iv_and_adds_percent():
    out = visualize.prep_smile(_frame(), "SPY", ["2026-06-20", "2026-06-27"], "call")
    # call rows for SPY: strikes 100 (IV .25), 110 (IV 0 -> dropped), 90 (IV NaN -> dropped)
    assert out["strike"].tolist() == [100.0]
    assert out["ivPct"].tolist() == [25.0]


def test_prep_smile_filters_by_type():
    out = visualize.prep_smile(_frame(), "SPY", ["2026-06-20"], "put")
    assert out["type"].tolist() == ["put"]
    assert out["ivPct"].tolist() == [30.0]


def test_prep_greek_drops_nan_and_sorts():
    out = visualize.prep_greek(_frame(), "SPY", "2026-06-20", "delta")
    # strikes 90 (delta NaN -> dropped) and 100 (call .55, put -.45) remain, sorted
    assert out["strike"].tolist() == [100.0, 100.0]
    assert set(out["delta"].tolist()) == {0.55, -0.45}


def test_prep_greek_rejects_unknown_greek():
    with pytest.raises(ValueError):
        visualize.prep_greek(_frame(), "SPY", "2026-06-20", "charm")


def test_prep_volume_oi_fills_nan_with_zero():
    out = visualize.prep_volume_oi(_frame(), "SPY", "2026-06-20")
    assert out["volume"].isna().sum() == 0
    assert out["openInterest"].isna().sum() == 0
    # the put row had NaN volume -> 0
    assert 0.0 in out["volume"].tolist()


def test_list_snapshots_newest_first(tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    old.write_text("a\n")
    new.write_text("a\n")
    import os

    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    assert visualize.list_snapshots(tmp_path) == [new, old]


def test_list_snapshots_missing_dir_returns_empty(tmp_path):
    assert visualize.list_snapshots(tmp_path / "nope") == []


# --- Integration against committed sample data ----------------------------- #
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="sample data CSV not present")


@needs_sample
def test_load_sample_and_prep_all_views():
    df = visualize.load_chain(SAMPLE)
    tickers = visualize.tickers_in(df)
    assert "SPY" in tickers

    exps = visualize.expirations_for(df, "SPY")
    assert exps, "expected at least one expiration"

    smile = visualize.prep_smile(df, "SPY", exps[:2], "call")
    assert (smile["ivPct"] > 0).all()

    for greek in GREEK_COLUMNS:
        g = visualize.prep_greek(df, "SPY", exps[0], greek)
        assert g[greek].notna().all()

    voi = visualize.prep_volume_oi(df, "SPY", exps[0])
    assert voi["volume"].notna().all()
    assert voi["openInterest"].notna().all()
