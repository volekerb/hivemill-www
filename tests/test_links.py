"""Committed-source checks: every <img> is sized and labelled; 404.html links resolve."""
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from site_metadata import page_paths  # noqa: E402

LINK_ATTRS = ('href', 'src', 'data-src')
# The 404 links are resolved in the built site (what GitHub Pages serves), because /demo/ is generated.
SITE = Path(os.environ.get('SITE_ROOT', ROOT / 'build/site')).resolve()


class Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.imgs = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img':
            self.imgs.append(attrs)
        for name in LINK_ATTRS:
            if attrs.get(name):
                self.links.append(attrs[name])

    handle_startendtag = handle_starttag


def scan(path):
    parser = Scan()
    parser.feed(path.read_text(encoding='utf-8'))
    return parser


def pages():
    return page_paths(ROOT) + [ROOT / '404.html']


def positive_int(value):
    return re.fullmatch(r'[0-9]+', (value or '').strip()) is not None and int(value) > 0


def image_problems(attrs):
    problems = []
    for name in ('width', 'height'):
        if not positive_int(attrs.get(name)):
            problems.append(f'{name} is missing or not a positive integer ({attrs.get(name)!r})')
    alt = attrs.get('alt')
    if alt is None:
        problems.append('alt is missing')
    elif not alt.strip() and attrs.get('role') != 'presentation' and attrs.get('aria-hidden') != 'true':
        problems.append('alt is empty without role="presentation" or aria-hidden="true"')
    return problems


def broken_links(page, links, root):
    """Local links of `page` (a page of the site at `root`) that do not resolve under `root`.

    A directory link resolves only to its index.html.
    """
    broken = []
    for url in links:
        parts = urlsplit(url.strip())
        if parts.scheme or parts.netloc or not parts.path:
            continue  # http(s), mailto:, tel:, //host, #fragment-only
        path = unquote(parts.path)
        target = (root / path.lstrip('/')) if path.startswith('/') else (page.parent / path)
        target = target.resolve()
        inside = target == root or root in target.parents
        if not inside or not (target.is_file() or (target / 'index.html').is_file()):
            broken.append(url)
    return broken


class TestLinks(unittest.TestCase):
    def test_every_image_is_sized_and_labelled(self):
        failures = []
        for page in pages():
            for attrs in scan(page).imgs:
                for problem in image_problems(attrs):
                    failures.append(f'{page.relative_to(ROOT)}: <img src="{attrs.get("src")}">: {problem}')
        self.assertEqual(failures, [])

    def test_404_local_links_resolve(self):
        self.assertTrue((SITE / 'index.html').is_file(),
                        f'built site not found at {SITE}: run tools/build_site.py (or set SITE_ROOT)')
        page = SITE / '404.html'
        self.assertEqual(broken_links(page, scan(page).links, SITE), [])

    def test_not_vacuous(self):
        checked = pages()
        self.assertGreaterEqual(len(checked), 30)
        self.assertGreaterEqual(sum(len(scan(p).imgs) for p in checked), 1)
        self.assertTrue(scan(ROOT / '404.html').links)


if __name__ == '__main__':
    unittest.main()
