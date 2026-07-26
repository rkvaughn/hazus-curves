#!/usr/bin/env python3
"""Check that our mirrored copies still match the upstream sources.

This project re-hosts the raw source files as GitHub Release assets so it survives an
upstream bucket disappearing -- FEMA's own fema-ftp-snapshot bucket, referenced by
FEMA's FAST repository, has already gone. A mirror is only worth having if it is
provably identical to what it mirrors, so this script compares SHA-256 digests.

    python scripts/validate_mirror.py               # local raw/ vs upstream
    python scripts/validate_mirror.py --mirror URL  # also check our release assets

Writes docs/mirror_validation.md.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hazus_curves.sources import DATA_SOURCES

REPO = Path(__file__).resolve().parent.parent
RAW, DOCS = REPO / "raw", REPO / "docs"
CHUNK = 1 << 20


def stream_sha256(url: str) -> tuple:
    h = hashlib.sha256()
    n = 0
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        for block in r.iter_content(CHUNK):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def local_sha256(path: Path) -> tuple:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest(), path.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mirror", help="base URL of our release assets")
    ap.add_argument("--skip-upstream", action="store_true",
                    help="only check local files against MANIFEST.json")
    args = ap.parse_args()

    manifest_path = RAW / "MANIFEST.json"
    if not manifest_path.exists():
        print("no raw/MANIFEST.json - run scripts/fetch.py first", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())

    rows, failures = [], []
    for source in DATA_SOURCES:
        entry = manifest.get(source.name)
        if entry is None:
            rows.append((source.name, "-", "not in manifest", ""))
            continue
        recorded = entry["sha256"]

        path = RAW / source.name
        if path.exists():
            digest, size = local_sha256(path)
            local_ok = digest == recorded
            if not local_ok:
                failures.append(f"{source.name}: local file differs from manifest")
        else:
            local_ok, size = None, entry["bytes"]

        upstream_ok = None
        if not args.skip_upstream:
            try:
                digest, _ = stream_sha256(source.url)
                upstream_ok = digest == recorded
                if not upstream_ok:
                    failures.append(
                        f"{source.name}: UPSTREAM CHANGED - now {digest[:16]}..., "
                        f"manifest records {recorded[:16]}..."
                    )
            except requests.RequestException as exc:
                upstream_ok = f"unreachable ({exc.__class__.__name__})"
                failures.append(f"{source.name}: upstream unreachable: {exc}")

        mirror_ok = None
        if args.mirror:
            try:
                digest, _ = stream_sha256(urljoin(args.mirror, source.name))
                mirror_ok = digest == recorded
                if not mirror_ok:
                    failures.append(f"{source.name}: MIRROR differs from manifest")
            except requests.RequestException as exc:
                mirror_ok = f"unreachable ({exc.__class__.__name__})"
                failures.append(f"{source.name}: mirror unreachable: {exc}")

        def mark(v):
            return {True: "match", False: "**DIFFERS**", None: "-"}.get(v, str(v))

        rows.append((source.name, f"{size:,}", mark(local_ok),
                     mark(upstream_ok) + (f" / {mark(mirror_ok)}" if args.mirror else "")))
        print(f"  {source.name:<45} local={mark(local_ok):<12} "
              f"upstream={mark(upstream_ok)}")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Mirror validation",
        "",
        "SHA-256 comparison of the recorded manifest against the local copies, the",
        "upstream sources, and (when checked) this project's own re-hosted release",
        "assets.",
        "",
        "This exists because upstream sources decay. FEMA's `fema-ftp-snapshot` S3",
        "bucket, still referenced by FEMA's own FAST repository, no longer exists.",
        "",
        f"Last run: {stamp}",
        "",
        "| File | Bytes | Local vs manifest | Upstream"
        + (" / mirror |" if args.mirror else " |"),
        "|---|---:|---|---|",
    ]
    for name, size, loc, up in rows:
        lines.append(f"| `{name}` | {size} | {loc} | {up} |")
    lines += ["", f"Reproduce with `python {Path(__file__).relative_to(REPO)}`.", ""]
    if failures:
        lines += ["## Failures", ""] + [f"- {f}" for f in failures] + [""]

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "mirror_validation.md").write_text("\n".join(lines))
    print(f"\n  wrote docs/mirror_validation.md")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
