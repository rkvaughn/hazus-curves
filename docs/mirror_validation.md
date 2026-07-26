# Mirror validation

SHA-256 comparison of the recorded manifest against the local copies, the
upstream sources, and (when checked) this project's own re-hosted release
assets.

This exists because upstream sources decay. FEMA's `fema-ftp-snapshot` S3
bucket, still referenced by FEMA's own FAST repository, no longer exists.

Last run: 2026-07-26T16:06:48+00:00

| File | Bytes | Local vs manifest | Upstream |
|---|---:|---|---|
| `flBldgStructDmgFn.csv` | 98,616 | match | - |
| `flBldgContDmgFn.csv` | 86,626 | match | - |
| `flBldgInvDmgFn.csv` | 18,141 | match | - |
| `Building_DDF_Riverine_LUT_Hazus4p0.csv` | 33,699 | match | - |
| `Building_DDF_CoastalA_LUT_Hazus4p0.csv` | 11,582 | match | - |
| `Building_DDF_CoastalV_LUT_Hazus4p0.csv` | 11,571 | match | - |
| `Content_DDF_Riverine_LUT_Hazus4p0.csv` | 37,054 | match | - |
| `Content_DDF_CoastalA_LUT_Hazus4p0.csv` | 12,120 | match | - |
| `Content_DDF_CoastalV_LUT_Hazus4p0.csv` | 12,116 | match | - |
| `Inventory_DDF_LUT_Hazus4p0.csv` | 9,849 | match | - |
| `OccupancyTypes.csv` | 4,959 | match | - |
| `HazusFloodDamageFunctions_Hazus61.xlsx` | 403,618 | match | - |
| `HazusWindDamFunctions_Hazus61.xlsx` | 102,182,624 | match | - |
| `flUtilFltyDmgFn.csv` | 7,480 | match | - |

Reproduce with `python scripts/validate_mirror.py`.
