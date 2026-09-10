from pathlib import Path
import hashlib
import json
import shutil
from collections import Counter

import argparse
parser=argparse.ArgumentParser(description='将测试包中的音频复制为中文文件名；保留 WAV 样本。')
parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
ROOT=args.root.resolve()
DEST=args.output.resolve()
scenes=json.loads((ROOT/'metadata/scenes.json').read_text())
by_id={s['id']:s for s in scenes}
manifest=json.loads((ROOT/'manifest.json').read_text())

def number(x,signed=False):
    x=float(x)
    return f'{x:+g}' if signed and x!=0 else f'{x:g}'

def position(az,el):
    az=(az+180)%360-180
    if el==90:return '正上方_仰角+90度'
    if el==-90:return '正下方_仰角-90度'
    if az==-180:az=180
    if az==0:label='正前方'
    elif az==180:label='正后方'
    elif az==90:label='正左方'
    elif az==-90:label='正右方'
    elif 0<az<90:label='左前方'
    elif 90<az<180:label='左后方'
    elif -90<az<0:label='右前方'
    else:label='右后方'
    return f'{label}_方位{number(az,True)}度_仰角{number(el,True)}度'

def describe(scene):
    sid=scene['id']; f=scene['family']; ss=scene['sources']
    special={
      's0048':'粉红噪声_水平逆时针绕头一周_方位0至+360度',
      's0049':'粉红噪声_水平顺时针绕头一周_方位0至-360度',
      's0050':'粉红噪声_右侧经过前方到左侧_方位-90至+90度',
      's0051':'粉红噪声_前方由低到高_仰角-30至+80度',
      's0052':'粉红噪声_经过正后方_方位+150至+210度',
      's0053':'模拟头向左转_固定声源相对方位0至-90度',
      's0054':'两个独立粉红噪声_左方+70度与右方-70度',
      's0055':'双声源交叉_220Hz由右向左_370Hz由左向右_两端80度',
      's0056':'三声源_右70度低频_前上30度中频_左80度高频',
      's0063':'左右两声源交替出现_右-60度与左+60度',
      's0064':'两个同波形声源相加_均在左前方+30度',
      's0065':'左右相反方向同相信号_方位+90与-90度',
      's0066':'左右相反方向反相信号_方位+90与-90度',
      's0067':'近似弥散场_12个方向独立粉红噪声',
      's0078':'正左方+90度_单采样脉冲_时刻0.5、1、1.75、2.5秒',
      's0079':'右前方-45度_谐波声1秒开始2秒结束',
      's0080':'数字静音_所有采样均为零',
    }
    if sid in special:return special[sid]
    if f=='separation':
        sep=ss[1]['azimuth_deg']-ss[0]['azimuth_deg']
        return f'双声源夹角{number(sep)}度_右{number(sep/2)}度与左{number(sep/2)}度'
    if f=='interference':
        return f'目标左前35度_干扰右前65度_目标比干扰{number(scene["requested_source_sir_db"],True)}dB'
    if f=='reflections':
        return f'直达声左前20度_加三路离散反射_分量能量比{number(scene["direct_to_sum_reflection_component_energy_db"])}dB'
    if f=='level':
        return f'左前方+45度_同一粉红噪声_相对电平{number(scene["relative_level_db"],True)}dB'
    if f=='amplitude_distance_proxy':
        d=scene['relative_distance_parameter']
        return f'左前方+30度_仅模拟距离幅度变化_幅度为基准的1除以{number(d)}'
    s=ss[0]
    kind={'pink':'粉红噪声','white':'带限白噪声','tone':f'{number(s.get("frequency_hz",1000))}Hz纯音',
          'harmonic':'谐波与幅度调制声','sweep':'40Hz至18000Hz对数扫频'}[s['kind']]
    desc=kind+'_'+position(s['azimuth_deg'],s['elevation_deg'])
    return ('格式对照原信号_'+desc) if f=='format_reference' else desc

