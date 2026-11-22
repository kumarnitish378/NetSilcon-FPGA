import json, os, subprocess, asyncio, numpy as np, soundfile as sf
from playwright.async_api import async_playwright
FPS=30; GAP=0.30; BEATGAP=0.75; LEAD=0.5; TAIL=3.0
meta=json.load(open('meta.json'))
# timeline
t=LEAD; segs=[]
for i,m in enumerate(meta):
    last = i==len(meta)-1 or meta[i+1]['beat']!=m['beat']
    pad = TAIL if i==len(meta)-1 else (BEATGAP if last else GAP)
    start=t; L=m['dur']+pad
    if i==0: start=0; L+=LEAD
    # round to frame grid
    nf=round(L*FPS); segs.append(dict(m, start=start if i else 0, nf=nf)); t=start+nf/FPS if i else nf/FPS
total=sum(s['nf'] for s in segs)/FPS
print('total',round(total,1),'s')
# audio
sr=24000; out=np.zeros(int(total*sr)+sr,dtype=np.float32); t=0
for i,s in enumerate(segs):
    a,_=sf.read(s['file'],dtype='float32'); off=int((t+(LEAD if i==0 else 0))*sr); out[off:off+len(a)]+=a; t+=s['nf']/FPS
sf.write('narration.wav',out[:int(total*sr)],sr)
os.makedirs('seg',exist_ok=True); os.makedirs('img',exist_ok=True)
ENC=['-c:v','libx264','-crf','18','-preset','veryfast','-pix_fmt','yuv420p','-r','30']
def run(c): subprocess.run(c,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
async def render():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(viewport={'width':1920,'height':1080})
        await pg.goto('file:///home/claude/vid/scenes.html'); await pg.wait_for_timeout(500); await pg.evaluate('document.fonts.ready')
        acc=0
        for k,s in enumerate(segs):
            s['img']=f'img/{k:03d}.jpg'
            if s['sid']!='sim':
                await pg.evaluate('([a,b,c,d])=>show(a,b,c,d)',[s['sid'],s['line'],s['text'],acc/(total*FPS)])
                await pg.screenshot(path=s['img'],type='jpeg',quality=92)
            acc+=s['nf']
        # sim footage
        sp=await b.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1.5)
        await sp.goto('file:///home/claude/netsilcon/public/sim/rover_simulator.html'); await sp.wait_for_timeout(800)
        await sp.add_style_tag(content=".vcap{position:absolute;left:960px;transform:translateX(-50%);top:930px;max-width:1040px;background:rgba(11,18,32,.9);color:#fff;font:400 21px/1.35 'IBM Plex Sans',sans-serif;padding:9px 18px;border-radius:5px;text-align:center;z-index:99}.vprog{position:absolute;left:320px;top:996px;height:4px;background:#2DD4BF;z-index:99}")
        await sp.evaluate("opts.run=false;document.body.insertAdjacentHTML('beforeend','<div class=vcap id=vcap></div><div class=vprog id=vprog></div>')")
        acc=0; steps=0
        for k,s in enumerate(segs):
            if s['sid']=='sim':
                os.makedirs(f'simf/{k}',exist_ok=True)
                await sp.evaluate('([c,w])=>{document.getElementById("vcap").textContent=c;document.getElementById("vprog").style.width=w+"px"}',[s['text'],1280*acc/(total*FPS)])
                for f in range(s['nf']):
                    tt=(steps_t:= (f+1)/FPS)
                    want=int((sum(x['nf'] for x in segs[:k] if x['sid']=='sim')+f+1)/FPS/0.05)
                    while steps<want: await sp.evaluate('step()'); steps+=1
                    await sp.evaluate('draw();updatePanel()')
                    await sp.screenshot(path=f'simf/{k}/{f:04d}.jpg',type='jpeg',quality=92,clip={'x':320,'y':280,'width':1280,'height':720})
            acc+=s['nf']
        await b.close()
asyncio.run(render())
lst=open('seg/list.txt','w')
for k,s in enumerate(segs):
    o=f'seg/{k:03d}.mp4'; tmp=f'seg/tmp_{k:03d}.mp4'
    if s['sid']=='sim':
        run(['ffmpeg','-y','-framerate','30','-i',f'simf/{k}/%04d.jpg','-vf','scale=1920:1080']+ENC+[tmp])
    else:
        run(['ffmpeg','-y','-framerate','30','-i',s['img'],'-vf',f'format=yuv420p,loop=-1:1,trim=end_frame={s["nf"]}']+ENC+[tmp])
    os.replace(tmp,o); lst.write(f"file '{k:03d}.mp4'\n")
lst.close()
run(['ffmpeg','-y','-f','concat','-safe','0','-i','seg/list.txt','-c','copy','video_only.mp4'])
run(['ffmpeg','-y','-i','video_only.mp4','-i','narration.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart','NetSilcon_YouTube.mp4'])
# SRT
def ts(x): h=int(x//3600); m=int(x%3600//60); s_=x%60; return f"{h:02d}:{m:02d}:{int(s_):02d},{int(round((s_-int(s_))*1000))%1000:03d}"
t=0; srt=[]; chaps=[]; lastb=-1
for k,s in enumerate(segs):
    a0=t+(LEAD if k==0 else 0); srt.append(f"{k+1}\n{ts(a0)} --> {ts(a0+s['dur'])}\n{s['text']}\n")
    if s['beat']!=lastb and (not chaps or chaps[-1][1]!=s['chap']): chaps.append((t,s['chap']))
    lastb=s['beat']; t+=s['nf']/FPS
open('NetSilcon_YouTube.en.srt','w').write('\n'.join(srt))
json.dump(chaps,open('chapters.json','w'))
print('done')
