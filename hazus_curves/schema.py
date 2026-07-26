"""The one schema definition.

Every engine's DDL, the Parquet writer, and the losslessness test all read from here,
so the SQLite / DuckDB / PostgreSQL / Snowflake representations cannot drift apart.

Design notes
------------
The published model is tidy: one observation per row, nothing encoded in column names.
Sources are wide (``m4..p24`` for flood, one column per wind speed for hurricane) and
that shape does not survive into anything we publish.

Perils are genuinely heterogeneous -- flood is keyed by occupancy x zone x stories x
basement, hurricane by building type x wind building characteristics x terrain. Rather
than widening ``curves`` for every peril, peril-specific keys live in
``curve_attributes`` as key/value rows. Adding earthquake later adds rows, not columns.
"""

from dataclasses import dataclass
from typing import List

TEXT, INT, REAL, BOOL = "TEXT", "INT", "REAL", "BOOL"

# Per-engine physical types. Keep every engine in this map or DDL generation fails
# loudly rather than emitting something plausible-but-wrong.
TYPE_MAP = {
    "sqlite":     {TEXT: "TEXT", INT: "INTEGER", REAL: "REAL", BOOL: "INTEGER"},
    "duckdb":     {TEXT: "VARCHAR", INT: "INTEGER", REAL: "DOUBLE", BOOL: "BOOLEAN"},
    "postgresql": {TEXT: "TEXT", INT: "INTEGER", REAL: "DOUBLE PRECISION",
                   BOOL: "BOOLEAN"},
    "snowflake":  {TEXT: "VARCHAR", INT: "NUMBER(38,0)", REAL: "FLOAT",
                   BOOL: "BOOLEAN"},
}

# Snowflake has no CREATE INDEX -- it uses micro-partition pruning instead. Emitting
# index DDL there produces SQL that fails at execution time.
SUPPORTS_INDEXES = {"sqlite", "duckdb", "postgresql"}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    null: bool = True
    doc: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    columns: List[Column]
    pk: List[str]
    doc: str = ""
    indexes: tuple = ()


CURVES = Table(
    "curves",
    [
        Column("curve_id", TEXT, False, "Stable synthetic key: peril-version-type-id."),
        Column("peril", TEXT, False, "fl = flood, hu = hurricane wind."),
        Column("hazus_version", TEXT, False, "Hazus release the content represents."),
        Column("damage_type", TEXT, False,
               "structure | contents | inventory | downtime."),
        Column("occupancy", TEXT, True,
               "Hazus occupancy class (RES1, COM1, ...). Null where not applicable."),
        Column("building_type", TEXT, True,
               "Hazus specific building type. Hurricane; null for flood."),
        Column("source_agency", TEXT, True,
               "Originating agency, verbatim from Hazus (e.g. 'USACE - Galveston')."),
        Column("description", TEXT, True, "Hazus description, verbatim."),
        Column("defect_flag", TEXT, True,
               "Non-null when FEMA has disclosed a defect in this curve. See "
               "docs/provenance.md. Null means no known defect, NOT 'verified correct'."),
        Column("source_file", TEXT, False, "File in raw/ this row came from."),
        Column("source_table", TEXT, False, "Sheet or table within that file."),
        Column("source_row_id", TEXT, False, "Native Hazus primary key, verbatim."),
    ],
    pk=["curve_id"],
    doc="One row per damage/vulnerability curve.",
    indexes=(("curves_peril_occ", ["peril", "occupancy"]),
             ("curves_srcagency", ["source_agency"])),
)

CURVE_POINTS = Table(
    "curve_points",
    [
        Column("curve_id", TEXT, False),
        Column("x", REAL, False,
               "flood: depth in feet relative to first finished floor (-4..24). "
               "hurricane: 3-second peak gust in mph. Units in curve_kind."),
        Column("y", REAL, True,
               "Damage as percent of replacement value. NULL means the source was "
               "empty -- gaps are preserved, never interpolated or filled."),
    ],
    pk=["curve_id", "x"],
    doc="Tidy long-format curve points. One row per (curve, x).",
)

