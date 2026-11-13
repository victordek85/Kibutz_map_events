#!/usr/bin/env python3
"""Build the automatic map for one kibbutz from free, open sources.

    .venv/bin/python tools/build_kibbutz.py <slug> [--name NAME | --osm r123|n123|w123 | --bbox W,S,E,N]
                                                    [--fetch] [--report]

  slug      folder name under kibbutzim/, e.g. ramat-hashofet
  --name    a Hebrew or English place name to look up in OSM (first build only)
  --osm     an OSM place id: r=relation, n=node, w=way (first build only)
  --bbox    a lng/lat box, when OSM has no usable place (first build only)
  --fetch   download again even if raw/ already has the data
  --report  also write docs/coverage-<slug>.md

The first run creates kibbutzim/<slug>/config.json from the arguments. After
that `tools/build_kibbutz.py <slug>` alone rebuilds.

Steps:
  1. resolve   find the place in OSM; boundary = place relation, else the
               residential landuse around the place, else a hull of buildings
  2. fetch     OSM (Overpass): roads, paths, landuse, water, named places
               Overture: building outlines (OSM + Microsoft ML + others)
               Raw downloads are kept in kibbutzim/<slug>/raw/ so rebuilds
               (e.g. after editing config.json) don't hit the servers.
  3. build     clip, classify, apply config.json (landmarks, spots, gate, ...)
               and write kibbutzim/<slug>/map.js, which index.html loads.
"""
import argparse, datetime, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402
from shapely.geometry import shape, mapping, box, Point, LineString, Polygon, MultiPolygon  # noqa: E402
from shapely.ops import polygonize, unary_union  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISRAEL = (29.4, 34.2, 33.4, 35.95)   # s, w, n, e for name lookups
log = fetch.log

ROAD_RANK = {'motorway': 9, 'trunk': 8, 'primary': 7, 'secondary': 6, 'tertiary': 5,
             'unclassified': 4, 'residential': 3, 'living_street': 3, 'service': 2, 'track': 1}
PATH_KINDS = {'footway', 'path', 'pedestrian', 'steps', 'cycleway', 'bridleway'}
SKIP_HW = {'construction', 'proposed', 'platform', 'elevator', 'corridor', 'abandoned', 'razed', 'bus_stop'}
AREA_KIND = [   # (tag, values, kind); first match wins
    ('leisure', {'swimming_pool'}, 'water'), ('natural', {'water'}, 'water'), ('water', None, 'water'),
    ('landuse', {'reservoir', 'basin'}, 'water'),
    ('landuse', {'cemetery'}, 'cemetery'), ('amenity', {'grave_yard'}, 'cemetery'),
    ('landuse', {'orchard', 'vineyard', 'plant_nursery'}, 'orchard'),
    ('leisure', {'park', 'garden', 'playground', 'pitch', 'recreation_ground', 'sports_centre', 'dog_park'}, 'green'),
    ('landuse', {'grass', 'meadow', 'village_green', 'recreation_ground'}, 'green'),
    ('natural', {'wood', 'scrub'}, 'wood'), ('landuse', {'forest'}, 'wood'),
    ('landuse', {'farmland', 'farmyard', 'greenhouse_horticulture', 'animal_keeping', 'industrial'}, 'farm'),
]
SPOT_TAGS = ('amenity', 'shop', 'tourism', 'leisure', 'office', 'healthcare', 'historic', 'craft', 'club', 'man_made')
SKIP_SPOT = {'parking', 'parking_space', 'bench', 'waste_basket', 'waste_disposal', 'recycling', 'vending_machine',
             'bicycle_parking', 'fire_hydrant', 'drinking_water', 'toilets', 'shelter', 'water_tower',
             'storage_tank', 'mast', 'antenna', 'pipeline', 'street_cabinet'}
PRIVATE_NAME = re.compile(r'משפחת|family', re.I)   # never auto-label a private home


# ---------- small helpers ----------
def P(*a):
    return os.path.join(ROOT, *a)


def jload(p):
    return json.load(open(p, encoding='utf-8'))


def jsave(p, obj, compact=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=None if compact else 2,
                  separators=(',', ':') if compact else None)


def heb(tags):
    return (tags.get('name:he') or tags.get('name') or '').strip()


def r6(c):
    return [round(c[0], 6), round(c[1], 6)]


def metres_per_deg(lat):
    return 111320 * math.cos(math.radians(lat)), 110540


