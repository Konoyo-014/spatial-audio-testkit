#!/usr/bin/env python3
"""Deterministic spatial-audio regression fixtures. See README.md for conventions."""
import argparse
import hashlib
import io
import json
import math
import platform
import re
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import scipy
import soundfile as sf
from scipy.signal import butter, chirp, fftconvolve, resample_poly, sosfilt

ROOT = Path(__file__).resolve().parents[1]
SR = 48000
SEED = 20260910
MASTER = 0.35
TAIL = 0.1
CONTROL_HZ = 50


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def db(x):
    return None if x <= 0 else float(20 * np.log10(x))


def unit(az, el):
    a, e = np.deg2rad(az), np.deg2rad(el)
    return np.stack([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)], axis=-1)


def sh1(az, el):
    u = unit(az, el)
    return np.concatenate([np.ones(u.shape[:-1] + (1,)), u[..., [1, 2, 0]]], axis=-1)


def source(kind='pink', az=0, el=0, start=0.25, end=2.75, seed=11,
           gain_db=0, trajectory=None, role='source', **params):
    return dict(kind=kind, azimuth_deg=az, elevation_deg=el, start_s=start,
                end_s=end, seed=seed, gain_db=gain_db, trajectory=trajectory,
                role=role, **params)


def direction(s, t):
    tr = s.get('trajectory')
    if tr:
        az = np.interp(t, [r[0] for r in tr], [r[1] for r in tr])
        el = np.interp(t, [r[0] for r in tr], [r[2] for r in tr])
    else:
        az = np.full_like(t, s['azimuth_deg'], dtype=float)
        el = np.full_like(t, s['elevation_deg'], dtype=float)
    return az, el


