#!/usr/bin/env python3
"""Export the real Hivemill demo UI for static hosting; never connects to a live factory.

Requires a checkout of hivemill, and uses only its isolated demo seeder/server.
Navigation, sample goals/tasks, selected filters, disclosures and themes remain usable.
Unexported compound filters and fictional external PR links are visibly unavailable.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE_PATHS = ('/', '/goals', '/tasks', '/agents', '/throughput', '/quality', '/tokens', '/changelog', '/resources')
LINK = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.S)
HREF = re.compile(r'\bhref="([^"]*)"')

def canonical(ref):
    u = urlsplit(html.unescape(ref))
    if u.scheme or u.netloc or not (u.path in BASE_PATHS or re.fullmatch(r'/(?:goal|task)/[A-Z]-\d+', u.path)):
        return None
    q = urlencode(sorted(parse_qsl(u.query)))
    return u.path + ('?' + q if q else '')

def supported(route):
    u = urlsplit(route)
    keys = set(dict(parse_qsl(u.query))) - {'org'}
    if u.path == '/tasks':
        return keys <= {'sort', 'dir'} or keys <= {'status'} or keys <= {'goal'}
    if u.path == '/agents':
        return len(keys) <= 1
    if u.path == '/tokens':
        return keys <= {'days', 'by'}
    return True

def filename(route):
    if route == '/': return 'index.html'
    path = urlsplit(route).path.strip('/').replace('/', '-').lower() or 'overview'
    suffix = '-' + hashlib.sha256(route.encode()).hexdigest()[:10] if '?' in route else ''
    return path + suffix + '.html'

def render(raw, pages):
    def anchor(match):
        attrs, label = match.groups()
        href = HREF.search(attrs)
        if not href: return match.group()
        value = html.unescape(href.group(1))
        if value.startswith('#'): return match.group()
        route = canonical(value)
        if route in pages:
            frag = urlsplit(value).fragment
            dest = filename(route) + ('#' + frag if frag else '')
            return '<a' + HREF.sub('href="' + html.escape(dest, quote=True) + '"', attrs) + '>' + label + '</a>'
        reason = 'Fictional pull request in the demo' if value.startswith('https://') else 'This combined filter is not included in the demo'
        return '<span class="demo-unavailable" title="' + reason + '">' + label + '</span>'
    raw = LINK.sub(anchor, raw)
    raw = raw.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    raw = re.sub(r'<meta http-equiv="refresh"[^>]*>', '', raw)
    raw = re.sub(r'<span class="updated"[^>]*>.*?</span>', '<span class="updated">Demo snapshot</span>', raw, flags=re.S)
    raw = re.sub(r' · data -?\d+ min old', ' · fixed demo sample', raw)
    raw = raw.replace('</head>', '<link rel="stylesheet" href="static/demo.css"><meta name="robots" content="noindex"></head>')
    banner = '<aside class="demo-banner" aria-label="Demo information"><div><strong>Interactive product demo</strong><span>Fictional data · No agents running</span></div><nav aria-label="Demo actions"><a href="index.html#needs-you">View alerts</a><a href="resources.html">Resources</a><a href="tokens.html">Cost &amp; usage</a><a href="../">Back to Hivemill ↗</a></nav><details><summary>About this demo</summary><p>This is the actual Hivemill interface with a fixed fictional scenario. Explore pages, goals, tasks, supported filters and themes. Some combined filters and external pull requests are unavailable. No live factory is connected.</p></details></aside>'
    return raw.replace('<body>', '<body>' + banner)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', type=Path, required=True)
    args = parser.parse_args()
    factory = args.factory.resolve()
    sys.path.insert(0, str(factory / 'ci'))
    from demo_cdp import seed_demo, serve_demo, stop
    out = ROOT / 'demo'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hivemill-marketing-demo-') as tmp:
        scenario = Path(tmp) / 'factory'
        seed_demo(scenario, datetime.now(timezone.utc).isoformat(timespec='seconds'))
        port, process = serve_demo(scenario)
        try:
            queue, queued, pages = deque(BASE_PATHS), set(BASE_PATHS), {}
            while queue:
                route = queue.popleft()
                with urlopen(f'http://127.0.0.1:{port}' + route, timeout=20) as response:
                    raw = response.read().decode()
                pages[route] = raw
                for ref in HREF.findall(raw):
                    target = canonical(ref)
                    if target and target not in queued and supported(target):
                        queued.add(target); queue.append(target)
                if len(queued) > 1500:
                    raise RuntimeError('Demo route graph unexpectedly large; inspect before exporting.')
        finally:
            stop(process)
    for route, raw in pages.items():
        (out / filename(route)).write_text(render(raw, pages))
    shutil.copytree(factory / 'web/static', out / 'static', dirs_exist_ok=True)
    # Stylesheet URLs must remain inside /demo/static on a static host.
    for css in (out / 'static').glob('*.css'):
        css.write_text(re.sub(r'''url\((["']?)/static/''', r'url(\1', css.read_text()))
    shutil.copyfile(ROOT / 'assets/css/demo.css', out / 'static/demo.css')
    # Theme preference must not affect a live factory on another path of the same origin.
    theme = out / 'static/theme.js'
    theme.write_text(theme.read_text().replace('"factory-theme"', '"hivemill-demo-theme"').replace('"factory-keep"', '"hivemill-demo-keep"'))
    provenance = {'source': 'https://github.com/volekerb/hivemill',
                  'sha': subprocess.check_output(['git', '-C', str(factory), 'rev-parse', 'HEAD'], text=True).strip(),
                  'data': 'Isolated ci demo_seed fictional data; no live factory data',
                  'pages': len(pages), 'routes': {k: filename(k) for k in sorted(pages)}}
    (out / 'manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'Exported {len(pages)} real dashboard views to {out}')

if __name__ == '__main__': main()
