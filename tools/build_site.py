"""Stage public files and generate the pinned demo for GitHub Pages."""
import argparse
from pathlib import Path
import shutil
import tempfile

from export_demo import export_demo
from site_metadata import validate_metadata, write_discovery

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
SITE = BUILD / 'site'
PUBLIC_FILES = ('index.html', 'CNAME', '.nojekyll', 'LICENSE')
PUBLIC_DIRS = ('assets', 'catalog', 'factories', 'film', 'guides', 'work-with-me')


def build_site(factory):
    validate_metadata(ROOT)
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='site-', dir=BUILD) as tmp:
        stage = Path(tmp) / 'site'
        stage.mkdir()
        for name in PUBLIC_FILES:
            shutil.copy2(ROOT / name, stage / name)
        for name in PUBLIC_DIRS:
            ignore = shutil.ignore_patterns('template.html', 'detail-template.html', 'overrides.json') if name == 'catalog' else None
            shutil.copytree(ROOT / name, stage / name, ignore=ignore)
        write_discovery(stage)
        export_demo(factory, stage / 'demo')
        # Replace only our generated output, and only after a successful export.
        if SITE.exists():
            shutil.rmtree(SITE)
        stage.rename(SITE)
    print(f'Website ready at {SITE}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', type=Path, required=True)
    args = parser.parse_args()
    build_site(args.factory)


if __name__ == '__main__':
    main()
