# Kibutz_map_events (kibutz-map-events)

A plug-and-play version of the Yiftah map tool (github.com/victordek85/yiftah_mark_a_map, v1.1.0) that works for **any kibbutz**. Someone marks houses, roads or golf-cart paths, or draws freely on a clean map of the kibbutz. They add a caption, such as "הפסקת מים מחר 8:00–12:00", and get two images (a close-up and an overview) to share in the kibbutz WhatsApp groups.

The UI is Hebrew and RTL, and it's built for phones first. The interaction model, the export flow and the phone layout are the same as Yiftah v1.1. **Yiftah's `CLAUDE.md` is the spec for behaviour**: modes, two-finger pan, long-press erase, label collision, the caption band and the share flow. This file covers what is new: the data pipeline, the two phases and privacy.

- Repo: https://github.com/victordek85/Kibutz_map_events (public). Work happens on the `v0.1` branch.
- No Pages site yet. A release would publish `main`, so turn Pages on only after "release it".

---

## Two phases

| | Phase 1: automatic map (now) | Phase 2: final map (after the Marom order) |
|---|---|---|
| Markable units | building outlines (OSM + Microsoft ML, via Overture) | lots from Marom's "נכסים" layer |
| Names / numbers | none (only landmark names from OSM and config) | NUM, DAYAR, MAKOR, GUSH, HELKA |
| Buildings | the main view | an optional "מבנים" layer, drawn dashed over the lots |
| Where the data lives | this repo (`kibbutzim/<slug>/map.js`), all open data | **outside this repo**, one place per kibbutz |
| URL | `?k=<slug>` | `?k=<slug>&lots=1` (or `<meta name="kmap-lots" content="1">`) |

The user prefers lots as the main view once a kibbutz has them. Don't switch that around.

---

## Files

| Path | What |
|---|---|
| `index.html` | The whole app: HTML, CSS and JS, with no build step and no libraries. It loads `kibbutzim/<slug>/map.js` and, with `lots=1`, `lots.js` or `lots.enc.js`. Without `?k=` it shows a list of kibbutzim from `kibbutzim/index.js`. |
| `kibbutzim/<slug>/config.json` | **Hand-edited.** The human fixes (see below). |
| `kibbutzim/<slug>/raw/` | Raw downloads (OSM and Overture), so rebuilds don't hit the servers. Committed: it's open data. |
| `kibbutzim/<slug>/map.js` | **Generated**: `window.KMAP`. Don't edit it. |
| `kibbutzim/index.js` | Generated list of kibbutzim. |
| `tools/build_kibbutz.py` | The pipeline: resolve → fetch → build. |
| `tools/fetch.py` | Overpass (with mirrors and backoff), the OSM API, Nominatim and Overture/DuckDB. |
| `tools/load_lots.py` | Phase 2: the lots loader (stub, tested only with fake data). |
| `tools/coverage_report.py` | Writes `docs/coverage-<slug>.md`. |
| `tools/export_html.py` | Writes `exports/<slug>.html` (git-ignored): one self-contained file with `map.js` inlined, for sending to a reviewer. Never used with lots. |
| `tools/release.py` | Cuts a release. Same rules as Yiftah. |
| `samples/fake_lots.geojson` | **Invented** lots for testing the loader: made-up names, plain rectangles. |
| `docs/` | Coverage reports and the draft Hebrew request to Marom (`marom-request.he.md`). |
| `.venv/`, `private/` | Git-ignored. `private/<slug>/` is the loader's default output. |

Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. Preview: `python3 -m http.server 8766` from the repo root, then open `http://localhost:8766/?k=ramat-hashofet`. Port 8765 belongs to the Yiftah app.

---

## Pipeline: `tools/build_kibbutz.py`

```bash
.venv/bin/python tools/build_kibbutz.py ramat-hashofet --osm r21252389 --report   # first build of a new kibbutz
.venv/bin/python tools/build_kibbutz.py yiftah --name יפתח --report
.venv/bin/python tools/build_kibbutz.py yiftah            # rebuild from raw/ after editing config.json (seconds)
.venv/bin/python tools/build_kibbutz.py yiftah --fetch    # download again (new OSM edits / Overture release)
```

1. **Resolve.** The input is `--name`, `--osm r|w|n<id>` or `--bbox W,S,E,N`, saved into `config.json` on the first run. The boundary comes from the first of these that exists:
   1. `config.json` `boundary`
   2. the place's own polygon (a relation or way)
   3. the OSM `landuse=residential` around the place node
   4. `--bbox`

   The map box is the boundary plus `margin_m` (default 250 m), or `clip_bbox`.
