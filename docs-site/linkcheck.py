#!/usr/bin/env python3
"""Base-path link-check for the KGIS docs satellite (AC-3).

Serves no HTTP: it reasons about the built ``dist/`` directly, as if mounted at
``--base-path`` on the hub, and fails on either problem the acceptance criterion
names:

1. an **absolute in-site URL** (``href="/foo"`` / ``src="/foo"``) that is not
   rooted at the mount prefix -- it would 404 under a sub-path deploy; and
2. a **broken internal link or asset** -- a relative (or mount-rooted) target
   whose file does not exist in ``dist/``.

External links (``http(s)://``, protocol-relative ``//``), ``mailto:``,
in-page anchors (``#...``) and ``data:`` URIs are ignored.

The one intentional exception is ``404.html``: MkDocs must emit absolute URLs
there (a 404 is served at an arbitrary depth), so its absolute URLs are allowed
*only* when rooted at the mount prefix, and are still resolved on disk.

Usage:
    python docs-site/linkcheck.py --dist docs-site/dist \\
        --base-path /projects/kgis/kgis-docs/
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urldefrag

ATTR_RE = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _is_external(url: str) -> bool:
    return (
        url.startswith("http://")
        or url.startswith("https://")
        or url.startswith("//")
        or url.startswith("mailto:")
        or url.startswith("data:")
        or url.startswith("tel:")
        or url.startswith("#")
    )


def check(dist: Path, base_path: str) -> list[str]:
    base = "/" + base_path.strip("/") + "/"
    errors: list[str] = []
    html_files = sorted(dist.rglob("*.html"))
    if not html_files:
        return [f"no HTML files under {dist}"]

    for page in html_files:
        rel_page = page.relative_to(dist)
        is_404 = rel_page.name == "404.html"
        text = page.read_text(encoding="utf-8")
        for raw in ATTR_RE.findall(text):
            url = html.unescape(raw).strip()
            if not url or _is_external(url):
                continue
            target, _frag = urldefrag(url)
            if not target:
                continue

            if target.startswith("/"):
                # Absolute in-site URL. Allowed only if rooted at the mount,
                # and (outside 404.html) it is still a policy violation to emit
                # absolute in-site links from content pages.
                if not target.startswith(base):
                    errors.append(
                        f"{rel_page}: absolute in-site URL not rooted at "
                        f"{base!r}: {url!r}"
                    )
                    continue
                if not is_404:
                    errors.append(
                        f"{rel_page}: absolute in-site URL {url!r} "
                        f"(use a relative link; only 404.html may be absolute)"
                    )
                resolved = dist / unquote(target[len(base):])
            else:
                resolved = (page.parent / unquote(target)).resolve()

            # Directory URL -> its index.html.
            if resolved.is_dir():
                resolved = resolved / "index.html"
            try:
                resolved.relative_to(dist.resolve())
            except ValueError:
                errors.append(f"{rel_page}: link escapes dist/: {url!r}")
                continue
            if not resolved.exists():
                errors.append(f"{rel_page}: broken link/asset {url!r} -> {resolved}")

    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--base-path", required=True)
    args = parser.parse_args(argv)

    dist = args.dist.resolve()
    if not dist.is_dir():
        sys.stderr.write(f"no dist directory at {dist}\n")
        return 1

    errors = check(dist, args.base_path)
    if errors:
        sys.stderr.write(
            f"\nLink-check FAILED with {len(errors)} problem(s) under "
            f"{args.base_path}:\n"
        )
        for e in errors:
            sys.stderr.write(f"  {e}\n")
        return 1

    n = len(list(dist.rglob("*.html")))
    sys.stdout.write(
        f"Link-check passed: {n} page(s), no broken links and no stray "
        f"absolute in-site URLs under {args.base_path}.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
