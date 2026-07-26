# Hurricane multi-family curve defect — independent verification

FEMA's Hazus 7.1 release notes (RSA-21186) disclose that in Hazus 6.1 and 7.0
the 2- and 3-story multi-family wind damage functions were inadvertently
overwritten with copies of the 1-story functions.

This project verified that claim directly against the Hazus 6.1 data it
publishes, by comparing each 2-/3-story curve with the 1-story curve having
identical building characteristics, terrain, and loss class.

## Result

**15,200 of 34,560** 2-/3-story multi-family curves 
(44.0%) are byte-identical to their 1-story counterpart.
The defect is real and measurable in the published data.

| Building type | Curves | Identical to 1-story | Share |
|---|---:|---:|---:|
| MMUH2 | 11,520 | 5,120 | 44.4% |
| MMUH3 | 11,520 | 5,120 | 44.4% |
| WMUH2 | 5,760 | 2,560 | 44.4% |
| WMUH3 | 5,760 | 2,400 | 41.7% |

## How this is represented in the data

| Column | Meaning |
|---|---|
| `defect_flag` | FEMA disclosed that this building-type family is affected. |
| `defect_verified` | `identical_to_1_story` — measured here to be a duplicate. `differs_from_1_story` — not a duplicate. |

`differs_from_1_story` does **not** mean the curve is correct. FEMA also
reported that mitigated variants (with shutters, or stronger roof deck
attachment) lacked correct data in a different way, and that its 7.1 fix
*synthesised* replacements for those rather than recovering originals.
Absence of evidence is recorded as absence of evidence, not as absence of the
defect.

## Why these curves are published rather than withheld

A flagged curve is more useful than a missing one, and the flag is itself
information that no other open dataset carries. Hazus 7.1+ contains the
corrected functions but is not publicly extractable without Windows, ArcGIS
Pro, and SQL Server.

Reproduce with `python scripts/verify_hurricane_defect.py`.
