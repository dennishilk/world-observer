#!/usr/bin/env python3
"""Germany-only German-language media headline observer.

This observer fetches a small set of public German RSS feeds, extracts titles
only, and counts transparent keyword-category matches. It separately aggregates
public-broadcast and private-media source groups using the exact same scoring
function. It does not infer cause, intent, manipulation, or real-world risk.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, Iterable, List, Tuple

OBSERVER = "media-language-germany"

PUBLIC_BROADCAST_SOURCES: List[Dict[str, str]] = [
    {"name": "tagesschau", "url": "https://www.tagesschau.de/xml/rss2"},
    {"name": "zdfheute", "url": "https://www.zdf.de/rss/zdf/nachrichten"},
    {"name": "deutschlandfunk", "url": "https://www.deutschlandfunk.de/nachrichten-100.rss"},
]

PRIVATE_MEDIA_SOURCES: List[Dict[str, str]] = [
    {"name": "spiegel", "url": "https://www.spiegel.de/schlagzeilen/index.rss"},
    {"name": "zeit", "url": "https://newsfeed.zeit.de/index"},
    {"name": "focus", "url": "https://www.focus.de/rss/fol/XML/rss_folnews.xml"},
    {"name": "n-tv", "url": "https://www.n-tv.de/rss"},
]

SOURCE_GROUPS: Dict[str, List[Dict[str, str]]] = {
    "public_broadcast": PUBLIC_BROADCAST_SOURCES,
    "private_media": PRIVATE_MEDIA_SOURCES,
}

# Backward-compatible all-source list for callers/tests that imported SOURCES.
SOURCES: List[Dict[str, str]] = PUBLIC_BROADCAST_SOURCES + PRIVATE_MEDIA_SOURCES

# German headline-only categories. Terms are deliberately simple and auditable.
KEYWORD_CATEGORIES: Dict[str, List[str]] = {
    "climate": ["klima", "klimawandel", "hitze", "duerre", "dürre", "emission", "co2", "flut"],
    "war_security": ["krieg", "angriff", "waffe", "rakete", "militaer", "militär", "sicherheit", "terror"],
    "health": ["gesundheit", "krankheit", "virus", "corona", "pandemie", "klinik", "pflege"],
    "economy": ["wirtschaft", "inflation", "preis", "energie", "arbeitslos", "rezession", "haushalt"],
    "crime": ["kriminalitaet", "kriminalität", "mord", "betrug", "raub", "polizei", "gewalt"],
    "disaster": ["katastrophe", "unwetter", "erdbeben", "brand", "ueberschwemmung", "überschwemmung", "sturm"],
    "political_pressure": ["krise", "streit", "druck", "protest", "ruecktritt", "rücktritt", "skandal"],
    "general_alarm": ["warnung", "alarm", "gefahr", "notfall", "bedrohung", "eskalation", "chaos"],
}

CATEGORY_WEIGHTS: Dict[str, float] = {
    "climate": 1.0,
    "war_security": 1.4,
    "health": 1.0,
    "economy": 0.9,
    "crime": 1.1,
    "disaster": 1.3,
    "political_pressure": 1.0,
    "general_alarm": 1.5,
}

REQUEST_TIMEOUT_S = 8
USER_AGENT = "world-observer/1.0 (+https://github.com/)"


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_text(value: str) -> str:
    value = unescape(value).casefold()
    decomposed = unicodedata.normalize("NFKD", value)
    asciiish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", asciiish).strip()


def parse_rss_titles(xml_text: str) -> List[str]:
    """Return RSS/Atom titles excluding channel/feed titles."""
    root = ET.fromstring(xml_text)
    titles: List[str] = []
    for item in root.findall(".//item"):
        title = item.findtext("title")
        if title and title.strip():
            titles.append(unescape(title.strip()))
    for entry in root.findall(".//{*}entry"):
        title = entry.findtext("{*}title") or entry.findtext("title")
        if title and title.strip():
            titles.append(unescape(title.strip()))
    return titles


def _compile_terms() -> Dict[str, List[Tuple[str, re.Pattern[str]]]]:
    compiled: Dict[str, List[Tuple[str, re.Pattern[str]]]] = {}
    for category, terms in KEYWORD_CATEGORIES.items():
        compiled[category] = []
        for term in terms:
            norm = _normalize_text(term)
            compiled[category].append((norm, re.compile(rf"(?<!\w){re.escape(norm)}\w*")))
    return compiled


COMPILED_TERMS = _compile_terms()


def score_headlines(headlines: Iterable[str]) -> Dict[str, Any]:
    """Score headlines using normalized weighted keyword frequency.

    Formula:
      weighted_hits = sum(category_count[category] * CATEGORY_WEIGHTS[category])
      raw_frequency = weighted_hits / max(1, headline_count)
      fear_index = round(min(100, raw_frequency * 20), 2)

    The factor 20 maps roughly five weighted keyword hits per headline to 100.
    This is a simple language-frequency score, not a causal or sentiment model.
    """
    headline_list = list(headlines)
    category_counts = {category: 0 for category in KEYWORD_CATEGORIES}
    term_counts: Counter[str] = Counter()
    matched_headlines = 0

    for headline in headline_list:
        normalized = _normalize_text(headline)
        matched_this_headline = False
        for category, terms in COMPILED_TERMS.items():
            for term, pattern in terms:
                hits = len(pattern.findall(normalized))
                if hits:
                    category_counts[category] += hits
                    term_counts[term] += hits
                    matched_this_headline = True
        if matched_this_headline:
            matched_headlines += 1

    headline_count = len(headline_list)
    weighted_hits = sum(category_counts[c] * CATEGORY_WEIGHTS.get(c, 1.0) for c in category_counts)
    fear_index = round(min(100.0, (weighted_hits / max(1, headline_count)) * 20.0), 2)
    return {
        "headline_count": headline_count,
        "matched_headline_count": matched_headlines,
        "total_term_hits": int(sum(category_counts.values())),
        "category_counts": category_counts,
        "top_terms": [{"term": term, "count": count} for term, count in term_counts.most_common(15)],
        "fear_index": fear_index,
    }


def _fetch_titles(source: Dict[str, str]) -> Tuple[List[str], str | None]:
    request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = response.read(1_000_000).decode("utf-8", errors="replace")
        return parse_rss_titles(body), None
    except (OSError, urllib.error.URLError, ET.ParseError, UnicodeError) as exc:
        return [], f"{source['name']}: {type(exc).__name__}: {exc}"


def _collect_group(sources: List[Dict[str, str]]) -> Tuple[List[str], Dict[str, Any]]:
    start = time.perf_counter()
    headlines: List[str] = []
    succeeded: List[str] = []
    failed: List[Dict[str, str]] = []

    for source in sources:
        titles, error = _fetch_titles(source)
        if error is None:
            succeeded.append(source.get("name", source.get("url", "unknown")))
            headlines.extend(titles)
        else:
            failed.append({"source": source.get("name", "unknown"), "error": error[:500]})

    diagnostics = {
        "sources_attempted": len(sources),
        "sources_succeeded": len(succeeded),
        "sources_failed": len(failed),
        "source_names_succeeded": succeeded,
        "source_errors": failed,
        "headlines_seen": len(headlines),
        "duration_s": round(time.perf_counter() - start, 3),
    }
    return headlines, diagnostics


def _data_status(group_diagnostics: Dict[str, Dict[str, Any]]) -> str:
    attempted = sum(int(d["sources_attempted"]) for d in group_diagnostics.values())
    succeeded = sum(int(d["sources_succeeded"]) for d in group_diagnostics.values())
    failed = sum(int(d["sources_failed"]) for d in group_diagnostics.values())
    if attempted == 0 or succeeded == 0:
        return "unavailable"
    if failed:
        return "partial"
    return "ok"


def run(
    sources: List[Dict[str, str]] | None = None,
    source_groups: Dict[str, List[Dict[str, str]]] | None = None,
) -> Dict[str, Any]:
    if source_groups is None:
        if sources is not None:
            source_groups = {"public_broadcast": sources, "private_media": []}
        elif os.environ.get("WORLD_OBSERVER_MEDIA_LANGUAGE_GERMANY_DISABLE_NETWORK") == "1":
            source_groups = {"public_broadcast": [], "private_media": []}
        else:
            source_groups = SOURCE_GROUPS

    start = time.perf_counter()
    all_headlines: List[str] = []
    group_scores: Dict[str, Dict[str, Any]] = {}
    group_diagnostics: Dict[str, Dict[str, Any]] = {}

    for group_name in ("public_broadcast", "private_media"):
        group_headlines, diagnostics = _collect_group(source_groups.get(group_name, []))
        all_headlines.extend(group_headlines)
        score = score_headlines(group_headlines)
        group_scores[group_name] = {
            "headline_count": score["headline_count"],
            "matched_headline_count": score["matched_headline_count"],
            "fear_index": score["fear_index"],
            "category_counts": score["category_counts"],
            "top_terms": score["top_terms"],
        }
        group_diagnostics[group_name] = diagnostics

    scores = score_headlines(all_headlines)
    data_status = _data_status(group_diagnostics)
    duration_s = round(time.perf_counter() - start, 3)

    diagnostics = {
        "sources_attempted": sum(d["sources_attempted"] for d in group_diagnostics.values()),
        "sources_succeeded": sum(d["sources_succeeded"] for d in group_diagnostics.values()),
        "sources_failed": sum(d["sources_failed"] for d in group_diagnostics.values()),
        "source_names_succeeded": [
            name for d in group_diagnostics.values() for name in d["source_names_succeeded"]
        ],
        "source_errors": [error for d in group_diagnostics.values() for error in d["source_errors"]],
        "headlines_seen": len(all_headlines),
        "duration_s": duration_s,
        "source_groups": group_diagnostics,
        "api_attempts": sum(d["sources_attempted"] for d in group_diagnostics.values()),
        "retries": 0,
        "http_status": None,
    }
    return {
        "observer": OBSERVER,
        "date_utc": _date_utc(),
        "status": "ok",
        "data_status": data_status,
        "scope": {
            "country": "Germany",
            "language": "German",
            "content": "RSS headline/title text only",
            "source_groups": "public broadcasting and private media in Germany only",
            "claims": "observational keyword frequencies only; no causality or manipulation claims",
        },
        **scores,
        "fear_index_overall": scores["fear_index"],
        "source_groups": group_scores,
        "diagnostics": diagnostics,
    }


def main() -> None:
    json.dump(run(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
