#!/usr/bin/env python3
"""
SGSITS website scraper for QA bot training.
Captures: page info, text, links, buttons, forms, APIs, dynamic vs static indicators,
and all useful metadata in a structured format.
"""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# Optional: Playwright for dynamic content and network capture
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# Optional: PDF text extraction for training data
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


BASE_URL = "https://www.sgsits.ac.in/"
OUTPUT_DIR = Path(__file__).resolve().parent / "scraped_data"
# Don't crawl these as "pages" — they're files/images, not HTML (saves budget for real pages)
FILE_EXTENSIONS_TO_SKIP = frozenset([
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".zip", ".rar", ".exe", ".mp4", ".mp3", ".wav", ".csv",
])
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class PageMetadata:
    """Structured metadata for one scraped page."""

    url: str
    scraped_at: str
    page_info: dict = field(default_factory=dict)
    content: dict = field(default_factory=dict)
    links: list = field(default_factory=list)
    buttons: list = field(default_factory=list)
    forms: list = field(default_factory=list)
    scripts: list = field(default_factory=list)
    apis_observed: list = field(default_factory=list)
    dynamic_indicators: dict = field(default_factory=dict)
    media: dict = field(default_factory=dict)
    structure: list = field(default_factory=list)
    raw_meta_tags: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _clean_text(el) -> str:
    if el is None:
        return ""
    text = el.get_text(separator=" ", strip=True)
    return " ".join(text.split())


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().rstrip("/").endswith(".pdf")


def _extract_pdf_text(pdf_bytes: bytes, max_chars: int = 200000) -> str:
    """Extract text from PDF bytes for QA/training. Returns empty string if PyMuPDF missing or error."""
    if not HAS_PYMUPDF:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        total = 0
        for page in doc:
            if total >= max_chars:
                break
            t = page.get_text()
            parts.append(t)
            total += len(t)
        doc.close()
        text = "\n".join(parts)
        return text[:max_chars] if len(text) > max_chars else text
    except Exception:
        return ""


def _is_internal(href: str, base: str) -> bool:
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return True
    try:
        return urlparse(href).netloc == "" or urlparse(base).netloc in href
    except Exception:
        return False


