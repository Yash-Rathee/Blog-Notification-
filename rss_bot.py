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
import re
import html as htmllib

# ===== CONFIG =====
RSS_URL = "https://defence.in/forums/news/index.rss"
STATE_FILE = "seen_items.json"
SITE_BASE = "https://defence.in"  # used to fix relative image URLs
# ==================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables.")
    sys.exit(1)

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
TIMEOUT = 15

# ------------------ state helpers ------------------
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

# ------------------ id helper ------------------
def make_item_id(entry):
    # Prefer guid/id/link; fallback to hash of title+published+summary
    if entry.get("id"):
        return entry.get("id")
    if entry.get("guid"):
        return entry.get("guid")
    if entry.get("link"):
        return entry.get("link")
    s = (entry.get("title","") + "|" + entry.get("published","") + "|" + entry.get("summary","")).encode("utf-8")
    return hashlib.sha256(s).hexdigest()

# ------------------ HTML/text helpers ------------------
IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', flags=re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')

def escape_html(s: str) -> str:
    if s is None:
        return ""
    # minimal escaping for Telegram HTML parse_mode
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))

def strip_tags(text: str) -> str:
    if not text:
        return ""
    # unescape entities first (converts &#039; etc.)
    txt = htmllib.unescape(text)
    # remove all tags
    txt = TAG_RE.sub('', txt)
    # collapse whitespace
    txt = " ".join(txt.split())
    return txt.strip()

def fix_image_url(url: str) -> str:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return SITE_BASE.rstrip("/") + url
    # if missing scheme but like "images/..." treat as relative
    if not re.match(r'^https?://', url, flags=re.IGNORECASE):
        return SITE_BASE.rstrip("/") + "/" + url.lstrip("/")
    return url

# ------------------ image extraction ------------------
def extract_first_image(entry):
    # Check common feed fields that may contain media
    for key in ("media_content", "media_thumbnail", "media", "image", "enclosures"):
        val = entry.get(key)
        if not val:
            continue
        try:
            # media_content or enclosures often a list
            if isinstance(val, list):
                for item in val:
                    # item may be dict with 'url' or 'href'
                    if isinstance(item, dict):
                        for candidate_key in ("url", "href", "value"):
                            if item.get(candidate_key):
                                return fix_image_url(item.get(candidate_key))
                    # item might be a string (URL)
                    if isinstance(item, str) and item:
                        return fix_image_url(item)
            elif isinstance(val, dict):
                # dict with url
                for candidate_key in ("url", "href", "value"):
                    if val.get(candidate_key):
                        return fix_image_url(val.get(candidate_key))
            elif isinstance(val, str) and val:
                return fix_image_url(val)
        except Exception:
            pass

    # Fallback: search in summary/description/content for first <img src="...">
    for text_field in ("summary", "description", "content"):
        text = entry.get(text_field)
        if not text:
            continue
        # normalize to string
        if isinstance(text, list):
            text = " ".join([str(x) for x in text])
        elif isinstance(text, dict):
            text = text.get("value", "") if isinstance(text, dict) else str(text)
        if not text:
            continue
        m = IMG_SRC_RE.search(text)
        if m:
            return fix_image_url(m.group(1))
    return None

# ------------------ caption builder ------------------
def build_caption(entry, max_summary_len=600):
    # Title (bold), cleaned summary (no tags), and link
    title = entry.get("title", "No title") or "No title"
    summary = entry.get("summary") or entry.get("description") or ""
    summary_text = strip_tags(summary)
    if summary_text and len(summary_text) > max_summary_len:
        summary_text = summary_text[:max_summary_len-3].rstrip() + "..."
    link = entry.get("link", "") or ""

    parts = []
    parts.append(f"<b>{escape_html(title)}</b>")
    if summary_text:
        parts.append(escape_html(summary_text))
    if link:
        parts.append(f"🔗 <a href=\"{escape_html(link)}\">Open post</a>")
    caption = "\n\n".join(parts)
    # Telegram photo caption limit ~1024, keep safe margin
    if len(caption) > 900:
        caption = caption[:900].rstrip() + "..."
    return caption

# ------------------ telegram send helpers ------------------
def send_telegram_message_plain(text):
    url = TELEGRAM_API_BASE + "/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": False}
    try:
        r = requests.post(url, data=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return True, r.json()
    except Exception as e:
        return False, str(e)

def send_telegram_photo(photo_url, caption):
    url = TELEGRAM_API_BASE + "/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=payload, timeout=TIMEOUT)
        if r.status_code == 200:
            return True, r.json()
        # log response and return failure info for fallback
        print("Telegram sendPhoto error:", r.status_code, r.text)
        return False, r.text
    except Exception as e:
        return False, str(e)

def send_telegram_entry(entry):
    """
    High-level send:
     - If image exists: try sendPhoto with caption (HTML)
     - If photo fails: fallback to sending plain text message with cleaned text + link
     - If no image: send sendMessage with HTML caption (escaped), fallback to plain text
    """
    img = extract_first_image(entry)
    caption = build_caption(entry)
    link = entry.get("link", "") or ""
    if img:
        ok, resp = send_telegram_photo(img, caption)
        if ok:
            return True, resp
        # fallback: send plain message (title + cleaned summary + link)
        print("Falling back to plain message due to photo/send error.")
        fallback_text = strip_tags(entry.get("title","")) + "\n\n" + strip_tags(entry.get("summary","") or entry.get("description","") or "") + ("\n\n" + link if link else "")
        return send_telegram_message_plain(fallback_text)
    else:
        # try HTML message first
        url = TELEGRAM_API_BASE + "/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML", "disable_web_page_preview": False}
        try:
            r = requests.post(url, data=payload, timeout=TIMEOUT)
            r.raise_for_status()
            return True, r.json()
        except Exception as e:
            print("sendMessage with HTML failed, retrying plain text. Error:", e)
            fallback_text = strip_tags(entry.get("title","")) + "\n\n" + strip_tags(entry.get("summary","") or entry.get("description","") or "") + ("\n\n" + link if link else "")
            return send_telegram_message_plain(fallback_text)

# ------------------ main ------------------
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
        # Print short preview for debugging in Actions logs
        preview = strip_tags(entry.get("title",""))[:300]
        print("Preparing to send:", preview)
        ok, resp = send_telegram_entry(entry)
        timestamp = datetime.utcnow().isoformat() + "Z"
        if ok:
            print(f"[{timestamp}] Sent: {entry.get('title','(no title)')}")
            seen.add(iid)
            any_sent = True
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
