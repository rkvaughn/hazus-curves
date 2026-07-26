"""Tests for hazus_curves/sources.py and the raw/ manifest integrity."""

import json
from pathlib import Path

import pytest

from conftest import REPO, RAW, sha256_of

import sys
sys.path.insert(0, str(REPO))
from hazus_curves.sources import ALL_SOURCES, DATA_SOURCES, for_perils


# ---------------------------------------------------------------------------
# Registry structure
# ---------------------------------------------------------------------------

def test_all_source_names_are_unique():
    names = [s.name for s in ALL_SOURCES]
    duplicates = [n for n in names if names.count(n) > 1]
    assert not duplicates, f"Duplicate source names: {sorted(set(duplicates))}"


def test_all_sources_have_non_empty_url_or_note():
    bad = []
    for s in ALL_SOURCES:
        if not s.url or not s.url.strip():
            bad.append(f"{s.name}: empty url")
        # note is optional (empty string is valid per the dataclass default)
    assert not bad, "\n".join(bad)


def test_for_perils_fl_excludes_hurricane_only():
    fl_sources = for_perils(["fl"])
    hu_only = [s for s in fl_sources if s.peril == "hu"]
    assert not hu_only, (
        f"for_perils(['fl']) returned hurricane-only sources: "
        f"{[s.name for s in hu_only]}"
    )


def test_for_perils_fl_includes_all_peril_sources():
    fl_sources = for_perils(["fl"])
    names = {s.name for s in fl_sources}
    all_shared = [s for s in DATA_SOURCES if s.peril == "all"]
    missing = [s.name for s in all_shared if s.name not in names]
    assert not missing, (
        f"for_perils(['fl']) is missing 'all'-peril sources: {missing}"
    )


def test_for_perils_fl_includes_fl_sources():
    fl_sources = for_perils(["fl"])
    names = {s.name for s in fl_sources}
    fl_only = [s for s in DATA_SOURCES if s.peril == "fl"]
    missing = [s.name for s in fl_only if s.name not in names]
    assert not missing, (
        f"for_perils(['fl']) is missing fl-peril sources: {missing}"
    )


# ---------------------------------------------------------------------------
# MANIFEST.json integrity (skip if absent)
# ---------------------------------------------------------------------------

MANIFEST_PATH = RAW / "MANIFEST.json"


def _load_manifest():
    if not MANIFEST_PATH.exists():
        pytest.skip("raw/MANIFEST.json not present")
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_sha256_matches_files():
    manifest = _load_manifest()
    failures = []
    for name, entry in manifest.items():
        fpath = RAW / name
        if not fpath.exists():
            # Missing files are reported, not skipped — manifest says they should exist
            failures.append(f"{name}: listed in MANIFEST but not on disk")
            continue
        actual = sha256_of(fpath)
        expected = entry["sha256"]
        if actual != expected:
            failures.append(
                f"{name}: sha256 mismatch\n"
                f"  manifest: {expected}\n"
                f"  on disk:  {actual}"
            )
    assert not failures, "\n".join(failures)


def test_manifest_bytes_match_files():
    manifest = _load_manifest()
    failures = []
    for name, entry in manifest.items():
        fpath = RAW / name
        if not fpath.exists():
            failures.append(f"{name}: listed in MANIFEST but not on disk")
            continue
        actual = fpath.stat().st_size
        expected = entry["bytes"]
        if actual != expected:
            failures.append(
                f"{name}: size mismatch  manifest={expected}  on_disk={actual}"
            )
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# expected_bytes / expected_rows from Source declarations
# ---------------------------------------------------------------------------

def test_declared_expected_bytes_match_on_disk():
    """Where a Source declares expected_bytes, the file on disk must match exactly."""
    failures = []
    for s in ALL_SOURCES:
        if s.expected_bytes is None:
            continue
        fpath = RAW / s.name
        if not fpath.exists():
            pytest.skip(f"raw/{s.name} not present")
        actual = fpath.stat().st_size
        if actual != s.expected_bytes:
            failures.append(
                f"{s.name}: expected_bytes={s.expected_bytes}  actual={actual}"
            )
    assert not failures, "\n".join(failures)


def test_declared_expected_rows_match_on_disk():
    """Where a Source declares expected_rows (CSV row count including header), verify it."""
    import csv

    failures = []
    for s in ALL_SOURCES:
        if s.expected_rows is None:
            continue
        fpath = RAW / s.name
        if not fpath.exists():
            pytest.skip(f"raw/{s.name} not present")
        with open(fpath, newline="", encoding="utf-8-sig") as f:
            actual = sum(1 for _ in csv.reader(f))
        if actual != s.expected_rows:
            failures.append(
                f"{s.name}: expected_rows={s.expected_rows}  actual={actual}"
            )
    assert not failures, "\n".join(failures)