def scrape_static(url: str, html: str, base: str) -> dict:
    """Parse HTML and extract static structure, content, and indicators."""
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base).netloc or "www.sgsits.ac.in"

    # ----- Page info -----
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    meta_tags = []
    for m in soup.find_all("meta", attrs={"name": True}) + soup.find_all(
        "meta", attrs={"property": True}
    ):
        name = m.get("name") or m.get("property") or ""
        content = m.get("content", "")
        if name and content:
            meta_tags.append({"name": name, "content": content[:500]})
        if (name or "").lower() in ("description", "og:description") and not meta_desc:
            meta_desc = content

    page_info = {
        "title": title,
        "meta_description": meta_desc,
        "language": soup.html.get("lang", "") if soup.html else "",
        "charset": "",
    }
    for m in soup.find_all("meta", attrs={"charset": True}):
        page_info["charset"] = m.get("charset", "")
        break

    # ----- Main text content (for QA) -----
    for tag in ("script", "style", "nav", "header", "footer"):
        for t in soup.find_all(tag):
            t.decompose()
    body = soup.find("body") or soup
    main_text = _clean_text(body)
    headings = []
    for i in range(1, 7):
        for h in soup.find_all(f"h{i}"):
            headings.append({"level": i, "text": _clean_text(h)})

    content = {
        "main_text_preview": main_text[:15000],
        "main_text_length": len(main_text),
        "headings": headings,
    }

    # ----- Links -----
    links = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("javascript:") or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        full_url = urljoin(base, href)
        links.append({
            "href": href,
            "full_url": full_url,
            "text": _clean_text(a)[:200],
            "is_internal": _is_internal(href, base),
        })
    links = links[:2000]

    # ----- Buttons & inputs (submit) -----
    buttons = []
    for btn in soup.find_all(["button", "input"]):
        if btn.name == "input" and (btn.get("type") or "text").lower() not in (
            "submit",
            "button",
            "image",
            "reset",
        ):
            continue
        entry = {
            "tag": btn.name,
            "type": (btn.get("type") or "submit").lower(),
            "name": btn.get("name"),
            "value": btn.get("value"),
            "text": _clean_text(btn) if btn.name == "button" else (btn.get("value") or ""),
            "id": btn.get("id"),
            "form": btn.get("form"),
            "onclick": (btn.get("onclick") or "")[:500],
            "data_attributes": {k: v for k, v in btn.attrs.items() if k.startswith("data-")},
            "aria_label": btn.get("aria-label"),
        }
        buttons.append(entry)
    for el in soup.find_all(class_=re.compile(r"btn|button", re.I)):
        if el.name in ("button", "input"):
            continue
        role = el.get("role")
        onclick = el.get("onclick", "")[:500]
        if role == "button" or onclick or "btn" in (el.get("class") or []):
            buttons.append({
                "tag": el.name,
                "type": "div/span/other",
                "text": _clean_text(el)[:200],
                "id": el.get("id"),
                "onclick": onclick,
                "data_attributes": {k: v for k, v in el.attrs.items() if k.startswith("data-")},
                "classes": el.get("class", []),
                "aria_label": el.get("aria-label"),
            })

    # ----- Forms -----
    forms = []
    for f in soup.find_all("form"):
        fields = []
        for inp in f.find_all(["input", "textarea", "select"]):
            fields.append({
                "tag": inp.name,
                "type": inp.get("type", "text"),
                "name": inp.get("name"),
                "id": inp.get("id"),
                "required": inp.has_attr("required"),
            })
        forms.append({
            "action": urljoin(base, f.get("action", "") or url),
            "method": (f.get("method") or "get").upper(),
            "id": f.get("id"),
            "fields": fields,
        })

    # ----- Scripts (dynamic indicators) -----
    scripts = []
    inline_js = []
    for s in soup.find_all("script"):
        src = s.get("src")
        if src:
            scripts.append({
                "src": urljoin(base, src),
                "inline": False,
                "snippet": None,
            })
        else:
            raw = (s.string or "").strip()[:2000]
            inline_js.append(raw)
            scripts.append({"src": None, "inline": True, "snippet": raw[:1500] if raw else None})

    # ----- Dynamic indicators -----
    has_react = "react" in html.lower() or "reactroot" in html.lower() or "data-reactroot" in html
    has_vue = "vue" in html.lower() or "v-bind" in html.lower() or "data-v-" in html
    has_angular = "ng-" in html or "angular" in html.lower()
    has_jquery = "jquery" in html.lower()
    has_ajax = "xmlhttprequest" in html.lower() or "fetch(" in html.lower() or "ajax" in html.lower()
    data_attrs_count = sum(
        1 for el in soup.find_all(True) if any(k.startswith("data-") for k in el.attrs)
    )
    dynamic_indicators = {
        "has_inline_scripts": len(inline_js) > 0,
        "inline_script_count": len(inline_js),
        "external_script_count": len([s for s in scripts if s["src"]]),
        "has_react_like": has_react,
        "has_vue_like": has_vue,
        "has_angular_like": has_angular,
        "has_jquery_like": has_jquery,
        "has_ajax_fetch_indicators": has_ajax,
        "data_attributes_used": data_attrs_count > 0,
        "data_attribute_elements": data_attrs_count,
        "likely_dynamic": has_react or has_vue or has_angular or (len(scripts) > 2 and has_ajax),
    }

    # ----- Media -----
    images = []
    for img in soup.find_all("img", src=True)[:500]:
        images.append({
            "src": urljoin(base, img.get("src", "")),
            "alt": (img.get("alt") or "")[:200],
        })
    iframes = []
    for ifr in soup.find_all("iframe", src=True)[:50]:
        iframes.append({"src": urljoin(base, ifr.get("src", "")), "id": ifr.get("id")})

    media = {"images": images, "iframes": iframes}

    # ----- Structure (sections for QA context) -----
    structure = []
    for section in soup.find_all(["section", "article", "main", "aside"]):
        structure.append({
            "tag": section.name,
            "id": section.get("id"),
            "classes": section.get("class", []),
            "text_preview": _clean_text(section)[:1000],
        })
    if not structure and headings:
        structure.append({"note": "no_semantic_sections", "headings": [h["text"] for h in headings[:20]]})

    return {
        "page_info": page_info,
        "content": content,
        "links": links,
        "buttons": buttons,
        "forms": forms,
        "scripts": scripts,
        "dynamic_indicators": dynamic_indicators,
        "media": media,
        "structure": structure,
        "raw_meta_tags": meta_tags,
    }


