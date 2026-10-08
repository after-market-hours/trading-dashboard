"""Send the scheduled news digest (8:00, 12:00, 15:30 ET) for the tickers in tickers.txt.

Usage:
  python news_email.py              # send only if now is within a slot window (used by cron)
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
SLOTS = [(time(8, 0), "Premarket"), (time(12, 0), "Midday"), (time(15, 30), "Pre-close")]
GRACE = timedelta(minutes=45)  # GitHub cron can start late; send if within this window after a slot


def hm(dt: datetime) -> str:
    """12-hour time without a leading zero (portable; %-I is not supported on Windows)."""
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def current_slot(now: datetime):
    """Return (slot_start, label) if `now` is within GRACE after a slot on a weekday, else None."""
    if now.weekday() >= 5:
        return None
    for t, label in SLOTS:
        start = datetime.combine(now.date(), t, tzinfo=ET)
        if start <= now < start + GRACE:
            return start, label
    return None


def previous_slot(start: datetime) -> datetime:
    """Start of the slot before `start`, skipping weekends."""
    idx = [t for t, _ in SLOTS].index(start.timetz().replace(tzinfo=None))
    if idx > 0:
        return datetime.combine(start.date(), SLOTS[idx - 1][0], tzinfo=ET)
    d = start.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, SLOTS[-1][0], tzinfo=ET)


def build_email(slot_start: datetime, label: str, since: datetime) -> tuple[str, str]:
    subject = f"[{label} {hm(slot_start)} ET] Equities news - {slot_start:%b %d}"
    parts = [
        f"<h2>{html.escape(label)} news - {slot_start:%a %b %d}, {hm(slot_start)} ET</h2>",
        f"<p style='color:#666'>Headlines published since {since:%a} {hm(since)} ET. Source: Yahoo Finance.</p>",
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
    slot = current_slot(now)
    if slot is None:
        if not (args.force or args.dry_run):
            print(f"{now:%a %H:%M} ET is outside every slot window; skipping.")
            return 0
        # Forced run: use the most recent slot of today, or the next-closest for labelling.
        label_t, label = min(SLOTS, key=lambda s: abs(datetime.combine(now.date(), s[0], tzinfo=ET) - now))
        slot = (datetime.combine(now.date(), label_t, tzinfo=ET), label)
    start, label = slot
    since = previous_slot(start)
    subject, body = build_email(start, label, since)
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
