"""URL discovery for the Scout — let Atlas find its own reading material.

The Scout can already read a URL you hand it. This module lets it *find* the
URLs itself: given a topic ("opening range breakout intraday forex"), it uses
the Anthropic web-search server tool to locate articles that describe concrete,
backtestable strategies, and returns a list of candidate URLs. The Scout then
fetches, extracts, and tests each one through the same ruthless ladder.

Why the server tool: web search runs on Anthropic's infrastructure, so it works
from the user's laptop with just an ANTHROPIC_API_KEY — no scraping stack, no
search-engine API key, and it is unaffected by any local network policy. It
imports the SDK lazily so the portable core never depends on it.

Honesty: discovery only *finds candidates*. It asserts nothing about whether a
strategy works. Every discovered idea still has to survive the validation ladder
on real data — the same bar every hand-authored hypothesis clears. The searcher
is injectable so the discovery→scout→test pipeline is testable without a live
API call.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List

_SYSTEM = (
    "You are a research librarian for a quantitative trading lab. You find "
    "public articles that describe CONCRETE, RULE-BASED, backtestable trading "
    "strategies — ones that state entries, exits, indicators, and risk in "
    "specific enough terms that a backtester could implement them. You avoid "
    "vague 'mindset' pieces, paywalled stubs, and pure product ads. You never "
    "claim a strategy is profitable; a separate system decides that."
)

_PROMPT = """\
Search the web for articles describing concrete, backtestable trading strategies
about: %s

Prefer sources that spell out specific rules (indicators, periods, entry/exit,
stop, target). Find up to %d good ones.

After searching, return STRICT JSON only — no prose — as an array:
[{"url": "...", "title": "...", "why": "one line on what rule set it describes"}]
"""

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def _http_only(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        u = u.strip().rstrip(".,)")
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def urls_from_message(msg) -> List[str]:
    """Pull candidate URLs from a completed Anthropic message.

    Two sources, merged: (1) a JSON array in the model's final text, and
    (2) the raw web_search_tool_result blocks (reliable even if the model's
    text isn't clean JSON). JSON-declared URLs come first (they're the model's
    curated picks), then any remaining search-result URLs.
    """
    text_parts, result_urls = [], []
    for block in getattr(msg, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "web_search_tool_result":
            for item in (getattr(block, "content", None) or []):
                u = getattr(item, "url", None)
                if u:
                    result_urls.append(u)
    text = "\n".join(text_parts)

    json_urls: List[str] = []
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict) and d.get("url"):
                        json_urls.append(d["url"])
                    elif isinstance(d, str):
                        json_urls.append(d)
        except json.JSONDecodeError:
            pass
    if not json_urls:                       # fall back to any URL in the prose
        json_urls = _URL_RE.findall(text)

    return _http_only(json_urls + result_urls)


def anthropic_searcher(model: str = "claude-opus-5", max_searches: int = 5,
                       max_tokens: int = 4096) -> Callable[[str, int], List[str]]:
    """Return a ``searcher(query, max_results) -> [url, ...]`` backed by the
    Anthropic web-search server tool. Requires the ``anthropic`` package and an
    ANTHROPIC_API_KEY. Raises on any failure so callers can degrade gracefully.
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic package not installed — run `pip install anthropic` and "
            "set ANTHROPIC_API_KEY to use web-search discovery.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set — web-search discovery "
                           "needs it.")

    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": max_searches}]

    def searcher(query: str, max_results: int = 5) -> List[str]:
        messages = [{"role": "user",
                     "content": _PROMPT % (query, max_results)}]
        resp = client.messages.create(model=model, max_tokens=max_tokens,
                                       system=_SYSTEM, tools=tools,
                                       messages=messages)
        # server-tool turns can pause; resume by re-sending with the partial turn
        restarts = 0
        while getattr(resp, "stop_reason", None) == "pause_turn" and restarts < 5:
            messages.append({"role": "assistant", "content": resp.content})
            resp = client.messages.create(model=model, max_tokens=max_tokens,
                                           system=_SYSTEM, tools=tools,
                                           messages=messages)
            restarts += 1
        return urls_from_message(resp)[:max_results]

    return searcher