def capture_network_apis(url: str, timeout_ms: int = 15000) -> tuple[str, list]:
    """Use Playwright to load page and capture XHR/fetch API requests. Returns (html, apis)."""
    if not HAS_PLAYWRIGHT:
        return "", []

    apis = []
    html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)

        def on_request(req):
            resource = req.resource_type
            u = req.url
            if resource in ("xhr", "fetch") or "/api/" in u or "json" in req.headers.get("accept", ""):
                apis.append({
                    "url": u,
                    "method": req.method,
                    "resource_type": resource,
                    "headers_referer": req.headers.get("referer", "")[:200],
                })

        context.on("request", on_request)
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            html = page.content()
        except Exception as e:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                html = page.content()
            except Exception:
                pass
        browser.close()

    return html, apis


def scrape_page(url: str, use_playwright: bool = True) -> dict:
    """Scrape one URL: HTML (or PDF text extraction) + optional Playwright for HTML."""
    from datetime import datetime

    meta = PageMetadata(
        url=url,
        scraped_at=datetime.utcnow().isoformat() + "Z",
    )

    # 1) Fetch
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        r.raise_for_status()
    except Exception as e:
        meta.errors.append(f"static_fetch: {e!s}")
        return asdict(meta)

    content_type = (r.headers.get("Content-Type") or "").lower()
    is_pdf = "application/pdf" in content_type or _is_pdf_url(url)

    # 2) PDF: extract text for QA/training (same JSON shape as HTML pages)
    if is_pdf and HAS_PYMUPDF:
        try:
            pdf_text = _extract_pdf_text(r.content)
            filename = Path(urlparse(url).path).name or "document.pdf"
            meta.page_info = {"title": filename, "meta_description": "", "language": "", "charset": ""}
            meta.content = {
                "main_text_preview": pdf_text[:15000],
                "main_text_length": len(pdf_text),
                "headings": [],
                "source_type": "pdf",
            }
            meta.links = []
            meta.raw_meta_tags = []
            return asdict(meta)
        except Exception as e:
            meta.errors.append(f"pdf_extract: {e!s}")
            return asdict(meta)
    elif is_pdf and not HAS_PYMUPDF:
        meta.errors.append("pdf_extract: PyMuPDF not installed (pip install PyMuPDF)")
        meta.content = {"main_text_preview": "", "main_text_length": 0, "headings": [], "source_type": "pdf"}
        return asdict(meta)

    # 3) HTML: use response text
    static_html = r.text
    apis = []
    if use_playwright and HAS_PLAYWRIGHT:
        try:
            dynamic_html, apis = capture_network_apis(url)
            if dynamic_html:
                static_html = dynamic_html
        except Exception as e:
            meta.errors.append(f"playwright: {e!s}")
    meta.apis_observed = apis

    # 4) Parse HTML with BeautifulSoup
    if static_html:
        parsed = scrape_static(url, static_html, url)
        meta.page_info = parsed["page_info"]
        meta.content = {**parsed["content"], "source_type": "html"}
        meta.links = parsed["links"]
        meta.buttons = parsed["buttons"]
        meta.forms = parsed["forms"]
        meta.scripts = parsed["scripts"]
        meta.dynamic_indicators = parsed["dynamic_indicators"]
        meta.media = parsed["media"]
        meta.structure = parsed["structure"]
        meta.raw_meta_tags = parsed["raw_meta_tags"]

    return asdict(meta)