diagnostic_names={
 'valid_acn_n3d':'FOA_N3D归一化_WYZX_左前30度上20度',
 'valid_fuma':'FOA_FuMa格式_WXYZ_左前30度上20度',
 'fault_swap_x_y':'FOA_故意交换X与Y_原方向左前30度上20度',
 'mirror_left_right':'FOA_左右镜像_右前方30度上20度',
 'fault_z_polarity':'FOA_Z声道反相_左前方30度下20度',
 'fault_w_gain_minus3db':'FOA_故意将W衰减3.01dB_原方向左前30度上20度',
 'fault_drop_y':'FOA_故意丢失Y声道_原方向左前30度上20度',
 'fault_whole_polarity':'FOA_全部声道反相_左前方30度上20度',
 'yaw_plus90':'FOA_声场向左旋转90度_左后方120度上20度',
 'fault_y_delay_16samples':'FOA_故意将Y延迟16采样_原方向左前30度上20度',
 'channel_order_W_Y_Z_X':'FOA_声道依次发声_W然后Y然后Z然后X',
 'left_only':'立体声_只有左声道_1000Hz纯音',
 'right_only':'立体声_只有右声道_1000Hz纯音',
 'in_phase':'立体声_左右同相_1000Hz纯音',
 'anti_phase':'立体声_左右反相_合为单声道时抵消',
 'uncorrelated':'立体声_左右互不相关的带限噪声',
 'near_full_scale_minus1db':'立体声_接近满幅_峰值-1dBFS_1000Hz纯音',
 'dc_offset':'立体声_直流偏置+0.01_数值检查用',
}
folders={'foa':'01_FOA四声道_WYZX_SN3D','stereo':'02_立体声','binaural':'03_双耳_HRTF'}
reps={'foa':'FOA','stereo':'立体声','binaural':'双耳'}
planned=[]
for f in manifest['files']:
    cat=f['category']; p=Path(f['path'])
    if cat=='stem':continue
    sr=f['sample_rate_hz']; bit=16 if f['subtype']=='PCM_16' else 24
    fmt=f'{sr//1000 if sr%1000==0 else sr/1000:g}kHz_{bit}位'
    if cat in folders:
        s=by_id[f['scene_id']]
        name=f'{int(s["id"][1:]):03d}_{reps[cat]}_{describe(s)}_{fmt}.wav'
        sub=folders[cat]
    elif cat=='foa_decoded_binaural':
        s=by_id[f['scene_id']]
        name=f'{int(s["id"][1:]):03d}_FOA解码为双耳_{describe(s)}_{fmt}.wav'
        sub='06_FOA解码为双耳'
    elif cat=='compatibility':
        s=by_id[f['scene_id']];rep=p.parts[-2]
        name=f'{int(s["id"][1:]):03d}_{reps[rep]}_{describe(s)}_{fmt}.wav'
        sub='05_采样率与位深对照'
    elif cat in ['diagnostic','stress']:
        stem=p.stem
        if 'itd_r_minus_l_samples' in f:
            lag=f['itd_r_minus_l_samples'];ear='左耳' if lag>0 else '右耳'
            desc=f'双耳_仅有时间差_{ear}提前{number(abs(lag)/sr*1e6)}微秒'
        elif 'ild_l_minus_r_db' in f:
            ild=f['ild_l_minus_r_db'];ear='左耳' if ild>0 else '右耳'
            desc=f'双耳_仅有电平差_{ear}更响{abs(ild)}dB'
        else:desc=diagnostic_names[stem]
        name=f'{desc}_{fmt}.wav'
        sub='08_满幅与直流数值检查' if cat=='stress' else '04_声道与格式对照'
    elif cat=='audition':
        rep='binaural' if 'binaural' in p.name else 'stereo'
        name=f'{reps[rep]}_43秒综合试听_后右前左上及绕头运动_{fmt}.wav'
        sub='07_快速试听'
    else:raise ValueError(cat)
    assert len(name.encode('utf-8'))<=255,(len(name.encode('utf-8')),name)
    planned.append((f,Path(sub)/name))
assert len({str(p) for _,p in planned})==len(planned)
if DEST.exists():raise SystemExit('Destination already exists; refusing to overwrite: '+str(DEST))
DEST.mkdir()
records=[]
for f,rel in planned:
    dst=DEST/rel;dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/f['path'],dst)
    digest=hashlib.sha256(dst.read_bytes()).hexdigest()
    assert digest==f['sha256'],str(dst)
    records.append(dict(original=f['path'],desktop_path=str(dst),sha256=digest))

print(json.dumps(dict(destination=str(DEST),wav_count=len(records),bytes=sum((DEST/p).stat().st_size for _,p in planned),
    groups=dict(Counter(str(p.parent) for _,p in planned)),maximum_filename_bytes=max(len(p.name.encode('utf-8')) for _,p in planned),
    examples=[str(p) for _,p in planned if '045' in str(p) or '左前方_方位+45' in str(p)][:8]),ensure_ascii=False,indent=2))