def way_geom(el):
    return [(p['lon'], p['lat']) for p in el.get('geometry') or [] if p]


def element_shape(el):
    """Polygon/MultiPolygon (or LineString) from an Overpass `out geom` element."""
    if el['type'] == 'way':
        pts = way_geom(el)
        if len(pts) >= 4 and pts[0] == pts[-1]:
            return Polygon(pts)
        return LineString(pts) if len(pts) >= 2 else None
    if el['type'] == 'relation':
        outer = [LineString(way_geom(m)) for m in el.get('members', [])
                 if m.get('type') == 'way' and m.get('role') in ('outer', '') and len(way_geom(m)) >= 2]
        inner = [LineString(way_geom(m)) for m in el.get('members', [])
                 if m.get('type') == 'way' and m.get('role') == 'inner' and len(way_geom(m)) >= 2]
        polys = list(polygonize(outer))
        if not polys:
            return None
        g = unary_union(polys)
        holes = list(polygonize(inner))
        if holes:
            g = g.difference(unary_union(holes))
        return g
    return None


def multipoly_coords(g):
    """shapely (Multi)Polygon -> [[[ring],[hole]...], ...] rounded, like the Yiftah data model."""
    polys = [g] if isinstance(g, Polygon) else [p for p in getattr(g, 'geoms', []) if isinstance(p, Polygon)]
    out = []
    for p in polys:
        if p.is_empty or p.area == 0:
            continue
        rings = [p.exterior] + list(p.interiors)
        out.append([[r6(c) for c in r.coords] for r in rings])
    return out


def lines_coords(g):
    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [[r6(c) for c in g.coords]]
    return [l for part in getattr(g, 'geoms', []) for l in lines_coords(part)]


def label_point(g):
    """A point inside the polygon, near its middle (the centroid can fall outside an L shape)."""
    c = g.centroid
    return c if g.contains(c) else g.representative_point()