def normalize_url(u: str, base: str) -> str:
    """Normalize URL and strip fragment."""
    full = urljoin(base, u)
    parsed = urlparse(full)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def is_html_crawlable(url: str) -> bool:
    """True if URL looks like an HTML page (not a file/image to skip)."""
    path = urlparse(url).path.lower()
    if not path or path == "/":
        return True
    return not any(path.rstrip("/").endswith(ext) for ext in FILE_EXTENSIONS_TO_SKIP)


def should_crawl_url(url: str, include_pdfs: bool = False) -> bool:
    """True if we should add this URL to the crawl queue (HTML only, or HTML + PDFs if include_pdfs)."""
    if is_html_crawlable(url):
        return True
    if include_pdfs and _is_pdf_url(url):
        return True
    return False


def get_internal_links(html: str, base: str, domain: str) -> set:
    """Extract internal links from HTML (same domain)."""
    soup = BeautifulSoup(html, "lxml")
    out = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full = normalize_url(href, base)
        try:
            if urlparse(full).netloc == domain or (not urlparse(full).netloc and domain):
                out.add(full)
        except Exception:
            pass
    return out


def crawl_all(
    start_url: str = BASE_URL,
    max_pages: int = 100,
    use_playwright: bool = False,
    output_dir: Optional[Path] = None,
    include_pdfs: bool = False,
    resume: bool = False,
) -> List[dict]:
    """Crawl SGSITS site and scrape each internal page. If resume=True, only crawl URLs not in existing index."""
    from datetime import datetime

    output_dir = output_dir or OUTPUT_DIR
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    domain = urlparse(start_url).netloc
    visited = set()
    existing_index_entries: List[dict] = []
    to_visit: set = set()

    if resume:
        index_path = output_dir / "crawl_index.json"
        if not index_path.exists():
            print("No crawl_index.json found; starting fresh crawl.", file=sys.stderr)
            resume = False
            to_visit = {normalize_url(start_url, start_url)}
        else:
            with open(index_path, encoding="utf-8") as f:
                existing = json.load(f)
            visited = set(existing.get("urls", []))
            existing_index_entries = list(existing.get("index", []))
            # Seed to_visit with missing internal links from homepage
            try:
                r = requests.get(start_url, headers={"User-Agent": USER_AGENT}, timeout=15)
                if r.ok:
                    internal = get_internal_links(r.text, start_url, domain)
                    to_visit = {
                        u for u in internal
                        if u not in visited and should_crawl_url(u, include_pdfs=include_pdfs)
                    }
            except Exception as e:
                print(f"Could not fetch homepage for resume: {e}", file=sys.stderr)
                return []
            if not to_visit:
                print("No remaining pages to crawl (all homepage links already in index).", file=sys.stderr)
                return []
            print(f"Resume: {len(visited)} already done, {len(to_visit)} remaining to try.", file=sys.stderr)
            max_pages = len(visited) + len(to_visit) + 500
    if not resume and not to_visit:
        to_visit = {normalize_url(start_url, start_url)}

    results = []
    while to_visit and len(visited) < max_pages:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        print(f"Scraping [{len(visited)}] {url}", file=sys.stderr)

        try:
            data = scrape_page(url, use_playwright=use_playwright)
            results.append(data)

            # Save per-page JSON
            slug = re.sub(r"[^\w\-]", "_", urlparse(url).path.strip("/") or "index")[:120]
            path = pages_dir / f"{slug}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Discover new links from this page's HTML (from static fetch)
            if data.get("content") and data.get("links"):
                for link in data["links"]:
                    full_url = link.get("full_url") or urljoin(url, link.get("href", ""))
                    full_url = normalize_url(full_url, url)
                    if (
                        urlparse(full_url).netloc == domain
                        and full_url not in visited
                        and should_crawl_url(full_url, include_pdfs=include_pdfs)
                    ):
                        to_visit.add(full_url)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)

    # Build index: merge existing (on resume) with new results
    new_index_entries = [{"url": r["url"], "title": r.get("page_info", {}).get("title", "")} for r in results]
    if resume and existing_index_entries is not None:
        index_entries = existing_index_entries + new_index_entries
        index_urls = list(visited)
    else:
        index_entries = new_index_entries
        index_urls = list(visited)

    index = {
        "crawled_at": datetime.utcnow().isoformat() + "Z",
        "base_url": start_url,
        "total_pages": len(index_urls),
        "urls": index_urls,
        "index": index_entries,
    }
    with open(output_dir / "crawl_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return results


def _url_type(url: str) -> str:
    """Classify URL as 'html', 'pdf', or 'file' (other files/images)."""
    path = urlparse(url).path.lower()
    if not path or path == "/":
        return "html"
    if path.rstrip("/").endswith(".pdf"):
        return "pdf"
    for ext in FILE_EXTENSIONS_TO_SKIP:
        if path.rstrip("/").endswith(ext):
            return "file"
    return "html"


def report_coverage(output_dir: Optional[Path] = None) -> None:
    """Report what was crawled: HTML pages vs files/images, and whether we likely covered the site."""
    output_dir = output_dir or OUTPUT_DIR
    index_path = output_dir / "crawl_index.json"
    if not index_path.exists():
        print("No crawl_index.json found. Run --crawl first, or --build-index after scraping.", file=sys.stderr)
        return
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    urls = index.get("urls", [])
    by_type = {"html": [], "pdf": [], "file": []}
    for u in urls:
        t = _url_type(u)
        by_type.setdefault(t, []).append(u)
    total = len(urls)
    html_count = len(by_type["html"])
    pdf_count = len(by_type.get("pdf", []))
    file_count = len(by_type.get("file", []))
    print("=== Crawl coverage report ===\n", file=sys.stderr)
    print(f"Total URLs scraped: {total}", file=sys.stderr)
    print(f"  HTML pages (useful for QA): {html_count}", file=sys.stderr)
    print(f"  PDFs (text extracted for QA if PyMuPDF used): {pdf_count}", file=sys.stderr)
    print(f"  Other files / images: {file_count}", file=sys.stderr)
    print("", file=sys.stderr)
    if file_count > 0:
        print("Sample other file URLs:", file=sys.stderr)
        for u in by_type.get("file", [])[:8]:
            print(f"  {u}", file=sys.stderr)
        print("", file=sys.stderr)
    print("To get only HTML pages next time, run:", file=sys.stderr)
    print("  python scrape_sgsits.py --crawl --max-pages 500", file=sys.stderr)
    print("(Files are now excluded from the crawl queue, so more real pages will be discovered.)", file=sys.stderr)
    # Optional: load homepage and count internal links not in index
    try:
        r = requests.get(BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.ok:
            soup = BeautifulSoup(r.text, "lxml")
            internal = set()
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                    continue
                full = normalize_url(href, BASE_URL)
                if urlparse(full).netloc == urlparse(BASE_URL).netloc:
                    internal.add(full)
            visited_set = set(urls)
            missing = [u for u in internal if u not in visited_set and is_html_crawlable(u)]
            print("", file=sys.stderr)
            print(f"Internal links on homepage: {len(internal)}", file=sys.stderr)
            print(f"HTML links from homepage not in this crawl: {len(missing)}", file=sys.stderr)
            if missing and len(missing) <= 20:
                for u in missing[:20]:
                    print(f"  {u}", file=sys.stderr)
            elif missing:
                print("  (First 15 missing)", file=sys.stderr)
                for u in missing[:15]:
                    print(f"  {u}", file=sys.stderr)
    except Exception as e:
        print(f"(Could not fetch homepage to compare links: {e})", file=sys.stderr)


def build_index_from_pages(output_dir: Optional[Path] = None) -> None:
    """Build crawl_index.json from existing scraped_data/pages/*.json (e.g. after interrupted crawl)."""
    from datetime import datetime

    output_dir = output_dir or OUTPUT_DIR
    pages_dir = output_dir / "pages"
    if not pages_dir.exists():
        print("No scraped_data/pages/ found.", file=sys.stderr)
        return
    index_entries = []
    urls = []
    for path in sorted(pages_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("url", "")
            title = (data.get("page_info") or {}).get("title", "")
            index_entries.append({"url": url, "title": title})
            urls.append(url)
        except Exception as e:
            print(f"Skip {path.name}: {e}", file=sys.stderr)
    index = {
        "crawled_at": datetime.utcnow().isoformat() + "Z",
        "base_url": BASE_URL,
        "total_pages": len(index_entries),
        "urls": urls,
        "index": index_entries,
    }
    out = output_dir / "crawl_index.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"Built index with {len(index_entries)} pages: {out}", file=sys.stderr)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scrape SGSITS site for QA bot metadata.")
    parser.add_argument("--url", default=BASE_URL, help="URL to scrape")
    parser.add_argument("--no-playwright", action="store_true", help="Skip Playwright (no API capture)")
    parser.add_argument("-o", "--output", default=None, help="Output JSON file path")
    parser.add_argument("--crawl", action="store_true", help="Crawl entire site (internal links only)")
    parser.add_argument("--resume", action="store_true", help="Only crawl remaining pages (requires existing crawl_index.json)")
    parser.add_argument("--max-pages", type=int, default=100, help="Max pages when crawling (default 100)")
    parser.add_argument("--include-pdfs", action="store_true", help="Also crawl PDFs and extract text for QA training")
    parser.add_argument("--build-index", action="store_true", help="Build crawl_index.json from existing pages/")
    parser.add_argument("--report", action="store_true", help="Report coverage: HTML vs file counts and missing links")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.report:
        report_coverage(OUTPUT_DIR)
        return

    if args.build_index:
        build_index_from_pages(OUTPUT_DIR)
        return

    if args.crawl:
        print("Crawling site (static only for speed)...", file=sys.stderr)
        if args.resume:
            print("Resume mode: only crawling remaining pages.", file=sys.stderr)
        if args.include_pdfs:
            print("Including PDFs (text will be extracted for QA).", file=sys.stderr)
        results = crawl_all(
            start_url=args.url,
            max_pages=args.max_pages,
            use_playwright=False,
            output_dir=OUTPUT_DIR,
            include_pdfs=args.include_pdfs,
            resume=args.resume,
        )
        out_path = OUTPUT_DIR / "crawl_index.json"
        print(f"Done. Scraped {len(results)} pages. Index: {out_path}", file=sys.stderr)
        return

    out_path = Path(args.output) if args.output else OUTPUT_DIR / "sgsits_home_metadata.json"
    print("Scraping (static + optional Playwright)...", file=sys.stderr)
    data = scrape_page(args.url, use_playwright=not args.no_playwright)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Written: {out_path}", file=sys.stderr)
    print(f"Links: {len(data.get('links', []))}, Buttons: {len(data.get('buttons', []))}, "
          f"APIs: {len(data.get('apis_observed', []))}, Dynamic: {data.get('dynamic_indicators', {}).get('likely_dynamic')}")


if __name__ == "__main__":
    main()
