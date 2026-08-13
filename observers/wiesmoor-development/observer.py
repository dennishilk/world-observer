#!/usr/bin/env python3
"""Observe public planning-document listings published by the City of Wiesmoor."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

OBSERVER = "wiesmoor-development"
CITY_PAGE_URL = "https://www.wiesmoor.de/Bauen-Wohnen-und-Grundstuecke/Bauleitplanung.htm"
LISTING_URL = "https://bauamt.wiesmoor.de/auslegung/"
ARCHIVE_URL = "https://bauamt.wiesmoor.de/bauleitplanung/"
MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 20
USER_AGENT = "world-observer/wiesmoor-development (+https://github.com/dennishilk/world-observer)"
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")

KNOWN_COLLECTIONS: dict[str, tuple[str, str]] = {
    "70_Aend_FNP": ("70. Änderung des Flächennutzungsplans", "70th amendment to the land-use plan"),
    "A11_2_Aenderung": ("Bebauungsplan A11 · 2. Änderung", "Development plan A11 · 2nd amendment"),
    "A26_4_2BauGB": ("Bebauungsplan A26 · Unterlagen § 4 Abs. 2 BauGB", "Development plan A26 · documents labelled Section 4(2) BauGB"),
    "B16_63_Aenderung_FNP": ("Bebauungsplan B16 · 63. Änderung des Flächennutzungsplans", "Development plan B16 · 63rd amendment to the land-use plan"),
    "B8_4_Aenderung": ("Bebauungsplan B8 · 4. Änderung", "Development plan B8 · 4th amendment"),
    "C16": ("Bebauungsplan C16", "Development plan C16"),
    "C20_63_Aenderung_FNP": ("Bebauungsplan C20 · 63. Änderung des Flächennutzungsplans", "Development plan C20 · 63rd amendment to the land-use plan"),
    "C26_73_Aend_FNP": ("Bebauungsplan C26 · 73. Änderung des Flächennutzungsplans", "Development plan C26 · 73rd amendment to the land-use plan"),
    "C9_4_Aenderung": ("Bebauungsplan C9 · 4. Änderung", "Development plan C9 · 4th amendment"),
}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_links(html: str) -> list[str]:
    parser = LinkParser()
    parser.feed(html)
    return parser.hrefs


def parse_collection_ids(html: str) -> list[str]:
    collections: set[str] = set()
    for href in parse_links(html):
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme or parsed.netloc or href.startswith("/") or not parsed.path.endswith("/"):
            continue
        identifier = urllib.parse.unquote(parsed.path).strip("/")
        if identifier and identifier not in {".", ".."} and "/" not in identifier:
            collections.add(identifier)
    return sorted(collections)


def _date_from_filename(filename: str) -> str | None:
    decoded = urllib.parse.unquote(filename)
    patterns = (
        r"(?<!\d)(20\d{2})[_-](\d{2})[_-](\d{2})(?!\d)",
        r"(?<!\d)(\d{2})[._-](\d{2})[._-](20\d{2})(?!\d)",
        r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, decoded)
        if not match:
            continue
        parts = match.groups()
        year, month, day = parts if index == 0 else (parts[2], parts[1], parts[0])
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue
    return None


def parse_documents(html: str, collection_url: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for href in parse_links(html):
        parsed = urllib.parse.urlparse(href)
        decoded_path = urllib.parse.unquote(parsed.path)
        if href.startswith("/") or not decoded_path.lower().endswith(DOCUMENT_EXTENSIONS):
            continue
        filename = decoded_path.rsplit("/", 1)[-1]
        title = re.sub(r"\s+", " ", filename.rsplit(".", 1)[0].replace("_", " ")).strip()
        documents.append({
            "title_from_official_filename": title,
            "document_date_from_filename": _date_from_filename(filename),
            "url": urllib.parse.urljoin(collection_url, href),
        })
    return sorted(documents, key=lambda item: (item["document_date_from_filename"] or "", item["title_from_official_filename"]))


def _fetch_text(url: str) -> tuple[str, dict[str, Any]]:
    attempts = 0
    retries = 0
    last_status: int | None = None
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        attempts += 1
        if attempt:
            retries += 1
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                last_status = getattr(response, "status", None)
                text = response.read().decode("utf-8", errors="replace")
            return text, {"api_attempts": attempts, "retries": retries, "http_status": last_status}
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"official planning-directory request failed: {last_error.__class__.__name__ if last_error else 'unknown error'}")


def _base_payload() -> dict[str, Any]:
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor City Development Observer",
        "category": "society",
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "collected_at_utc": _now_utc(),
        "observation_mode": "periodic_official_document_listing",
        "geography": {
            "municipality": "Wiesmoor",
            "municipality_code_ags": "03452025",
            "state": "Lower Saxony",
            "country": "Germany",
        },
        "sources": [
            {"name": "City of Wiesmoor — Bauleitplanung", "url": CITY_PAGE_URL, "role": "official planning entry page"},
            {"name": "City of Wiesmoor — Auslegungen", "url": LISTING_URL, "role": "official public document listing"},
            {"name": "City of Wiesmoor — Bauleitplanung archive", "url": ARCHIVE_URL, "role": "official planning archive"},
        ],
        "status_definition": {
            "documents_listed": "The official directory lists the collection at observation time.",
            "project_stage": "not inferred",
        },
        "limitations": [
            "Directory presence alone does not establish a current legal project stage, consultation period, deadline, approval, or construction status.",
            "Dates are parsed only when they are visible in official filenames; they are document dates, not inferred publication dates.",
            "The observer links to official files and does not mirror planning documents.",
        ],
        "do_not_interpret_as": [
            "a legal notice service",
            "proof that a consultation period is currently open",
            "an inferred planning or construction stage",
        ],
        "update_policy": {"cadence": "daily", "collection_scope": "directory indexes only; document bodies are not downloaded"},
    }


def build_payload(fetch_text: Callable[[str], tuple[str, dict[str, Any]]] = _fetch_text) -> dict[str, Any]:
    payload = _base_payload()
    diagnostics = {"api_attempts": 0, "retries": 0, "http_status": None, "collection_errors": 0}
    try:
        root_html, root_diag = fetch_text(LISTING_URL)
        for key in ("api_attempts", "retries"):
            diagnostics[key] += int(root_diag.get(key) or 0)
        diagnostics["http_status"] = root_diag.get("http_status")
        identifiers = parse_collection_ids(root_html)
        if not identifiers:
            raise ValueError("official directory contained no document collections")
    except Exception as exc:
        payload.update({
            "status": "unavailable",
            "data_status": "unavailable",
            "listed_collections": [],
            "document_timeline": [],
            "diagnostics": {**diagnostics, "error_type": exc.__class__.__name__},
        })
        return payload

    collections: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for identifier in identifiers:
        collection_url = urllib.parse.urljoin(LISTING_URL, f"{urllib.parse.quote(identifier)}/")
        title_de, title_en = KNOWN_COLLECTIONS.get(
            identifier,
            (f"Offizielle Dokumentensammlung {identifier}", f"Official document collection {identifier}"),
        )
        try:
            collection_html, collection_diag = fetch_text(collection_url)
            for key in ("api_attempts", "retries"):
                diagnostics[key] += int(collection_diag.get(key) or 0)
            diagnostics["http_status"] = collection_diag.get("http_status")
            documents = parse_documents(collection_html, collection_url)
            collection_status = "documents_listed"
        except Exception:
            diagnostics["collection_errors"] += 1
            documents = []
            collection_status = "collection_listed_documents_unavailable"
        collections.append({
            "official_identifier": identifier,
            "title_de": title_de,
            "title_en": title_en,
            "status": collection_status,
            "project_stage": "not_inferred",
            "source_url": collection_url,
            "document_count": len(documents),
            "documents": documents,
        })
        for document in documents:
            if document["document_date_from_filename"]:
                timeline.append({
                    "date": document["document_date_from_filename"],
                    "date_type": "document_date_from_official_filename",
                    "collection_identifier": identifier,
                    "document_title": document["title_from_official_filename"],
                    "source_url": document["url"],
                })
    timeline.sort(key=lambda item: (item["date"], item["collection_identifier"], item["document_title"]), reverse=True)
    payload.update({
        "status": "ok" if diagnostics["collection_errors"] == 0 else "partial",
        "data_status": "ok" if diagnostics["collection_errors"] == 0 else "partial",
        "listing_observed_at_utc": payload["collected_at_utc"],
        "listed_collection_count": len(collections),
        "listed_document_count": sum(item["document_count"] for item in collections),
        "listed_collections": collections,
        "document_timeline": timeline,
        "diagnostics": {
            **diagnostics,
            "collections_found": len(collections),
            "dated_documents_found": len(timeline),
        },
    })
    return payload


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
