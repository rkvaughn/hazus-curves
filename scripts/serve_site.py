#!/usr/bin/env python3
"""Serve site/ locally for review, with HTTP Range support.

    python scripts/serve_site.py            # http://localhost:8931
    python scripts/serve_site.py --port 9000

Why this exists rather than `python -m http.server`: the stdlib handler ignores the
Range header and answers every request with the whole file. DuckDB-WASM reads Parquet
by fetching byte ranges, so under the stdlib server it has to pull all 57 MB of
curve_points_hu.parquet before it can answer a single hurricane query. GitHub Pages
supports ranges, so the stdlib server also misrepresents production behaviour.

Copies dist/*.parquet into site/data/ first unless --no-sync is passed.
"""

import argparse
import http.server
import os
import re
import shutil
import socketserver
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE, DIST = REPO / "site", REPO / "dist"

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus single-range byte serving.

    HTTP/1.1 matters as much as the range support itself. Advertising Accept-Ranges
    makes DuckDB-WASM switch from one bulk download to thousands of small ranged
    reads; under the stdlib default of HTTP/1.0 every one of those closes its
    connection, and the browser appears to hang. Keep-alive makes it fast.

    Safe here because every response this handler produces carries an accurate
    Content-Length.
    """

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - stdlib naming
        header = self.headers.get("Range")
        if not header:
            return super().do_GET()

        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().do_GET()

        m = RANGE_RE.match(header.strip())
        if not m:
            return super().do_GET()

        size = os.path.getsize(path)
        start_s, end_s = m.groups()
        if start_s == "":                      # suffix range: bytes=-500
            length = int(end_s or 0)
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)

        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        remaining = end - start + 1
        with open(path, "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return          # browser cancelled; normal for range readers
                remaining -= len(chunk)

    def send_response(self, code, message=None):
        # Reset per-response state, then advertise range support on every reply so
        # DuckDB-WASM takes the ranged-read path.
        self._sent_accept_ranges = False
        super().send_response(code, message)

    def send_header(self, keyword, value):
        if keyword.lower() == "accept-ranges":
            self._sent_accept_ranges = True
        super().send_header(keyword, value)

    def end_headers(self):
        if not getattr(self, "_sent_accept_ranges", False):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def sync_data() -> int:
    dest = SITE / "data"
    dest.mkdir(parents=True, exist_ok=True)
    files = sorted(DIST.glob("*.parquet"))
    if not files:
        print("no dist/*.parquet found - run: python scripts/build_all.py --perils fl,hu",
              file=sys.stderr)
        return 0
    for f in files:
        target = dest / f.name
        if not target.exists() or target.stat().st_mtime < f.stat().st_mtime:
            shutil.copy2(f, target)
    return len(files)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--no-sync", action="store_true",
                    help="do not refresh site/data from dist/")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not (SITE / "index.html").exists():
        print(f"no site/index.html under {SITE}", file=sys.stderr)
        return 1
    if not args.no_sync:
        n = sync_data()
        print(f"  synced {n} parquet file(s) into site/data/")

    os.chdir(SITE)
    with Server(("127.0.0.1", args.port), RangeHandler) as httpd:
        print(f"\n  Hazus curve browser:  http://localhost:{args.port}\n")
        print("  Ctrl-C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
