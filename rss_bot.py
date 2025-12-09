#!/usr/bin/env python3
"""
rss_bot.py

One-shot RSS -> Telegram notifier for GitHub Actions.
Reads/writes seen_items.json in the repo working directory.
Environment variables required:
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
Config:
  - RSS_URL : the feed to monitor
"""

import os
import json
import time
from datetime import datetime
import feedparser
import requests
import hashlib
import sys

# ===== CONFIG =====
RSS_URL = "https://defence.in/forums/news/index.rss"
STATE_FILE = "seen_items.json"
# ==================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables.")
    sys.exit(1)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TIMEOUT = 15

def load_seen():
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            arr = json.load(f)
            return set(arr)
    except Exception as e:
        print("Failed to load seen state:", e)
        return set()

def save_seen(seen_set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)

def make_item_id(entry):
    # Prefer guid/id/link; fallback to hash of title+published
    if entry.get("id"):
        return entry.get("id")
    if entry.get("guid"):
        return entry.get("guid")
    if entry.get("link"):
        return entry.get("link")
    # last resort: hash of title+summary+published
    s = (entry.get("title","") + "|" + entry.get("published","") + "|" + entry.get("summary","")).encode("utf-8")
    return hashlib.sha256(s).hexdigest()

def make_message(entry):
    title = entry.get("title", "No title")
    link = entry.get("link", "")
    published = entry.get("published", "") or entry.get("updated", "")
    summary = entry.get("summary", "") or entry.get("description", "")
    if summary:
        summary = " ".join(summary.split())
        if len(summary) > 300:
            summary = summary[:297] + "..."
    parts = []
    parts.append(f"<b>{escape_html(title)}</b>")
    if published:
        parts.append(f"<i>{escape_html(published)}</i>")
    if summary:
        parts.append(escape_html(summary))
    if link:
        parts.append(f"🔗 <a href=\"{escape_html(link)}\">Open post</a>")
    return "\n\n".join(parts)

def escape_html(s: str) -> str:
    # minimal html escaping for Telegram HTML mode
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))

def send_telegram(text):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        r = requests.post(TELEGRAM_API, data=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return True, r.json()
    except Exception as e:
        return False, str(e)

def main():
    print("Starting RSS check:", RSS_URL)
    seen = load_seen()
    print(f"Loaded {len(seen)} seen items")
    feed = feedparser.parse(RSS_URL)
    if getattr(feed, "bozo", False):
        print("Feed parse warning:", getattr(feed, "bozo_exception", "unknown"))
    entries = feed.entries or []
    new_entries = []
    for e in entries:
        iid = make_item_id(e)
        if iid not in seen:
            new_entries.append((iid, e))
    # sort new entries by published_parsed if available
    def sort_key(x):
        e = x[1]
        return e.get("published_parsed") or e.get("updated_parsed") or time.gmtime(0)
    new_entries.sort(key=sort_key)
    print(f"Found {len(new_entries)} new items")
    any_sent = False
    for iid, entry in new_entries:
        msg = make_message(entry)
        ok, resp = send_telegram(msg)
        timestamp = datetime.utcnow().isoformat() + "Z"
        if ok:
            print(f"[{timestamp}] Sent: {entry.get('title','(no title)')}")
            seen.add(iid)
            any_sent = True
            # small sleep to avoid hitting rate limits if many items
            time.sleep(1)
        else:
            print(f"[{timestamp}] Failed to send: {entry.get('title','(no title)')} -> {resp}")
            # Do NOT mark as seen if send failed; break to retry next run
            break
    if any_sent:
        save_seen(seen)
        print("Saved updated seen_items.")
    else:
        print("No messages sent; seen state unchanged.")
    print("Done.")

if __name__ == "__main__":
    main()
