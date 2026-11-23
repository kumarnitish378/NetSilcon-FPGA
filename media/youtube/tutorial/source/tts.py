import sys, os, json, numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
from tscript import BEATS
k=Kokoro('/home/claude/kokoro/kokoro-v1.0.onnx','/home/claude/kokoro/voices-v1.0.bin')
os.makedirs('audio',exist_ok=True)
meta=[]
for bi,(sid,chap,lines) in enumerate(BEATS):
    for li,t in enumerate(lines):
        f=f'audio/{bi:02d}_{li:02d}.wav'
        if not os.path.exists(f):
            s,sr=k.create(t.replace('LiDAR','lidar').replace('RTL','R T L').replace('A5','A 5').replace('GW2AR','G W 2 AR').replace('COM seven','com seven'),voice='af_heart',speed=1.0,lang='en-us')
            sf.write(f,s,sr)
        d=sf.info(f).duration
        meta.append(dict(beat=bi,sid=sid,chap=chap,line=li,text=t,file=f,dur=d))
        print(f,round(d,2),flush=True)
json.dump(meta,open('meta.json','w'),indent=1)
