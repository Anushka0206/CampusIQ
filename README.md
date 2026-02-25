# SGSITS Bot – Scraper & QA training data

Scrapes [SGSITS](https://www.sgsits.ac.in/) to collect page info, structure, buttons, forms, APIs, and dynamic vs static metadata for training a question-answer bot.

## Setup

```bash
# Create and use venv (already created)
source venv/bin/activate   # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for API capture and dynamic detection)
playwright install chromium
```

## Usage

**Single page (homepage) with full metadata + API capture:**

```bash
python scrape_sgsits.py
# Output: scraped_data/sgsits_home_metadata.json
```

**Single page without Playwright (faster, no XHR/fetch capture):**

```bash
python scrape_sgsits.py --no-playwright
```

**Crawl entire site (internal links only, saves each page + index):**

```bash
python scrape_sgsits.py --crawl --max-pages 150
# Output: scraped_data/pages/*.json and scraped_data/crawl_index.json
```

**Crawl only remaining pages (no re-fetch of already crawled URLs):**

```bash
python scrape_sgsits.py --crawl --resume
```

Requires an existing `scraped_data/crawl_index.json`. Fetches the homepage, finds internal links not in the index, and only scrapes those.

**Custom URL and output path:**

```bash
python scrape_sgsits.py --url "https://www.sgsits.ac.in/admission" -o scraped_data/admission.json
```

**Coverage report (HTML vs files, missing links):**

```bash
python scrape_sgsits.py --report
```

**Crawl only HTML pages (skips PDFs, images):**  
By default the crawler skips PDFs and images so your page limit is used for HTML. For full site coverage:

```bash
python scrape_sgsits.py --crawl --max-pages 500
```

**Include PDFs (extract text for QA/training):**  
PDFs (notices, circulars, reports) are useful for the bot. With `--include-pdfs`, the crawler also visits PDF links and **extracts text** into the same JSON shape (`content.main_text_preview`, `content.source_type: "pdf"`), so you can use them for RAG or training:

```bash
python scrape_sgsits.py --crawl --max-pages 500 --include-pdfs
```

Requires `PyMuPDF` (`pip install PyMuPDF`). Images (jpg, webp, etc.) are still skipped; adding OCR for images is possible later if needed.

## What to do with existing crawled data

Your current crawl has a mix of **93 HTML pages**, **116 PDFs** (stored as binary before text extraction), and **41 other files/images**. To get a clean, complete dataset:

1. **Option A – Start fresh (recommended)**  
   Remove old pages and re-crawl with the current script (HTML-only or HTML+PDF with text extraction):
   ```bash
   rm -rf scraped_data/pages scraped_data/crawl_index.json
   python scrape_sgsits.py --crawl --max-pages 500
   # Or with PDFs: python scrape_sgsits.py --crawl --max-pages 700 --include-pdfs
   ```

2. **Option B – Keep old data and add more**  
   Run another crawl with a higher `--max-pages`. New/updated URLs will be written; same slugs will be overwritten. You’ll still have some legacy file/image JSONs unless you delete them manually.

## How many pages to crawl to fully cover the site

- Run a **coverage report** first:
  ```bash
  python scrape_sgsits.py --report
  ```
  It prints **“HTML links from homepage not in this crawl”**. Right now that’s **86**; with only 93 HTML pages, the site is not fully covered.

- **Suggested limits:**  
  - **HTML only:** `--max-pages 500` is enough in practice. Crawl then run `--report` again; if “HTML links from homepage not in this crawl” is **0**, you’re done.  
  - **HTML + PDFs:** `--max-pages 700` (or 800 to be safe). PDFs don’t yield new links, so total discovered HTML pages stay in the same ballpark.

- **Check when you’re done:**  
  After each crawl, run `python scrape_sgsits.py --report`. When **“HTML links from homepage not in this crawl”** is **0**, the site is fully covered (from the perspective of the homepage and all pages the crawler reached).

## Output schema (per page)

| Field | Description |
|-------|-------------|
| `url`, `scraped_at` | Page URL and scrape time |
| `page_info` | `title`, `meta_description`, `language`, `charset` |
| `content` | `main_text_preview`, `headings` (for QA context) |
| `links` | `href`, `full_url`, `text`, `is_internal` |
| `buttons` | `tag`, `type`, `onclick`, `form`, `data_attributes`, `aria_label` |
| `forms` | `action`, `method`, `fields[]` |
| `scripts` | `src`, `inline`, `snippet` (first 1500 chars of inline JS) |
| `apis_observed` | XHR/fetch URLs captured via Playwright |
| `dynamic_indicators` | `likely_dynamic`, `has_react_like`, `has_ajax_fetch_indicators`, etc. |
| `media` | `images[]`, `iframes[]` |
| `structure` | Semantic sections/articles with text previews |
| `raw_meta_tags` | All meta name/content and og:* tags |

Use this JSON for RAG, fine-tuning, or as context for a QA bot over SGSITS content.

## Static vs API content (for the bot)

- **Static content** (in each page JSON): Use `content.main_text_preview`, `page_info.title`, etc. for RAG/training. The bot can answer from this without calling the site again.
- **Dynamic/API content**: Some pages load data via XHR/fetch. The crawler sets `dynamic_indicators.likely_dynamic` and `apis_observed` (only when Playwright is used). So the bot should:
  - Prefer static content for answers when possible.
  - For pages that need real-time data, the bot needs to know **which API to call**. The crawl does not capture API URLs by default (for speed).

**To get API endpoints and a bot-ready mapping (page → which API to call):**

```bash
python discover_apis.py
# Optional: python discover_apis.py --urls "https://www.sgsits.ac.in/notices" "https://www.sgsits.ac.in/exam" --max 10
```

This runs Playwright on key pages (homepage, notices, exam, etc.), captures XHR/fetch requests, and writes **`scraped_data/api_discovery.json`** with:

- `page_url`, `page_title`, `description_for_bot`
- `content_source`: `"api"` | `"dynamic"` | `"static"`
- `apis`: list of `{ "url", "method" }` to call in real time

The bot can then: answer from static JSONs when possible, and for topics that match a page in `api_discovery.json` with non-empty `apis`, call those URLs when the user asks for up-to-date info.
