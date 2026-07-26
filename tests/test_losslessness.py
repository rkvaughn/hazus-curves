"""Losslessness: every source column is either mapped, a depth column, or explicitly ignored."""

import sys
from pathlib import Path

import pandas as pd
import pytest

from conftest import REPO, RAW

sys.path.insert(0, str(REPO))
from scripts.build_flood import (
    COLUMN_ROLES,
    IGNORED_COLUMNS,
    DATASETS,
    depth_of,
)


# ---------------------------------------------------------------------------
# Flood source tables
# ---------------------------------------------------------------------------

WORKBOOK_61 = "HazusFloodDamageFunctions_Hazus61.xlsx"


def _check_columns(df: pd.DataFrame, source_table: str) -> list:
    """Return a list of unaccounted column names for df."""
    unaccounted = []
    for col in df.columns:
        if depth_of(col) is not None:
            continue  # depth column -- accounted for
        if col in COLUMN_ROLES:
            continue  # mapped to a known role
        if (source_table, col) in IGNORED_COLUMNS:
            continue  # explicitly ignored with a reason
        unaccounted.append(col)
    return unaccounted


@pytest.mark.parametrize("damage_type,csv_name,sheet_name,_id", DATASETS)
def test_flood_40_losslessness(damage_type, csv_name, sheet_name, _id):
    """Every column in each 4.0 CSV is mapped, a depth column, or explicitly ignored."""
    fpath = RAW / csv_name
    if not fpath.exists():
        pytest.skip(f"raw/{csv_name} not present")
    df = pd.read_csv(fpath, dtype=object)
    unaccounted = _check_columns(df, csv_name.split(".")[0])
    assert not unaccounted, (
        f"{csv_name}: {len(unaccounted)} column(s) are not accounted for: "
        f"{unaccounted}. Add them to COLUMN_ROLES or IGNORED_COLUMNS with a reason."
    )


@pytest.mark.parametrize("damage_type,_csv,sheet_name,_id", DATASETS)
def test_flood_61_losslessness(damage_type, _csv, sheet_name, _id):
    """Every column in each 6.1 workbook sheet is mapped, a depth column, or explicitly ignored."""
    wb_path = RAW / WORKBOOK_61
    if not wb_path.exists():
        pytest.skip(f"raw/{WORKBOOK_61} not present")
    xl = pd.ExcelFile(wb_path)
    df = xl.parse(sheet_name)
    unaccounted = _check_columns(df, sheet_name)
    assert not unaccounted, (
        f"{sheet_name}: {len(unaccounted)} column(s) are not accounted for: "
        f"{unaccounted}. Add them to COLUMN_ROLES or IGNORED_COLUMNS with a reason."
    )


# ---------------------------------------------------------------------------
# Hurricane source table (best-effort; skip if workbook absent)
# ---------------------------------------------------------------------------

HU_WORKBOOK = "HazusWindDamFunctions_Hazus61.xlsx"

# Columns in huDamLossFun that are explicitly the key dimensions, not curve data.
# The wind speed columns (WS50..WS250) are the measurement columns; everything else
# is either a key or metadata.
_HU_KEY_COLS = {"wbID", "TERRAINID", "DamLossDescID"}


def test_hurricane_losslessness():
    """Every non-WS column in huDamLossFun is a recognized key dimension."""
    import openpyxl

    wb_path = RAW / HU_WORKBOOK
    if not wb_path.exists():
        pytest.skip(f"raw/{HU_WORKBOOK} not present")

    wb = openpyxl.load_workbook(wb_path, read_only=True)
    ws = wb["huDamLossFun"]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    wb.close()

    ws_cols = {h for h in header if h.startswith("WS")}
    non_ws = [h for h in header if h not in ws_cols]

    unaccounted = [c for c in non_ws if c not in _HU_KEY_COLS]
    assert not unaccounted, (
        f"huDamLossFun: unexpected non-WS columns that are not key dimensions: "
        f"{unaccounted}. Update _HU_KEY_COLS or the hurricane build if this is intentional."
    )
