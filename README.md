# Kibutz_map_events: מפת קיבוץ להודעות

A simple Hebrew mobile web app for any kibbutz. You mark houses, roads, golf-cart paths or free-drawn lines on a clean map, add a short message, and share two images in WhatsApp.

- Phase 1 builds the map automatically from **OpenStreetMap** and **Overture Maps** buildings (OSM + Microsoft ML) with one command per kibbutz.
- Phase 2 adds the kibbutz's own lots layer, which is kept outside this repo.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/build_kibbutz.py ramat-hashofet --osm r21252389 --report
python3 -m http.server 8766   # open http://localhost:8766/?k=ramat-hashofet
```

See `CLAUDE.md` for the architecture, data sources, licences and privacy rules.

Map data © OpenStreetMap contributors (ODbL), Overture Maps Foundation, Microsoft.