CURVE_ATTRIBUTES = Table(
    "curve_attributes",
    [
        Column("curve_id", TEXT, False),
        Column("key", TEXT, False, "Attribute name, e.g. flood_zone, basement, terrain."),
        Column("value", TEXT, True, "Attribute value as text, verbatim from source."),
    ],
    pk=["curve_id", "key"],
    doc="Peril-specific keying dimensions. This is what makes the unified schema "
        "lossless and peril-pluggable.",
    indexes=(("curve_attr_kv", ["key", "value"]),),
)

CURVE_KIND = Table(
    "curve_kind",
    [
        Column("peril", TEXT, False),
        Column("damage_type", TEXT, False),
        Column("x_name", TEXT, False),
        Column("x_units", TEXT, False),
        Column("y_name", TEXT, False),
        Column("y_units", TEXT, False),
        Column("interpolation", TEXT, False, "How to read between points."),
        Column("notes", TEXT, True),
    ],
    pk=["peril", "damage_type"],
    doc="What x and y actually mean, per peril. Consumers should read this rather "
        "than assume units.",
)

ASSIGNMENT_RULES = Table(
    "assignment_rules",
    [
        Column("rule_id", TEXT, False),
        Column("peril", TEXT, False),
        Column("hazus_version", TEXT, False),
        Column("damage_type", TEXT, False),
        Column("occupancy", TEXT, True),
        Column("flood_zone", TEXT, True, "Riverine | CoastalA | CoastalV."),
        Column("stories", TEXT, True),
        Column("basement", TEXT, True),
        Column("curve_id", TEXT, True, "Curve this combination selects by default."),
        Column("source_file", TEXT, False),
        Column("source_table", TEXT, False),
        Column("notes", TEXT, True),
    ],
    pk=["rule_id"],
    doc="Hazus's own default curve selection. Note that Hazus 7.0 changed the coastal "
        "selection rule (depth-limited at 3 ft and 6 ft) without changing any curve; "
        "that rule is recorded here, not as curve data.",
)

DIM_OCCUPANCY = Table(
    "dim_occupancy",
    [
        Column("occupancy", TEXT, False),
        Column("category", TEXT, True),
        Column("description", TEXT, True),
    ],
    pk=["occupancy"],
    doc="Hazus occupancy classes. Source values are space-padded; stripped on load.",
)

DIM_BUILDING_TYPE = Table(
    "dim_building_type",
    [
        Column("building_type", TEXT, False),
        Column("description", TEXT, True),
    ],
    pk=["building_type"],
    doc="Hazus specific building types (hurricane).",
)

PROVENANCE = Table(
    "provenance",
    [
        Column("source_file", TEXT, False),
        Column("url", TEXT, False),
        Column("sha256", TEXT, False),
        Column("bytes", INT, False),
        Column("retrieved_at", TEXT, False),
        Column("hazus_version", TEXT, False),
        Column("note", TEXT, True),
    ],
    pk=["source_file"],
    doc="Integrity record for every upstream file, copied from raw/MANIFEST.json so "
        "the database is self-describing once detached from the repo.",
)

TABLES = [
    CURVES, CURVE_POINTS, CURVE_ATTRIBUTES, CURVE_KIND,
    ASSIGNMENT_RULES, DIM_OCCUPANCY, DIM_BUILDING_TYPE, PROVENANCE,
]


def ddl(engine: str, tables=None) -> str:
    """Render CREATE TABLE + CREATE INDEX for one engine."""
    if engine not in TYPE_MAP:
        raise ValueError(
            f"unsupported engine {engine!r}; known: {sorted(TYPE_MAP)}"
        )
    types = TYPE_MAP[engine]
    out = []
    for t in tables or TABLES:
        cols = []
        for c in t.columns:
            cols.append(
                f"    {c.name} {types[c.type]}" + ("" if c.null else " NOT NULL")
            )
        cols.append(f"    PRIMARY KEY ({', '.join(t.pk)})")
        body = ",\n".join(cols)
        out.append(f"-- {t.doc}\nCREATE TABLE IF NOT EXISTS {t.name} (\n{body}\n);")
        if engine in SUPPORTS_INDEXES:
            for idx_name, idx_cols in t.indexes:
                out.append(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} "
                    f"ON {t.name} ({', '.join(idx_cols)});"
                )
    return "\n\n".join(out) + "\n"
