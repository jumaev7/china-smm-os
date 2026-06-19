#!/usr/bin/env python3
"""Verify /dashboard serves CSS and JS static assets."""
import re
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:3000"


def fetch(path: str) -> tuple[int, bytes]:
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.status, resp.read()


def main() -> int:
    status, body = fetch("/dashboard")
    html = body.decode("utf-8", errors="replace")
    print(f"dashboard: HTTP {status}, html_len={len(html)}")
    print(f"  has_tailwind_classes: {'bg-gray' in html or 'font-sans' in html}")

    css_urls = re.findall(r"/_next/static/css/[^\s\"'>]+", html)
    if not css_urls:
        print("FAIL: no CSS URLs in dashboard HTML")
        return 1

    ok = True
    for url in css_urls[:2]:
        try:
            s, data = fetch(url)
            print(f"  CSS {url}: HTTP {s}, bytes={len(data)}")
            if s != 200 or len(data) < 100:
                ok = False
        except urllib.error.HTTPError as e:
            print(f"  CSS {url}: HTTP {e.code} FAIL")
            ok = False

    js_urls = re.findall(r"/_next/static/chunks/[^\s\"'>]+", html)[:2]
    for url in js_urls:
        try:
            s, data = fetch(url)
            print(f"  JS {url[:70]}: HTTP {s}, bytes={len(data)}")
            if s != 200:
                ok = False
        except urllib.error.HTTPError as e:
            print(f"  JS {url[:70]}: HTTP {e.code} FAIL")
            ok = False

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
