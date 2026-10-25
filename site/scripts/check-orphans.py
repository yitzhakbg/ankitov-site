#!/usr/bin/env python3
"""Orphaned-word gate for the AnkiTov site (T-188).

An "orphan" is a block text element whose last rendered line is exactly one
word — the classic typographic wart that reads as sloppy on a marketing site.

Scope (T-188):
  * every ``*.html`` page in the site root x viewport widths 390/768/1024/
    1280/1440 (a page that only misbehaves at one width is still broken)
  * served by the site's own ``serve-nocache.py`` (Range support), falling
    back to stdlib ``http.server`` if it is missing
  * wired as a pre-deploy gate in ``deploy.sh``: a deploy is REFUSED while
    findings exist; ``./deploy.sh --force-orphans`` overrides with a loud
    warning. CI gate on ``*.html``/``styles.css`` PRs rides T-189 (the site's
    future repo home).

Doctrine for FIXING orphans — do not fight this gate by other means:
  * ``text-wrap: pretty`` globally (already in ``styles.css``)
  * ``<span class="nb">...</span>`` nowrap spans for fragile phrases
  * NEVER bare ``&nbsp;`` — Chromium breaks AT nbsp under ``text-wrap:pretty``
    (verified 2026-10-25)

Self-test (proves the detector without touching the real site):
  python3 scripts/check-orphans.py --selftest
  Serves ``tests/fixtures/orphan-fixture.html`` — an intentional orphan plus a
  control paragraph — and expects exactly one finding (the orphan, at every
  tested width) and nothing else. Exit 0 = detector sane.

Runtime: playwright + Chromium. If this python lacks playwright and ``uv`` is
available, the script re-execs itself under ``uv run --with playwright``
(browser binaries come from the shared ms-playwright cache). A gate that
cannot run must fail CLOSED.

Exit codes: 0 = clean pass | 1 = findings (or selftest mismatch) |
2 = gate could not run (environment error).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WIDTHS_DEFAULT = [390, 768, 1024, 1280, 1440]

# Detector: ported from the 2026-10-25 orphan sweep (/tmp/orphan-sweep.py),
# minus its dead selector variable, with a guard for elements whose words all
# report null rects. Semantics are unchanged: cluster word rects into lines by
# top coordinate (3px), flag an element when its LAST rendered line holds
# exactly one word and the element renders at least two lines.
DETECT_JS = r"""
() => {
  const out = [];
  const els = document.querySelectorAll(
    'p, h1,h2,h3,h4,h5,h6, li, blockquote, figcaption, dt, dd, summary, td, th, label');
  for (const el of els) {
    if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    // Text nodes this element renders directly (skip nested block children).
    const textNodes = [];
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        let p = n.parentElement;
        while (p && p !== el) {
          const d = getComputedStyle(p).display;
          if (d === 'block' || d === 'flex' || d === 'list-item' || d === 'table-cell') {
            return NodeFilter.FILTER_REJECT;
          }
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    let n;
    while ((n = tw.nextNode())) textNodes.push(n);
    const words = [];
    for (const node of textNodes) {
      const re = /\S+/g;
      let m;
      while ((m = re.exec(node.textContent))) {
        words.push({node, start: m.index, end: m.index + m[0].length});
      }
    }
    if (words.length < 2) continue;
    const range = document.createRange();
    const tops = [];
    for (const w of words) {
      range.setStart(w.node, w.start);
      range.setEnd(w.node, w.end);
      const rects = range.getClientRects();
      if (!rects.length) { tops.push(null); continue; }
      tops.push(rects[0].top);
    }
    // Cluster word tops into rendered lines (within 3px).
    const lines = [];
    for (const t of tops) {
      if (t === null) continue;
      const line = lines.find(L => Math.abs(L.top - t) < 3);
      if (line) line.count++;
      else lines.push({top: t, count: 1});
    }
    lines.sort((a, b) => a.top - b.top);
    if (lines.length < 2) continue;
    const last = lines[lines.length - 1];
    if (last.count !== 1) continue;
    let idx = 0;
    const lastWords = [];
    for (const w of words) {
      const t = tops[idx++];
      if (t !== null && Math.abs(t - last.top) < 3) lastWords.push(w);
    }
    if (!lastWords.length) continue;
    range.setStart(lastWords[0].node, lastWords[0].start);
    range.setEnd(lastWords[0].node, lastWords[0].end);
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 80),
      text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 140),
      orphan: range.toString()
    });
  }
  return out;
}
"""


def die(msg: str, code: int = 2) -> "None":
    print(f"check-orphans: {msg}", file=sys.stderr)
    sys.exit(code)


def bootstrap_playwright() -> None:
    """Ensure playwright is importable; re-exec under uv if needed (fail closed)."""
    try:
        import playwright  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("ORPHANS_NO_UV") != "1" and shutil.which("uv"):
        os.execvp("uv", ["uv", "run", "--with", "playwright",
                         sys.executable, __file__, *sys.argv[1:]])
        # execvp never returns
    die("playwright is not installed for this python and no 'uv' fallback.\n"
        "  install once:   python3 -m pip install playwright\n"
        "                  python3 -m playwright install chromium\n"
        "  or rely on uv:  ensure 'uv' is on PATH (gate self-bootstraps via it)\n"
        "  (deploy.sh refuses to deploy while the gate cannot run — override\n"
        "   with ./deploy.sh --force-orphans if you truly must)", 2)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(site: Path, port: int) -> subprocess.Popen:
    """Serve `site` on 127.0.0.1:port, preferring the site's own no-cache server."""
    serve = site / "serve-nocache.py"
    cmd = ([sys.executable, str(serve), str(port), "127.0.0.1"]
           if serve.exists() else
           [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"])
    return subprocess.Popen(cmd, cwd=str(site),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_healthy(port: int, first_page: str, timeout_s: float = 10.0) -> bool:
    url = f"http://127.0.0.1:{port}/{first_page}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    return False


async def sweep(site: Path, pages: list[str], widths: list[int], port: int) -> list[dict]:
    from playwright.async_api import async_playwright

    findings: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for width in widths:
                page = await browser.new_page(viewport={"width": width, "height": 900})
                for pg in pages:
                    await page.goto(f"http://127.0.0.1:{port}/{pg}",
                                    wait_until="networkidle", timeout=30_000)
                    await page.wait_for_timeout(300)
                    for hit in await page.evaluate(DETECT_JS):
                        findings.append({"page": pg, "width": width, **hit})
                await page.close()
        finally:
            await browser.close()
    return findings


def merge(findings: list[dict]) -> list[dict]:
    """Dedupe identical findings, unioning the widths each one appears at."""
    merged: dict[tuple, dict] = {}
    for f in findings:
        key = (f["page"], f["tag"], f["cls"], f["text"], f["orphan"])
        entry = merged.setdefault(key, {**f, "widths": set()})
        entry["widths"].add(f["width"])
    return sorted(merged.values(), key=lambda e: (e["page"], min(e["widths"]), e["orphan"]))


def report(findings: list[dict], widths: list[int], pages: list[str]) -> None:
    if not findings:
        print(f"NO ORPHANS — {len(pages)} page(s) x {widths} widths: clean")
        return
    print(f"ORPHANS FOUND: {len(findings)} element(s) end on a single word\n")
    for e in findings:
        w = ",".join(str(x) for x in sorted(e["widths"]))
        print(f"{e['page']} [{w}px] <{e['tag']} class={e['cls']!r}> orphan={e['orphan']!r}")
        print(f"   text: {e['text']}")
    print("\nFix doctrine: text-wrap: pretty (global) + <span class=\"nb\"> "
          "nowrap spans for fragile phrases. NEVER bare &nbsp;.")


def selftest(site: Path, widths: list[int], port: int) -> int:
    """Gate must fail on the intentional-orphan fixture and only on it."""
    fixture = "tests/fixtures/orphan-fixture.html"
    if not (site / fixture).exists():
        die(f"selftest fixture missing: {site / fixture}")
    findings = asyncio.run(sweep(site, [fixture], widths, port))
    merged = merge(findings)
    problems = []
    if len(merged) != 1:
        problems.append(f"expected exactly 1 finding, got {len(merged)}: {merged!r}")
    else:
        e = merged[0]
        if e["orphan"] != "orphan":
            problems.append(f"flagged wrong orphan word: {e['orphan']!r}")
        if e["tag"] != "p":
            problems.append(f"flagged wrong element: <{e['tag']}>")
        if sorted(e["widths"]) != sorted(widths):
            problems.append(f"orphan not detected at all widths: {sorted(e['widths'])}")
    if problems:
        for p in problems:
            print(f"SELFTEST FAIL: {p}", file=sys.stderr)
        print("selftest: FAIL (detector did not behave as specified)", file=sys.stderr)
        return 1
    print(f"selftest: PASS — intentional orphan flagged at {widths}, "
          "control paragraph clean (no false positive)")
    return 0


def main() -> None:
    site_default = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(
        description="Orphaned-word gate: block text whose last rendered line is one word.")
    ap.add_argument("--site", type=Path, default=site_default,
                    help=f"site root (default: {site_default})")
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS_DEFAULT)),
                    help="comma-separated viewport widths (default 390,768,1024,1280,1440)")
    ap.add_argument("--pages", default="",
                    help="comma-separated page paths relative to --site "
                         "(default: every *.html in the site root)")
    ap.add_argument("--port", type=int, default=0,
                    help="local server port (default: ephemeral)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable findings on stdout (for CI)")
    ap.add_argument("--selftest", action="store_true",
                    help="run against tests/fixtures/ and verify gate behavior")
    args = ap.parse_args()

    bootstrap_playwright()  # after parse so --help works without playwright

    site = args.site.resolve()
    if not site.is_dir():
        die(f"site dir not found: {site}")
    try:
        widths = [int(w) for w in str(args.widths).split(",") if w.strip()]
    except ValueError:
        die(f"bad --widths: {args.widths!r}")
    if not widths:
        die("no widths given")

    if args.pages:
        pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    else:
        pages = sorted(p.name for p in site.glob("*.html"))
    if not pages:
        die(f"no *.html pages found in {site}")

    port = args.port or free_port()
    server = start_server(site, port)
    try:
        if not wait_healthy(port, pages[0]):
            die(f"local server did not come up on 127.0.0.1:{port}", 2)
        if args.selftest:
            sys.exit(selftest(site, widths, port))
        findings = merge(asyncio.run(sweep(site, pages, widths, port)))
        if args.json:
            print(json.dumps({"findings": [
                {**{k: v for k, v in e.items() if k != "widths"},
                 "widths": sorted(e["widths"])} for e in findings],
                "pages": pages, "widths": widths}, indent=2))
        else:
            report(findings, widths, pages)
        sys.exit(1 if findings else 0)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
