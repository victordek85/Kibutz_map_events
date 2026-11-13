# Changelog

All notable changes to **kibutz-map-events** are listed here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/):

- **MAJOR**: a change that breaks how people already use the app.
- **MINOR**: a new feature, or a visible change to an existing one.
- **PATCH**: bug fixes, wording tweaks and data refreshes.

Add every change under **Unreleased** as you make it. `python3 tools/release.py patch|minor|major` turns that section into a numbered release.

## [Unreleased]

The first version: a plug-and-play copy of the Yiftah map tool that works for any kibbutz.

### Added
- **An automatic map for any kibbutz**, built from free sources with one command (`tools/build_kibbutz.py <slug>`). The boundary, roads, footpaths and golf-cart paths, orchards, parks, water and named places come from OpenStreetMap. Building outlines come from Overture Maps: OSM buildings plus Microsoft's machine-learned buildings.
- When every Overpass server is busy, the build falls back to the OSM API for the place itself and to Overture's copy of the OSM roads, landuse and water.
- **A small `config.json` per kibbutz** for the things a person knows: landmark names, hand-placed spots (a clinic, a coffee cart), the gate, label priorities, and hand-drawn areas such as the pool or the central lawn.
- **Two kibbutzim:** Yiftah (the reference) and Ramat HaShofet (a kibbutz the pipeline had never seen). Open one with `?k=yiftah` or `?k=ramat-hashofet`, or pick from a list.
- **Phase 2 is ready for the Marom lots layer.** `tools/load_lots.py` reads a GeoJSON or Shapefile (WGS84 or ITM) with field names set per kibbutz. With `?lots=1` the lots become the main view, with names, numbers and search, and the buildings become an optional **מבנים** layer. Lots can be encrypted with a per-kibbutz password; the app then asks for it and shows the map without names when it's skipped.
- **Map credits** (© OpenStreetMap contributors, Overture Maps, Microsoft) appear on the map and at the bottom of every exported image.
- A coverage report for each kibbutz in `docs/`, and a draft Hebrew request to Marom for the lots layer.

### Kept from Yiftah v1.1
- The three modes (houses, roads, free draw), two-finger pan and zoom, long-press to erase, landmark labels that never overlap, the caption step, the two images with copy and share, and the one-screen phone layout.
