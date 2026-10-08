# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Fundamental-equities dashboard (Streamlit) plus scheduled news-digest emails, for the tickers in `tickers.txt`. All data is from Yahoo Finance via `yfinance` (free, unofficial).

## Commands

Windows; Python 3.12 lives in `.venv` (not on PATH globally).

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py                 # dashboard
.venv\Scripts\python.exe news_email.py --dry-run                 # builds digest, writes digest_preview.html, sends nothing
.venv\Scripts\python.exe news_email.py --force                   # actually sends (needs GMAIL_USER, GMAIL_APP_PASSWORD env)
gh workflow run news.yml -f force=true                           # send a test digest from GitHub Actions
```

No test suite or linter is configured.

## Architecture

- `tickers.txt` is the single source of truth for the watchlist; both the app and the emailer read it via `data.load_tickers()`. Adding a name is a one-line change.
- `data.py` is the shared data layer. `fetch_metrics()` builds one row of valuation metrics; `fetch_news()` reads Yahoo's RSS feed because `yfinance`'s own `Ticker.news` returns empty.
- `app.py` renders a metrics table plus a per-ticker detail view; it only calls `data.py` (cached 15 min).
- `news_email.py` builds and sends the HTML digest. `.github/workflows/news.yml` runs it on cron.

## Non-obvious details

- **NTM metrics are derived.** NTM EPS/revenue = time-weighted blend of Yahoo's FY0 and FY+1 consensus (weight from `nextFiscalYearEnd`). Yahoo has no EBITDA consensus, so NTM EBITDA = LTM EBITDA scaled by consensus NTM revenue growth (constant margin). This is an approximation and is labelled as such in the UI.
- **Data distortions are expected**: spin-off names (HON) mix LTM actuals including divested units with post-spin consensus; recent IPOs (MAIR, INIO, DPC) have thin history and few analysts. Non-positive EPS/EBITDA yield N/A multiples (`_div`).
- **Scheduling.** GitHub cron is UTC and ignores DST, so each ET slot (8:00, 12:00, 15:30) has two UTC crons; `news_email.py` sends only if the ET time is within `GRACE` (55 min) after a slot on a weekday, otherwise exits 0. `workflow_dispatch` with `force` bypasses this.
- **Digest dedup is stateless**: each email shows headlines published since the previous slot (Monday 8:00 looks back to Friday 15:30), so no state is persisted between runs.
- Secrets `GMAIL_USER` and `GMAIL_APP_PASSWORD` are GitHub Actions secrets; the recipient is set in the workflow (`EMAIL_TO`).
- Windows portability: `strftime` `%-I` is unsupported on Windows, so use `hm()` in `news_email.py`. When writing text files from PowerShell 5.1 use UTF-8 *without* BOM (a BOM once broke `tickers.txt` parsing); `load_tickers` reads with `utf-8-sig` as a safeguard.
- Pushing from this machine: git has no credential helper, so use `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`. Git identity is set repo-locally.
