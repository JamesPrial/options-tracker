#!/usr/bin/env python3
"""Interactive Streamlit dashboard for the option-chain snapshots in ``data/``.

Reads the CSVs written by ``pull_options.py`` (no network access) and renders
three trader-oriented views of a single ticker's chain:

- **Volatility smile/skew** — implied volatility vs strike, one curve per expiration.
- **Greeks vs strike** — a chosen Greek (delta/gamma/theta/vega/rho) across strikes.
- **Volume & open interest** — liquidity by strike, calls vs puts.

Run with::

    ./venv/bin/streamlit run visualize.py

The pure data-prep helpers (``list_snapshots``, ``load_chain``, ``prep_smile``,
``prep_greek``, ``prep_volume_oi``) are kept free of Streamlit calls so they can
be unit-tested directly (see ``test_visualize.py``).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from greeks import GREEK_COLUMNS

DEFAULT_DATA_DIR = "data"

# Human-readable units for each Greek, matching greeks.py's broker-style scaling.
GREEK_UNITS = {
    "delta": "per $1 underlying move",
    "gamma": "per $1 underlying move",
    "theta": "per calendar day",
    "vega": "per 1% IV change",
    "rho": "per 1% rate change",
}


# --------------------------------------------------------------------------- #
# Pure data helpers (no Streamlit) — unit-tested.
# --------------------------------------------------------------------------- #
def list_snapshots(data_dir: str | Path = DEFAULT_DATA_DIR) -> list[Path]:
    """Return ``data_dir``'s CSV files, newest first by modification time."""
    directory = Path(data_dir)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_chain(path: str | Path) -> pd.DataFrame:
    """Load one snapshot CSV into a DataFrame (identity columns are strings)."""
    return pd.read_csv(path, dtype={"ticker": "string", "type": "string", "expiration": "string"})


def tickers_in(df: pd.DataFrame) -> list[str]:
    """Unique tickers in a (possibly combined) chain, in first-seen order."""
    return list(dict.fromkeys(df["ticker"].dropna().tolist()))


def expirations_for(df: pd.DataFrame, ticker: str) -> list[str]:
    """Sorted unique expirations available for ``ticker``."""
    rows = df[df["ticker"] == ticker]
    return sorted(rows["expiration"].dropna().unique().tolist())


def spot_price(df: pd.DataFrame, ticker: str) -> float | None:
    """Underlying spot used at snapshot time for ``ticker`` (NaN/missing -> None)."""
    rows = df[df["ticker"] == ticker]
    if rows.empty or "underlyingPrice" not in rows.columns:
        return None
    series = rows["underlyingPrice"].dropna()
    if series.empty:
        return None
    return float(series.iloc[0])


def prep_smile(
    df: pd.DataFrame, ticker: str, expirations: list[str], opt_type: str
) -> pd.DataFrame:
    """Rows for the volatility smile: valid IV only, IV expressed as a percent.

    ``opt_type`` is "call" or "put". Adds an ``ivPct`` column (impliedVolatility * 100)
    and drops rows with non-positive/missing IV. Sorted by strike.
    """
    rows = df[
        (df["ticker"] == ticker) & (df["type"] == opt_type) & (df["expiration"].isin(expirations))
    ].copy()
    iv = pd.to_numeric(rows["impliedVolatility"], errors="coerce")
    rows = rows[iv > 0]
    rows["ivPct"] = pd.to_numeric(rows["impliedVolatility"], errors="coerce") * 100.0
    return rows.sort_values("strike")


def prep_greek(df: pd.DataFrame, ticker: str, expiration: str, greek: str) -> pd.DataFrame:
    """Rows for a Greek-vs-strike plot: drop rows where the Greek is undefined.

    Returns columns ``strike``, ``type``, ``<greek>`` sorted by strike.
    """
    if greek not in GREEK_COLUMNS:
        raise ValueError(f"unknown greek: {greek!r} (expected one of {GREEK_COLUMNS})")
    rows = df[(df["ticker"] == ticker) & (df["expiration"] == expiration)].copy()
    rows[greek] = pd.to_numeric(rows[greek], errors="coerce")
    rows = rows.dropna(subset=[greek])
    return rows[["strike", "type", greek]].sort_values("strike")


def prep_volume_oi(df: pd.DataFrame, ticker: str, expiration: str) -> pd.DataFrame:
    """Rows for the volume/open-interest view: NaN volume/OI treated as 0.

    Returns ``strike``, ``type``, ``volume``, ``openInterest`` sorted by strike.
    """
    rows = df[(df["ticker"] == ticker) & (df["expiration"] == expiration)].copy()
    for col in ("volume", "openInterest"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0)
    return rows[["strike", "type", "volume", "openInterest"]].sort_values("strike")


