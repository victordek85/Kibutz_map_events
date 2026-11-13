"""Network fetchers for the pipeline: Overpass (OSM) and Overture buildings.

Both are free, open sources:
  - OpenStreetMap via the Overpass API (ODbL). The public servers are often
    busy, so every query rotates through the main server and mirrors with
    exponential backoff, and sends an identifying User-Agent.
  - Overture Maps buildings (ODbL; OSM buildings plus Microsoft ML buildings and
    others), read with DuckDB straight from the public S3 parquet, filtered by bbox.
"""
import json, random, sys, time, urllib.error, urllib.parse, urllib.request

USER_AGENT = ('Kibutz_map_events/0.1 (open-source kibbutz notice map; '
              'https://github.com/victordek85/Kibutz_map_events)')

OVERPASS_SERVERS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]

STAC_CATALOG = 'https://stac.overturemaps.org/catalog.json'
OVERTURE_S3 = 's3://overturemaps-us-west-2/release/{rel}/theme=buildings/type=building/*'


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _http(url, data=None, timeout=200):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT,
                                                          'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class OverpassBusy(Exception):
    pass


def overpass(query, attempts=4, base_wait=5, timeout=75):
    """Run an Overpass QL query; rotate servers, back off exponentially on errors.

    A busy server answers 429/502/504, or 200 with an HTML/XML error page, or a
    JSON body with a 'remark' saying it timed out. All of those count as failures.
    """
    body = urllib.parse.urlencode({'data': query}).encode()
    wait = base_wait
    last = None
    for i in range(attempts):
        server = OVERPASS_SERVERS[i % len(OVERPASS_SERVERS)]
        try:
            raw = _http(server, body, timeout=timeout)
            j = json.loads(raw)
            remark = j.get('remark', '')
            if 'runtime error' in remark or 'timed out' in remark:
                raise RuntimeError(remark[:160])
            log(f'  overpass ok: {server.split("/")[2]} ({len(j.get("elements", []))} elements)')
            return j
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, RuntimeError, TimeoutError, OSError) as e:
            last = e
            msg = getattr(e, 'code', None) or str(e)[:120]
            log(f'  overpass busy/failed at {server.split("/")[2]}: {msg}; retry in {wait}s')
            time.sleep(wait + random.random() * 2)
            wait = min(wait * 2, 120)
    raise OverpassBusy(f'Overpass failed after {attempts} attempts: {last}')


def overture_latest_release():
    cat = json.loads(_http(STAC_CATALOG, timeout=60))
    if cat.get('latest'):
        return cat['latest']
    rels = [l for l in cat.get('links', []) if l.get('rel') == 'child']
    latest = [l for l in rels if l.get('latest')] or rels[-1:]
    return latest[0]['href'].rstrip('/').split('/')[-2]


def overture_buildings(bbox, release=None):
    """bbox = (west, south, east, north). Returns (release, list of GeoJSON features)."""
    import duckdb
    release = release or overture_latest_release()
    w, s, e, n = bbox
    con = duckdb.connect()
    for ext in ('httpfs', 'spatial'):
        con.execute(f'INSTALL {ext}; LOAD {ext};')
    con.execute("SET s3_region='us-west-2'; SET enable_progress_bar=false;")
    t0 = time.time()
    src = OVERTURE_S3.format(rel=release)
    rows = con.execute(f"""
        SELECT id, ST_AsGeoJSON(geometry) AS g,
               sources[1].dataset AS ds, sources[1].record_id AS rec,
               names.primary AS nm, class, subtype, height, num_floors
        FROM read_parquet('{src}', hive_partitioning=1)
        WHERE bbox.xmin < {e} AND bbox.xmax > {w} AND bbox.ymin < {n} AND bbox.ymax > {s}
    """).fetchall()
    log(f'  overture {release}: {len(rows)} buildings in {time.time() - t0:.0f}s')
    feats = []
    for (gid, g, ds, rec, nm, cls, sub, h, fl) in rows:
        feats.append({'type': 'Feature', 'geometry': json.loads(g),
                      'properties': {'id': gid, 'dataset': ds, 'record_id': rec, 'name': nm,
                                     'class': cls, 'subtype': sub, 'height': h, 'num_floors': fl}})
    return release, feats


# ---------- fallbacks when every Overpass server is busy ----------
OSM_API = 'https://api.openstreetmap.org/api/0.6'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'


def osm_api_element(kind, osm_id):
    """One place from the OSM API (`/full`), shaped like an Overpass `out geom` element.
    A single small read; contributor names/uids are dropped."""
    kind = {'r': 'relation', 'w': 'way', 'n': 'node'}.get(kind, kind)
    url = f'{OSM_API}/{kind}/{osm_id}' + ('' if kind == 'node' else '/full') + '.json'
    els = json.loads(_http(url, timeout=60))['elements']
    nodes = {e['id']: e for e in els if e['type'] == 'node'}
    ways = {e['id']: e for e in els if e['type'] == 'way'}
    geom = lambda w: [{'lat': nodes[i]['lat'], 'lon': nodes[i]['lon']} for i in w['nodes'] if i in nodes]
    me = next(e for e in els if e['type'] == kind and e['id'] == int(osm_id))
    out = {'type': kind, 'id': me['id'], 'tags': me.get('tags', {})}
    if kind == 'node':
        out.update(lat=me['lat'], lon=me['lon'])
    elif kind == 'way':
        out['geometry'] = geom(me)
    else:
        out['members'] = [{'type': m['type'], 'ref': m['ref'], 'role': m['role'],
                           'geometry': geom(ways[m['ref']])} for m in me['members']
                          if m['type'] == 'way' and m['ref'] in ways]
    log(f'  OSM API ok: {kind} {osm_id}')
    return out


