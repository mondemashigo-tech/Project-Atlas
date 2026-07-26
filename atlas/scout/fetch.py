"""Fetch source material for the Scout. Web via urllib (no heavy deps), or a
local file. HTML is reduced to readable text (scripts/styles/tags stripped)."""
from __future__ import annotations

import os
import re
import urllib.request

_UA = "Mozilla/5.0 (Atlas Scout)"


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _h
    text = _h.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="ignore")
    return html_to_text(raw) if ("<html" in raw.lower() or "<body" in raw.lower()
                                 or url.lower().endswith((".html", "/"))) else raw


def fetch_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    if path.lower().endswith((".html", ".htm")):
        return html_to_text(text)
    return text


def fetch(source: str) -> str:
    if source.startswith(("http://", "https://")):
        return fetch_url(source)
    if os.path.exists(source):
        return fetch_file(source)
    return source            # treat as raw text
