#!/usr/bin/env python3
"""Inject the locale switcher into every page and rewrite internal links per locale.

- Appends .lang-switch CSS to styles.css (idempotent).
- For each locale page site/{lc}/*.html: rewrites root-internal page links to
  /{lc}/... and injects the switcher with that locale selected.
- For each EN page site/*.html: injects the switcher with English selected.
- Idempotent: skips pages already carrying the data-lang-switch marker.

Locales: en (root) + fr es de it pt ru zh ja ko hi ar he (dirs).
"""
import os, re, sys

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # site root (script lives in scripts/)
LOCALES = ["fr", "es", "de", "it", "pt", "ru", "zh", "ja", "ko", "hi", "ar", "he"]
NAMES = {"en": "English", "fr": "Français", "es": "Español", "de": "Deutsch",
         "it": "Italiano", "pt": "Português", "ru": "Русский", "zh": "中文",
         "ja": "日本語", "ko": "한국어", "hi": "हिन्दी", "ar": "العربية", "he": "עברית"}
PAGES = ["index.html", "about.html", "community.html", "blog.html", "tour.html"]
MARKER = "data-lang-switch"

CSS = """
/* --- locale switcher (injected) --- */
.lang-switch { margin-left: auto; }
.lang-switch select {
  font: inherit; font-size: 0.85rem; color: inherit;
  background: transparent; border: 1px solid currentColor;
  border-radius: 8px; padding: 0.25rem 0.5rem; cursor: pointer;
}
.lang-switch select option { color: #0f172a; background: #fff; }
"""

def switcher(current_lc, page):
    """Build the <select> for a page. page='' means home."""
    def url(lc):
        if page in ("", "index.html"):
            return "/" if lc == "en" else f"/{lc}/"
        return f"/{page}" if lc == "en" else f"/{lc}/{page}"
    opts = []
    for lc in ["en"] + LOCALES:
        sel = " selected" if lc == current_lc else ""
        opts.append(f'<option value="{url(lc)}"{sel}>{NAMES[lc]}</option>')
    return (f'<select {MARKER} aria-label="Language" '
            f'onchange="location.href=this.value">{"".join(opts)}</select>')

def inject(html, current_lc, page):
    if MARKER in html:
        return html, False
    sw = switcher(current_lc, page)
    # nav injection: before the closing </nav> of nav-links
    if "</nav>" in html:
        html = html.replace("</nav>", sw + "\n    </nav>", 1)
    else:  # pages without nav: top of body
        html = html.replace("<body>", "<body>\n  " + sw, 1)
    return html, True

def rewrite_links(html, lc):
    """Rewrite root-internal page links to locale-prefixed ones."""
    for page in PAGES:
        html = html.replace(f'href="/{page}"', f'href="/{lc}/{page}"')
    html = html.replace('href="/"', f'href="/{lc}/"')
    return html

def main():
    changed = []
    # 1. CSS
    css_path = os.path.join(SITE, "styles.css")
    css = open(css_path).read()
    if ".lang-switch" not in css:
        open(css_path, "a").write(CSS)
        changed.append("styles.css (appended)")
    # 2. EN pages
    for page in PAGES:
        p = os.path.join(SITE, page)
        html = open(p).read()
        html, did = inject(html, "en", page)
        if did:
            open(p, "w").write(html); changed.append(page)
    # 3. Locale pages
    for lc in LOCALES:
        for page in PAGES:
            p = os.path.join(SITE, lc, page)
            if not os.path.exists(p):
                print(f"MISSING {lc}/{page}"); continue
            html = open(p).read()
            html = rewrite_links(html, lc)
            html, did = inject(html, lc, page)
            open(p, "w").write(html)
            changed.append(f"{lc}/{page}")
    print(f"injected/rewritten: {len(changed)} files")
    for c in changed[:8]:
        print("  ·", c)
    if len(changed) > 8:
        print(f"  … +{len(changed)-8} more")

if __name__ == "__main__":
    main()
