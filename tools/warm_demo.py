#!/usr/bin/env python3
"""Warm demo pages and their asset bundles before Playwright.

Odoo generates JS/CSS bundles on the first request for each bundle, which can
take longer than Playwright's default timeouts right after `make demo`.
"""
import os
import re
import time
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

PAGES = ("/billiard/booking", "/web/login")
ASSET_RE = re.compile(r'(?:src|href)="(/web/assets/[^"]+)"')


def _fetch(base, path, deadline):
    # localhost subdomains are not resolved by every host resolver.
    parsed = urlsplit(base)
    local = parsed.hostname and parsed.hostname.endswith(".localhost")
    address = urlunsplit((parsed.scheme, f"127.0.0.1:{parsed.port or 80}" if local else parsed.netloc, path, "", ""))
    request = Request(address, headers={"Host": parsed.netloc})
    with urlopen(request, timeout=min(60, max(1, deadline - time.monotonic()))) as response:
        if response.status != 200:
            raise URLError(f"HTTP {response.status}")
        return response.read()


def _fetch_with_retry(base, path, deadline):
    while True:
        try:
            return _fetch(base, path, deadline)
        except (URLError, TimeoutError, OSError):
            if time.monotonic() >= deadline:
                raise SystemExit(f"Demo warmup timed out: {path}; run make demo first") from None
            time.sleep(2)


def main():
    base = os.environ.get("E2E_BASE_URL") or "http://qclub.localhost:8069"
    deadline = time.monotonic() + 180
    for page in PAGES:
        html = _fetch_with_retry(base, page, deadline).decode("utf-8", "replace")
        assets = sorted(set(ASSET_RE.findall(html)))
        for asset in assets:
            _fetch_with_retry(base, asset, deadline)
        print(f"Demo ready: {page} ({len(assets)} asset bundles)")


if __name__ == "__main__":
    main()