def wave(s, duration):
    n = round(duration * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(SEED + s['seed'])
    kind = s['kind']
    if kind in ('pink', 'white', 'bandnoise'):
        x = rng.standard_normal(n)
        if kind == 'pink':
            f = np.fft.rfftfreq(n, 1 / SR)
            weight = 1 / np.sqrt(np.maximum(f, 80))
            weight[(f < 80) | (f > 16000)] = 0
            x = np.fft.irfft(np.fft.rfft(x) * weight, n)
        else:
            lo, hi = s.get('band_hz', [100, 16000])
            x = sosfilt(butter(4, [lo, hi], fs=SR, btype='bandpass', output='sos'), x)
    elif kind == 'tone':
        x = np.sin(2 * np.pi * s.get('frequency_hz', 1000) * t)
    elif kind == 'harmonic':
        f = s.get('frequency_hz', 220)
        x = sum(np.sin(2 * np.pi * f * k * t + k * 0.31) / k for k in range(1, 13))
        x *= 0.3 + 0.7 * (0.5 + 0.5 * np.sin(2 * np.pi * 3.1 * t))
    elif kind == 'sweep':
        # Phase time starts at the nominal onset, so the documented endpoints are exact.
        u = t - s['start_s']
        x = chirp(u, f0=s.get('f0_hz', 40), f1=s.get('f1_hz', 18000),
                  t1=s['end_s'] - s['start_s'], method='logarithmic', phi=-90)
    elif kind == 'clicks':
        x = np.zeros(n)
        for event in s.get('events_s', [0.5, 1.0, 1.75, 2.5]):
            x[round(event * SR)] = 0.4
        return x * MASTER * 10 ** (s['gain_db'] / 20)
    else:
        raise ValueError(kind)
    active = (t >= s['start_s']) & (t < s['end_s'])
    rms = np.sqrt(np.mean(x[active] ** 2))
    x *= 0.1 / max(rms, 1e-12)
    fade = s.get('fade_s', 0.02)
    env = np.minimum(np.clip((t-s['start_s'])/fade, 0, 1),
                     np.clip((s['end_s']-t)/fade, 0, 1))
    env = np.sin(env * np.pi / 2) ** 2
    if 'gates_s' in s:
        gate = np.zeros(n)
        for a, b in s['gates_s']:
            g = np.minimum(np.clip((t-a)/fade, 0, 1), np.clip((b-t)/fade, 0, 1))
            gate = np.maximum(gate, np.sin(g*np.pi/2)**2)
        env *= gate
    return x * env * MASTER * 10 ** (s['gain_db'] / 20)


class HRTF:
    def __init__(self, archive):
        positions, filters, names = [], [], []
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise ValueError('HRTF archive CRC failed')
            for name in sorted(z.namelist()):
                m = re.search(r'H(-?\d+)e(\d+)a.wav$', name)
                if not m:
                    continue
                el, right_az = map(int, m.groups())
                h, rate = sf.read(io.BytesIO(z.read(name)), always_2d=True)
                assert rate == 44100 and h.shape == (128, 2)
                # IR resampling needs the sample-interval ratio to preserve convolution gain.
                h = resample_poly(h, 160, 147, axis=0) * (147 / 160)
                positions.append([-right_az, el])
                filters.append(h)
                names.append(name)
                if right_az not in (0, 180):
                    positions.append([right_az, el])
                    filters.append(h[:, ::-1])
                    names.append(name + ':ear_swap')
        self.positions = np.array(positions, float)
        self.filters = np.array(filters)
        self.names = names
        self.vectors = unit(self.positions[:, 0], self.positions[:, 1])

    def select(self, az, el):
        u = unit(az, el)
        dots = u @ self.vectors.T
        idx = np.argmax(dots, axis=-1)
        err = np.rad2deg(np.arccos(np.clip(np.max(dots, axis=-1), -1, 1)))
        return idx, err

    def render(self, x, s):
        n = len(x)
        t = np.arange(n) / SR
        ct = np.arange(0, (n-1)/SR + 1/CONTROL_HZ, 1/CONTROL_HZ)
        az, el = direction(s, ct)
        idx, err = self.select(az, el)
        y = np.zeros((n + len(self.filters[0]) - 1, 2))
        for j in np.unique(idx):
            # Weight before convolution: controls follow input-sample time.
            w = np.interp(t, ct, (idx == j).astype(float))
            for ear in range(2):
                y[:, ear] += fftconvolve(x*w, self.filters[j, :, ear])
        meta = dict(method='nearest_grid_at_50Hz_with_linear_kernel_crossfade',
                    control_hz=CONTROL_HZ, max_control_error_deg=float(np.max(err)),
                    controls=[dict(time_s=round(float(v), 6), index=int(j),
                                   azimuth_deg=float(self.positions[j, 0]),
                                   elevation_deg=float(self.positions[j, 1]),
                                   error_deg=float(e)) for v, j, e in zip(ct, idx, err)])
        return y, meta

    def decoder(self):
        # Area weights: each elevation ring represents its spherical latitude band.
        elevs = np.unique(self.positions[:, 1])
        edges = np.r_[max(-90, elevs[0]-(elevs[1]-elevs[0])/2),
                      (elevs[:-1]+elevs[1:])/2, 90]
        w = np.zeros(len(self.positions))
        for k, el in enumerate(elevs):
            mask = self.positions[:, 1] == el
            w[mask] = (np.sin(np.deg2rad(edges[k+1]))-np.sin(np.deg2rad(edges[k]))) / sum(mask)
        A = sh1(self.positions[:, 0], self.positions[:, 1])
        # Solve A @ D = HRIR, one shared linear decoder for all scenes.
        D = np.linalg.solve(A.T @ (w[:, None]*A),
                            A.T @ (w[:, None]*self.filters.reshape(len(A), -1)))
        return D.reshape(4, self.filters.shape[1], 2)


def specifications():
    scenes = []
    def add(name, family, sources, duration=3., representations=None, **extra):
        scenes.append(dict(id=f's{len(scenes)+1:04d}', name=name, family=family,
                           duration_s=duration, sources=sources,
                           representations=representations or ['foa', 'stereo', 'binaural'], **extra))
    for az in range(-180, 180, 15):
        add(f'水平静止声源 {az:+d}°', 'static_azimuth', [source(az=az)])
    for el in [-30, 30, 60]:
        for az in [0, 90, 180, -90]:
            add(f'方位 {az:+d}°，仰角 {el:+d}°', 'static_elevation', [source(az=az, el=el)])
    add('正上方', 'static_elevation', [source(el=90)])
    add('正下方，FOA 专用', 'static_elevation', [source(el=-90)], representations=['foa'])
    add('格式对照的共同原信号，方位 +30°、仰角 +20°', 'format_reference', [source(az=30, el=20)])
    for f in [125, 500, 1000, 4000, 8000]:
        add(f'{f} Hz 窄带定位', 'narrowband', [source('tone', az=45, frequency_hz=f)])
    add('40 Hz–18 kHz 对数扫频', 'spectral', [source('sweep', az=30, end=5.75)], 6)
    add('宽带随机噪声', 'spectral', [source('white', az=-30)])
    add('谐波与幅度调制声源', 'spectral', [source('harmonic', az=60)])
    for name, tr in [
        ('水平逆时针一周', [[0.25,0,0],[8.25,360,0]]),
        ('水平顺时针一周', [[0.25,0,0],[8.25,-360,0]]),
        ('右侧经过前方到左侧', [[0.25,-90,0],[8.25,90,0]]),
        ('前方从低处升到高处', [[0.25,0,-30],[8.25,0,80]]),
        ('跨越后方 ±180°', [[0.25,150,0],[8.25,210,0]]),
        ('头向左转时，固定世界声源向右移动', [[0.25,0,0],[8.25,-90,0]])]:
        add(name, 'motion', [source('pink', end=8.25, trajectory=tr)], 8.5)
    add('两个独立声源：左右', 'multisource', [source(az=70, seed=21, end=5.75), source(az=-70, seed=22, end=5.75)], 6)
    add('两个声源相向运动并交叉', 'multisource', [
        source('harmonic', seed=31, end=5.75, frequency_hz=220, trajectory=[[.25,-80,0],[5.75,80,0]]),
        source('harmonic', seed=32, end=5.75, frequency_hz=370, trajectory=[[.25,80,0],[5.75,-80,0]])], 6)
    add('三个方向、三个频带', 'multisource', [source('bandnoise', az=a, el=e, seed=k+40,
        band_hz=b, end=5.75) for k,(a,e,b) in enumerate([(-70,0,[200,700]),(0,30,[1000,2500]),(80,0,[4000,8000])])], 6)
    for sep in [10,30,60]:
        add(f'双源角间隔 {sep}°', 'separation', [source(az=-sep/2, seed=51, end=5.75),source(az=sep/2, seed=52, end=5.75)], 6)
    for sir in [-10,0,10]:
        add(f'目标与干扰的源信号能量比 {sir:+d} dB', 'interference', [source('harmonic', az=35, seed=61,end=5.75),
            source(az=-65,seed=62,gain_db=-sir,end=5.75)], 6, target_source_id='a01', requested_source_sir_db=sir)
    add('两个声源交替出现', 'activity', [source(az=-60,end=5.75,gates_s=[[.25,1.5],[3,4.3]],seed=71),
        source(az=60,end=5.75,gates_s=[[1.7,2.8],[4.5,5.75]],seed=72)],6)
    add('同向、同波形双源相加', 'coherence', [source(az=30,seed=81),source(az=30,seed=81)],
        evaluation='exclude_coherent_source_count')
    add('相反方向、同相波形', 'coherence', [source(az=90,seed=81),source(az=-90,seed=81)],
        evaluation='exclude_coherent_source_count')
    add('相反方向、反相波形', 'coherence', [source(az=90,seed=81),source(az=-90,seed=81,polarity=-1)],
        evaluation='exclude_coherent_source_count')
    dirs = [(-135,30),(-45,30),(45,30),(135,30),(-135,-30),(-45,-30),(45,-30),(135,-30),(0,0),(90,0),(180,0),(-90,0)]
    add('12 个方向的独立噪声，近似弥散场', 'diffuse', [source(az=a,el=e,seed=100+k,gain_db=-10*np.log10(12),end=3.75)
        for k,(a,e) in enumerate(dirs)],4,evaluation='exclude_diffuse',note='有限 12 方向，不是连续各向同性声场')
    for dr in [0,6,12]:
        direct=source('harmonic',az=20,seed=121,end=4.75)
        ss=[direct]
        rg=10**(-dr/20)/np.sqrt(3)
        for k,(a,e,d) in enumerate([(-65,0,.017),(100,30,.031),(175,-30,.053)]):
            ss.append(source('harmonic',az=a,el=e,seed=121,end=4.75,role='reflection',
                             copy_from=0,delay_s=d,linear_gain=rg))
        add(f'直达声与离散反射，分量能量比 {dr} dB','reflections',ss,5,
            direct_to_sum_reflection_component_energy_db=dr,
            note='手工指定到达方向、延迟和增益；不对应某个房间，也不含晚期混响')
    for level in [0,-20,-40,-60]:
        add(f'共同波形，相对电平 {level} dB','level',[source(az=45,gain_db=level,seed=131)],relative_level_db=level)
    for distance in [1,2,4]:
        add(f'幅度随 1/r 变化：r={distance}','amplitude_distance_proxy',
            [source(az=30,gain_db=-20*np.log10(distance),seed=141)],
            evaluation='exclude_physical_distance',relative_distance_parameter=distance,
            note='只有 1/r 幅度变化；没有距离相关 HRTF、传播延迟、近场或空气吸收')
    add('精确事件时刻的单采样脉冲','timing',[source('clicks',az=90)])
    add('延迟出现并停止的声源','activity',[source('harmonic',az=-45,start=1.0,end=2.0)])
    add('数字静音','silence',[],evaluation='silence_false_positive')
    return scenes


def write_audio(out, rel, x, records, category, scene_id=None, sample_rate=SR,
                subtype='PCM_24', **extra):
    x = np.asarray(x)
    if x.ndim == 1:
        x = x[:, None]
    if not np.all(np.isfinite(x)) or np.max(np.abs(x), initial=0) >= 1:
        raise ValueError(f'Invalid samples or clipping before write: {rel}')
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, x, sample_rate, subtype=subtype)
    # Measure the saved PCM, including quantization.
    y, rate = sf.read(path, always_2d=True)
    rec = dict(path=rel, category=category, scene_id=scene_id, sample_rate_hz=rate,
               channels=y.shape[1], frames=len(y), duration_s=len(y)/rate, subtype=subtype,
               peak_dbfs=db(np.max(np.abs(y))), rms_dbfs_per_channel=[db(v) for v in np.sqrt(np.mean(y*y,axis=0))],
               sha256=sha(path), **extra)
    records.append(rec)
    return y


