#!/usr/bin/env python3
"""Link checker for the AnkiTov site (T-189 CI gate).

Checks every href/src in every ``*.html`` page under a site root:

* **internal** links and image/script sources must resolve to a file that
  exists in the site root (root-absolute ``/path`` resolves against the site
  root; relative paths resolve against the page's directory);
* **internal fragments** (``page.html#anchor``) must match an ``id``/``name``
  in the target page;
* **external** http(s) links are probed with HEAD (GET fallback) and reported
  as WARNINGS only by default — external probes are inherently flaky in CI
  (bot blocks, rate limits) and a transient 403 must not block a deploy.
  Pass ``--strict-external`` to make external failures fatal.

Skipped schemes: mailto:, tel:, javascript:, data:, # (same-page fragments are
still validated against the page's own anchors).

Exit codes: 0 = clean (warnings allowed) | 1 = broken internal link/anchor
(or external failure under --strict-external).
"""
from __future__ import annotations

import argparse
import html.parser
import sys
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urljoin, urlsplit

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data"}
ATTRS = ("href", "src")
TIMEOUT_S = 10


class LinkCollector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []  # (attr, value)
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in ATTRS:
                self.links.append((name, value))
            if name == "id" or (tag == "a" and name == "name"):
                self.anchors.add(value.lstrip("#"))


def collect(root: Path) -> dict[Path, LinkCollector]:
    pages: dict[Path, LinkCollector] = {}
    for path in sorted(root.rglob("*.html")):
        p = LinkCollector()
        p.feed(path.read_text(encoding="utf-8", errors="replace"))
        pages[path] = p
    return pages


def check_internal(root: Path, page: Path, raw: str) -> str | None:
    """Return an error string if the internal link/fragment is broken."""
    target, _, frag = raw.partition("#")
    target = target.split("?", 1)[0]  # strip cache-buster query strings (?v=11)
    if target == "":
        # same-page fragment
        if frag and frag not in page.resolve().name and frag not in _page_anchors(page, root):
            pass  # handled below via anchors of this page
    if target == "":
        return None if frag == "" or frag in _page_anchors(page, root) else \
            f"same-page fragment #{frag} not found"
    # resolve the target file
    if target.startswith("/"):
        f = root / target.lstrip("/")
    else:
        f = (page.parent / target)
    f = f.resolve()
    try:
        f.relative_to(root.resolve())
    except ValueError:
        return f"escapes site root: {raw}"
    if not f.exists():
        return f"target missing: {raw}"
    if frag:
        if frag not in _page_anchors(f, root):
            return f"fragment #{frag} not found in {target}"
    return None


def _page_anchors(page: Path, root: Path) -> set[str]:
    p = LinkCollector()
    p.feed(page.read_text(encoding="utf-8", errors="replace"))
    return p.anchors


def check_external(url: str) -> str | None:
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0 (link-check; ankitov.org CI)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if resp.status < 400:
                return None
    except urllib.error.HTTPError as e:
        if e.code in (403, 405, 429, 503):
            # HEAD may be disallowed; retry with GET before giving up
            try:
                req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check; ankitov.org CI)"})
                with urllib.request.urlopen(req2, timeout=TIMEOUT_S) as resp2:
                    if resp2.status < 400:
                        return None
            except Exception:
                return f"HTTP {e.code} (HEAD+GET)"
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — report any probe failure as a string
        return f"{type(e).__name__}: {e}"
    return None


def main() -> None:
    site_default = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Link checker for the AnkiTov site.")
    ap.add_argument("--site", type=Path, default=site_default,
                    help=f"site root (default: {site_default})")
    ap.add_argument("--strict-external", action="store_true",
                    help="make external-link probe failures fatal (default: warn)")
    args = ap.parse_args()
    root = args.site.resolve()
    if not root.is_dir():
        print(f"site dir not found: {root}", file=sys.stderr)
        sys.exit(1)

    pages = collect(root)
    broken: list[str] = []
    warnings: list[str] = []
    external_seen = 0
    for page, parser in pages.items():
        rel = page.relative_to(root)
        for _attr, raw in parser.links:
            scheme = urlsplit(raw).scheme
            if scheme in SKIP_SCHEMES:
                continue
            if scheme in ("http", "https"):
                external_seen += 1
                err = check_external(raw)
                if err:
                    warnings.append(f"{rel}: external {raw} → {err}")
                continue
            if raw.startswith("#") or raw == "":
                frag = raw.lstrip("#")
                if frag and frag not in parser.anchors:
                    broken.append(f"{rel}: same-page fragment {raw} not found")
                continue
            err = check_internal(root, page, raw)
            if err:
                broken.append(f"{rel}: {err}")

    print(f"checked {len(pages)} page(s), {external_seen} external link(s)")
    for w in warnings:
        print(f"WARN  {w}")
    for b in broken:
        print(f"BROKEN  {b}")
    if broken or (args.strict_external and warnings):
        sys.exit(1)
    print("link check: clean.")


if __name__ == "__main__":
    main()
