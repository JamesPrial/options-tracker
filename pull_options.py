#!/usr/bin/env python3
"""Pull current options chains for one or more tickers and save them as CSV.

Data source: yfinance (unofficial Yahoo Finance API; no API key required).
For each ticker, every available expiration is fetched (calls + puts) and
written to one timestamped CSV per ticker, e.g. data/AAPL_2026-06-13_150752.csv.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

import greeks

# Columns we want to lead each row, followed by the native yfinance columns.
LEAD_COLUMNS = ["ticker", "snapshot", "expiration", "type"]

# Pause between expiration requests to be gentle on Yahoo's endpoint.
REQUEST_DELAY_SECONDS = 0.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull current options chains and save them as CSV (via yfinance).",
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        help="One or more ticker symbols, e.g. AAPL MSFT NVDA.",
    )
    parser.add_argument(
        "--file",
        dest="file",
        help="Path to a file of tickers, one per line ('#' comments allowed).",
    )
    parser.add_argument(
        "--out-dir",
        dest="out_dir",
        default="data",
        help="Directory to write CSVs into (default: ./data).",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help="Also write a single combined CSV of all tickers for this run.",
    )
    return parser.parse_args(argv)


def read_tickers_from_file(path: str) -> list[str]:
    lines = Path(path).read_text().splitlines()
    out: list[str] = []
    for line in lines:
        # Strip inline/full-line comments and surrounding whitespace.
        symbol = line.split("#", 1)[0].strip()
        if symbol:
            out.append(symbol)
    return out


def normalize_tickers(raw: list[str]) -> list[str]:
    """Upper-case, strip, dedupe while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        sym = item.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            result.append(sym)
    return result


def get_spot_price(ticker: yf.Ticker) -> float:
    """Return the underlying's latest price, or NaN if unavailable."""
    try:
        price = float(ticker.fast_info["last_price"])
        if price > 0:
            return price
    except Exception:  # noqa: BLE001 - fall back to history
        pass
    try:
        hist = ticker.history(period="1d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].dropna().iloc[-1])
    except Exception:  # noqa: BLE001 - give up, return NaN
        pass
    return float("nan")


def get_dividend_yield(ticker: yf.Ticker) -> float:
    """Return the dividend yield as a fraction (e.g. 0.005 for 0.5%), or 0.0.

    yfinance's ``dividendYield`` scale has varied across versions: some report a
    fraction (0.005), others a percent (0.5). Normalize: values > 1 are treated
    as percentages. None/missing -> 0.0 (treat as non-dividend-paying).
    """
    try:
        raw = ticker.info.get("dividendYield")
    except Exception:  # noqa: BLE001 - no info available
        return 0.0
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    # A "yield" above 1.0 is almost certainly expressed in percent.
    return value / 100.0 if value > 1.0 else value


def fetch_ticker_chain(symbol: str, snapshot: str, r: float) -> pd.DataFrame | None:
    """Return a DataFrame of all expirations (calls + puts) for one ticker.

    Includes computed Greeks (delta/gamma/theta/vega/rho). ``r`` is the
    risk-free rate (fraction). Returns None if the ticker has no listed options.
    Raises on hard failures so the caller can record the error and continue with
    the next ticker.
    """
    ticker = yf.Ticker(symbol)
    expirations = ticker.options or []
    if not expirations:
        print(f"[{symbol}] no options listed — skipping.")
        return None

    frames: list[pd.DataFrame] = []
    for exp in expirations:
        try:
            chain = ticker.option_chain(exp)
        except Exception as err:  # noqa: BLE001 - keep going on a bad expiry
            print(f"[{symbol}] failed to fetch expiration {exp}: {err}")
            continue

        for option_type, df in (("call", chain.calls), ("put", chain.puts)):
            if df is None or df.empty:
                continue
            df = df.copy()
            df["type"] = option_type
            df["expiration"] = exp
            df["ticker"] = symbol
            df["snapshot"] = snapshot
            frames.append(df)

        time.sleep(REQUEST_DELAY_SECONDS)

    if not frames:
        print(f"[{symbol}] no contract rows returned — skipping.")
        return None

    combined = pd.concat(frames, ignore_index=True)

    # Compute the Greeks. Never let this abort the ticker: on failure, leave the
    # Greek columns empty and write the raw chain anyway.
    try:
        snapshot_date = datetime.fromisoformat(snapshot).date()
        exp_dates = pd.to_datetime(combined["expiration"]).dt.date
        combined["timeToExpiry"] = [
            (exp - snapshot_date).days / greeks.DAYS_PER_YEAR for exp in exp_dates
        ]
        spot = get_spot_price(ticker)
        div_yield = get_dividend_yield(ticker)
        combined = greeks.compute_greeks(combined, spot, r, div_yield)
    except Exception as err:  # noqa: BLE001 - keep the raw chain on Greeks failure
        print(f"[{symbol}] warning: could not compute Greeks: {err}")
        for col in (*greeks.GREEK_COLUMNS, *greeks.TRACE_COLUMNS):
            if col not in combined.columns:
                combined[col] = pd.NA

    # Put our lead columns first, then everything else in its existing order.
    rest = [c for c in combined.columns if c not in LEAD_COLUMNS]
    return combined[LEAD_COLUMNS + rest]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    raw_tickers = list(args.tickers)
    if args.file:
        raw_tickers.extend(read_tickers_from_file(args.file))
    tickers = normalize_tickers(raw_tickers)

    if not tickers:
        print("error: no tickers provided (pass them as arguments or via --file).",
              file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_time = datetime.now()
    snapshot = run_time.isoformat(timespec="seconds")
    stamp = run_time.strftime("%Y-%m-%d_%H%M%S")

    # Fetch the risk-free rate once for the whole run (used for the Greeks).
    risk_free_rate = greeks.get_risk_free_rate()
    print(f"risk-free rate (13-week T-bill): {risk_free_rate:.4%}")

    all_frames: list[pd.DataFrame] = []
    succeeded = 0
    failed = 0

    for symbol in tickers:
        try:
            df = fetch_ticker_chain(symbol, snapshot, risk_free_rate)
        except Exception as err:  # noqa: BLE001 - one bad ticker mustn't abort the run
            print(f"[{symbol}] error: {err}")
            failed += 1
            continue

        if df is None:
            failed += 1
            continue

        out_path = out_dir / f"{symbol}_{stamp}.csv"
        df.to_csv(out_path, index=False)
        print(f"[{symbol}] wrote {len(df)} rows -> {out_path}")
        succeeded += 1
        if args.combined:
            all_frames.append(df)

    if args.combined and all_frames:
        combined_path = out_dir / f"options_{stamp}.csv"
        pd.concat(all_frames, ignore_index=True).to_csv(combined_path, index=False)
        print(f"[combined] wrote {combined_path}")

    print(f"done: {succeeded} succeeded, {failed} failed, {len(tickers)} requested.")
    # Non-zero exit only if everything failed.
    return 1 if succeeded == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
