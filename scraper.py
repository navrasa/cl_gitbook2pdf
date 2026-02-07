#!/usr/bin/env python3
"""
Scrape a modern GitBook site using Playwright (headless Chromium) and generate a PDF.
Works with both legacy and modern GitBook sites by rendering JavaScript.
"""
import asyncio
import os
import re
import sys
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright


async def extract_nav_links(page, base_url):
    """Extract all navigation links from the GitBook sidebar."""
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    # Try multiple selectors for different GitBook versions
    links = await page.evaluate("""() => {
        const results = [];
        const seen = new Set();

        // Strategy 1: Modern GitBook nav links
        const navLinks = document.querySelectorAll(
            'nav a[href], aside a[href], [class*="sidebar"] a[href], [class*="navigation"] a[href], [class*="menu"] a[href], [class*="toc"] a[href], [class*="table-of-contents"] a[href]'
        );
        navLinks.forEach(a => {
            const href = a.href;
            const text = a.textContent.trim();
            if (href && text && !seen.has(href)) {
                seen.add(href);
                results.push({href, text});
            }
        });

        // Strategy 2: Legacy GitBook ul.summary
        if (results.length === 0) {
            const summaryLinks = document.querySelectorAll('ul.summary a[href]');
            summaryLinks.forEach(a => {
                const href = a.href;
                const text = a.textContent.trim();
                if (href && text && !seen.has(href)) {
                    seen.add(href);
                    results.push({href, text});
                }
            });
        }

        return results;
    }""")

    # Filter to same-domain links only
    filtered = []
    seen_paths = set()
    for link in links:
        parsed = urlparse(link["href"])
        if parsed.netloc == base_domain and parsed.path not in seen_paths:
            seen_paths.add(parsed.path)
            filtered.append(link)

    return filtered


async def extract_page_content(page):
    """Extract the main content area from a GitBook page."""
    content = await page.evaluate("""() => {
        // Try multiple selectors for different GitBook versions
        const selectors = [
            'main article',
            'main',
            '[role="main"]',
            '.markdown-section',
            'section.normal.markdown-section',
            'section.normal',
            '.page-inner .page-body',
            '.page-wrapper .page-inner',
            'article',
            '.content',
        ];

        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.innerHTML.trim().length > 50) {
                // Remove navigation, footer, and interactive elements
                const clone = el.cloneNode(true);
                clone.querySelectorAll('nav, footer, [class*="navigation"], [class*="pagination"], button, [class*="edit"]').forEach(e => e.remove());
                return clone.innerHTML;
            }
        }

        // Fallback: get body content
        return document.body.innerHTML;
    }""")
    return content


async def get_page_title(page):
    """Get the page title."""
    title = await page.evaluate("""() => {
        const h1 = document.querySelector('main h1, article h1, .markdown-section h1, h1');
        if (h1) return h1.textContent.trim();
        return document.title || '';
    }""")
    return title


async def scrape_gitbook(url, output_dir):
    """Main scraping function."""
    print(f"Launching browser...")
    sys.stdout.flush()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # Navigate to main page
        print(f"Loading {url}")
        sys.stdout.flush()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)  # Extra wait for JS rendering

        # Get site title for filename
        site_title = await get_page_title(page)
        if not site_title:
            site_title = urlparse(url).netloc.split(".")[0]
        safe_title = re.sub(r'[^\w\s-]', '', site_title).strip().replace(' ', '')
        if not safe_title:
            safe_title = "gitbook-export"

        # Extract navigation links
        print(f"Extracting navigation links...")
        sys.stdout.flush()
        nav_links = await extract_nav_links(page, url)

        if not nav_links:
            # If no nav links found, just convert the single page
            print("No navigation found, converting single page...")
            sys.stdout.flush()
            nav_links = [{"href": url, "text": site_title}]
        else:
            print(f"Found {len(nav_links)} pages to convert")
            sys.stdout.flush()

        # Collect content from each page
        all_sections = []
        for i, link in enumerate(nav_links):
            page_url = link["href"]
            page_title = link["text"]
            print(f"Crawling ({i+1}/{len(nav_links)}): {page_title}")
            sys.stdout.flush()

            try:
                if page.url != page_url:
                    await page.goto(page_url, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(1000)

                content = await extract_page_content(page)
                if content and len(content.strip()) > 10:
                    all_sections.append(f"""
                        <div class="page-section" style="page-break-before: always;">
                            <h1 class="section-title">{page_title}</h1>
                            <div class="section-content">{content}</div>
                        </div>
                    """)
                    print(f"  Done: {page_title}")
                else:
                    print(f"  Skipped (empty): {page_title}")
            except Exception as e:
                print(f"  Failed: {page_title} ({e})")
            sys.stdout.flush()

        if not all_sections:
            raise RuntimeError("No content was extracted from any page")

        # Build combined HTML document
        combined_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{site_title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        .section-title {{
            font-size: 1.8em;
            border-bottom: 2px solid #eee;
            padding-bottom: 0.3em;
            margin-top: 0;
        }}
        .page-section:first-child {{
            page-break-before: avoid;
        }}
        h1 {{ font-size: 1.8em; }}
        h2 {{ font-size: 1.5em; }}
        h3 {{ font-size: 1.3em; }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        pre {{
            background: #f6f8fa;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.85em;
        }}
        code {{
            background: #f6f8fa;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px 12px;
            text-align: left;
        }}
        th {{
            background: #f6f8fa;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            margin: 1em 0;
            padding: 0.5em 1em;
            color: #666;
        }}
        a {{
            color: #0366d6;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    {"".join(all_sections)}
</body>
</html>"""

        # Generate PDF using Playwright's built-in PDF (Chrome print-to-PDF)
        print("Generating PDF, please wait...")
        sys.stdout.flush()

        # Set content to the combined HTML
        await page.set_content(combined_html, wait_until="networkidle")
        await page.wait_for_timeout(1000)

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{safe_title}.pdf")

        await page.pdf(
            path=output_path,
            format="A4",
            margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
            print_background=True,
        )

        print(f"Generated: {safe_title}.pdf")
        sys.stdout.flush()

        await browser.close()

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <gitbook-url> [output-dir]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./output"

    asyncio.run(scrape_gitbook(url, output_dir))
