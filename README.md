# options-tracker

Pull the current options chain for one or more tickers and save it as CSV.

Data comes from [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance,
no API key required). For each ticker, **all** available expirations are fetched
(calls + puts) and written to one timestamped CSV per ticker.

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Usage

```bash
# Single ticker
./venv/bin/python pull_options.py AAPL

# Multiple tickers
./venv/bin/python pull_options.py AAPL MSFT NVDA

# From a file (one ticker per line, '#' comments allowed)
./venv/bin/python pull_options.py --file tickers.txt

# Custom output directory
./venv/bin/python pull_options.py AAPL --out-dir snapshots

# Also write a single combined CSV across all tickers
./venv/bin/python pull_options.py AAPL MSFT --combined
```

Output is written to `./data` by default, e.g. `data/AAPL_2026-06-13.csv`.

## CSV columns

Each row is one option contract. Lead columns:

| column     | meaning                                  |
|------------|------------------------------------------|
| ticker     | underlying symbol                        |
| snapshot   | ISO timestamp of the run                 |
| expiration | contract expiration date (`YYYY-MM-DD`)  |
| type       | `call` or `put`                          |

followed by the native yfinance fields: `contractSymbol, strike, lastPrice, bid,
ask, change, percentChange, volume, openInterest, impliedVolatility, inTheMoney,
contractSize, currency`, etc.

### Greeks

Each row also carries the option Greeks, computed from the Black-Scholes-Merton
model (yfinance does not provide them). Implied volatility comes from yfinance, the
risk-free rate is auto-fetched from the 13-week US T-bill (`^IRX`) once per run, and
the dividend yield is fetched per ticker.

| column          | meaning                                              |
|-----------------|------------------------------------------------------|
| delta           | ∂price/∂underlying (per $1 move)                     |
| gamma           | ∂delta/∂underlying (per $1 move)                     |
| theta           | time decay, **per calendar day**                     |
| vega            | sensitivity to IV, **per 1% change** in volatility   |
| rho             | sensitivity to rates, **per 1% change** in the rate  |
| underlyingPrice | spot price used in the calculation                   |
| timeToExpiry    | years to expiration (calendar days / 365)            |

Greeks are left blank for contracts where they aren't well defined (expired or
same-day, zero/missing implied volatility, or missing spot price).

## Notes

yfinance uses an unofficial Yahoo endpoint, so occasional rate-limiting or schema
changes are possible. One bad ticker or expiration won't abort the run — errors are
logged and the script continues. The script exits non-zero only if every ticker fails.