2. **Fetch.**
   - **OSM from Overpass:** roads, paths, landuse, leisure, water, named amenities and buildings, and gate nodes. It rotates between `overpass-api.de`, `overpass.private.coffee`, `maps.mail.ru` and `overpass.kumi.systems`, with exponential backoff and an identifying User-Agent.
   - **If every Overpass server fails (as they did on 2026-11-13):**
     - the place comes from the OSM API (`/relation/<id>/full`, one small read) or from Nominatim when looking up by name;
     - the features come from **Overture's transportation and base themes**, which are derived from OSM.
     - `meta.osm_source` in `map.js` records which source was used.
   - **Buildings:** Overture `theme=buildings/type=building` for the latest release from `https://stac.overturemaps.org/catalog.json`, read with DuckDB over `s3://overturemaps-us-west-2/release/<rel>/...` and a bbox filter. Yiftah: 275 buildings (207 OSM + 68 Microsoft ML) in about 25 s.
3. **Build** writes `map.js`:
   - `units`: buildings as `{id, gid (Overture id), src: osm|ms|other, c (label point), geom (MultiPolygon), v (1 = inside the boundary + 30 m), name, anchor}`
   - `roads` and `paths` as polylines
   - `areas` as `{k: farm|wood|orchard|green|cemetery|water, g}`
   - `spots` as `{name, c, icon: dot|house|none}`
   - `boundary` and `gate`
   - `meta`: attribution, label priority and so on

**Auto landmarks:** named OSM buildings, and named amenities, shops or offices inside a building, become green landmarks. A named place outside any building becomes a spot. Names that look private ("משפחת …") and plain houses are never labelled automatically.

**Gate:** from `config.json`; else an OSM `barrier=gate` on a road near the boundary; else the biggest road that crosses the boundary (a guess, and the report says so).

### `config.json`: the human fixes

```jsonc
{
  "name": "רמת השופט", "name_en": "Ramat HaShofet",
  "source": {"osm": "r21252389"},          // or {"name": "..."} or {"bbox": [W,S,E,N]}
  "margin_m": 250, "clip_bbox": null,       // the map box
  "boundary": null,                         // a ring to override the OSM boundary
  "landmarks": [{"name": "חדר אוכל", "at": [lng, lat], "label_at": [lng, lat]}],  // by a POINT inside the building
  "spots": [{"name": "קופת חולים", "at": [lng, lat], "icon": "house"}],
  "gate": [lng, lat],
  "label_priority": ["חדר אוכל", "מזכירות"],   // which landmark wins when labels clash
  "zoomed_in_only": ["ספרייה"],
  "hide_landmarks": ["..."],                // drop an OSM name you don't want
  "areas": [{"kind": "water", "ring": [[lng, lat], ...]}],   // hand-drawn pool, lawn...
  "lots_fields": {"num": "NUM", "name": "DAYAR", "kind": "MAKOR", "gush": "GUSH", "helka": "HELKA", "id": "ORIG_ID"}
}
```

Landmarks are found **by a point, not by a building id**, so they survive a new Overture release. A landmark point with no building under it, within 6 m, becomes a spot, and the build prints a warning.

---

## Data sources and licences

