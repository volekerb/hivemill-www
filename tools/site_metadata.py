"""Render/check shared search metadata; generate discovery files for the public site."""
import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://hivemill.dev'
PAGE_DIRS = ('catalog', 'factories', 'film', 'guides', 'work-with-me')
IMAGE = ORIGIN + '/assets/brand/hive-mill-master.png'
START = '<!-- Generated search metadata: tools/site_metadata.py -->'
END = '<!-- End generated search metadata -->'


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''
        self.description = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and attrs.get('name', '').lower() == 'description':
            self.description = attrs.get('content', '')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def page_paths(root):
    """Only deliberate marketing destinations, never demo variants or source templates."""
    root = Path(root)
    return [root / 'index.html'] + sorted(
        page for directory in PAGE_DIRS for page in (root / directory).rglob('index.html'))


def page_url(relative):
    path = Path(relative).as_posix()
    if path == 'index.html':
        return ORIGIN + '/'
    if not path.endswith('/index.html') or '..' in Path(path).parts or path.startswith('/'):
        raise ValueError(f'Not a marketing index path: {relative}')
    return ORIGIN + '/' + path.removesuffix('index.html')


def structured_data(relative, title, description):
    url = page_url(relative)
    if str(relative) == 'index.html':
        return {'@context': 'https://schema.org', '@graph': [
            {'@type': 'WebSite', '@id': ORIGIN + '/#website', 'name': 'Hivemill', 'url': url},
            {'@type': 'SoftwareSourceCode', '@id': ORIGIN + '/#software', 'name': 'Hivemill',
             'url': url, 'description': description, 'codeRepository': 'https://github.com/volekerb/hivemill',
             'license': 'https://github.com/volekerb/hivemill/blob/main/LICENSE'}]}
    if Path(relative).parts[0] == 'catalog':
        crumbs = [('Hivemill', ORIGIN + '/'), ('Catalog', ORIGIN + '/catalog/')]
        if str(relative) != 'catalog/index.html':
            crumbs.append((title.removesuffix(' | Hivemill'), url))
        return {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': index, 'name': name, 'item': item}
            for index, (name, item) in enumerate(crumbs, 1)]}
    return None


def apply_metadata(text, relative):
    """Keep author-owned title/description; deterministically derive the shared metadata."""
    text = re.sub(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)
    head, separator, body = text.partition('</head>')
    if not separator:
        raise ValueError(f'{relative}: missing </head>')
    parsed = Head()
    parsed.feed(head)
    title, description = parsed.title.strip(), parsed.description.strip()
    if not title or not description:
        raise ValueError(f'{relative}: title and description are required')
    # Replace the old scattered tags once; never alter body markup or source-code examples.
    head = re.sub(r'[ \t]*<link\b(?=[^>]*\brel=["\']canonical["\'])[^>]*>\s*\n?', '', head,
                  flags=re.M | re.I)
    head = re.sub(r'[ \t]*<meta\b(?=[^>]*\b(?:property|name)=["\'](?:og:|twitter:)[^"\']*["\'])[^>]*>\s*\n?',
                  '', head, flags=re.M | re.I)
    url = page_url(relative)
    esc = lambda value: html.escape(value, quote=True)
    tags = [START, f'<link rel="canonical" href="{url}">']
    for key, value in [('og:type', 'website'), ('og:site_name', 'Hivemill'), ('og:title', title),
                       ('og:description', description), ('og:url', url), ('og:image', IMAGE),
                       ('og:image:width', '1344'), ('og:image:height', '752'),
                       ('og:image:alt', 'Hivemill honeycomb production line with amber workpieces')]:
        tags.append(f'<meta property="{key}" content="{esc(value)}">')
    for key, value in [('twitter:card', 'summary_large_image'), ('twitter:title', title),
                       ('twitter:description', description), ('twitter:image', IMAGE),
                       ('twitter:image:alt', 'Hivemill honeycomb production line with amber workpieces')]:
        tags.append(f'<meta name="{key}" content="{esc(value)}">')
    data = structured_data(relative, title, description)
    if data:
        encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
        tags.append('<script type="application/ld+json">' + encoded + '</script>')
    tags.append(END)
    return head.rstrip() + '\n' + '\n'.join(tags) + '\n</head>' + body


def sync_metadata(root, write=False):
    stale = []
    for page in page_paths(root):
        original = page.read_text()
        rendered = apply_metadata(original, page.relative_to(root))
        if original != rendered:
            stale.append(str(page.relative_to(root)))
            if write:
                page.write_text(rendered)
    return stale


def validate_metadata(root):
    stale = sync_metadata(root)
    if stale:
        raise ValueError('Stale search metadata: ' + ', '.join(stale) +
                         '. Run python3 tools/site_metadata.py --write after editing titles/descriptions.')


def write_discovery(root):
    root = Path(root)
    ns = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('', ns)
    sitemap = ET.Element(f'{{{ns}}}urlset')
    for page in page_paths(root):
        entry = ET.SubElement(sitemap, f'{{{ns}}}url')
        ET.SubElement(entry, f'{{{ns}}}loc').text = page_url(page.relative_to(root))
    ET.indent(sitemap, space='  ')
    (root / 'sitemap.xml').write_bytes(ET.tostring(sitemap, encoding='utf-8', xml_declaration=True) + b'\n')
    # Search and training policy stay unchanged: the previous site allowed all crawlers.
    # Do not block demo crawling: crawlers need to read each page's existing noindex.
    (root / 'robots.txt').write_text('User-agent: *\nAllow: /\n\nSitemap: ' + ORIGIN + '/sitemap.xml\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = sync_metadata(ROOT, write=args.write)
    if stale and args.check:
        parser.exit(1, 'Stale search metadata: ' + ', '.join(stale) + '\nRun tools/site_metadata.py --write.\n')
    print(f'Search metadata {"updated" if args.write else "checked"}: {len(page_paths(ROOT))} pages')


if __name__ == '__main__':
    main()
