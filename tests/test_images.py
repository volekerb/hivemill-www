"""The site's product screenshots: every <picture> is complete and every file is registered.

Reads the committed pages and assets/img only; no network, no browser, no clock.
Run: python3 -m unittest discover -s tests -p test_images.py
"""
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "assets" / "img"
# Native 1x crops of the Herdr desktop app (one theme, no 2x exists): exempt from light/dark and 2x.
NATIVE = re.compile(r"herdr-[a-z]+-1x\.")


class Pictures(HTMLParser):
    """Collects each <picture> as a list of (tag, attrs) and every <img> outside a picture."""

    def __init__(self):
        super().__init__()
        self.pictures, self.loose, self.catalog, self._cur = [], [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "picture":
            self._cur = []
        elif tag in ("source", "img"):
            if self._cur is not None:
                self._cur.append((tag, a))
            elif tag == "img":
                self.loose.append(a)

    def handle_endtag(self, tag):
        if tag == "picture" and self._cur is not None:
            # catalog panels (T-1809) are native single-theme crops owned by the catalog; tracked for the orphan check only
            img = next((a for t, a in self._cur if t == "img"), {})
            (self.catalog if Path(img.get("src", "")).name.startswith(("panel-", "herdr-panel-")) else self.pictures).append(self._cur)
            self._cur = None


def pages():
    return sorted(p for p in ROOT.rglob("index.html") if ".local" not in p.parts and "build" not in p.parts)


def parse(page):
    p = Pictures()
    p.feed(page.read_text())
    return p


def files_in(srcset):
    return [part.split()[0] for part in srcset.split(",") if part.strip()]


def resolve(page, ref):
    return (page.parent / ref).resolve()


class TestImages(unittest.TestCase):
    def test_pages_have_screenshots(self):
        total = sum(len(parse(p).pictures) for p in pages())
        self.assertGreaterEqual(total, 9, "expected the 9 product screenshots on the pages")

    def test_no_loose_site_images(self):
        # a screenshot is always a <picture>; a bare <img> pointing into assets/ is the old single-file form
        for page in pages():
            for a in parse(page).loose:
                self.assertFalse(re.search(r"\.(png|webp|jpe?g)$", a.get("src", "")),
                                 f"{page.relative_to(ROOT)}: bare <img> {a.get('src')}")

    def test_every_picture_is_complete(self):
        for page in pages():
            for pic in parse(page).pictures:
                where = page.relative_to(ROOT)
                img = [a for t, a in pic if t == "img"]
                self.assertEqual(len(img), 1, f"{where}: a <picture> needs exactly one <img>")
                img = img[0]
                self.assertTrue(img.get("alt"), f"{where}: {img.get('src')} has no alt")
                self.assertTrue(img.get("width", "").isdigit() and img.get("height", "").isdigit(),
                                f"{where}: {img.get('src')} needs explicit width and height")
                if img.get("fetchpriority") != "high":
                    self.assertEqual(img.get("loading"), "lazy", f"{where}: {img.get('src')} must be lazy below the fold")
                for t, a in pic:
                    if t == "source":
                        self.assertTrue(a.get("width", "").isdigit() and a.get("height", "").isdigit(),
                                        f"{where}: <source> {a.get('srcset')} needs width and height (no layout shift)")

    def test_light_dark_webp_png_and_density(self):
        for page in pages():
            for pic in parse(page).pictures:
                where = page.relative_to(ROOT)
                refs = []
                for t, a in pic:
                    refs += files_in(a["srcset"]) if "srcset" in a else []
                    if t == "img":
                        refs.append(a["src"])
                names = {Path(r).name for r in refs}
                self.assertTrue(names, f"{where}: empty picture")
                first = sorted(names)[0]
                for n in names:
                    self.assertTrue(resolve(page, next(r for r in refs if Path(r).name == n)).is_file(),
                                    f"{where}: {n} is missing from assets/img")
                    if NATIVE.match(n):
                        continue
                    stem = re.sub(r"-(light|dark)-[12]x\.(webp|png)$", "", n)
                    for theme in ("light", "dark"):
                        for d in ("1x", "2x"):
                            for ext in ("webp", "png"):
                                want = f"{stem}-{theme}-{d}.{ext}"
                                self.assertIn(want, names, f"{where}: {first} picture lacks {want}")
                # the png fallback is the <img> and carries a 1x/2x srcset unless it is a native 1x crop
                img = next(a for t, a in pic if t == "img")
                if not NATIVE.match(Path(img["src"]).name):
                    self.assertIn("2x", img["srcset"], f"{where}: {img['src']} needs a 2x srcset entry")
                dark = [a for t, a in pic if t == "source" and "dark" in a.get("media", "")]
                if not NATIVE.match(Path(img["src"]).name):
                    self.assertTrue(dark, f"{where}: {img['src']} has no prefers-color-scheme: dark source")

    def test_every_file_is_registered_and_used(self):
        entries = {e["file"]: e for e in json.loads((IMG / "SOURCES.json").read_text())}
        on_disk = {p.name for p in IMG.iterdir() if p.suffix in (".webp", ".png")}
        self.assertEqual(on_disk, set(entries), "assets/img and SOURCES.json disagree")
        used = set()
        for page in pages():
            parsed = parse(page)
            for pic in parsed.pictures + parsed.catalog:
                for t, a in pic:
                    for r in (files_in(a["srcset"]) if "srcset" in a else []) + ([a["src"]] if t == "img" else []):
                        used.add(Path(r).name)
        self.assertEqual(on_disk - used, set(), "orphan files in assets/img (unreferenced); rebuild with tools/images.py")

    def test_sources_json_records_provenance_and_size(self):
        from PIL import Image
        for e in json.loads((IMG / "SOURCES.json").read_text()):
            for k in ("source_repo", "source_sha", "source_path", "source_sha256", "crop", "width", "height"):
                self.assertIn(k, e, f"{e['file']}: SOURCES.json lacks {k}")
            self.assertRegex(e["source_sha"], r"^[0-9a-f]{40}$")
            self.assertRegex(e["source_sha256"], r"^[0-9a-f]{64}$")
            with Image.open(IMG / e["file"]) as im:
                self.assertEqual(im.size, (e["width"], e["height"]), f"{e['file']}: size differs from SOURCES.json")

    def test_attribute_dimensions_match_files(self):
        from PIL import Image
        for page in pages():
            for pic in parse(page).pictures:
                for t, a in pic:
                    ref = a.get("src") if t == "img" else files_in(a["srcset"])[0]
                    with Image.open(resolve(page, ref)) as im:
                        density = 2 if re.search(r"-2x\.", ref) else 1
                        self.assertEqual((im.width // density, im.height // density),
                                         (int(a["width"]), int(a["height"])),
                                         f"{page.relative_to(ROOT)}: {ref} does not match its width/height attributes")

    def test_old_single_file_images_are_gone(self):
        for name in ("agents-light.png", "goals-light.png", "goal-light.png", "home-light.png",
                     "tasks-light.png", "panel-factory.png"):
            self.assertFalse((ROOT / "assets" / name).exists(), f"assets/{name} is superseded; delete it")


if __name__ == "__main__":
    unittest.main()