def diagnostics(out, records, reference, hrtf):
    n=3*SR
    t=np.arange(n)/SR
    x=np.sin(2*np.pi*1000*t)*.12
    env=np.sin(np.minimum(np.clip((t-.25)/.02,0,1),np.clip((2.75-t)/.02,0,1))*np.pi/2)**2
    x*=env
    base=reference
    variants = {
        'valid_acn_n3d': (base*np.array([1,np.sqrt(3),np.sqrt(3),np.sqrt(3)]),'合法 ACN/N3D；转换回 SN3D 后应与共同原信号一致'),
        'valid_fuma': (base[:,[0,3,1,2]]*np.array([1/np.sqrt(2),1,1,1]),'合法 FuMa：WXYZ，W 缩小 sqrt(2)'),
        'fault_swap_x_y': (base[:,[0,3,2,1]],'故障：X、Y 交换'),
        'mirror_left_right': (base*np.array([1,-1,1,1]),'Y 反号，左右镜像；几何标签随之改变'),
        'fault_z_polarity': (base*np.array([1,1,-1,1]),'Z 反号，上下翻转'),
        'fault_w_gain_minus3db': (base*np.array([1/np.sqrt(2),1,1,1]),'故障：仅 W 缩小 sqrt(2)，仍按 SN3D 读取会出错'),
        'fault_drop_y': (base*np.array([1,0,1,1]),'故障：Y 声道丢失'),
        'fault_whole_polarity': (-base,'全声道反相；相对方向应保持'),
    }
    # Active rotation +90 degrees about +Z: X'=-Y, Y'=X.
    rot=base.copy(); rot[:,1]=base[:,3]; rot[:,3]=-base[:,1]
    variants['yaw_plus90']=(rot,'声场主动向左旋转 90°；仰角保持')
    delayed=base.copy(); delayed[:,1]=0; delayed[16:,1]=base[:-16,1]
    variants['fault_y_delay_16samples']=(delayed,'故障：仅 Y 延迟 16 个采样点')
    for name,(a,desc) in variants.items():
        write_audio(out,f'audio/diagnostics/foa/{name}.wav',a,records,'diagnostic',
                    description=desc,reference_path='audio/foa/s0039.wav',transformation=name)
    # Basis vectors are channel-routing probes, not single plane-wave scenes.
    a=np.zeros((4*SR,4))
    for k in range(4):
        begin=k*SR+SR//4
        a[begin:begin+SR//2,k]=.12*np.sin(2*np.pi*(400+200*k)*np.arange(SR//2)/SR)*np.hanning(SR//2)
    write_audio(out,'audio/diagnostics/foa/channel_order_W_Y_Z_X.wav',a,records,'diagnostic',
                description='每秒只激活一个声道，依次 W/Y/Z/X；非点声源')
    for name,a,desc in [
        ('left_only',np.c_[x,np.zeros(n)],'仅左声道'),
        ('right_only',np.c_[np.zeros(n),x],'仅右声道'),
        ('in_phase',np.c_[x,x],'L=R；单声道平均后保持'),
        ('anti_phase',np.c_[x,-x],'L=-R；单声道平均后抵消')]:
        write_audio(out,f'audio/diagnostics/stereo/{name}.wav',a,records,'diagnostic',description=desc)
    rng=np.random.default_rng(SEED+900)
    a=sosfilt(butter(4,[150,8000],fs=SR,btype='bandpass',output='sos'),rng.standard_normal((n,2)),axis=0)
    a*=.05/np.sqrt(np.mean(a*a,axis=0)); a*=env[:,None]
    write_audio(out,'audio/diagnostics/stereo/uncorrelated.wav',a,records,'diagnostic',description='两路独立带限噪声')
    mono=a[:,0]
    for lag in [-24,-12,12,24]:
        # delta = arrival R - arrival L. Positive delta means left leads.
        y=np.zeros((n,2)); dl=40+max(0,-lag); dr=40+max(0,lag)
        y[dl:,0]=mono[:-dl]; y[dr:,1]=mono[:-dr]
        write_audio(out,f'audio/diagnostics/binaural/analytic_itd_{lag:+d}samples.wav',y,records,'diagnostic',
                    description='仅耳间时差的解析对照，不含耳廓滤波',itd_r_minus_l_samples=lag,rendering='analytic_itd')
    for ild in [-12,-6,6,12]:
        gains=10**(np.array([min(ild,0),min(-ild,0)])/20)
        y=mono[:,None]*gains
        write_audio(out,f'audio/diagnostics/binaural/analytic_ild_{ild:+d}db.wav',y,records,'diagnostic',
                    description='仅耳间电平差的解析对照，正值表示左耳较强',ild_l_minus_r_db=ild,rendering='analytic_ild')
    write_audio(out,'audio/diagnostics/stress/near_full_scale_minus1db.wav',
                np.c_[x,x]/.12*10**(-1/20),records,'stress',description='接近满幅的 -1 dBFS 正弦；不放入试听文件')
    # Exact numeric zero and a DC offset are useful input-sanitization tests.
    write_audio(out,'audio/diagnostics/stress/dc_offset.wav',np.full((SR,2),.01),records,'stress',
                description='恒定 +0.01 DC，算法输入检查专用')


def generate(out):
    out=out.resolve()
    if (out/'manifest.json').exists():
        raise SystemExit(f'{out} already contains a generated pack. Choose a new --output directory.')
    if out != ROOT and out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty. Choose a new --output directory.')
    archive=ROOT/'resources/kemar_compact.zip'
    hrtf=HRTF(archive)
    out.mkdir(parents=True,exist_ok=True)
    if out != ROOT:
        shutil.copytree(ROOT/'resources',out/'resources',dirs_exist_ok=True)
        shutil.copytree(ROOT/'scripts',out/'scripts',dirs_exist_ok=True)
        for name in ['README.md','requirements.txt','LICENSE.txt']:
            if (ROOT/name).exists(): shutil.copy2(ROOT/name,out/name)
    records=[]
    scene_specs=specifications()
    dump(out/'metadata/scene_specs.json',scene_specs)
    dump(out/'metadata/hrtf_grid.json',dict(sample_rate_hz=SR,positions_deg=hrtf.positions.tolist(),
        original_files=hrtf.names,ir_samples=hrtf.filters.shape[1],archive_sha256=sha(archive),
        original_sample_rate_hz=44100,original_ir_samples=128,ir_resample_scale=147/160,
        coordinates='azimuth positive left; elevation positive up; x front, y left, z up'))
    np.savez_compressed(out/'resources/hrtf_48k.npz',hrir=hrtf.filters,positions_deg=hrtf.positions,decoder=hrtf.decoder())
    refs=[]; scenes=[]; foa_ref=None; audition={'stereo':[],'binaural':[]}; audition_marks=[]
    quick_ids={'s0013','s0019','s0007','s0001','s0037','s0048','s0049','s0054'}
    for spec in scene_specs:
        sid=spec['id']; duration=spec['duration_s']; n=round(duration*SR); nt=n+round(TAIL*SR)
        audio={r:np.zeros((nt,4 if r=='foa' else 2)) for r in spec['representations']}
        t=np.arange(n)/SR; stems=[]; source_meta=[]
        for k,s in enumerate(spec['sources']):
            s=dict(s); source_id=f'a{k+1:02d}'
            if 'copy_from' in s:
                delay=round(s['delay_s']*SR); x=np.zeros(n)
                x[delay:]=stems[s['copy_from']][:-delay]*s['linear_gain']
            else:
                x=wave(s,duration)*s.get('polarity',1)
            rel=f'audio/stems/{sid}_{source_id}.wav'
            x=write_audio(out,rel,x,records,'stem',sid,source_id=source_id)[:,0]
            stems.append(x)
            az,el=direction(s,t)
            if 'foa' in audio: audio['foa'][:n]+=x[:,None]*sh1(az,el)
            if 'stereo' in audio:
                lateral=unit(az,el)[:,1]
                gains=np.sqrt(np.maximum(0,np.c_[(1+lateral)/2,(1-lateral)/2]))
                audio['stereo'][:n]+=x[:,None]*gains
            sm=dict(s,source_id=source_id,stem_path=rel)
            if 'binaural' in audio:
                binaural,hm=hrtf.render(x,s)
                audio['binaural'][:len(binaural)]+=binaural
                sm['hrtf']=hm
            source_meta.append(sm)
        scene=dict(spec,sources=source_meta,tail_s=TAIL,paths={})
        for rep,a in audio.items():
            rel=f'audio/{rep}/{sid}.wav'
            write_audio(out,rel,a,records,rep,sid,
                        channel_order=['W','Y','Z','X'] if rep=='foa' else ['L','R'],
                        normalization='SN3D' if rep=='foa' else None)
            scene['paths'][rep]=rel
        if spec['family']=='format_reference': foa_ref=audio['foa']
        # FOA-to-binaural is deliberately distinct from direct HRIR rendering.
        if sid in {'s0007','s0013','s0019','s0039','s0048','s0054'}:
            D=hrtf.decoder(); decoded=np.zeros((nt+len(D[0])-1,2))
            for ch in range(4):
                for ear in range(2): decoded[:,ear]+=fftconvolve(audio['foa'][:,ch],D[ch,:,ear])
            rel=f'audio/foa_decoded_binaural/{sid}.wav'
            write_audio(out,rel,decoded[:nt],records,'foa_decoded_binaural',sid,
                        description='一阶球谐最小二乘 HRIR 拟合；不应与直接双耳渲染逐采样相等')
            scene['paths']['foa_decoded_binaural']=rel
        if sid in quick_ids and 'stereo' in audio and 'binaural' in audio:
            elapsed=sum(len(a) for a in audition['stereo'])/SR
            audition_marks.append(dict(start_s=elapsed,end_s=elapsed+nt/SR,scene_id=sid,name=spec['name']))
            for rep in audition:
                audition[rep].extend([audio[rep],np.zeros((SR//2,2))])
        # Frame labels concern nominal source samples, not post-HRIR tails.
        for ti in np.arange(0,duration,0.1):
            labels=[]
            for sm in source_meta:
                if sm['role']!='source': continue
                active=sm['start_s']<=ti<sm['end_s']
                if 'gates_s' in sm: active &= any(a<=ti<b for a,b in sm['gates_s'])
                if sm['kind']=='clicks': active=any(ti<=e<ti+.1 for e in sm.get('events_s',[.5,1,1.75,2.5]))
                if active:
                    az,el=direction(sm,np.array([ti])); labels.append(dict(source_id=sm['source_id'],
                        azimuth_deg=float((az[0]+180)%360-180),elevation_deg=float(el[0])))
            refs.append(dict(scene_id=sid,time_s=round(float(ti),6),sources=labels,
                             evaluation=spec.get('evaluation','doa_and_activity')))
        scenes.append(scene)
        print(f'{sid} {spec["family"]} complete',flush=True)
    diagnostics(out,records,foa_ref,hrtf)
    # Resample saved complete multichannel arrays together; avoid implicit downmix.
    for sid in ['s0013','s0039','s0048']:
        for rep in ['foa','stereo','binaural']:
            a,_=sf.read(out/f'audio/{rep}/{sid}.wav',always_2d=True)
            for sr,bits in [(44100,'PCM_24'),(16000,'PCM_16')]:
                gcd=math.gcd(SR,sr); y=resample_poly(a,sr//gcd,SR//gcd,axis=0)
                write_audio(out,f'audio/compatibility/{sr}_{bits}/{rep}/{sid}.wav',y,records,'compatibility',sid,
                            sample_rate=sr,subtype=bits,source_path=f'audio/{rep}/{sid}.wav')
    for rep,parts in audition.items():
        write_audio(out,f'quick_listen/{rep}_tour.wav',np.concatenate(parts),records,'audition',
                    description='按时间表拼接；增益与各自原文件一致')
    dump(out/'quick_listen/timeline.json',audition_marks)
    dump(out/'metadata/scenes.json',scenes)
    (out/'metadata/references_100ms.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in refs))
    inputs=[dict(id=f'{s["id"]}_{rep}',audio_path=path,sample_rate_hz=SR,
                 channels=4 if rep=='foa' else 2) for s in scenes for rep,path in s['paths'].items()
            if rep in ['foa','stereo','binaural']]
    (out/'model_inputs.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in inputs))
    dump(out/'manifest.json',dict(version='1.0.0',seed=SEED,master_gain=MASTER,
        sample_rate_hz=SR,files=records,environment=dict(python=platform.python_version(),numpy=np.__version__,
        scipy=scipy.__version__,soundfile=sf.__version__,libsndfile=sf.__libsndfile_version__),
        generation_status='executed',hrtf_sha256=sha(archive)))
    for rep in ['foa','stereo','binaural']:
        (out/f'{rep}.m3u').write_text('#EXTM3U\n'+''.join(f'{s["paths"][rep]}\n' for s in scenes if rep in s['paths']))
    catalog=['# 信号目录\n','生成文件已执行；数值检查结果见 `validation/report.md`。\n',
             '|编号|测试内容|类别|时长（秒，含尾部）|格式|','|---|---|---|---:|---|']
    for s in scenes:
        links=' / '.join(f'[{r}]({p})' for r,p in s['paths'].items())
        catalog.append(f'|{s["id"]}|{s["name"]}|{s["family"]}|{s["duration_s"]+TAIL:.1f}|{links}|')
    catalog.extend(['\n## 格式和数值对照\n','|文件|用途|','|---|---|'])
    for r in records:
        if r['category'] in ['diagnostic','stress']:
            catalog.append(f'|[{Path(r["path"]).stem}]({r["path"]})|{r["description"]}|')
    (out/'CATALOG.md').write_text('\n'.join(catalog)+'\n')
    print(f'Generated {len(scenes)} scenes, {len(records)} WAV files in {out}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT)
    p.add_argument('--seed',type=int,default=SEED,help='Master seed; use a new output directory for every run')
    args=p.parse_args()
    SEED=args.seed
    generate(args.output)
