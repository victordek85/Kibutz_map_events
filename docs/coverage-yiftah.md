# Coverage: יפתח (yiftah)

Built 2026-11-13 by `tools/build_kibbutz.py yiftah`. Overture release 2026-10-21.0.

## What the automatic map has

- **Boundary:** OSM place relation 21216303; about 38 ha.
- **Buildings:** 275 in the map box, 269 of them inside the village boundary (OSM 207, Microsoft ML 62, other 0).
- **Roads:** 52 lines, 15.0 km. **Footpaths / golf-cart paths:** 33 lines, 2.9 km.
- **Areas:** cemetery 1, farm 4, green 6, orchard 1, water 2, wood 5.
- **Landmarks** (named buildings): 9: אגס, אולם ספורט, בית אריזה, גן דולב, מאפייה, מועדון לחבר, מזכירות, מינימרקט, שקד.
- **Spots** (named places with no building): 8: בית עלמין, מצפור יפתח, ספרייה, סביון, מגרשי ספורט, בריכה, קפה גליקי, קופת חולים.
- **Gate:** config.json.

## Compared with the real lots (Yiftah only)

Reference: the old Yiftah app's lots file, read in place (271 features). Only totals are shown here. No names or house numbers are copied.

| Marom type | Lots | Has a building | from OSM | from Microsoft ML only | other | No building |
|---|---:|---:|---:|---:|---:|---:|
| מגרש | 178 | 165 (93%) | 162 | 3 | 0 | 13 |
| מבנה | 93 | 62 (67%) | 56 | 6 | 0 | 31 |

"Has a building" counts a real overlap (at least 15 m², or 30% of the building), so one building that crosses into a neighbour's lot counts for both. The strict count needs a building's centre inside the lot:

- מגרש: 111 of 178 (62%) by the strict count.
- מבנה: 48 of 93 (52%) by the strict count.

Where the house lots with no building outline are (village box split 3×3, north at the top, west on the left):

| | west | middle | east |
|---|---:|---:|---:|
| north | 1 | 2 | 1 |
| middle | 0 | 7 | 2 |
| south | 0 | 0 | 0 |

## What a person should still check

- Landmark names: add the dining hall, secretariat, clinic, kindergartens, pool and so on in `config.json` (`landmarks`, by a point inside the building).
- The gate position (`gate` in `config.json`), when it is a guess or missing.
- Houses with no outline: in phase 1 they can only be marked with free draw. Phase 2 (the Marom lots layer) fixes this.
