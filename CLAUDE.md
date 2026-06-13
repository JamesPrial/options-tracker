# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI that pulls option chains from Yahoo Finance (via `yfinance`) and computes
Black-Scholes-Merton Greeks. Single module: `pull_options.py` (CLI/fetch) + `greeks.py`
(Greeks math) + `test_greeks.py`.

## Commands

Always use the project venv — system Python lacks the dependencies.

```bash
# Setup (first time)
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# Tests
./venv/bin/python -m pytest test_greeks.py -v

# Lint / format
./venv/bin/ruff check .          # lint
./venv/bin/ruff format .         # format

# Run a single test
./venv/bin/python -m pytest test_greeks.py -k 'test_name'

# Pull a snapshot
./venv/bin/python pull_options.py AAPL MSFT --combined
```

## Conventions & gotchas

- Commit directly to `main` (solo project, no PR flow).
- `yfinance` uses an **unofficial** Yahoo endpoint — expect occasional rate-limiting and
  schema drift across versions. `get_dividend_yield` already normalizes a known scale
  inconsistency (fraction vs. percent); watch for similar quirks.
- **One bad ticker/expiration must never abort the run.** Errors are logged and the loop
  continues; the script exits non-zero only if *every* ticker fails. Preserve this — the
  `except Exception  # noqa: BLE001` blocks are intentional, not lazy.
- On a Greeks-computation failure, the raw chain is still written with empty Greek columns.
- Greeks are NaN/blank when undefined: expired/same-day (T<=0), zero/missing implied
  volatility, or missing spot price.
- Risk-free rate is fetched once per run from `^IRX` (13-week T-bill), falling back to 0.04.
- `REQUEST_DELAY_SECONDS = 0.5` throttles expiration requests — keep the delay to stay
  gentle on Yahoo's endpoint.
- Output: one timestamped CSV per ticker, `data/{SYMBOL}_{YYYY-MM-DD_HHMMSS}.csv`; lead
  columns (`ticker, snapshot, expiration, type`) come first, native yfinance fields after.