def nominatim_place(name):
    """(type letter, id) of the best Israeli match for a place name."""
    q = urllib.parse.urlencode({'q': name, 'countrycodes': 'il', 'format': 'jsonv2', 'limit': 5})
    res = json.loads(_http(f'{NOMINATIM}?{q}', timeout=60))
    res = [r for r in res if r.get('category') in ('place', 'boundary', 'landuse')] or res
    if not res:
        return None
    r = res[0]
    log(f'  nominatim: {r.get("display_name", "")[:80]}')
    return r['osm_type'][0], r['osm_id']


def overture_osm_like(bbox, release=None):
    """Roads, paths, landuse, water and gates from Overture's copies of OSM
    (transportation + base themes), turned into Overpass-like elements so the
    builder can use either source."""
    import duckdb
    release = release or overture_latest_release()
    w, s, e, n = bbox
    con = duckdb.connect()
    for ext in ('httpfs', 'spatial'):
        con.execute(f'INSTALL {ext}; LOAD {ext};')
    con.execute("SET s3_region='us-west-2'; SET enable_progress_bar=false;")
    where = f'bbox.xmin < {e} AND bbox.xmax > {w} AND bbox.ymin < {n} AND bbox.ymax > {s}'
    src = lambda th, ty: f"read_parquet('s3://overturemaps-us-west-2/release/{release}/theme={th}/type={ty}/*', hive_partitioning=1)"
    LEISURE = {'park', 'garden', 'playground', 'pitch', 'recreation_ground', 'sports_centre', 'dog_park'}
    els, k = [], 0

    def add(tags, gj):
        nonlocal k
        g = json.loads(gj)
        k += 1
        ring = lambda cs: [{'lat': y, 'lon': x} for x, y in cs]
        if g['type'] == 'Point':
            els.append({'type': 'node', 'id': -k, 'lat': g['coordinates'][1], 'lon': g['coordinates'][0], 'tags': tags})
        elif g['type'] == 'LineString':
            els.append({'type': 'way', 'id': -k, 'tags': tags, 'geometry': ring(g['coordinates'])})
        elif g['type'] == 'Polygon' and len(g['coordinates']) == 1:
            els.append({'type': 'way', 'id': -k, 'tags': tags, 'geometry': ring(g['coordinates'][0])})
        elif g['type'] in ('Polygon', 'MultiPolygon'):
            polys = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
            mem = [{'type': 'way', 'role': 'outer' if i == 0 else 'inner', 'geometry': ring(r)}
                   for p in polys for i, r in enumerate(p)]
            els.append({'type': 'relation', 'id': -k, 'tags': tags, 'members': mem})

    t0 = time.time()
    for cls, nm, gj in con.execute(f"SELECT class, names.primary, ST_AsGeoJSON(geometry) FROM {src('transportation', 'segment')} "
                                   f"WHERE subtype='road' AND {where}").fetchall():
        if cls and cls != 'unknown':
            add({'highway': cls, **({'name': nm} if nm else {})}, gj)
    for sub, cls, nm, gj in con.execute(f"SELECT subtype, class, names.primary, ST_AsGeoJSON(geometry) FROM {src('base', 'land_use')} WHERE {where}").fetchall():
        if sub == 'protected' or not cls:
            continue
        tags = {'leisure': cls} if cls in LEISURE else {'landuse': cls}
        if nm: tags['name'] = nm
        add(tags, gj)
    for sub, cls, nm, gj in con.execute(f"SELECT subtype, class, names.primary, ST_AsGeoJSON(geometry) FROM {src('base', 'water')} "
                                        f"WHERE {where} AND subtype NOT IN ('physical','ocean') AND ST_GeometryType(geometry) <> 'LINESTRING'").fetchall():
        tags = {'leisure': 'swimming_pool'} if cls == 'swimming_pool' else {'natural': 'water'}
        if nm: tags['name'] = nm
        add(tags, gj)
    for sub, cls, gj in con.execute(f"SELECT subtype, class, ST_AsGeoJSON(geometry) FROM {src('base', 'land')} "
                                    f"WHERE {where} AND class IN ('forest','wood','scrub')").fetchall():
        add({'natural': 'wood' if cls != 'scrub' else 'scrub'}, gj)
    for cls, gj in con.execute(f"SELECT class, ST_AsGeoJSON(geometry) FROM {src('base', 'infrastructure')} "
                               f"WHERE {where} AND class IN ('gate','lift_gate')").fetchall():
        add({'barrier': cls}, gj)
    log(f'  overture (OSM-derived) features: {len(els)} in {time.time() - t0:.0f}s')
    return {'elements': els, 'source': f'Overture {release} transportation+base (from OSM)'}
