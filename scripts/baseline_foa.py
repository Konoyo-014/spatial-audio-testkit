#!/usr/bin/env python3
"""A single-source FOA direction estimate from W-X/Y/Z cross-products."""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--scene-ids',default='s0013,s0039,s0048,s0080')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rms-threshold',type=float,default=1e-5)
    a=p.parse_args();rows=[]
    if a.rms_threshold<0:p.error('RMS threshold must be nonnegative')
    specs={s['id']:s for s in json.loads((a.root/'metadata/scenes.json').read_text())}
    for sid in a.scene_ids.split(','):
        if sid not in specs:p.error('Unknown scene '+sid)
        s=specs[sid];data,sr=sf.read(a.root/s['paths']['foa'],always_2d=True)
        for t in np.arange(0,s['duration_s'],.1):
            center=round(t*sr);frame=data[max(0,center-round(.01*sr)):center+round(.01*sr)]
            labels=[]
            if np.sqrt(np.mean(frame[:,0]**2))>a.rms_threshold:
                v=np.mean(frame[:,0,None]*frame[:,[3,1,2]],axis=0)
                if np.linalg.norm(v)>1e-15:
                    labels=[dict(azimuth_deg=float(np.rad2deg(np.arctan2(v[1],v[0]))),
                        elevation_deg=float(np.rad2deg(np.arctan2(v[2],np.hypot(v[0],v[1])))))]
            rows.append(dict(scene_id=sid,time_s=round(float(t),6),sources=labels))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    print(f'Wrote {len(rows)} frames to {a.output}')


if __name__=='__main__':main()
