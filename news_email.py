"""Send the daily 7:00 ET news digest (headlines since the prior market close) for the tickers in tickers.txt.

Usage:
  python news_email.py              # send only if now is within the 7:00 ET window (used by cron)
  python news_email.py --force      # send now, regardless of time
  python news_email.py --dry-run    # build the email, write digest_preview.html, don't send

Env for sending: GMAIL_USER, GMAIL_APP_PASSWORD; optional EMAIL_TO (default: GMAIL_USER).
"""
from __future__ import annotations

import argparse
import html
import os
import smtplib
import sys
from datetime import datetime, time, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import data

ET = ZoneInfo("America/New_York")
SEND_AT = time(7, 0)
CLOSE = time(16, 0)  # market close; the digest covers everything since the previous weekday's close
GRACE = timedelta(minutes=55)  # GitHub cron can start late; send if within this window after SEND_AT


def hm(dt: datetime) -> str:
    """12-hour time without a leading zero (portable; %-I is not supported on Windows)."""
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def in_window(now: datetime) -> bool:
    """True if `now` is within GRACE after SEND_AT on a weekday."""
    if now.weekday() >= 5:
        return False
    start = datetime.combine(now.date(), SEND_AT, tzinfo=ET)
    return start <= now < start + GRACE


def previous_close(start: datetime) -> datetime:
    """Previous weekday's 4:00 PM ET close (Monday looks back to Friday)."""
    d = start.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, CLOSE, tzinfo=ET)


def build_email(slot_start: datetime, since: datetime) -> tuple[str, str]:
    subject = f"[Morning] Equities news - {slot_start:%a %b %d}"
    parts = [
        f"<h2>Morning news - {slot_start:%a %b %d}, {hm(slot_start)} ET</h2>",
        f"<p style='color:#666'>Headlines published since the {since:%a %b %d} {hm(since)} ET close. Source: Yahoo Finance.</p>",
    ]
    for tk in data.load_tickers():
        parts.append(f"<h3 style='margin-bottom:2px'>{tk}</h3>")
        try:
            m = data.fetch_metrics(tk)
            bits = []
            if m.get("Price") is not None:
                bits.append(f"${m['Price']:,.2f}")
            if m.get("Day %") is not None:
                color = "#1a9850" if m["Day %"] >= 0 else "#d73027"
                bits.append(f"<span style='color:{color}'>{m['Day %']:+.1f}%</span>")
            if m.get("% from High") is not None:
                bits.append(f"{m['% from High']:+.1f}% vs 52W high")
            ne = m.get("Next Earnings")
            if ne is not None and 0 <= (ne - slot_start.date()).days <= 14:
                bits.append(f"<b>earnings {ne:%b %d}</b>")
            parts.append(f"<div style='color:#444'>{m.get('Company') or ''} &middot; {' &middot; '.join(bits)}</div>")
        except Exception as e:
            parts.append(f"<div style='color:#999'>quote unavailable ({html.escape(str(e))})</div>")
        try:
            news = [n for n in data.fetch_news(tk) if n["published"] and n["published"] >= since]
        except Exception as e:
            parts.append(f"<div style='color:#999'>news unavailable ({html.escape(str(e))})</div>")
            continue
        if not news:
            parts.append("<div style='color:#999'>No new headlines.</div>")
            continue
        parts.append("<ul style='margin-top:4px'>")
        for n in sorted(news, key=lambda n: n["published"], reverse=True):
            when = n["published"].astimezone(ET)
            parts.append(
                f"<li><a href='{html.escape(n['link'])}'>{html.escape(n['title'])}</a> "
                f"<span style='color:#999'>{when:%a} {hm(when)}</span></li>"
            )
        parts.append("</ul>")
    body = "<html><body style='font-family:Arial,sans-serif;max-width:720px'>" + "".join(parts) + "</body></html>"
    return subject, body


def send(subject: str, body: str) -> None:
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("EMAIL_TO", user)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(ET)
    if not (args.force or args.dry_run) and not in_window(now):
        print(f"{now:%a %H:%M} ET is outside the 7:00 ET window; skipping.")
        return 0
    start = datetime.combine(now.date(), SEND_AT, tzinfo=ET)
    since = previous_close(start)
    subject, body = build_email(start, since)
    if args.dry_run:
        with open("digest_preview.html", "w", encoding="utf-8") as f:
            f.write(body)
        print(f"Dry run: {subject}\nWrote digest_preview.html")
        return 0
    send(subject, body)
    print(f"Sent: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
