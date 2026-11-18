"""Static demo integrity: no live endpoints, complete links, truthful labeling."""
import importlib.util
import hashlib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(os.environ.get('SITE_ROOT', ROOT / 'build/site')).resolve()
spec = importlib.util.spec_from_file_location('export_demo', ROOT / 'tools/export_demo.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

class Links(HTMLParser):
    def __init__(self): super().__init__(); self.refs = []; self.refresh = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ('href', 'src'):
            if key in a: self.refs.append(a[key])
        if tag == 'meta' and a.get('http-equiv', '').lower() == 'refresh': self.refresh = True

class TestDemo(unittest.TestCase):
    def test_external_sources_cannot_enter_route_graph(self):
        for ref in ('http://192.0.2.1:8765/', '//example.com/tasks', '/api/tasks.json', '/static/app.css'):
            self.assertIsNone(export.canonical(ref))
        self.assertEqual(export.canonical('/tasks?status=blocked&amp;org=claude'), '/tasks?org=claude&status=blocked')

    def test_compound_filters_are_explicitly_bounded(self):
        self.assertTrue(export.supported('/tasks?org=claude&status=blocked'))
        self.assertFalse(export.supported('/tasks?goal=G-001&status=blocked'))
        self.assertFalse(export.supported('/tokens?goal=G-001&model=example'))

    def test_every_demo_link_and_asset_resolves_locally(self):
        pages = list((SITE / 'demo').glob('*.html'))
        self.assertGreater(len(pages), 9)
        for page in pages:
            parser = Links(); parser.feed(page.read_text())
            for ref in parser.refs:
                url = urlsplit(ref)
                self.assertFalse(url.netloc or url.scheme, f'{page.name}: external endpoint {ref}')
                path = (page.parent / unquote(url.path)).resolve()
                self.assertTrue(path.is_relative_to(SITE), f'Escapes website: {ref}')
                self.assertTrue(path.exists(), f'{page.name}: missing {ref}')
                if path.is_dir():
                    self.assertTrue((path / 'index.html').is_file(), f'{page.name}: directory has no index: {ref}')
            self.assertFalse(parser.refresh, f'{page.name}: misleading auto-refresh')

    def test_demo_is_labeled_and_manifest_is_complete(self):
        demo = SITE / 'demo'
        manifest = json.loads((demo / 'manifest.json').read_text())
        source = json.loads((ROOT / 'demo/source.json').read_text())
        self.assertEqual(manifest['sha'], source['sha'])
        self.assertEqual(manifest['pages'], source['routes']['count'])
        self.assertEqual(hashlib.sha256(json.dumps(manifest['routes'], sort_keys=True).encode()).hexdigest(),
                         source['routes']['sha256'], 'existing demo URLs must remain compatible')
        self.assertEqual(manifest['pages'], len(manifest['routes']))
        self.assertEqual(set(manifest['routes'].values()), {p.name for p in demo.glob('*.html')})
        for route, name in manifest['routes'].items():
            raw = (demo / name).read_text()
            self.assertIn('Fictional data · No agents running', raw)
            self.assertIn('Demo snapshot', raw)
            self.assertNotRegex(raw, r'https?://192\.168\.')
            self.assertNotIn('127.0.0.1:', raw)
            self.assertEqual(export.filename(route), name)

    def test_stylesheet_assets_resolve_under_the_demo_path(self):
        refs = []
        for css in (SITE / 'demo/static').glob('*.css'):
            for value in re.findall(r'url\(([^)]+)\)', css.read_text()):
                ref = value.strip().strip('"\'')
                url = urlsplit(ref)
                if url.scheme == 'data':
                    continue
                refs.append(ref)
                self.assertFalse(url.scheme or url.netloc, f'{css.name}: external asset {ref}')
                path = SITE / url.path.lstrip('/') if url.path.startswith('/') else css.parent / url.path
                self.assertTrue(path.is_file(), f'{css.name}: missing stylesheet asset {ref}')
        self.assertGreaterEqual(len(refs), 4, 'expected the four self-hosted font faces')

    def test_demo_theme_preferences_are_isolated(self):
        theme = (SITE / 'demo/static/theme.js').read_text()
        self.assertIn('"hivemill-demo-theme"', theme)
        self.assertIn('"hivemill-demo-keep"', theme)
        self.assertNotIn('"factory-theme"', theme)
        self.assertNotIn('"factory-keep"', theme)

    def test_demo_capacity_does_not_depend_on_the_build_machine(self):
        machine = json.loads((ROOT / 'demo/source.json').read_text())['machine']
        label = f'{machine["load"][0]:.1f} / {machine["cpus"]} CPUs'
        for name in ('index.html', 'resources.html'):
            self.assertIn(label, (SITE / 'demo' / name).read_text())

    def test_artifact_contains_public_pages_without_source_or_factory_data(self):
        self.assertTrue((SITE / '.nojekyll').is_file())
        self.assertEqual((SITE / 'CNAME').read_text().strip(), 'hivemill.dev')
        for name in ('.git', '.github', '.local', 'tools', 'tests', 'requirements-dev.txt', 'README.md'):
            self.assertFalse((SITE / name).exists(), f'source-only path leaked into artifact: {name}')
        for page in ROOT.rglob('index.html'):
            relative = page.relative_to(ROOT)
            if relative.parts[0] in ('build', 'demo', '.local', '.git'):
                continue
            self.assertEqual((SITE / relative).read_bytes(), page.read_bytes(), f'missing/stale public page: {relative}')
        self.assertFalse(list(SITE.rglob('*.db')), 'factory database must never be deployed')
        self.assertFalse((SITE / 'demo/source.json').exists())

    def test_fictional_pr_does_not_link_to_an_unrelated_repository(self):
        raw = '<body><a href="https://github.com/example/shop/pull/123">#123</a></body>'
        rendered = export.render(raw, {})
        self.assertIn('Fictional pull request in the demo', rendered)
        self.assertNotIn('href="https://github.com/example', rendered)

if __name__ == '__main__': unittest.main()
