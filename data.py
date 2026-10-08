"""Shared data layer (Yahoo Finance via yfinance) for the dashboard and news emailer."""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS_FILE = Path(__file__).parent / "tickers.txt"


def load_tickers() -> list[str]:
    lines = TICKERS_FILE.read_text(encoding="utf-8-sig").splitlines()
    return [l.strip().upper() for l in lines if l.strip() and not l.startswith("#")]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(v) else v


def _div(a, b):
    """a / b, or None when undefined or non-positive denominator."""
    a, b = _num(a), _num(b)
    if a is None or b is None or b <= 0:
        return None
    return a / b


def _est(df: pd.DataFrame | None, period: str, col: str = "avg"):
    try:
        return _num(df.loc[period, col])
    except Exception:
        return None


def _ntm(fy0, fy1, weight_fy0: float | None):
    """Time-weighted blend of current-FY and next-FY estimates."""
    if fy0 is None or fy1 is None or weight_fy0 is None:
        return fy1 if fy1 is not None else None
    return weight_fy0 * fy0 + (1 - weight_fy0) * fy1


def fetch_metrics(ticker: str) -> dict:
    """Valuation and market snapshot for one ticker. Missing data comes back as None."""
    t = yf.Ticker(ticker)
    info = t.info or {}
    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev = _num(info.get("regularMarketPreviousClose"))
    hi, lo = _num(info.get("fiftyTwoWeekHigh")), _num(info.get("fiftyTwoWeekLow"))
    ev = _num(info.get("enterpriseValue"))

    # Fraction of the current fiscal year still ahead, used to build NTM numbers.
    w = None
    nfye = _num(info.get("nextFiscalYearEnd"))
    if nfye:
        days = (datetime.fromtimestamp(nfye, tz=timezone.utc) - datetime.now(timezone.utc)).days
        w = min(max(days / 365, 0.0), 1.0)

    try:
        eps_est, rev_est = t.earnings_estimate, t.revenue_estimate
    except Exception:
        eps_est = rev_est = None

    ntm_eps = _ntm(_est(eps_est, "0y"), _est(eps_est, "+1y"), w)
    ntm_rev = _ntm(_est(rev_est, "0y"), _est(rev_est, "+1y"), w)
    ltm_rev, ltm_ebitda = _num(info.get("totalRevenue")), _num(info.get("ebitda"))
    # Yahoo has no EBITDA consensus: scale LTM EBITDA by consensus revenue growth (constant margin).
    ntm_ebitda = None
    if ltm_ebitda is not None and ltm_rev and ntm_rev:
        ntm_ebitda = ltm_ebitda * ntm_rev / ltm_rev

    target = _num(info.get("targetMeanPrice"))
    debt, cash = _num(info.get("totalDebt")), _num(info.get("totalCash"))
    net_debt = debt - cash if debt is not None and cash is not None else None

    next_earn = None
    try:
        dates = (t.calendar or {}).get("Earnings Date") or []
        next_earn = dates[0] if dates else None
    except Exception:
        pass

    return {
        "Ticker": ticker,
        "Company": info.get("shortName") or info.get("longName"),
        "Price": price,
        "Day %": (price / prev - 1) * 100 if price and prev else None,
        "52W High": hi,
        "52W Low": lo,
        "% from High": (price / hi - 1) * 100 if price and hi else None,
        "% from Low": (price / lo - 1) * 100 if price and lo else None,
        "Mkt Cap ($B)": (_num(info.get("marketCap")) or 0) / 1e9 or None,
        "EV ($B)": ev / 1e9 if ev else None,
        "LTM P/E": _div(price, info.get("trailingEps")),
        "NTM P/E": _div(price, ntm_eps),
        "LTM EV/EBITDA": _div(ev, ltm_ebitda),
        "NTM EV/EBITDA": _div(ev, ntm_ebitda),
        "LTM EPS": _num(info.get("trailingEps")),
        "NTM EPS": ntm_eps,
        "NTM Rev Growth %": (ntm_rev / ltm_rev - 1) * 100 if ntm_rev and ltm_rev else None,
        "EBITDA Margin %": ltm_ebitda / ltm_rev * 100 if ltm_ebitda is not None and ltm_rev else None,
        "Net Debt/EBITDA": _div(net_debt, ltm_ebitda),
        "Target": target,
        "Upside %": (target / price - 1) * 100 if target and price else None,
        "Rating (1=Buy, 5=Sell)": _num(info.get("recommendationMean")),
        "# Analysts": _num(info.get("numberOfAnalystOpinions")),
        "Next Earnings": next_earn,
    }


def fetch_all(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for tk in tickers:
        try:
            rows.append(fetch_metrics(tk))
        except Exception as e:  # keep the table whole if one ticker fails
            rows.append({"Ticker": tk, "Company": f"error: {e}"})
    return pd.DataFrame(rows)


def fetch_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period)


def fetch_news(ticker: str) -> list[dict]:
    """Headlines from Yahoo's RSS feed (yfinance's own news endpoint returns empty)."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "published": parsedate_to_datetime(pub) if pub else None,
        })
    return items
