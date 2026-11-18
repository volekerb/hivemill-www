"""Static demo integrity: no live endpoints, complete links, truthful labeling."""
import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
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
        pages = list((ROOT / 'demo').glob('*.html'))
        self.assertGreater(len(pages), 9)
        for page in pages:
            parser = Links(); parser.feed(page.read_text())
            for ref in parser.refs:
                url = urlsplit(ref)
                self.assertFalse(url.netloc or url.scheme, f'{page.name}: external endpoint {ref}')
                path = (page.parent / unquote(url.path)).resolve()
                self.assertTrue(path.is_relative_to(ROOT), f'Escapes website: {ref}')
                self.assertTrue(path.exists(), f'{page.name}: missing {ref}')
            self.assertFalse(parser.refresh, f'{page.name}: misleading auto-refresh')

    def test_demo_is_labeled_and_manifest_is_complete(self):
        demo = ROOT / 'demo'
        manifest = json.loads((demo / 'manifest.json').read_text())
        self.assertEqual(manifest['pages'], len(manifest['routes']))
        for route, name in manifest['routes'].items():
            raw = (demo / name).read_text()
            self.assertIn('Fictional data · No agents running', raw)
            self.assertIn('Demo snapshot', raw)
            self.assertNotRegex(raw, r'https?://192\.168\.')
            self.assertNotIn('127.0.0.1:', raw)
            self.assertEqual(export.filename(route), name)

    def test_stylesheet_assets_resolve_under_the_demo_path(self):
        refs = []
        for css in (ROOT / 'demo/static').glob('*.css'):
            for value in re.findall(r'url\(([^)]+)\)', css.read_text()):
                ref = value.strip().strip('"\'')
                url = urlsplit(ref)
                if url.scheme == 'data':
                    continue
                refs.append(ref)
                self.assertFalse(url.scheme or url.netloc, f'{css.name}: external asset {ref}')
                path = ROOT / url.path.lstrip('/') if url.path.startswith('/') else css.parent / url.path
                self.assertTrue(path.is_file(), f'{css.name}: missing stylesheet asset {ref}')
        self.assertGreaterEqual(len(refs), 4, 'expected the four self-hosted font faces')

    def test_fictional_pr_does_not_link_to_an_unrelated_repository(self):
        raw = '<body><a href="https://github.com/example/shop/pull/123">#123</a></body>'
        rendered = export.render(raw, {})
        self.assertIn('Fictional pull request in the demo', rendered)
        self.assertNotIn('href="https://github.com/example', rendered)

if __name__ == '__main__': unittest.main()
