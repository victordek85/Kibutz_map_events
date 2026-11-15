#!/usr/bin/env python3
"""Export one kibbutz as a single self-contained HTML file.

    .venv/bin/python tools/export_html.py ramat-hashofet

Writes exports/<slug>.html: index.html with the kibbutz's map.js inlined and
set as the default. The file opens offline from WhatsApp, mail or Files,
so someone can review the map without a server. Lots are never included:
this is for the free-source map only.
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    slug = sys.argv[1]
    map_js = ROOT / 'kibbutzim' / slug / 'map.js'
    if not map_js.exists():
        sys.exit(f'no {map_js}; run tools/build_kibbutz.py {slug} first')
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    data = map_js.read_text(encoding='utf-8').replace('</script', '<\\/script')
    html, n = re.subn(r'<meta name="kmap-default" content="[^"]*">',
                      f'<meta name="kmap-default" content="{slug}">', html, count=1)
    assert n == 1, 'kmap-default meta not found'
    marker = '<script>\n/* ---------- data loading ----------'
    assert html.count(marker) == 1, 'loader script not found'
    html = html.replace(marker, '<script>\n' + data + '\n</script>\n' + marker)
    out = ROOT / 'exports' / f'{slug}.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding='utf-8')
    print(f'✔ {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
