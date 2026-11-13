#!/usr/bin/env python3
"""Write docs/coverage-<slug>.md: what the automatic map has for one kibbutz.

    .venv/bin/python tools/coverage_report.py <slug> [--reference PATH]

--reference points to a lots GeoJSON outside this repo (for Yiftah: the old
app's data/parcels_raw.geojson). It is read in place, never copied, and the
report keeps only totals: no names, no house numbers.
"""
import argparse, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import shape, Polygon, MultiPolygon  # noqa: E402
from build_kibbutz import P, metres_per_deg  # noqa: E402

YIFTAH_REF = os.path.expanduser('~/Documents/Claude Files/Yiftah Map App/data/parcels_raw.geojson')


def load_map(slug):
    js = open(P('kibbutzim', slug, 'map.js'), encoding='utf-8').read()
    return json.loads(re.search(r'window\.KMAP=(.*);\s*$', js, re.S).group(1))


def mp(geom):
    return MultiPolygon([Polygon(p[0], p[1:]) for p in geom]).buffer(0)


def line_len_m(lines, mx, my):
    t = 0
    for ln in lines:
        for (x0, y0), (x1, y1) in zip(ln, ln[1:]):
            t += math.hypot((x1 - x0) * mx, (y1 - y0) * my)
    return t


def reference_section(m, ref_path, mx, my):
    """Compare with a real lots layer: how many house lots have a building outline."""
    ref = json.load(open(ref_path, encoding='utf-8'))['features']
    blds = [(b, mp(b['geom'])) for b in m['units']]
    rows = {}
    missing_pts = []
    for f in ref:
        if not f.get('geometry'):
            continue
        kind = (f['properties'].get('MAKOR') or '').strip() or '?'
        lot = shape(f['geometry']).buffer(0)
        best_src = None
        for b, g in blds:
            if not g.intersects(lot):
                continue
            inter = g.intersection(lot).area * mx * my
            if inter >= 15 or inter >= 0.3 * g.area * mx * my:   # a real overlap, not a shared edge
                best_src = 'osm' if b['src'] == 'osm' or best_src == 'osm' else b['src']
        r = rows.setdefault(kind, {'n': 0, 'osm': 0, 'ms': 0, 'other': 0, 'none': 0})
        r['n'] += 1
        r[best_src or 'none'] += 1
        if not best_src and kind == 'מגרש':
            c = lot.centroid
            missing_pts.append((c.x, c.y))
    out = ['## Compared with the real lots (Yiftah only)', '',
           f'Reference: the old Yiftah app\'s lots file, read in place ({len(ref)} features). '
           'Only totals are shown here. No names or house numbers are copied.', '',
           '| Marom type | Lots | Has a building | from OSM | from Microsoft ML only | other | No building |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for k, r in sorted(rows.items(), key=lambda kv: -kv[1]['n']):
        has = r['n'] - r['none']
        out.append(f"| {k} | {r['n']} | {has} ({100 * has / r['n']:.0f}%) | {r['osm']} | {r['ms']} | {r['other']} | {r['none']} |")
    if missing_pts:
        # where are the gaps? split the village bbox into a 3x3 grid
        xs = [p[0] for p in missing_pts]; ys = [p[1] for p in missing_pts]
        w, s, e, n = (min(x for x, _ in m['boundary']), min(y for _, y in m['boundary']),
                      max(x for x, _ in m['boundary']), max(y for _, y in m['boundary']))
        grid = [[0] * 3 for _ in range(3)]
        for x, y in missing_pts:
            cx = min(2, max(0, int(3 * (x - w) / (e - w)))); cy = min(2, max(0, int(3 * (n - y) / (n - s))))
            grid[cy][cx] += 1
        out += ['', 'Where the house lots with no building outline are (village box split 3×3, north at the top, west on the left):', '',
                '| | west | middle | east |', '|---|---:|---:|---:|']
        for lab, row in zip(['north', 'middle', 'south'], grid):
            out.append(f'| {lab} | ' + ' | '.join(str(v) for v in row) + ' |')
    return out


def write(slug, ref=None):
    m = load_map(slug)
    meta = m['meta']
    lat0 = sum(y for _, y in m['boundary']) / len(m['boundary'])
    mx, my = metres_per_deg(lat0)
    units = m['units']
    inv = [u for u in units if u['v']]
    by_src = {}
    for u in inv:
        by_src[u['src']] = by_src.get(u['src'], 0) + 1
    areas = {}
    for a in m['areas']:
        areas[a['k']] = areas.get(a['k'], 0) + 1
    bpoly = Polygon(m['boundary'])
    lines = [
        f'# Coverage: {meta["name"]} ({slug})', '',
        f'Built {meta["built"]} by `tools/build_kibbutz.py {slug}`. Overture release {meta["overture_release"]}.', '',
        '## What the automatic map has', '',
        f'- **Boundary:** {meta["boundary_from"]}; about {bpoly.area * mx * my / 10000:.0f} ha.',
        f'- **Buildings:** {len(units)} in the map box, {len(inv)} of them inside the village boundary '
        f'(OSM {by_src.get("osm", 0)}, Microsoft ML {by_src.get("ms", 0)}, other {by_src.get("other", 0)}).',
        f'- **Roads:** {len(m["roads"])} lines, {line_len_m(m["roads"], mx, my) / 1000:.1f} km. '
        f'**Footpaths / golf-cart paths:** {len(m["paths"])} lines, {line_len_m(m["paths"], mx, my) / 1000:.1f} km.',
        f'- **Areas:** ' + (', '.join(f'{k} {v}' for k, v in sorted(areas.items())) or 'none') + '.',
        f'- **Landmarks** (named buildings): {sum(1 for u in units if u["anchor"])}: '
        + (', '.join(sorted({u["anchor"] for u in units if u["anchor"]})) or 'none') + '.',
        f'- **Spots** (named places with no building): {len(m["spots"])}: '
        + (', '.join(s["name"] for s in m["spots"]) or 'none') + '.',
        f'- **Gate:** {meta["gate_from"] or "not found"}.',
        '',
    ]
    if ref and os.path.exists(ref):
        lines += reference_section(m, ref, mx, my) + ['']
    lines += ['## What a person should still check', '',
              '- Landmark names: add the dining hall, secretariat, clinic, kindergartens, pool and so on in `config.json` (`landmarks`, by a point inside the building).',
              '- The gate position (`gate` in `config.json`), when it is a guess or missing.',
              '- Houses with no outline: in phase 1 they can only be marked with free draw. Phase 2 (the Marom lots layer) fixes this.',
              '']
    path = P('docs', f'coverage-{slug}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))
    print('wrote', os.path.relpath(path, P()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('slug'); ap.add_argument('--reference')
    a = ap.parse_args()
    write(a.slug, a.reference or (YIFTAH_REF if a.slug == 'yiftah' else None))
