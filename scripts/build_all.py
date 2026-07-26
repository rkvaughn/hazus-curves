#!/usr/bin/env python3
"""Run the whole pipeline: fetch, extract, verify, and build every artifact.

    python scripts/build_all.py                # flood only (fast, ~7 MB)
    python scripts/build_all.py --perils fl,hu # add hurricane (~103 MB download)

This is the one command a user of the repository needs in order to reproduce the
published database from upstream sources. Each step is also runnable on its own; see
the README.

Order matters: the flood-only database is built last-but-one so that
``dist/hazus_curves.sqlite`` remains the small default artifact, while the Parquet files
are left holding the full peril set for the website and for other engines.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(script: str, *args: str) -> None:
    label = " ".join([script, *args])
    print(f"\n=== {label}")
    result = subprocess.run([PY, str(REPO / "scripts" / script), *args], cwd=REPO)
    if result.returncode != 0:
        raise SystemExit(f"\n{label} failed with exit code {result.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--perils", default="fl", help="comma-separated: fl,hu")
    ap.add_argument("--docs", action="store_true",
                    help="also fetch FEMA release notes and technical manuals")
    args = ap.parse_args()
    perils = [p.strip() for p in args.perils.split(",") if p.strip()]

    fetch_args = ["--perils", ",".join(perils)]
    if args.docs:
        fetch_args.append("--docs")
    run("fetch.py", *fetch_args)

    run("build_flood.py")
    run("diff_versions.py")

    if "hu" in perils:
        run("build_hurricane.py")
        run("verify_hurricane_defect.py")

    # Small default artifact first, then the full Parquet set on top.
    run("build_db.py", "--perils", "fl")
    if "hu" in perils:
        run("build_db.py", "--perils", "fl,hu")

    print("\n=== done")
    print("  dist/hazus_curves.sqlite       flood only, the `install` default")
    if "hu" in perils:
        print("  dist/hazus_curves_full.sqlite  flood + hurricane")
    print("  dist/*.parquet                 all tables, for other engines and the site")
    print("\nNext:  python -m pytest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
