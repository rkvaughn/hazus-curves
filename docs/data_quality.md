# Data quality notes

Characteristics of the upstream Hazus data that users should know about. Everything here
is reproduced from the source unchanged — this project does not correct upstream values,
because correcting them would mean inventing them.

Each finding below is pinned by an automated test, so if any of it changes the build
fails rather than drifting silently.

## 1. Hurricane probabilities and loss ratios slightly exceed 1.0

The Hazus 6.1 wind workbook contains values marginally above the theoretical maximum of
1.0. Verified by scanning `HazusWindDamFunctions_Hazus61.xlsx` directly:

| Loss class | Points above 1.0 | Maximum value |
|---|---:|---:|
| `damage_slight` | 1,911 | 1.001 |
| `damage_moderate` | 982 | 1.001 |
| `building_loss` | 5,402 | 1.000052 |
| `content_loss` | 2 | 1.000001 |

Out of 11,284,020 hurricane points, so roughly 0.07%. The excursions are small enough to
be rounding artefacts in FEMA's own generation process, and they occur at high wind
speeds where the curves are saturating at 1.0 anyway.

**We publish them unchanged.** Clamping to 1.0 would be a silent, undocumented alteration
of federal data. If your analysis needs strict [0, 1] bounds, clamp explicitly in your own
code so the decision is visible in your work.

Pinned by `tests/test_units_and_ranges.py::test_hurricane_over_one_values_match_known_upstream_quirk`.

## 2. Nine building characteristic codes are missing from the Hazus decode table

`huListOfWindBldgTypes` describes each wind building type with a concatenated string of
five-character characteristic codes. `huListOfBldgChar` is the workbook's own dictionary
for decoding them — and it is incomplete. These codes appear in the data but have no
dictionary entry:

| Code | Occurrences |
|---|---:|
| `rcshg` | 960 |
| `rcssm` | 768 |
| `wtnor` | 520 |
| `wtjal` | 520 |
| `rcapr` | 416 |
| `rcagd` | 416 |
| `rcpnt` | 192 |
| `rccor` | 64 |
| `rccnt` | 16 |

Affected building types are `MSF1`, `MSF2`, `WSF1`, `WSF2` — single-family masonry and
wood. Several look like they may be roof-cover variants (`rc*`) and window/shutter
variants (`wt*`), but **we do not guess.** Assigning them a meaning we cannot source
would be fabrication.

Handling: characteristic strings are split positionally into five-character codes — which
is exact, not heuristic, since all 53 known codes are exactly five characters and all
6,116 characteristic strings have a length that is an exact multiple of five. Codes
present in the dictionary become typed attributes (`Roof Shape` = `Gable`, and so on).
Codes absent from it are preserved verbatim under the attribute key
`characteristic_unmapped_code`.

Result: 36,224 characteristics decoded, 3,872 preserved verbatim. No information is lost
and none is invented.

## 3. Flood curve values are integers stored as percentages

Flood `y` values are percent of replacement value, 0–100, and are whole numbers in the
source. Hurricane `y` values are **not** percentages — see below.

## 4. The nine hurricane loss classes do not share units

This is the most common way to misuse this dataset. `huDamLossFun` mixes three unit
systems in one table:

| Loss classes | Units | Range |
|---|---|---|
| `damage_slight`, `damage_moderate`, `damage_severe`, `damage_total` | exceedance probability | 0–1 |
| `building_loss`, `content_loss` | loss ratio | 0–1 |
| `loss_of_use` | **days** | observed max 1,566.751 |
| `debris_brick_wood`, `debris_concrete_steel` | **lbs/sq ft** | observed max ~137.9 |

Join the `curve_kind` table to get units rather than assuming them. Averaging across
these classes produces a meaningless number; the website refuses to do it.

## 5. Occupancy codes are space-padded upstream

`OccupancyTypes.csv` and several Hazus tables store fixed-width, space-padded values
(`"RES1 "`, `"COM1 "`). These are stripped on load. Whitespace is the only thing altered
anywhere in this pipeline, and a test asserts no published occupancy value has leading or
trailing whitespace.

## 6. Hazus 6.1's own release-note count does not match the extract

FEMA's Hazus 6.1 release notes state that *"Almost 300 new structure and 400 new content
damage functions were added."* Measured against this extract:

- Structure: **295** added — consistent with "almost 300".
- Contents: **311** added — not ~400.

We report what the data contains. The discrepancy may mean the release note counts
something this extract does not include. It is not resolved here.

See `docs/version_changes.md`.