# ---------- 1. resolve ----------
def resolve(cfg, raw_dir, refetch):
    """Return (place_tags, centre (lng,lat), boundary shapely Polygon)."""
    cache = os.path.join(raw_dir, 'osm_place.json')
    src = cfg['source']
    if os.path.exists(cache) and not refetch:
        j = jload(cache)
    else:
        log('resolve: looking up the place in OSM')
        if src.get('osm'):
            t, i = src['osm'][0], src['osm'][1:]
            kind = {'r': 'rel', 'n': 'node', 'w': 'way'}[t]
            q = f'[out:json][timeout:90];{kind}({i})->.p;.p out geom;'
        elif src.get('name'):
            nm = src['name'].replace('"', '')
            s, w, n, e = ISRAEL
            bb = f'({s},{w},{n},{e})'
            q = (f'[out:json][timeout:90];(nwr["place"]["name:he"="{nm}"]{bb};nwr["place"]["name"="{nm}"]{bb};'
                 f'nwr["place"]["name:en"~"^{nm}$",i]{bb};)->.p;.p out geom;')
        else:
            q = None
        try:
            j = fetch.overpass(q) if q else {'elements': []}
        except fetch.OverpassBusy:
            log('  Overpass is busy; using the OSM API for the place itself')
            if src.get('osm'):
                ref = (src['osm'][0], src['osm'][1:])
            else:
                ref = fetch.nominatim_place(src['name'])
            j = {'elements': [fetch.osm_api_element(*ref)] if ref else []}
        els = j.get('elements', [])
        if src.get('name') and not src.get('osm'):
            # prefer a kibbutz-sized place: village/hamlet/isolated_dwelling, relation > way > node
            order = {'village': 0, 'hamlet': 1, 'isolated_dwelling': 2, 'neighbourhood': 3}
            els.sort(key=lambda e: (order.get(e.get('tags', {}).get('place'), 9),
                                    {'relation': 0, 'way': 1, 'node': 2}[e['type']]))
            if not els:
                raise SystemExit(f'No OSM place called {src["name"]!r}. Use --osm or --bbox.')
            if len(els) > 1:
                log('  several matches; using the first:',
                    [(e['type'][0] + str(e['id']), heb(e.get('tags', {}))) for e in els[:5]])
            els = els[:1]
        place = els[0] if els else None
        # residential landuse around the place, for a boundary when there is no place polygon
        if place is not None:
            c = centre_of(place)
            q2 = (f'[out:json][timeout:90];(way(around:900,{c[1]},{c[0]})["landuse"="residential"];'
                  f'rel(around:900,{c[1]},{c[0]})["landuse"="residential"];);out geom;')
        else:
            w, s, e, n = src['bbox']
            q2 = f'[out:json][timeout:90];(way["landuse"="residential"]({s},{w},{n},{e}););out geom;'
        try:
            resi = fetch.overpass(q2).get('elements', [])
        except fetch.OverpassBusy:
            resi = None     # filled from Overture below, only if the place has no polygon
        if resi is None and (place is None or place['type'] == 'node'):
            c = centre_of(place) if place else ((src['bbox'][0] + src['bbox'][2]) / 2, (src['bbox'][1] + src['bbox'][3]) / 2)
            d = 0.009
            near = fetch.overture_osm_like((c[0] - d, c[1] - d, c[0] + d, c[1] + d))
            resi = [e for e in near['elements'] if e.get('tags', {}).get('landuse') == 'residential']
        j = {'place': place, 'residential': resi or []}
        jsave(cache, j)
    place = j['place']
    tags = (place or {}).get('tags', {})
    centre = centre_of(place) if place else None
    if centre is None:
        w, s, e, n = src['bbox']
        centre = ((w + e) / 2, (s + n) / 2)

    boundary, how = None, ''
    if cfg.get('boundary'):
        boundary, how = Polygon(cfg['boundary']), 'config.json'
    if boundary is None and place and place['type'] in ('relation', 'way'):
        g = element_shape(place)
        if g is not None and g.geom_type in ('Polygon', 'MultiPolygon') and g.area > 0:
            boundary, how = g, f'OSM place {place["type"]} {place["id"]}'
    if boundary is None:
        cands = []
        for el in j['residential']:
            g = element_shape(el)
            if g is not None and g.geom_type in ('Polygon', 'MultiPolygon'):
                cands.append(g)
        pt = Point(centre)
        inside = [g for g in cands if g.buffer(0.0005).contains(pt)]
        if inside:
            boundary, how = max(inside, key=lambda g: g.area), 'OSM landuse=residential around the place'
        elif cands:
            g = min(cands, key=lambda g: g.distance(pt))
            if g.distance(pt) < 0.004:
                boundary, how = g, 'nearest OSM landuse=residential'
    if boundary is None and src.get('bbox'):
        boundary, how = box(*src['bbox']), '--bbox'
    if isinstance(boundary, MultiPolygon):
        boundary = max(boundary.geoms, key=lambda g: g.area)
    return tags, centre, boundary, how


def centre_of(el):
    if el is None:
        return None
    if el['type'] == 'node':
        return (el['lon'], el['lat'])
    if 'center' in el:
        return (el['center']['lon'], el['center']['lat'])
    g = element_shape(el)
    if g is not None:
        c = g.centroid
        return (c.x, c.y)
    b = el.get('bounds')
    return ((b['minlon'] + b['maxlon']) / 2, (b['minlat'] + b['maxlat']) / 2) if b else None


# ---------- 2. fetch ----------
def fetch_osm(clip, raw_dir, refetch):
    cache = os.path.join(raw_dir, 'osm_features.json')
    if os.path.exists(cache) and not refetch:
        return jload(cache)
    w, s, e, n = clip.bounds
    bb = f'({s:.6f},{w:.6f},{n:.6f},{e:.6f})'
    q = f"""[out:json][timeout:120];
(
  way["highway"]{bb};
  way["landuse"]{bb}; rel["landuse"]{bb};
  way["leisure"]{bb}; rel["leisure"]{bb};
  way["natural"~"water|wood|scrub"]{bb}; rel["natural"~"water|wood|scrub"]{bb};
  way["water"]{bb}; way["amenity"="grave_yard"]{bb};
  nwr["name"]["amenity"]{bb}; nwr["name"]["shop"]{bb}; nwr["name"]["tourism"]{bb};
  nwr["name"]["office"]{bb}; nwr["name"]["healthcare"]{bb}; nwr["name"]["historic"]{bb};
  nwr["name"]["club"]{bb}; nwr["name"]["craft"]{bb};
  way["building"]["name"]{bb};
  node["barrier"~"^(gate|lift_gate|entrance)$"]{bb};
);
out body geom;"""
    log('fetch: OSM features from Overpass')
    try:
        j = fetch.overpass(q)
        j['source'] = 'Overpass'
    except fetch.OverpassBusy:
        log('  Overpass is busy; using Overture\'s copy of the OSM roads/landuse/water instead')
        j = fetch.overture_osm_like(clip.bounds)
    jsave(cache, j, compact=True)
    return j


