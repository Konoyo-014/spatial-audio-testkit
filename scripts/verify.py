#!/usr/bin/env python3
"""Read saved assets and check channel geometry, reconstruction, timing and hashes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import correlate, correlation_lags, fftconvolve, resample_poly

ROOT=Path(__file__).resolve().parents[1]


def verify(root):
    manifest=json.loads((root/'manifest.json').read_text())
    scenes=json.loads((root/'metadata/scenes.json').read_text())
    checks=[]
    def check(name,condition,detail):
        checks.append(dict(name=name,passed=bool(condition),detail=detail))
    def read(p): return sf.read(root/p,always_2d=True)[0]
    def angles(s,t):
        if s.get('trajectory'):
            a=np.array(s['trajectory'])
            return np.interp(t,a[:,0],a[:,1]),np.interp(t,a[:,0],a[:,2])
        return np.full(t.shape,s['azimuth_deg']),np.full(t.shape,s['elevation_deg'])
    def vectors(az,el):
        a,e=np.deg2rad(az),np.deg2rad(el)
        return np.c_[np.cos(e)*np.cos(a),np.cos(e)*np.sin(a),np.sin(e)]
    bad=[]; peaks=[]; total_bytes=0
    for r in manifest['files']:
        p=root/r['path']
        try:
            a,sr=sf.read(p,always_2d=True)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            inf=sf.info(p)
            ok=(sr==r['sample_rate_hz'] and a.shape==(r['frames'],r['channels'])
                and inf.subtype==r['subtype'] and digest==r['sha256']
                and np.all(np.isfinite(a)) and np.max(np.abs(a))<1)
            if not ok: bad.append(r['path'])
            if r['category']!='stress': peaks.append(float(np.max(np.abs(a))))
            total_bytes+=p.stat().st_size
        except Exception as e: bad.append(r['path']+': '+str(e))
    check('all_wav_integrity',not bad,dict(wav_count=len(manifest['files']),bad_files=bad,
          total_wav_bytes=total_bytes,max_nonstress_peak_dbfs=float(20*np.log10(max(peaks)))))
    H=np.load(root/'resources/hrtf_48k.npz')
    hrir=H['hrir']; positions=H['positions_deg']
    check('hrtf_archive_hash',hashlib.sha256((root/'resources/kemar_compact.zip').read_bytes()).hexdigest()==manifest['hrtf_sha256'],
          dict(grid_directions=len(positions),ir_samples=hrir.shape[1],sample_rate_hz=48000))
    max_foa=0.; max_stereo=0.; max_binaural=0.; geometry=[]; pair_bad=[]; scene_errors=[]
    max_grid=0.
    for scene in scenes:
        n=round(scene['duration_s']*48000); nt=n+4800; t=np.arange(n)/48000
        ef=np.zeros((nt,4)); es=np.zeros((nt,2)); eb=np.zeros((nt,2))
        for s in scene['sources']:
            dry=read(s['stem_path'])[:,0]
            az,el=angles(s,t); v=vectors(az,el)
            ef[:n,0]+=dry
            ef[:n,1:]+=dry[:,None]*v[:,[1,2,0]]
            es[:n,0]+=dry*np.sqrt(np.maximum(0,(1+v[:,1])/2))
            es[:n,1]+=dry*np.sqrt(np.maximum(0,(1-v[:,1])/2))
            if 'hrtf' in s:
                controls=s['hrtf']['controls']; ct=np.array([c['time_s'] for c in controls]); ii=np.array([c['index'] for c in controls])
                max_grid=max(max_grid,s['hrtf']['max_control_error_deg'])
                for j in np.unique(ii):
                    w=np.interp(t,ct,(ii==j).astype(float))
                    for ear in range(2):
                        y=fftconvolve(dry*w,hrir[j,:,ear]); eb[:len(y),ear]+=y
        err={}
        if 'foa' in scene['paths']:
            a=read(scene['paths']['foa']); err['foa']=float(np.max(np.abs(a-ef))); max_foa=max(max_foa,err['foa'])
            if len(scene['sources'])==1 and not scene['sources'][0].get('trajectory') and scene['sources'][0]['kind']!='clicks':
                s=scene['sources'][0]
                xyz=np.mean(a[:,0,None]*a[:,[3,1,2]],axis=0)
                xyz/=max(np.linalg.norm(xyz),1e-20)
                target=vectors(np.array([s['azimuth_deg']]),np.array([s['elevation_deg']]))[0]
                angle=float(np.rad2deg(np.arccos(np.clip(xyz@target,-1,1))))
                geometry.append(dict(id=scene['id'],error_deg=angle,azimuth_deg=s['azimuth_deg'],elevation_deg=s['elevation_deg']))
        if 'stereo' in scene['paths']:
            err['stereo']=float(np.max(np.abs(read(scene['paths']['stereo'])-es))); max_stereo=max(max_stereo,err['stereo'])
        if 'binaural' in scene['paths']:
            err['binaural']=float(np.max(np.abs(read(scene['paths']['binaural'])-eb))); max_binaural=max(max_binaural,err['binaural'])
        lengths={len(read(path)) for rep,path in scene['paths'].items()}
        if lengths!={nt}: pair_bad.append(scene['id'])
        scene_errors.append(dict(scene_id=scene['id'],max_sample_error=err))
    limit=1.21e-7
    check('foa_reconstructed_from_stems',max_foa<limit,dict(max_sample_error=max_foa,limit=limit))
    check('stereo_reconstructed_from_stems',max_stereo<limit,dict(max_sample_error=max_stereo,limit=limit))
    check('binaural_reconstructed_from_stems_and_hrtf',max_binaural<limit,dict(max_sample_error=max_binaural,limit=limit))
    check('paired_lengths',not pair_bad,dict(bad_scenes=pair_bad))
    max_angle=max(g['error_deg'] for g in geometry)
    check('single_source_foa_direction',max_angle<0.03,dict(scene_count=len(geometry),max_error_deg=max_angle))
    check('binaural_grid_coverage',max_grid<8,dict(max_control_grid_error_deg=max_grid,lowest_elevation_deg=float(min(positions[:,1]))))
    check('no_binaural_nadir_substitution','binaural' not in next(s for s in scenes if s['id']=='s0038')['paths'],'正下方仅提供 FOA')
    base=read('audio/foa/s0039.wav')
    n3d=read('audio/diagnostics/foa/valid_acn_n3d.wav')/np.array([1,np.sqrt(3),np.sqrt(3),np.sqrt(3)])
    fuma=read('audio/diagnostics/foa/valid_fuma.wav')[:,[0,2,3,1]]*np.array([np.sqrt(2),1,1,1])
    check('normalization_roundtrip',max(np.max(np.abs(base-n3d)),np.max(np.abs(base-fuma)))<3e-7,
          dict(n3d_error=float(np.max(np.abs(base-n3d))),fuma_error=float(np.max(np.abs(base-fuma)))))
    rot=read('audio/diagnostics/foa/yaw_plus90.wav'); pred=base.copy(); pred[:,1]=base[:,3];pred[:,3]=-base[:,1]
    check('yaw_rotation',np.max(np.abs(rot-pred))<3e-7,'主动 +90°：X→Y，Y→−X，W/Z 不变')
    mirror=read('audio/diagnostics/foa/mirror_left_right.wav')
    check('left_right_mirror',np.max(np.abs(mirror-base*np.array([1,-1,1,1])))<3e-7,'仅 Y 反号')
    swapped=read('audio/diagnostics/foa/fault_swap_x_y.wav')
    wrong_norm=read('audio/diagnostics/foa/valid_acn_n3d.wav')
    delay=read('audio/diagnostics/foa/fault_y_delay_16samples.wav')
    check('negative_controls_are_detectable',all(np.max(np.abs(a-base))>0.01 for a in [swapped,wrong_norm,delay]),
          dict(swap_error=float(np.max(np.abs(swapped-base))),unconverted_n3d_error=float(np.max(np.abs(wrong_norm-base))),
               channel_delay_error=float(np.max(np.abs(delay-base)))))
    anti=read('audio/diagnostics/stereo/anti_phase.wav')
    check('stereo_antiphase_downmix',np.max(np.abs(np.mean(anti,axis=1)))<1.21e-7,
          dict(max_mono_residual=float(np.max(np.abs(np.mean(anti,axis=1))))))
    itd=[]; ild=[]
    for r in manifest['files']:
        if r.get('rendering')=='analytic_itd':
            a=read(r['path']); cc=correlate(a[:,1],a[:,0],mode='full',method='fft')
            lag=int(correlation_lags(len(a),len(a))[np.argmax(cc)])
            itd.append(dict(path=r['path'],expected=r['itd_r_minus_l_samples'],measured=lag))
        if r.get('rendering')=='analytic_ild':
            a=read(r['path']); power=np.mean(a*a,axis=0); diff=float(10*np.log10(power[0]/power[1]))
            ild.append(dict(path=r['path'],expected=r['ild_l_minus_r_db'],measured=diff))
    check('analytic_itd_sign_and_samples',all(r['expected']==r['measured'] for r in itd),itd)
    check('analytic_ild_sign_and_db',all(abs(r['expected']-r['measured'])<.001 for r in ild),ild)
    # Known physical convention: positive azimuth is left; left-ear response arrives earlier.
    j=np.argmin(np.sum((positions-np.array([90,0]))**2,axis=1)); hp=hrir[j]
    arrival=np.argmax(np.abs(hp),axis=0); power=np.sum(hp*hp,axis=0)
    check('measured_hrtf_left_right_orientation',arrival[0]<arrival[1] and power[0]>power[1],
          dict(position_deg=positions[j].tolist(),peak_samples_L_R=arrival.tolist(),energy_L_R=power.tolist()))
    j0=np.argmin(np.sum((positions-np.array([0,0]))**2,axis=1))
    check('measured_hrtf_frontal_symmetry',np.max(np.abs(hrir[j0,:,0]-hrir[j0,:,1]))<1e-12,'KEMAR compact 的双耳为对称构造')
    silent=next(s for s in scenes if s['family']=='silence')
    check('exact_digital_silence',all(np.count_nonzero(read(p))==0 for p in silent['paths'].values()),dict(scene_id=silent['id']))
    timing=next(s for s in scenes if s['family']=='timing')
    a=read(timing['sources'][0]['stem_path'])[:,0]
    expected=np.round(np.array([.5,1,1.75,2.5])*48000).astype(int)
    actual=np.flatnonzero(a)
    check('impulse_event_samples',np.array_equal(expected,actual),dict(expected=expected.tolist(),actual=actual.tolist()))
    levels=[s for s in scenes if s['family']=='level']
    rms=[np.sqrt(np.mean(read(s['paths']['foa'])[:,0]**2)) for s in levels]
    level_err=[float(20*np.log10(v/rms[0])-s['relative_level_db']) for s,v in zip(levels,rms)]
    check('level_ratios_preserved',max(abs(x) for x in level_err)<.01,dict(error_db=level_err))
    sir=[]
    for s in scenes:
        if s['family']=='interference':
            energies=[np.mean(read(q['stem_path'])**2) for q in s['sources']]
            measured=float(10*np.log10(energies[0]/energies[1]))
            sir.append(dict(scene_id=s['id'],requested_db=s['requested_source_sir_db'],measured_db=measured))
    check('interference_source_energy_ratios',all(abs(r['requested_db']-r['measured_db'])<.1 for r in sir),sir)
    comp=[]
    for r in manifest['files']:
        if r['category']=='compatibility':
            a=read(r['source_path']); sr=r['sample_rate_hz']; gcd=np.gcd(48000,sr)
            y=resample_poly(a,sr//gcd,48000//gcd,axis=0)
            err=float(np.max(np.abs(y-read(r['path'])))); tol=3.06e-5 if r['subtype']=='PCM_16' else limit
            comp.append(dict(path=r['path'],error=err,limit=tol))
    check('sample_rate_compatibility',all(r['error']<r['limit'] for r in comp),comp)
    refs=[json.loads(l) for l in (root/'metadata/references_100ms.jsonl').read_text().splitlines()]
    refkeys=[(r['scene_id'],r['time_s']) for r in refs]
    check('reference_timeline',len(refkeys)==len(set(refkeys)) and all(sum(r['scene_id']==s['id'] for r in refs)==round(s['duration_s']*10) for s in scenes),
          dict(frame_count=len(refs),step_s=.1))
    inputs=[json.loads(l) for l in (root/'model_inputs.jsonl').read_text().splitlines()]
    check('model_input_manifest',all(set(r)=={'id','audio_path','sample_rate_hz','channels'} and (root/r['audio_path']).exists() for r in inputs),
          dict(input_files=len(inputs),contains_direction_labels=False))
    # Scientific overview from saved files, not the generator's in-memory output.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    q=[g for g in geometry if next(s for s in scenes if s['id']==g['id'])['family']=='static_azimuth']
    az=np.array([g['azimuth_deg'] for g in q]); recovered=[]
    for g in q:
        a=read(f'audio/foa/{g["id"]}.wav'); v=np.mean(a[:,0,None]*a[:,[3,1,2]],axis=0)
        recovered.append(np.rad2deg(np.arctan2(v[1],v[0])))
    recovered=np.array(recovered); recovered[0]=-180 if recovered[0]>179 else recovered[0]
    ax[0,0].plot(az,az,color='#9b9b9b',lw=1,label='Reference');ax[0,0].scatter(az,recovered,s=15,c='#245b88',label='FOA intensity')
    ax[0,0].set(xlabel='Reference azimuth (deg)',ylabel='Recovered azimuth (deg)',title='Static FOA direction');ax[0,0].legend(frameon=False)
    ax[0,1].plot(np.arange(len(hp))/48,hp[:,0],label='Left ear',color='#245b88')
    ax[0,1].plot(np.arange(len(hp))/48,hp[:,1],label='Right ear',color='#b36042')
    ax[0,1].set(xlabel='Time (ms)',ylabel='Amplitude',title='Measured HRIR: source at +90 deg');ax[0,1].legend(frameon=False)
    moving=read('audio/foa/s0048.wav'); times=[]; est=[]
    for k in range(12000,len(moving)-24000,2400):
        z=moving[k:k+2400]; v=np.mean(z[:,0,None]*z[:,[3,1,2]],axis=0)
        if np.linalg.norm(v)>1e-10: times.append((k+1200)/48000);est.append(np.arctan2(v[1],v[0]))
    ax[1,0].plot(times,np.rad2deg(np.unwrap(est)),color='#245b88',label='FOA intensity')
    ax[1,0].plot([.25,8.25],[0,360],color='#9b9b9b',ls='--',label='Reference')
    ax[1,0].set(xlabel='Time (s)',ylabel='Unwrapped azimuth (deg)',title='Counterclockwise source motion');ax[1,0].legend(frameon=False)
    ax[1,1].plot([0,-20,-40,-60],[20*np.log10(r/rms[0]) for r in rms],'o-',color='#245b88')
    ax[1,1].set(xlabel='Requested relative level (dB)',ylabel='Measured relative level (dB)',title='Global gain preserves level differences')
    for a in ax.flat:a.spines[['top','right']].set_visible(False);a.grid(alpha=.15)
    dest=root/'validation';dest.mkdir(exist_ok=True)
    fig.savefig(dest/'overview.png',dpi=160);plt.close(fig)
    report=dict(status='passed' if all(c['passed'] for c in checks) else 'failed',checks=checks,
                scene_count=len(scenes),wav_count=len(manifest['files']),wav_bytes=total_bytes,
                geometry=geometry,scene_reconstruction=scene_errors,
                scope='File integrity and numerical signal properties; no learned model or human listening result.')
    (dest/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 数值检查结果\n',f'状态：{"已验证，通过" if report["status"]=="passed" else "检查失败"}。',
        f'本次读取 {len(scenes)} 个场景、{len(manifest["files"])} 个 WAV 文件。音频文件共 {total_bytes/1e6:.1f} MB。',
        '检查对象是文件、声道关系、生成标签和渲染计算；这里没有把任何模型性能或主观听感标记为通过。\n',
        '|检查|结果|','|---|---|']
    for c in checks:lines.append(f'|{c["name"]}|{"通过" if c["passed"] else "失败"}|')
    lines.extend(['\n完整数值见 [report.json](report.json)。','\n![从保存文件计算的结果](overview.png)'])
    (dest/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(status=report['status'],checks=len(checks),failed=[c for c in checks if not c['passed']],
                         scenes=len(scenes),wav_files=len(manifest['files']),wav_mb=total_bytes/1e6),ensure_ascii=False,indent=2))
    return report['status']=='passed'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    sys.exit(0 if verify(p.parse_args().root) else 1)
