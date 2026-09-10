#!/usr/bin/env python3
"""Permutation-invariant DOA + source detection evaluation on the supplied 100 ms grid."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT=Path(__file__).resolve().parents[1]


def vectors(items):
    if not items:return np.zeros((0,3))
    a=np.deg2rad([s['azimuth_deg'] for s in items]);e=np.deg2rad([s['elevation_deg'] for s in items])
    return np.c_[np.cos(e)*np.cos(a),np.cos(e)*np.sin(a),np.sin(e)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('predictions',type=Path)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--output',type=Path)
    p.add_argument('--scene-ids',help='Comma-separated explicit evaluation subset; otherwise all eligible scenes')
    p.add_argument('--threshold-deg',type=float,default=20.)
    args=p.parse_args()
    if not 0<args.threshold_deg<=180:p.error('threshold must be in (0, 180]')
    refs=[json.loads(l) for l in (args.root/'metadata/references_100ms.jsonl').read_text().splitlines()]
    subset=set(args.scene_ids.split(',')) if args.scene_ids else None
    known={r['scene_id'] for r in refs}
    if subset and not subset<=known: p.error('Unknown scene ids: '+str(subset-known))
    refs=[r for r in refs if r['evaluation'] in ['doa_and_activity','silence_false_positive'] and (not subset or r['scene_id'] in subset)]
    if not refs:p.error('No eligible references')
    predictions={}
    keys={(r['scene_id'],round(r['time_s'],6)) for r in refs}
    for line in args.predictions.read_text().splitlines():
        r=json.loads(line)
        key=(r['scene_id'],round(float(r['time_s']),6))
        if subset and key[0] not in subset:continue
        if key not in keys:p.error('Prediction outside requested reference grid: '+str(key))
        if key in predictions:p.error('Duplicate prediction frame: '+str(key))
        for s in r['sources']:
            if not np.isfinite([s['azimuth_deg'],s['elevation_deg']]).all() or not -90<=s['elevation_deg']<=90:
                p.error('Invalid direction in '+str(key))
        predictions[key]=r['sources']
    missing=keys-predictions.keys()
    if missing:p.error(f'{len(missing)} frames absent. Emit sources: [] for a no-source prediction. Use --scene-ids for a subset.')
    all_errors=[];tp=fp=fn=0;frames=[]
    for r in refs:
        pred=predictions[(r['scene_id'],round(r['time_s'],6))];truth=r['sources']
        costs=np.rad2deg(np.arccos(np.clip(vectors(truth)@vectors(pred).T,-1,1)))
        errors=[];hits=0
        if costs.size:
            # Large penalty maximizes number inside threshold before minimizing angular error.
            penalty=(costs>args.threshold_deg)*(181*(min(costs.shape)+1))
            rows,cols=linear_sum_assignment(costs+penalty)
            errors=costs[rows,cols].tolist();hits=sum(e<=args.threshold_deg for e in errors)
        tp+=hits;fp+=len(pred)-hits;fn+=len(truth)-hits;all_errors.extend(errors)
        frames.append(dict(scene_id=r['scene_id'],time_s=r['time_s'],reference_count=len(truth),
                           predicted_count=len(pred),matched_errors_deg=errors,true_positive=hits))
    precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
    result=dict(status='evaluated',reference_frames=len(refs),scene_count=len({r['scene_id'] for r in refs}),
        threshold_deg=args.threshold_deg,true_positive=tp,false_positive=fp,false_negative=fn,
        precision=precision,recall=recall,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
        matched_mean_error_deg=float(np.mean(all_errors)) if all_errors else None,
        matched_median_error_deg=float(np.median(all_errors)) if all_errors else None,
        matched_p95_error_deg=float(np.percentile(all_errors,95)) if all_errors else None,
        note='Assignment ignores identity. Angular error excludes unmatched sources; read it together with FP/FN/F1. '
             'Not a SELD score. Align algorithm latency before writing predictions. Nominal direction labels; '
             'binaural uses a finite, crossfaded HRTF grid. Reflections score direct sources only.',frames=frames)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