| Source | Used for | Licence and what we must do |
|---|---|---|
| OpenStreetMap (Overpass, OSM API, Nominatim) | boundary, roads, paths, landuse, water, names, gates | **ODbL 1.0.** Credit "© OpenStreetMap contributors" on the map and on every image (done). `map.js` is a derived database: if it's published, it's under the ODbL too. Follow the Nominatim and API usage policies: a few requests per build, a User-Agent, no bulk downloads. |
| Overture Maps, buildings | building outlines | **ODbL.** Credit OSM, Overture and Microsoft (done; `meta.datasets` lists what's actually present). |
| Overture transportation and base | fallback for the OSM features | **ODbL**, derived from OSM. Same credit. |
| Marom "נכסים" layer (phase 2) | lots, numbers, names | **Bought per kibbutz.** Used only for that kibbutz's map, never published openly. |

**Never:** scrape Marom or any other closed system; trace or copy Marom shapes into OSM; upload anything to OSM; use Google or other map tiles (their terms forbid it).

---

## Privacy rules

- **No personal data in this repo, ever.** That means no residents' names, no Marom data and no scraped files. The only lots file here is `samples/fake_lots.geojson`, with invented names.
- `tools/load_lots.py` keeps only the mapped fields and drops everything else (ARNONA, meters, notes…). It refuses to write inside the repo unless the input is under `samples/`. `kibbutzim/*/lots*.js` and `private/` are git-ignored as a second guard.
- For the Yiftah comparison, `tools/coverage_report.py` reads the old app's lots file **in place** and writes only totals.
- `robots.txt` and `<meta name="robots" content="noindex,nofollow">` keep search engines away.
- **Anything a website loads is public to whoever has the link, whatever the repo's visibility.** A private GitHub repo doesn't hide a Pages site's files.

### Phase 2: where the real data lives, and how to protect it

Each kibbutz gets its **own deployment**: a separate repo or folder outside this one. It holds a copy of `index.html` (with `kmap-default` and `kmap-lots` set), `kibbutzim/<slug>/map.js`, and the lots file from `load_lots.py --out <that folder>`. The options, from simplest to safest:

1. **A. Public but unlisted, with the kibbutz's written approval** (how Yiftah works today). A plain `lots.js`, noindex, and the link shared only in kibbutz groups. Anyone with the link sees the names. It's simple, and fine only with the secretariat's explicit OK.
2. **B. A per-kibbutz password, still on free static hosting (recommended).**
   - `load_lots.py --password …` writes `lots.enc.js`: the whole lots payload, names and shapes, encrypted with AES-GCM-256, with the key from PBKDF2-SHA256 (310k iterations, random salt).
   - The app asks for the password once per tab, decrypts it in the browser with WebCrypto, and keeps the password in `sessionStorage` only. "בלי שמות" shows the phase-1 map.
   - **What it protects:** the files can sit in a public repo or Pages site, and without the password they're noise.
   - **What it doesn't protect:** anyone who has the password, which is shared kibbutz-wide; a weak password, which can be brute-forced offline, so use a long passphrase; and screenshots.
   - **When residents change:** re-encrypt with a new password.
   - **Implemented and tested with the fake sample.**
3. **C. Real access control,** if a kibbutz needs per-person logins: Cloudflare Pages with Cloudflare Access (a free tier with email one-time codes), or Netlify with password protection (paid). This has more moving parts and isn't built.

Suggested default: **B for every new kibbutz, A only with written approval.**

---

## Phase 2 plan

1. The kibbutz orders **one layer** from Marom: "נכסים", with shapes and NUM, DAYAR, MAKOR, GUSH, HELKA (+ ORIG_ID), all features, as GeoJSON (or a full Shapefile) in WGS84 (or ITM with a `.prj`). The draft request is `docs/marom-request.he.md`. Yiftah's own version, which also asks for a separate buildings layer because open mapping near the border is thin, is `docs/marom-request-yiftah.he.md`.
2. Run `tools/load_lots.py <slug> <file> --map <field names if they differ> --out <deployment dir> [--password …]`.
3. Copy `index.html` and `kibbutzim/<slug>/map.js` into the deployment, and set `kmap-default` and `kmap-lots`.
4. In `config.json`, the landmark points now also name the lots that contain them.
5. Check the result at phone size, then publish the deployment, never this repo, with the data.

Still to do in phase 2 (not in v0.1): a deploy script that assembles the deployment folder; refreshing the lots when residents change; and matching each lot to its building, if wanted.

---

## Results so far (v0.1, 2026-11-13)

- **Ramat HaShofet** (never seen before): 349 buildings, 319 of them in the village (139 OSM + 210 Microsoft ML across the map box), 13 km of roads, 3.8 km of paths, the gate from OSM, and one landmark (רפת). It needs a person to add landmark names in `config.json`. See `docs/coverage-ramat-hashofet.md`.
- **Yiftah** (reference): 275 buildings (207 OSM + 68 Microsoft ML). Of the 178 Marom house lots, 165 (93%) overlap a building outline, and 111 (62%) have a building's centre inside them. The gaps sit in the middle and north of the old core. Four of the 13 landmarks have no outline (ספרייה, סביון, מגרשי ספורט, בריכה) and show as spots. OSM's boundary for Yiftah includes the southern farm area, so the full view is wider than the old app's. See `docs/coverage-yiftah.md`. For now Yiftah's `config.json` holds no hand-made tags, so it shows the plain free-source map. The tags from the old app (13 landmarks, 2 spots, the gate, the pool and lawn, the framing) are kept in `kibbutzim/yiftah/manual.json`, which the build doesn't read. They return later as the manual layer, next to the Marom layer.
- The reference file read for Yiftah is `data/parcels_raw.geojson` (271 lots). The old app's `extra_parcels` (12 more) aren't included.

## Versions and branches

- The version lives in `<meta name="app-version">` in `index.html` and starts at 0.0.0. The first release, `tools/release.py minor`, makes it 0.1.0.
- Work happens on a version branch (`v0.1`). Push it freely. **Never merge to `main`, tag or release until the user says "release it".** Then: merge into `main`, run `python3 tools/release.py minor`, `git push --follow-tags`, and `gh release create …`.
- Every user-visible change gets a line under **Unreleased** in `CHANGELOG.md`, in the same commit.

## Testing

There are no automated tests. Use the local preview (`python3 -m http.server 8766`) at **393×659, 393×852 and desktop**, for both `?k=yiftah` and `?k=ramat-hashofet`, and for `?k=ramat-hashofet&lots=1` after running the fake-sample loader:

```bash
.venv/bin/python tools/load_lots.py ramat-hashofet samples/fake_lots.geojson --map id=OBJECTID,num=MISPAR,name=SHEM_DAYAR,kind=SUG --out kibbutzim/ramat-hashofet
```

The fake output is git-ignored; delete it after testing. Use Yiftah's smoke-test checklist, plus: the credits show on the map and on both images; and the "מבנים" toggle appears only with lots.

## Conventions

The same as Yiftah: a single `index.html` with no dependencies; CSS variables with light and dark values; short Hebrew UI copy; English comments; flexbox and `gap`; a 16 px side gutter with no sideways scroll on phones; commit messages that say what changed and why.
