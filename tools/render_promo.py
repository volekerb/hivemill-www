"""Make a silent 30-second product film from real captures and Higgsfield footage.

No product content is synthesized or retouched. Screenshots are cropped and framed.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from fontTools.ttLib import TTFont
import imageio_ffmpeg
import subprocess

BASE = Path(__file__).resolve().parent.parent
SITE = BASE
OUT = BASE / 'assets/brand'
WORK = BASE / '.local/promo'
WORK.mkdir(parents=True, exist_ok=True)
FONT = WORK / 'instrument.ttf'
font = TTFont(SITE / 'assets/fonts/instrument-sans-latin.woff2')
font.flavor = None
font.save(FONT)
W, H = 1920, 1080
BG, WHITE, MUTED, AMBER = '#141513', '#f1f2eb', '#afb5a6', '#e9ad3f'

def text(draw, xy, value, size, fill=WHITE, spacing=4):
    draw.multiline_text(xy, value, font=ImageFont.truetype(str(FONT), size), fill=fill, spacing=spacing)

def base():
    canvas = Image.new('RGB', (W,H), BG)
    draw = ImageDraw.Draw(canvas)
    text(draw,(96,52),'Hivemill',32)
    return canvas

def framed(canvas, path, box, crop=None):
    im = Image.open(path).convert('RGB')
    if crop: im = im.crop(crop)
    im.thumbnail((box[2],box[3]), Image.Resampling.LANCZOS)
    x,y=box[0]+(box[2]-im.width)//2,box[1]+(box[3]-im.height)//2
    shadow=Image.new('RGBA',(W,H))
    ImageDraw.Draw(shadow).rounded_rectangle((x-1,y+14,x+im.width+1,y+im.height+14),18,fill=(0,0,0,150))
    canvas.paste(Image.alpha_composite(canvas.convert('RGBA'),shadow.filter(ImageFilter.GaussianBlur(28))).convert('RGB'))
    canvas.paste(im,(x,y))
    ImageDraw.Draw(canvas).rounded_rectangle((x-1,y-1,x+im.width,y+im.height),8,outline='#4d5347',width=2)

def finish(canvas, n, caption=None):
    if caption: text(ImageDraw.Draw(canvas),(96,1008),caption,23,MUTED)
    canvas.save(WORK/f'scene-{n}.png')

# Opening: fixed type over the moving Higgsfield machinery.
c=base()
hero=Image.open(SITE/'assets/brand/hive-mill-master.png').convert('RGB')
hero=hero.resize((W,H),Image.Resampling.LANCZOS)
c.paste(hero)
shade=Image.new('RGBA',(W,H)); sd=ImageDraw.Draw(shade)
for x in range(W):
    alpha=int(190*max(0,1-x/1600))
    sd.line((x,0,x,H),fill=(20,21,19,alpha))
c=Image.alpha_composite(c.convert('RGBA'),shade).convert('RGB'); d=ImageDraw.Draw(c)
text(d,(96,52),'Hivemill',32)
text(d,(96,290),'Close your laptop.\nKeep work moving.',96,spacing=0)
text(d,(100,566),'AI agents on your infrastructure.\nA laptop free for everything else.',34,MUTED,10)
finish(c,0)

# A real running factory overview, never an invented product interface.
c=base();d=ImageDraw.Draw(c)
text(d,(96,134),'Set the goal. The factory keeps working.',66)
text(d,(99,225),'Engineers, product managers and builders delegate to a team on their server.',30,MUTED)
framed(c,(SITE/'assets/brand/captures')/'current-factory-demo.jpg',(228,320,1464,620))
finish(c,1,'Real Hivemill interface. Fictional demo data.')

# The existing high-resolution capture is kept intact inside its frame.
c=base();d=ImageDraw.Draw(c)
text(d,(96,134),'Follow the work. See the pull requests.',66)
text(d,(99,225),'Clear tasks, assigned agents and an inspectable delivery process.',30,MUTED)
framed(c,SITE/'assets/img/tasks-wide-dark-2x.png',(210,320,1500,620))
finish(c,2,'Real Hivemill task view. Fictional demo data.')

# Focused crop of an actual review/retry record; headings explain the mechanism.
c=base();d=ImageDraw.Draw(c)
text(d,(96,134),'Independent checks. A judge-controlled merge.',62)
text(d,(99,225),'Review and QA must pass. Findings go back to the coder.',30,MUTED)
framed(c,(SITE/'assets/brand/captures')/'current-factory-review.jpg',(250,340,1420,520),crop=(250,195,1265,780))
text(d,(270,905),'REVIEWER',28,AMBER);text(d,(693,905),'QA',28,AMBER);text(d,(1060,905),'JUDGE',28,AMBER)
text(d,(270,945),'Reads the diff',23,MUTED);text(d,(693,945),'Runs the tests',23,MUTED);text(d,(1060,945),'Decides the merge',23,MUTED)
finish(c,3,'Actual review-and-retry record. Fictional demo data; this task is still in review.')

# Real resource gauges and the actual Herdr budget panel, with no changed values.
c=base();d=ImageDraw.Draw(c)
text(d,(96,134),'Resources. Cost. The work that needs you.',64)
text(d,(99,225),'Monitor the operation while the factory works on your infrastructure.',30,MUTED)
framed(c,(SITE/'assets/brand/captures')/'current-factory-resources.jpg',(96,340,1040,480),crop=(250,86,1262,380))
framed(c,SITE/'assets/img/herdr-budget-1x.png',(1230,330,600,520))
text(d,(100,880),'Capacity and agent-start checks',28,AMBER)
text(d,(1230,880),'Budget visibility in Herdr',28,AMBER)
finish(c,4,'Real interfaces. Fictional demo data. Cost estimates are not invoices; Cursor token cost is not reported.')

c=base()
art=Image.open(SITE/'assets/brand/agency-master.png').convert('RGB');art.thumbnail((960,800),Image.Resampling.LANCZOS)
c.paste(art,(960,180));d=ImageDraw.Draw(c)
text(d,(96,280),'Your own\nsoftware factory.',100,spacing=0)
text(d,(101,552),'Self-hosted. Open source.\nBuilt around independent checks.',35,MUTED,12)
text(d,(101,766),'hivemill.dev',42,AMBER)
finish(c,5)

# Fixed typography layers for the two moving brand scenes.
for n in (0,5):
    overlay=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(overlay)
    for x in range(W):
        alpha=int(210*max(0,1-x/1600))
        d.line((x,0,x,H),fill=(20,21,19,alpha))
    text(d,(96,52),'Hivemill',32)
    if n==0:
        text(d,(96,290),'Close your laptop.\nKeep work moving.',96,spacing=0)
        text(d,(100,566),'AI agents on your infrastructure.\nA laptop free for everything else.',34,MUTED,10)
    else:
        text(d,(96,280),'Your own\nsoftware factory.',100,spacing=0)
        text(d,(101,552),'Self-hosted. Open source.\nBuilt around independent checks.',35,MUTED,12)
        text(d,(101,766),'hivemill.dev',42,AMBER)
    overlay.save(WORK/f'overlay-{n}.png')

ff=imageio_ffmpeg.get_ffmpeg_exe()
clips=[]
for n in range(6):
    dest=WORK/f'clip-{n}.mp4';clips.append(dest)
    cmd=[ff,'-y','-hide_banner','-loglevel','error','-filter_complex_threads','2','-threads','2']
    if n in (0,5):
        cmd+=['-i',str(OUT/'hive-mill-motion.mp4'),'-loop','1','-framerate','30','-i',str(WORK/f'overlay-{n}.png'),
              '-filter_complex','[0:v]fps=30,scale=1920:1080,setsar=1,tpad=stop_mode=clone:stop_duration=0.5[base];[base][1:v]overlay=0:0,format=yuv420p[v]',
              '-map','[v]']
    else:
        cmd+=['-loop','1','-framerate','30','-i',str(WORK/f'scene-{n}.png'),'-vf','format=yuv420p,setsar=1']
    cmd+=['-t','5.4','-an','-c:v','libx264','-preset','fast','-crf','18','-threads','2',str(dest)]
    subprocess.run(cmd,check=True);print('Rendered scene',n+1,flush=True)
cmd=[ff,'-y','-hide_banner','-loglevel','error','-filter_complex_threads','2']
for clip in clips:cmd+=['-i',str(clip)]
filters=['[0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.9[v1]']
for n in range(2,6): filters.append(f'[v{n-1}][{n}:v]xfade=transition=fade:duration=0.5:offset={4.9*n}[v{n}]')
cmd+=['-filter_complex',';'.join(filters),'-map','[v5]','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2','-movflags','+faststart',str(OUT/'hivemill-promo.mp4')]
subprocess.run(cmd,check=True)
print('Wrote',OUT/'hivemill-promo.mp4',flush=True)
