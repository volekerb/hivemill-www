"""The Lighthouse gate measures every public page, with exact thresholds and no public upload."""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import site_metadata  # noqa: E402

CONFIG = ROOT / 'lighthouserc.json'
HOST = 'http://localhost'


def config():
    return json.loads(CONFIG.read_text())


def public_pages():
    return sorted(path.relative_to(ROOT).as_posix() for path in site_metadata.page_paths(ROOT))


def listed_pages():
    pages = []
    for url in config()['ci']['collect']['url']:
        parts = urlsplit(url)
        if (f'{parts.scheme}://{parts.netloc}' != HOST or parts.query or parts.fragment
                or not parts.path.endswith('/index.html')):
            raise AssertionError(f'lighthouserc.json URL must be {HOST}/<path>/index.html: {url}')
        pages.append(parts.path.removeprefix('/'))
    return pages


class TestLighthouseConfig(unittest.TestCase):
    def test_lists_exactly_the_public_pages(self):
        pages, listed = public_pages(), listed_pages()
        self.assertGreaterEqual(len(pages), 30, 'page_paths found too few public pages')
        duplicates = sorted({page for page in listed if listed.count(page) > 1})
        self.assertEqual(duplicates, [], f'lighthouserc.json lists a page twice: {duplicates}')
        self.assertEqual(
            sorted(listed), pages,
            f'missing from lighthouserc.json: {sorted(set(pages) - set(listed))}; '
            f'listed but not a public page: {sorted(set(listed) - set(pages))}')

    def test_collects_three_mobile_runs_of_the_built_site(self):
        collect = config()['ci']['collect']
        self.assertEqual(collect['staticDistDir'], 'build/site')
        self.assertEqual(collect['numberOfRuns'], 3)
        # No preset or form factor override: Lighthouse defaults to mobile.
        self.assertNotIn('preset', collect.get('settings', {}))
        self.assertNotIn('formFactor', collect.get('settings', {}))
        self.assertNotIn('screenEmulation', collect.get('settings', {}))

    def test_asserts_exact_thresholds_on_the_median_run(self):
        assertions = config()['ci']['assert']['assertions']
        expected = {
            'categories:performance': {'minScore': 0.9},
            'categories:accessibility': {'minScore': 0.9},
            'cumulative-layout-shift': {'maxNumericValue': 0.01},
        }
        for name, limit in expected.items():
            with self.subTest(assertion=name):
                self.assertIn(name, assertions)
                self.assertEqual(assertions[name], ['error', {**limit, 'aggregationMethod': 'median-run'}])

    def test_reports_stay_on_the_runner(self):
        self.assertNotIn('temporary-public-storage', CONFIG.read_text())
        self.assertEqual(config()['ci']['upload'], {'target': 'filesystem', 'outputDir': '.lighthouseci'})


if __name__ == '__main__':
    unittest.main()
