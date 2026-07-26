"""Shared fixtures and helpers for hazus_curves tests."""

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "raw"
DATA = REPO / "data"
DIST = REPO / "dist"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require_file(path: Path, label: str = None):
    """Skip the calling test if path does not exist; fail loudly if it does but is empty."""
    label = label or str(path.relative_to(REPO))
    if not path.exists():
        pytest.skip(f"{label} not present (run the build first)")
    if path.stat().st_size == 0:
        pytest.fail(f"{label} exists but is empty -- build may have failed")
