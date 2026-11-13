# Coverage: רמת השופט (ramat-hashofet)

Built 2026-11-13 by `tools/build_kibbutz.py ramat-hashofet`. Overture release 2026-10-21.0.

## What the automatic map has

- **Boundary:** OSM place relation 21252389; about 33 ha.
- **Buildings:** 349 in the map box, 319 of them inside the village boundary (OSM 131, Microsoft ML 188, other 0).
- **Roads:** 74 lines, 13.1 km. **Footpaths / golf-cart paths:** 35 lines, 3.8 km.
- **Areas:** cemetery 1, farm 6, green 19, water 1, wood 6.
- **Landmarks** (named buildings): 1: רפת.
- **Spots** (named places with no building): 4: בית עלמין, יער עין השופט, יוליאן מק, הפינה של יובל יפה.
- **Gate:** OSM barrier=gate.

## What a person should still check

- Landmark names: add the dining hall, secretariat, clinic, kindergartens, pool and so on in `config.json` (`landmarks`, by a point inside the building).
- The gate position (`gate` in `config.json`), when it is a guess or missing.
- Houses with no outline: in phase 1 they can only be marked with free draw. Phase 2 (the Marom lots layer) fixes this.
