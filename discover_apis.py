#!/usr/bin/env python3
"""
Discover API endpoints used by key SGSITS pages (via Playwright).
Outputs scraped_data/api_discovery.json so the bot knows:
- Which pages need real-time API data (vs static training data)
- Which API URL to call for each such page (description + link)
Requires: playwright, and run `playwright install chromium` once.
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

# Reuse scraper's capture and index
from scrape_sgsits import (
    BASE_URL,
    OUTPUT_DIR,
    capture_network_apis,
    scrape_page,
)

BOT_HINT = (
    "Use this for real-time answers: when the user asks about this topic, "
    "the bot can call the listed API(s) and use the response. Static content "
    "for training is in pages/*.json; this file tells the bot which API to call."
)


def discover_apis(
    urls: Optional[List[str]] = None,
    max_pages: int = 20,
    output_path: Optional[Path] = None,
) -> List[dict]:
    """
    Load page with Playwright, capture XHR/fetch requests, and return
    per-page entries with url, title, description_for_bot, apis[].
    """
    if urls is None:
        urls = [
            BASE_URL,
            f"{BASE_URL.rstrip('/')}/notices",
            f"{BASE_URL.rstrip('/')}/exam",
            f"{BASE_URL.rstrip('/')}/all-notices",
            f"{BASE_URL.rstrip('/')}/academics-1",
            f"{BASE_URL.rstrip('/')}/events",
        ]
    urls = urls[:max_pages]
    output_path = output_path or OUTPUT_DIR / "api_discovery.json"

    results = []
    for i, url in enumerate(urls):
        print(f"[{i+1}/{len(urls)}] {url}", file=sys.stderr)
        try:
            # Get title/description from static scrape (no Playwright)
            meta = scrape_page(url, use_playwright=False)
            title = (meta.get("page_info") or {}).get("title", "")
            desc = (meta.get("page_info") or {}).get("meta_description", "")
            text_preview = (meta.get("content") or {}).get("main_text_preview", "")[:300]
            likely_dynamic = (meta.get("dynamic_indicators") or {}).get("likely_dynamic", False)

            # Capture APIs with Playwright
            _, apis = capture_network_apis(url, timeout_ms=12000)
            apis = [{"url": a["url"], "method": a["method"], "resource_type": a.get("resource_type", "xhr")} for a in apis]

            entry = {
                "page_url": url,
                "page_title": title,
                "meta_description": desc,
                "text_preview_for_context": text_preview.replace("\n", " ")[:400],
                "likely_dynamic": likely_dynamic,
                "content_source": "api" if apis else ("dynamic" if likely_dynamic else "static"),
                "apis": apis,
                "description_for_bot": (
                    "This page may load data via API. Use apis[] to fetch in real time when the user asks about this topic."
                    if apis or likely_dynamic
                    else "Content is static; use scraped page JSON for answers."
                ),
            }
            results.append(entry)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            results.append({
                "page_url": url,
                "page_title": "",
                "apis": [],
                "error": str(e),
                "description_for_bot": "Discovery failed; treat as static or retry later.",
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "note": BOT_HINT,
        "pages": results,
        "summary": {
            "with_apis": sum(1 for r in results if r.get("apis")),
            "likely_dynamic": sum(1 for r in results if r.get("likely_dynamic")),
            "total_pages_checked": len(results),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Written: {output_path}", file=sys.stderr)
    print(f"Pages with APIs captured: {out['summary']['with_apis']}", file=sys.stderr)
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Discover API endpoints for key SGSITS pages (Playwright).")
    parser.add_argument("--urls", nargs="*", help="URLs to check (default: homepage + notices, exam, etc.)")
    parser.add_argument("--max", type=int, default=20, help="Max URLs to check")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()
    discover_apis(urls=args.urls or None, max_pages=args.max, output_path=args.output)


if __name__ == "__main__":
    main()
