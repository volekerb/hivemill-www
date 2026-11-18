"""Rebuild marketing views from committed full-page captures of the isolated demo.

No UI is synthesized. A complete-width content region is cropped, then downsampled
for the 1x variant. The source captures were taken through the connected browser.
"""
from pathlib import Path
import hashlib
import json
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / 'assets/brand/captures'
IMG = ROOT / 'assets/img'
VIEWS = ('agents', 'goals', 'home', 'goal')
CROP = (240, 100, 1280, 740)

def main():
    entries = json.loads((IMG/'SOURCES.json').read_text())
    sha = json.loads((ROOT/'demo/source.json').read_text())['sha']
    for view in VIEWS:
        for theme in ('light','dark'):
            source = CAPTURES/f'{view}-{theme}.jpg'
            data = source.read_bytes()
            with Image.open(source) as original:
                if original.width < CROP[2] or original.height < CROP[3]:
                    raise ValueError(f'{source} does not cover the declared crop')
                big = original.crop(CROP).convert('RGB')
            for density, size in ((1,(520,320)),(2,(1040,640))):
                im = big if density == 2 else big.resize(size,Image.Resampling.LANCZOS)
                for ext in ('png','webp'):
                    legacy=f'{view}-{theme}-{density}x.{ext}'
                    filename=f'{view}-current-{theme}-{density}x.{ext}'
                    im.save(IMG/filename,**({'lossless':True,'method':6} if ext=='webp' else {'optimize':True}))
                    record=next(e for e in entries if e['file'] in (legacy,filename))
                    record['file']=filename
                    (IMG/legacy).unlink(missing_ok=True)
                    record.update(width=size[0],height=size[1],source_sha=sha,
                        source_path=f'assets/brand/captures/{source.name}; actual exported demo UI',
                        source_sha256=hashlib.sha256(data).hexdigest(),
                        crop='x=240,y=100,width=1040,height=640; full-width main content',
                        capture_now='2026-11-18',kind='browser-capture',density=density)
    (IMG/'SOURCES.json').write_text(json.dumps(entries,indent=1)+'\n')
    print('Rebuilt 32 responsive assets from 8 real full-page captures.')

if __name__ == '__main__':
    main()