def fetch_buildings(clip, raw_dir, refetch, release=None):
    cache = os.path.join(raw_dir, 'overture_buildings.geojson')
    if os.path.exists(cache) and not refetch:
        return jload(cache)
    log('fetch: Overture buildings with DuckDB')
    rel, feats = fetch.overture_buildings(clip.bounds, release)
    fc = {'type': 'FeatureCollection', 'release': rel, 'bbox': list(clip.bounds), 'features': feats}
    jsave(cache, fc, compact=True)
    return fc


# ---------- 3. build ----------
def area_kind(tags):
    for k, vals, kind in AREA_KIND:
        v = tags.get(k)
        if v and (vals is None or v in vals):
            return kind
    return None


def build(slug, cfg, refetch):
    raw_dir = P('kibbutzim', slug, 'raw')
    ptags, centre, boundary, how = resolve(cfg, raw_dir, refetch)
    if boundary is None:
        raise SystemExit('No boundary found. Add "boundary" or source.bbox to config.json.')
    log(f'boundary: {how}')
    if cfg['name'] == slug and heb(ptags):
        cfg['name'] = heb(ptags)          # the Hebrew name from OSM, saved to config.json by main()
    lat0 = boundary.centroid.y
    mx, my = metres_per_deg(lat0)
    margin = cfg.get('margin_m', 250)
    if cfg.get('clip_bbox'):
        clip = box(*cfg['clip_bbox'])
    else:
        w, s, e, n = boundary.bounds
        clip = box(w - margin / mx, s - margin / my, e + margin / mx, n + margin / my)

    osm = fetch_osm(clip, raw_dir, refetch)
    bfc = fetch_buildings(clip, raw_dir, refetch, cfg.get('overture_release'))
    els = osm['elements']

    # roads and paths
    roads, paths, road_lines = [], [], []
    for el in els:
        t = el.get('tags', {})
        hw = t.get('highway')
        if el['type'] != 'way' or not hw or hw in SKIP_HW or t.get('area') == 'yes':
            continue
        pts = way_geom(el)
        if len(pts) < 2:
            continue
        g = LineString(pts).intersection(clip)
        lines = lines_coords(g)
        if hw in PATH_KINDS:
            paths += lines
        else:
            roads += lines
            road_lines.append((ROAD_RANK.get(hw, 2), el, LineString(pts)))

    # areas (landuse, parks, water...) and named areas
    areas, spots = [], []
    for el in els:
        if el['type'] == 'node':
            continue
        t = el.get('tags', {})
        if 'highway' in t and t.get('area') != 'yes':
            continue
        kind = area_kind(t)
        if not kind or 'building' in t:
            continue
        g = element_shape(el)
        if g is None or g.geom_type not in ('Polygon', 'MultiPolygon'):
            continue
        g = g.buffer(0).intersection(clip)
        if g.is_empty:
            continue
        areas.append({'k': kind, 'g': multipoly_coords(g)})
        nm = heb(t)
        if kind == 'cemetery':
            nm = 'בית עלמין'      # OSM often names it after the kibbutz itself
        if nm and g.area * mx * my < 40000 and not PRIVATE_NAME.search(nm):
            p = label_point(g)
            spots.append({'name': nm, 'c': r6((p.x, p.y)), 'icon': 'none', 'src': 'osm'})
    order = {'farm': 0, 'wood': 1, 'orchard': 2, 'green': 3, 'cemetery': 4, 'water': 5}
    areas.sort(key=lambda a: order[a['k']])

    # buildings
    bpoly = boundary.buffer(30 / mx)
    buildings = []
    datasets = {}
    for i, f in enumerate(bfc['features']):
        g = shape(f['geometry']).buffer(0)
        if g.is_empty or not g.intersects(clip):
            continue
        pr = f['properties']
        ds = pr.get('dataset') or 'other'
        datasets[ds] = datasets.get(ds, 0) + 1
        lp = label_point(g)
        buildings.append({
            'id': len(buildings) + 1,
            'gid': pr['id'],
            'src': {'OpenStreetMap': 'osm', 'Microsoft ML Buildings': 'ms'}.get(ds, 'other'),
            'osm': pr.get('record_id'),
            'c': r6((lp.x, lp.y)),
            'geom': multipoly_coords(g),
            'v': 1 if bpoly.intersects(g) else 0,     # inside the village boundary (+30 m)
            'name': '', 'anchor': None,
            '_g': g,
        })

    def building_at(lng, lat, tol_m=6):
        pt = Point(lng, lat)
        for b in buildings:
            if b['_g'].contains(pt):
                return b
        near = min(buildings, key=lambda b: b['_g'].distance(pt), default=None)
        if near and near['_g'].distance(pt) * mx <= tol_m:
            return near
        return None

    # named OSM buildings and named places become landmarks / spots
    hidden = set(cfg.get('hide_landmarks', []))
    for el in els:
        t = el.get('tags', {})
        nm = heb(t)
        if not nm or nm in hidden or PRIVATE_NAME.search(nm):
            continue
        is_building = 'building' in t
        spotty = any(k in t and t[k] not in SKIP_SPOT for k in SPOT_TAGS)
        if not (is_building or spotty) or area_kind(t) and not is_building:
            continue
        if is_building and t['building'] in ('house', 'detached', 'residential', 'semidetached_house') and not spotty:
            continue
        c = centre_of(el)
        if c is None or not clip.contains(Point(c)):
            continue
        b = None
        if el['type'] == 'way' and is_building:
            rid = f'w{el["id"]}'
            b = next((x for x in buildings if (x['osm'] or '').split('@')[0] == rid), None)
        b = b or building_at(*c, tol_m=0 if el['type'] == 'node' else 6)
        if b is not None:
            if not b['anchor']:
                b['anchor'] = b['name'] = nm
        else:
            spots.append({'name': nm, 'c': r6(c), 'src': 'osm'})

    # config: landmarks by point (robust across Overture releases), spots, gate
    for lm in cfg.get('landmarks', []):
        b = building_at(*lm['at'])
        if b is None:
            log(f'  ! landmark {lm["name"]!r}: no building at {lm["at"]}; drawn as a spot instead')
            spots.append({'name': lm['name'], 'c': lm['at'], 'src': 'config'})
            continue
        b['anchor'] = b['name'] = lm['name']
        if lm.get('label_at'):
            b['c'] = lm['label_at']
    for sp in cfg.get('spots', []):
        spots.append({'name': sp['name'], 'c': sp['at'], 'icon': sp.get('icon', 'dot'), 'src': 'config'})
    # drop OSM spots that duplicate a landmark name
    anchored = {b['anchor'] for b in buildings if b['anchor']}
    seen, uniq = set(), []
    for sp in spots:
        if sp['name'] in anchored and sp['src'] == 'osm' or sp['name'] in seen or sp['name'] in hidden:
            continue
        seen.add(sp['name']); uniq.append(sp)
    spots = uniq

    gate, gate_how = None, ''
    if cfg.get('gate'):
        gate, gate_how = cfg['gate'], 'config.json'
    else:
        gate, gate_how = guess_gate(els, road_lines, boundary, mx)

    w, s, e, n = clip.bounds
    attribution = ['© OpenStreetMap contributors']
    if any(k != 'OpenStreetMap' for k in datasets):
        extra = [d for d in datasets if d != 'OpenStreetMap']
        attribution.append('Overture Maps Foundation (' + ', '.join(extra) + ')')
    else:
        attribution.append('Overture Maps Foundation')

    for b in buildings:
        del b['_g']
        if not b['osm']:
            del b['osm']
    out = {
        'meta': {
            'slug': slug, 'name': cfg['name'], 'name_en': cfg.get('name_en', ''),
            'built': datetime.date.today().isoformat(),
            'osm_place': ptags.get('name') and {'name': heb(ptags), 'place': ptags.get('place')},
            'boundary_from': how, 'gate_from': gate_how,
            'clip': [round(w, 6), round(s, 6), round(e, 6), round(n, 6)],
            'overture_release': bfc.get('release'),
            'osm_source': osm.get('source', 'Overpass'),
            'datasets': datasets,
            'attribution': ' · '.join(attribution),
            'label_priority': cfg.get('label_priority', []),
            'zoomed_in_only': cfg.get('zoomed_in_only', []),
        },
        'boundary': [r6(c) for c in boundary.exterior.coords],
        'gate': gate and r6(gate),
        'units': buildings,
        'roads': roads, 'paths': paths,
        'areas': areas + [{'k': a['kind'], 'g': [[a['ring']]]} for a in cfg.get('areas', [])],
        'spots': spots,
    }
    js = ('/* Generated by tools/build_kibbutz.py. Do not edit; change config.json and rebuild.\n'
          f'   Map data {out["meta"]["attribution"]}. OSM data is under the ODbL. */\n'
          'window.KMAP=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    path = P('kibbutzim', slug, 'map.js')
    open(path, 'w', encoding='utf-8').write(js)
    nv = sum(b['v'] for b in buildings)
    log(f'✔ {slug}: {len(buildings)} buildings ({nv} in the village; {datasets}), '
        f'{len(roads)} road lines, {len(paths)} path lines, {len(areas)} areas, '
        f'{sum(1 for b in buildings if b["anchor"])} landmarks, {len(spots)} spots, '
        f'gate: {gate_how or "none"} -> {os.path.relpath(path, ROOT)} ({len(js) // 1024} KB)')
    write_index()
    return out


def write_index():
    """kibbutzim/index.js: the list the app shows when the URL has no ?k=."""
    items = []
    for slug in sorted(os.listdir(P('kibbutzim'))):
        cp = P('kibbutzim', slug, 'config.json')
        if os.path.exists(P('kibbutzim', slug, 'map.js')) and os.path.exists(cp):
            items.append({'slug': slug, 'name': jload(cp)['name']})
    open(P('kibbutzim', 'index.js'), 'w', encoding='utf-8').write(
        'window.KLIST=' + json.dumps(items, ensure_ascii=False) + ';\n')


def guess_gate(els, road_lines, boundary, mx):
    """A barrier=gate node on a road near the boundary, else where the biggest road
    crosses the boundary. Only a guess; config.json "gate" overrides it."""
    ring = boundary.exterior
    best = None
    for el in els:
        if el['type'] == 'node' and el.get('tags', {}).get('barrier') in ('gate', 'lift_gate'):
            pt = Point(el['lon'], el['lat'])
            d = ring.distance(pt) * mx
            if d > 120:
                continue
            rank = max((r for r, _, ln in road_lines if ln.distance(pt) * mx < 3), default=0)
            if rank == 0:
                continue
            key = (rank, -d)
            if best is None or key > best[0]:
                best = (key, (pt.x, pt.y))
    if best:
        return best[1], 'OSM barrier=gate'
    cands = []
    for rank, _, line in road_lines:
        if rank < 2:
            continue
        x = line.intersection(ring)
        pts = [x] if x.geom_type == 'Point' else [p for p in getattr(x, 'geoms', []) if p.geom_type == 'Point']
        for p in pts:
            cands.append((rank, (p.x, p.y)))
    if cands:
        cands.sort(key=lambda c: -c[0])
        return cands[0][1], 'guess: biggest road crossing the boundary'
    return None, ''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('slug')
    ap.add_argument('--name'); ap.add_argument('--osm'); ap.add_argument('--bbox')
    ap.add_argument('--fetch', action='store_true'); ap.add_argument('--report', action='store_true')
    a = ap.parse_args()
    cfg_path = P('kibbutzim', a.slug, 'config.json')
    if os.path.exists(cfg_path):
        cfg = jload(cfg_path)
    else:
        if not (a.name or a.osm or a.bbox):
            raise SystemExit('New kibbutz: give --name, --osm or --bbox')
        cfg = {'name': a.name or a.slug, 'name_en': '', 'source': {}, 'margin_m': 250,
               'landmarks': [], 'spots': [], 'gate': None, 'label_priority': [], 'zoomed_in_only': [],
               'hide_landmarks': []}
    src = cfg.setdefault('source', {})
    if a.name: src['name'] = a.name
    if a.osm: src['osm'] = a.osm
    if a.bbox: src['bbox'] = [float(x) for x in a.bbox.split(',')]
    if not os.path.exists(cfg_path):
        jsave(cfg_path, cfg)
        log(f'created {os.path.relpath(cfg_path, ROOT)}')
    out = build(a.slug, cfg, a.fetch)
    jsave(cfg_path, cfg)
    if a.report:
        import coverage_report
        coverage_report.write(a.slug, coverage_report.YIFTAH_REF if a.slug == 'yiftah' else None)


if __name__ == '__main__':
    main()
