#!/usr/bin/env python3
"""Render an explicitly supplied mono WAV into matching FOA, stereo and measured-HRTF binaural WAVs."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from generate import HRTF, ROOT, SR, direction, sh1, unit, write_audio


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--azimuth',type=float,default=30)
    p.add_argument('--elevation',type=float,default=0)
    p.add_argument('--trajectory',type=Path,help='JSON array [[time_s,azimuth_deg,elevation_deg], ...]; azimuth unwrapped')
    a=p.parse_args()
    if a.output.exists():p.error('Choose a new output directory')
    x,sr=sf.read(a.input,always_2d=True)
    if x.shape[1]!=1:p.error('Input must be mono; choose an explicit downmix before rendering')
    x=x[:,0]
    if not len(x) or not np.all(np.isfinite(x)):p.error('Input is empty or contains non-finite values')
    if sr!=SR:
        g=math.gcd(sr,SR);x=resample_poly(x,SR//g,sr//g)
    n=len(x);t=np.arange(n)/SR
    tr=json.loads(a.trajectory.read_text()) if a.trajectory else None
    if tr is not None:
        tr_arr=np.array(tr,dtype=float)
        if tr_arr.ndim!=2 or tr_arr.shape[1]!=3 or len(tr_arr)<2 or not np.all(np.isfinite(tr_arr)):
            p.error('Trajectory must contain at least two finite [time, azimuth, elevation] rows')
        if np.any(np.diff(tr_arr[:,0])<=0) or tr_arr[0,0]<0 or tr_arr[-1,0]>n/SR:
            p.error('Trajectory times must increase within the input duration')
    s=dict(azimuth_deg=a.azimuth,elevation_deg=a.elevation,trajectory=tr)
    az,el=direction(s,t)
    if not np.all(np.isfinite(az)) or not np.all(np.isfinite(el)) or np.any(el < -40) or np.any(el>90):
        p.error('Measured-HRTF rendering requires finite elevation in [-40,90] degrees')
    h=HRTF(ROOT/'resources/kemar_compact.zip')
    binaural,meta=h.render(x,s)
    nt=n+4800
    outputs={
        'foa':np.pad(x[:,None]*sh1(az,el),((0,4800),(0,0))),
        'stereo':np.pad(x[:,None]*np.sqrt(np.maximum(0,np.c_[(1+unit(az,el)[:,1])/2,(1-unit(az,el)[:,1])/2])),((0,4800),(0,0))),
        'binaural':np.pad(binaural,((0,nt-len(binaural)),(0,0)))
    }
    # One gain for this input and all three representations, never per channel or format.
    peak=max(np.max(np.abs(v)) for v in outputs.values())
    gain=min(1.,10**(-6/20)/max(peak,1e-12))
    a.output.mkdir(parents=True)
    records=[]
    write_audio(a.output,'source_48k.wav',x*gain,records,'stem')
    for rep,y in outputs.items():write_audio(a.output,f'{rep}.wav',y*gain,records,rep)
    result=dict(input_name=a.input.name,input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
        original_sample_rate_hz=sr,sample_rate_hz=SR,shared_gain=gain,source=s,hrtf=meta,
        foa_channel_order=['W','Y','Z','X'],normalization='SN3D',files=records)
    (a.output/'metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(f'Rendered {n/SR:.3f} seconds; common gain {gain:.8f}; output: {a.output}')


if __name__=='__main__':main()