# --------------------------------------------------------------------------- #
# Plotly figure builders.
# --------------------------------------------------------------------------- #
def _add_spot_line(fig, spot: float | None) -> None:
    if spot is not None:
        fig.add_vline(
            x=spot,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"spot {spot:.2f}",
            annotation_position="top",
        )


def smile_figure(
    df: pd.DataFrame, ticker: str, expirations: list[str], opt_type: str, spot: float | None
):
    import plotly.express as px

    data = prep_smile(df, ticker, expirations, opt_type)
    fig = px.line(
        data,
        x="strike",
        y="ivPct",
        color="expiration",
        markers=True,
        labels={"strike": "Strike", "ivPct": "Implied volatility (%)", "expiration": "Expiration"},
        title=f"{ticker} {opt_type} implied-volatility smile",
    )
    _add_spot_line(fig, spot)
    return fig


def greek_figure(df: pd.DataFrame, ticker: str, expiration: str, greek: str, spot: float | None):
    import plotly.express as px

    data = prep_greek(df, ticker, expiration, greek)
    unit = GREEK_UNITS.get(greek, "")
    fig = px.line(
        data,
        x="strike",
        y=greek,
        color="type",
        markers=True,
        labels={"strike": "Strike", greek: f"{greek} ({unit})", "type": "Type"},
        title=f"{ticker} {greek} vs strike — {expiration}",
    )
    _add_spot_line(fig, spot)
    return fig


def volume_oi_figure(
    df: pd.DataFrame, ticker: str, expiration: str, metric: str, spot: float | None
):
    import plotly.express as px

    data = prep_volume_oi(df, ticker, expiration)
    label = "Volume" if metric == "volume" else "Open interest"
    fig = px.bar(
        data,
        x="strike",
        y=metric,
        color="type",
        barmode="group",
        labels={"strike": "Strike", metric: label, "type": "Type"},
        title=f"{ticker} {label.lower()} by strike — {expiration}",
    )
    _add_spot_line(fig, spot)
    return fig


# --------------------------------------------------------------------------- #
# Streamlit UI.
# --------------------------------------------------------------------------- #
def main() -> None:
    import streamlit as st

    # Cache CSV loads so flipping views/expirations doesn't re-read from disk.
    load_cached = st.cache_data(load_chain)

    st.set_page_config(page_title="Options Visualizer", layout="wide")
    st.title("📈 Options chain visualizer")

    snapshots = list_snapshots(DEFAULT_DATA_DIR)
    if not snapshots:
        st.warning(
            f"No CSV files found in ./{DEFAULT_DATA_DIR}. "
            "Pull a snapshot first with pull_options.py."
        )
        return

    with st.sidebar:
        st.header("Data")
        file_choice = st.selectbox(
            "Snapshot file",
            snapshots,
            format_func=lambda p: p.name,
        )
        df = load_cached(str(file_choice))

        tickers = tickers_in(df)
        ticker = st.selectbox("Ticker", tickers)

        snap = df.loc[df["ticker"] == ticker, "snapshot"]
        if not snap.empty:
            st.caption(f"Snapshot: {snap.iloc[0]}")
        spot = spot_price(df, ticker)
        if spot is not None:
            st.metric("Spot (underlying)", f"{spot:.2f}")

        st.header("View")
        view = st.radio(
            "Chart",
            ["Volatility smile", "Greeks vs strike", "Volume & open interest"],
        )

    all_exps = expirations_for(df, ticker)
    if not all_exps:
        st.warning(f"No expirations found for {ticker}.")
        return

    if view == "Volatility smile":
        col1, col2 = st.columns([3, 1])
        with col2:
            opt_type = st.radio("Type", ["call", "put"], horizontal=True)
            chosen = st.multiselect(
                "Expirations", all_exps, default=all_exps[: min(3, len(all_exps))]
            )
        if not chosen:
            st.info("Select at least one expiration.")
        else:
            with col1:
                st.plotly_chart(
                    smile_figure(df, ticker, chosen, opt_type, spot), use_container_width=True
                )

    elif view == "Greeks vs strike":
        col1, col2 = st.columns([3, 1])
        with col2:
            greek = st.selectbox("Greek", GREEK_COLUMNS)
            exp = st.selectbox("Expiration", all_exps)
            st.caption(GREEK_UNITS.get(greek, ""))
        with col1:
            st.plotly_chart(greek_figure(df, ticker, exp, greek, spot), use_container_width=True)

    else:  # Volume & open interest
        col1, col2 = st.columns([3, 1])
        with col2:
            metric = st.radio("Metric", ["volume", "openInterest"])
            exp = st.selectbox("Expiration", all_exps)
        with col1:
            st.plotly_chart(
                volume_oi_figure(df, ticker, exp, metric, spot), use_container_width=True
            )


if __name__ == "__main__":
    main()
