#!/usr/bin/env python3
"""Download every declared upstream source and record its integrity metadata.

Idempotent: a file already present and matching its recorded SHA-256 is left alone.
Re-running verifies rather than re-downloads.

Usage:
    python scripts/fetch.py                  # data sources only
    python scripts/fetch.py --docs           # include FEMA PDFs
    python scripts/fetch.py --perils fl      # just what flood needs
    python scripts/fetch.py --verify         # verify existing files, download nothing
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hazus_curves.sources import (ALL_SOURCES, DATA_SOURCES, DOC_SOURCES,
                                  MIRROR_BASE, for_perils)

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "raw"
MANIFEST = RAW / "MANIFEST.json"

CHUNK = 1 << 20  # 1 MiB; the wind workbook is ~102 MB and must not be held in memory


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def download_from(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for block in resp.iter_content(CHUNK):
                fh.write(block)
        tmp.replace(dest)


def download(source, dest: Path, manifest: dict) -> str:
    """Fetch from upstream, falling back to our mirror. Returns which was used.

    The os-climate bucket that supplied the Hazus 6.1 workbooks went dark
    (403 AllAccessDisabled) on 2026-08-12, which would otherwise make this project
    unreproducible. Falling back is only safe because raw/MANIFEST.json is committed:
    a mirrored file is accepted only if its SHA-256 matches the hash recorded when the
    file was first retrieved from upstream, so the mirror cannot silently substitute
    different bytes.
    """
    try:
        download_from(source.url, dest)
        return "upstream"
    except requests.RequestException as exc:
        recorded = manifest.get(source.name, {}).get("sha256")
        if not recorded:
            raise
        print(f"           upstream unavailable ({exc.__class__.__name__}); "
              f"trying mirror")
        download_from(MIRROR_BASE + source.name, dest)
        digest = sha256_of(dest)
        if digest != recorded:
            dest.unlink(missing_ok=True)
            raise RuntimeError(
                f"{source.name}: mirror copy sha256 {digest[:16]}... does not match "
                f"the manifest hash {recorded[:16]}.... Refusing to use it."
            ) from exc
        return "mirror"


def check_expectations(source, path: Path, problems: list) -> None:
    """Compare against sizes/row counts observed when the source was declared.

    A mismatch means upstream changed. That is reported loudly and never papered
    over -- the whole point of this project is that the numbers are traceable.
    """
    actual_bytes = path.stat().st_size
    if source.expected_bytes is not None and actual_bytes != source.expected_bytes:
        problems.append(
            f"{source.name}: size {actual_bytes} != expected {source.expected_bytes}"
        )
    if source.expected_rows is not None:
        with path.open("rb") as fh:
            actual_rows = sum(1 for _ in fh)
        if actual_rows != source.expected_rows:
            problems.append(
                f"{source.name}: {actual_rows} rows != expected {source.expected_rows}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", action="store_true", help="also fetch FEMA PDFs")
    ap.add_argument("--perils", default="fl,hu", help="comma-separated: fl,hu")
    ap.add_argument("--verify", action="store_true",
                    help="verify existing files only; download nothing")
    args = ap.parse_args()

    perils = [p.strip() for p in args.perils.split(",") if p.strip()]
    sources = for_perils(perils)
    if args.docs:
        sources = sources + DOC_SOURCES

    RAW.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    problems: list = []

    for source in sources:
        dest = RAW / source.name
        recorded = manifest.get(source.name)

        if dest.exists():
            digest = sha256_of(dest)
            if recorded and recorded.get("sha256") == digest:
                print(f"  ok       {source.name}")
                check_expectations(source, dest, problems)
                continue
            if recorded:
                problems.append(
                    f"{source.name}: on-disk sha256 {digest[:12]}... does not match "
                    f"manifest {recorded['sha256'][:12]}... -- local file was modified "
                    f"or upstream changed"
                )
                continue
        elif args.verify:
            problems.append(f"{source.name}: missing")
            continue

        if args.verify:
            continue

        print(f"  fetch    {source.name}")
        try:
            origin = download(source, dest, manifest)
        except (requests.RequestException, RuntimeError) as exc:
            problems.append(f"{source.name}: download failed: {exc}")
            continue
        if origin == "mirror":
            print(f"           served from mirror; sha256 matches manifest")

        digest = sha256_of(dest)
        check_expectations(source, dest, problems)
        manifest[source.name] = {
            "url": source.url,
            "sha256": digest,
            "bytes": dest.stat().st_size,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hazus_version": source.hazus_version,
            "peril": source.peril,
            "kind": source.kind,
            "note": source.note,
        }
        save_manifest(manifest)

    save_manifest(manifest)

    if problems:
        print("\nPROBLEMS:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"\n{len(sources)} sources verified. Manifest: {MANIFEST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
