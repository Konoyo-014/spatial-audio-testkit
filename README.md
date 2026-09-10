# 空间音频测试 WAV：FOA、立体声与双耳

这套信号用于检查空间音频模型和算法的方向、运动、多声源、相位、电平、声道顺序和格式转换。每个场景的三种表示来自相同的单声道源，并保存方向与时间标签。

**直接拿 WAV 使用：**下载 [中文命名 WAV 包](https://github.com/Konoyo-014/spatial-audio-testkit/releases/download/v1.0.0/spatial-audio-testkit-v1.0.0-chinese-wav.zip)。包含 290 个 WAV，文件名写清方向、角度和测试内容，按 FOA、立体声、双耳等分组。例如：

```text
016_FOA_粉红噪声_左前方_方位+45度_仰角0度_48kHz_24位.wav
048_双耳_粉红噪声_水平逆时针绕头一周_方位0至+360度_48kHz_24位.wav
```

**需要源文件、标签和脚本：**下载 [完整测试包](https://github.com/Konoyo-014/spatial-audio-testkit/releases/download/v1.0.0/spatial-audio-testkit-v1.0.0-full.zip)。包含 80 个场景、403 个 WAV，音频约 520.7 MB，以及生成、中文命名、检查、评分和自定义素材渲染脚本。

所有下载文件见 [Release](https://github.com/Konoyo-014/spatial-audio-testkit/releases/tag/v1.0.0)。仓库保留代码、元数据和检查结果；WAV 放在 Release 附件中。GitHub 自动生成的 Source code 压缩包不含 WAV。

## 信号内容

|内容|范围|
|---|---|
|静止方向|水平每隔 15°；多种仰角；正上、正下方|
|运动|顺时针、逆时针、左右移动、上下移动、跨越后方和相对转头|
|多声源|双源、三源、交叉运动、10°/30°/60° 夹角、不同干扰强度|
|信号类型|粉红噪声、带限白噪声、纯音、扫频、谐波、脉冲和静音|
|处理检查|声道交换、镜像、相位、N3D/FuMa、采样率、位深、电平和延迟|
|声场对照|离散反射、有限方向的近似弥散场、仅幅度变化的距离对照|

大部分音频为 48 kHz、24-bit PCM，另有 44.1 kHz/24-bit 和 16 kHz/16-bit 子集。FOA 为 ACN/SN3D，顺序 **W、Y、Z、X**。坐标是前方 0°、左方 +90°、上方为正仰角。WAV 头不声明这些 FOA 约定，读取时必须显式设置。

双耳文件由 MIT KEMAR compact 实测 HRTF 渲染，保留来源说明。该 HRTF 不覆盖正下方，因此正下方场景只提供 FOA。立体声使用等功率幅度声像，不能表达全部前后及上下方向。

## 使用

下载完整包并解压后，在 `spatial_audio_testkit` 文件夹内运行：

```sh
python3 scripts/verify.py
python3 scripts/export_chinese_wavs.py --output ../中文命名WAV
python3 scripts/baseline_foa.py --output examples/foa_baseline_predictions.jsonl
python3 scripts/evaluate.py examples/foa_baseline_predictions.jsonl \
  --scene-ids s0013,s0039,s0048,s0080 --output validation/foa_baseline_score.json
```

依赖版本在 [requirements.txt](requirements.txt)。要在克隆的代码仓库中生成 WAV，运行 `python3 scripts/generate.py --output ../generated_testkit`。固定种子为 20260910；可用 `--seed` 改变随机波形。详细定义见 [使用说明](GUIDE.md)，音频编号见 [场景目录](CATALOG.md)，中文文件名见 [中文文件目录](中文文件目录.md)。

## 已完成的检查

[数值报告](validation/report.json) 包含 25 项检查；[重复生成结果](validation/reproducibility.json) 记录 403 个 WAV 的 SHA-256 全部一致；[评分器检查](validation/evaluator_tests.json) 检查缺帧、重复帧、无序匹配和错误方向惩罚。这里验证的是信号和程序行为，并未测量任何具体学习模型的性能。

这些信号是可控的合成测试材料。离散反射不对应真实房间，也不含晚期混响；距离对照仅改变幅度；运动不含多普勒。真实录音、不同耳廓及语义泛化需要另用相应数据评估。

## 来源与使用条件

代码和合成源信号采用 MIT License。KEMAR 数据及双耳衍生信号须保留 Bill Gardner 和 Keith Martin 的引用，详见 [LICENSE.txt](LICENSE.txt) 与 [原始数据说明](resources/KEMAR-README.txt)。原始资料来自 [MIT Media Lab](https://sound.media.mit.edu/resources/KEMAR.html)。
