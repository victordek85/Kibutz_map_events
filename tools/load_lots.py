#!/usr/bin/env python3
"""Phase 2 (stub): turn the one layer a kibbutz orders from Marom (נכסים: lot shapes
with NUM, DAYAR, MAKOR, GUSH, HELKA) into lots.js, which index.html shows as the
main view when opened with ?lots=1.

    .venv/bin/python tools/load_lots.py <slug> <lots.geojson|lots.shp>
           [--map num=NUM,name=DAYAR,kind=MAKOR,gush=GUSH,helka=HELKA,id=ORIG_ID]
           [--out DIR] [--password PW]

  --map       field names in the delivered file (they differ per kibbutz). Defaults
              come from "lots_fields" in kibbutzim/<slug>/config.json, then the Marom names.
  --out       where to write. Default: private/<slug>/ (git-ignored). Real data must
              go to the kibbutz's own deployment folder, never into this repo.
  --password  write lots.enc.js instead: the whole lots payload encrypted with
              AES-GCM-256, key = PBKDF2-SHA256(password). index.html asks for it.

Input CRS: WGS84 (lng/lat) or Israeli TM Grid (ITM, EPSG:2039); ITM is detected from
the .prj file or from coordinate size, and reprojected to WGS84.

Privacy: only the mapped fields are kept. Everything else (ARNONA, meters, notes...)
is dropped. Writing inside this repo is refused unless the input is under samples/
(the invented test file), so real names can't land in the product repo by accident.
"""
import argparse, base64, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import shape, Point  # noqa: E402
from build_kibbutz import multipoly_coords, label_point, r6, P, ROOT, jload  # noqa: E402

DEFAULT_FIELDS = {'id': 'ORIG_ID', 'num': 'NUM', 'name': 'DAYAR', 'kind': 'MAKOR', 'gush': 'GUSH', 'helka': 'HELKA'}


def read_features(path):
    if path.lower().endswith('.shp'):
        import shapefile  # pyshp
        sf = shapefile.Reader(path, encoding='utf-8')
        names = [f[0] for f in sf.fields[1:]]
        feats = [{'properties': dict(zip(names, sr.record)), 'geometry': sr.shape.__geo_interface__}
                 for sr in sf.iterShapeRecords()]
        prj = path[:-4] + '.prj'
        wkt = open(prj, encoding='utf-8', errors='ignore').read() if os.path.exists(prj) else ''
        return feats, wkt
    fc = jload(path)
    crs = json.dumps(fc.get('crs', ''))
    return fc['features'], crs


def to_wgs84(feats, crs_hint):
    """Reproject from ITM when needed."""
    sample = shape(feats[0]['geometry']).representative_point()
    itm = ('2039' in crs_hint or 'Israel' in crs_hint or 'ITM' in crs_hint
           or abs(sample.x) > 1000)
    if not itm:
        return feats, 'WGS84'
    from pyproj import Transformer
    from shapely.ops import transform
    tr = Transformer.from_crs('EPSG:2039', 'EPSG:4326', always_xy=True)
    for f in feats:
        f['geometry'] = transform(tr.transform, shape(f['geometry'])).__geo_interface__
    return feats, 'ITM (EPSG:2039) -> WGS84'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('slug'); ap.add_argument('src')
    ap.add_argument('--map'); ap.add_argument('--out'); ap.add_argument('--password')
    a = ap.parse_args()
    cfg_path = P('kibbutzim', a.slug, 'config.json')
    cfg = jload(cfg_path) if os.path.exists(cfg_path) else {}
    fields = dict(DEFAULT_FIELDS, **cfg.get('lots_fields', {}))
    if a.map:
        fields.update(dict(kv.split('=', 1) for kv in a.map.split(',')))

    out_dir = os.path.abspath(a.out or P('private', a.slug))
    src = os.path.abspath(a.src)
    inside_repo = out_dir.startswith(ROOT + os.sep) and not out_dir.startswith(P('private') + os.sep)
    if inside_repo and not src.startswith(P('samples') + os.sep):
        raise SystemExit('Refusing to write real lots data inside the product repo. Use --out <deployment dir>.')

    feats, crs = read_features(a.src)
    feats, how = to_wgs84(feats, crs)
    units, missing = [], {k: 0 for k in fields}
    for i, f in enumerate(feats):
        if not f.get('geometry'):
            continue
        p = f['properties']
        val = {}
        for k, col in fields.items():
            v = p.get(col)
            if v is None:
                missing[k] += 1
            val[k] = '' if v is None else str(v).strip()
        g = shape(f['geometry']).buffer(0)
        if g.is_empty:
            continue
        lp = label_point(g)
        units.append({'id': val['id'] or str(i + 1), 'num': val['num'], 'name': val['name'],
                      'kind': val['kind'], 'gush': val['gush'], 'helka': val['helka'],
                      'c': r6((lp.x, lp.y)), 'geom': multipoly_coords(g), 'anchor': None, '_g': g})

    # landmarks and name fixes from config.json, by point (same as for buildings)
    for lm in cfg.get('landmarks', []):
        pt = Point(lm['at'])
        u = next((u for u in units if u['_g'].contains(pt)), None)
        if u:
            u['anchor'] = lm['name']
            if lm.get('label_at'):
                u['c'] = lm['label_at']
    for u in units:
        del u['_g']

    payload = {'meta': {'slug': a.slug, 'count': len(units), 'crs': how, 'fields': fields,
                        'source': os.path.basename(a.src)}, 'units': units}
    os.makedirs(out_dir, exist_ok=True)
    if a.password:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        salt, iv, it = os.urandom(16), os.urandom(12), 310000
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it).derive(a.password.encode())
        ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), None)
        b = lambda x: base64.b64encode(x).decode()
        enc = {'v': 1, 'iter': it, 'salt': b(salt), 'iv': b(iv), 'ct': b(ct)}
        path = os.path.join(out_dir, 'lots.enc.js')
        open(path, 'w').write('window.KLOTS_ENC=' + json.dumps(enc) + ';\n')
    else:
        path = os.path.join(out_dir, 'lots.js')
        open(path, 'w', encoding='utf-8').write(
            '/* Generated by tools/load_lots.py. Contains personal data: never commit to the product repo. */\n'
            'window.KLOTS=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n')
    named = sum(1 for u in units if u['name'])
    print(f'✔ {len(units)} lots ({named} with a name, {sum(1 for u in units if u["anchor"])} landmarks), '
          f'{how}; missing fields: { {k: v for k, v in missing.items() if v} } -> {path}')


if __name__ == '__main__':
    main()
