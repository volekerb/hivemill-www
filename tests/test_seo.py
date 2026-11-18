"""Search/discovery and public navigation contracts, checked against the actual artifact."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(os.environ.get('SITE_ROOT', ROOT / 'build/site')).resolve()
sys.path.insert(0, str(ROOT / 'tools'))
import site_metadata as metadata


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas = {}
        self.canonicals = []
        self.refs = []
        self.ids = set()
        self.h1s = 0
        self.in_title = False
        self.title = ''
        self.json_data = []
        self.in_json = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'h1':
            self.h1s += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            key = attrs.get('name') or attrs.get('property')
            if key:
                self.metas.setdefault(key, []).append(attrs.get('content'))
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))
        for key in ('href', 'src', 'data-src'):
            if attrs.get(key):
                self.refs.append(attrs[key])
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.in_json = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'script':
            self.in_json = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_json:
            self.json_data.append(json.loads(data))


def parse(path):
    page = Page()
    page.feed(path.read_text())
    return page


class TestSearch(unittest.TestCase):
    def test_metadata_render_is_idempotent_and_escapes_content(self):
        original = ('<html><head><title>A &amp; B</title><meta name="description" '
                    'content="A &quot;quoted&quot; description &amp; facts.">'
                    '<link rel="canonical" href="https://wrong.invalid/">\n'
                    '<meta property="og:title" content="Old">\n</head><body>Keep me.</body></html>')
        rendered = metadata.apply_metadata(original, 'index.html')
        self.assertEqual(metadata.apply_metadata(rendered, 'index.html'), rendered)
        parsed = Page()
        parsed.feed(rendered)
        self.assertEqual(parsed.canonicals, ['https://hivemill.dev/'])
        self.assertEqual(parsed.metas['og:title'], ['A & B'])
        self.assertEqual(parsed.metas['og:description'], ['A "quoted" description & facts.'])
        self.assertIn('<body>Keep me.</body>', rendered)
        self.assertTrue(parsed.json_data)

    def test_source_metadata_is_current(self):
        self.assertEqual(metadata.sync_metadata(ROOT), [], 'run tools/site_metadata.py --write')

    def test_public_pages_have_consistent_unique_metadata(self):
        titles, urls = [], []
        for source in metadata.page_paths(ROOT):
            relative = source.relative_to(ROOT)
            page = SITE / relative
            self.assertTrue(page.is_file(), f'missing public page: {relative}')
            parsed = parse(page)
            expected = metadata.page_url(relative)
            self.assertEqual(parsed.canonicals, [expected], str(relative))
            self.assertEqual(parsed.h1s, 1, str(relative))
            for key in ('description', 'og:title', 'og:description', 'og:url', 'og:type',
                        'og:image', 'twitter:card', 'twitter:title', 'twitter:description', 'twitter:image'):
                self.assertEqual(len(parsed.metas.get(key, [])), 1, f'{relative}: {key}')
                self.assertTrue(parsed.metas[key][0], f'{relative}: empty {key}')
            self.assertEqual(parsed.metas['og:url'], [expected])
            self.assertEqual(parsed.metas['og:title'], [parsed.title])
            self.assertEqual(parsed.metas['og:description'], parsed.metas['description'])
            self.assertNotIn('noindex', ','.join(parsed.metas.get('robots', [])))
            titles.append(parsed.title)
            urls.append(expected)
        self.assertEqual(len(titles), len(set(titles)), 'distinct page intents need distinct titles')
        self.assertEqual(len(urls), len(set(urls)))

    def test_sitemap_only_lists_intended_canonical_destinations(self):
        expected = {metadata.page_url(p.relative_to(ROOT)) for p in metadata.page_paths(ROOT)}
        tree = ET.parse(SITE / 'sitemap.xml')
        actual = [node.text for node in tree.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(expected), 'no duplicate sitemap entries')
        self.assertFalse(any('/demo/' in url or 'template' in url for url in actual))
        robots = (SITE / 'robots.txt').read_text()
        self.assertIn('User-agent: *\nAllow: /', robots)
        self.assertIn('Sitemap: https://hivemill.dev/sitemap.xml', robots)
        self.assertNotIn('Disallow:', robots, 'do not prevent crawlers reading demo noindex')

    def test_templates_and_unresolved_template_variables_are_not_published(self):
        for name in ('template.html', 'detail-template.html', 'overrides.json'):
            self.assertFalse((SITE / 'catalog' / name).exists(), f'source-only catalog file: {name}')
        for source in metadata.page_paths(ROOT):
            page = SITE / source.relative_to(ROOT)
            self.assertNotRegex(page.read_text(), r'\{\{(?:root|title|description|content|built)\}\}', str(page))

    def test_public_links_assets_and_fragment_targets_resolve(self):
        parsed_targets = {}
        for source in metadata.page_paths(ROOT):
            page = SITE / source.relative_to(ROOT)
            parsed = parse(page)
            for ref in parsed.refs:
                url = urlsplit(ref)
                if url.scheme or url.netloc:
                    continue
                target = SITE / unquote(url.path).lstrip('/') if url.path.startswith('/') else page.parent / unquote(url.path)
                if not url.path:
                    target = page
                target = target.resolve()
                self.assertTrue(target.is_relative_to(SITE), f'{page}: escaping reference {ref}')
                if target.is_dir():
                    target /= 'index.html'
                self.assertTrue(target.is_file(), f'{page}: missing {ref}')
                if url.fragment and target.suffix == '.html':
                    if target not in parsed_targets:
                        parsed_targets[target] = parse(target)
                    self.assertIn(unquote(url.fragment), parsed_targets[target].ids, f'{page}: missing fragment {ref}')

    def test_demo_search_exclusion_is_preserved(self):
        pages = list((SITE / 'demo').glob('*.html'))
        self.assertEqual(len(pages), json.loads((ROOT / 'demo/source.json').read_text())['routes']['count'])
        for path in pages:
            self.assertIn('noindex', ','.join(parse(path).metas.get('robots', [])), path.name)


if __name__ == '__main__':
    unittest.main()
