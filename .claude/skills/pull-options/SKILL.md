---
name: pull-options
description: Fetch a fresh option-chain snapshot (with Greeks) for one or more tickers using pull_options.py. Use when the user wants to pull/refresh options data for given symbols.
disable-model-invocation: true
---

Run the options puller through the project venv. Arguments are the ticker symbols (and/or flags) the user provided: `$ARGUMENTS`

Steps:

1. Ensure the venv exists. If `./venv/bin/python` is missing, set it up first:
   `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`

2. Run the puller:
   ```bash
   ./venv/bin/python pull_options.py $ARGUMENTS
   ```
   - If the user gave no tickers, ask which symbols they want (or point them at `--file tickers.txt`).
   - Common flags: `--file <path>` (tickers from a file), `--out-dir <dir>` (default `data/`),
     `--combined` (also write one combined CSV across all tickers).

3. Report the result: which CSVs were written (path + row count from the script output) and any
   tickers that failed. Remember the script exits non-zero only if *every* ticker fails, so a
   non-zero exit with some successes is unexpected — surface it.
