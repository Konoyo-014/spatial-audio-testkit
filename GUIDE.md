> 本文说明下载后的完整测试包。文中 WAV 路径需先从 Release 下载并解压。

# 空间音频模型与算法测试包

这套信号用于反复检查音频读取、空间编码、方向估计、运动跟踪和多声源处理。相同场景的 FOA、立体声和双耳文件来自相同的单声道源，时间轴保持一致。源文件、方向轨迹、生成脚本和评分脚本都保存在包内。

当前包含 **80 个场景、403 个 WAV，音频文件约 520.7 MB**。主要文件为 48 kHz、24-bit PCM；另有 44.1 kHz/24-bit 和 16 kHz/16-bit 的格式兼容性子集。这次交付的文件已通过数值检查；具体证据见 [检查报告](validation/report.md) 和 [完整数值](validation/report.json)。重新生成的目录要再运行 verify.py，才能确认新文件的检查状态。

先从 [信号目录](CATALOG.md) 选文件。想快速听一遍，可以打开 双耳试听（完整包内 `quick_listen/binaural_tour.wav`） 或 立体声试听（完整包内 `quick_listen/stereo_tour.wav`），两段都是 42.8 秒，内容顺序一致。双耳文件适合耳机；FOA 四声道文件需要显式配置的解码器，普通播放器的自动混音不能用于判断 FOA 方向。接近满幅和 DC 测试单独放在 `audio/diagnostics/stress/`，未加入试听。

## 每次怎么用

更换模型、音频读取库或预处理代码后，先用 `audio/diagnostics/` 检查声道和电平，再用静止与运动场景看方向是否正确。通过这些检查后，再比较多声源、干扰和反射条件下的结果。`model_inputs.jsonl` 只列输入文件、采样率和声道数；方向、声源数量和时间标签单独放在 `metadata/`。编号和路径只用于匹配输出，不应当作为语言模型的提示内容。

在本机打开终端，进入本文件所在文件夹后，可以运行：

```sh
/usr/bin/python3 scripts/verify.py
```

也可以双击 [重新检查.command](重新检查.command)。这个操作只重新读取并检查文件，更新检查报告，不会开始播放。脚本在当前 Mac 已用 `/usr/bin/python3` 跑通；依赖版本见 [requirements.txt](requirements.txt)，环境记录也写入了 `manifest.json`。

下面的示例会运行一个简单的 FOA 方向估计器，然后检查前方静止、斜上方静止、逆时针运动和静音四个场景：

```sh
/usr/bin/python3 scripts/baseline_foa.py --output examples/foa_baseline_predictions.jsonl
/usr/bin/python3 scripts/evaluate.py examples/foa_baseline_predictions.jsonl \
  --scene-ids s0013,s0039,s0048,s0080 \
  --output validation/foa_baseline_score.json
```

这是读取、估计和评分流程的示例。它没有源分离能力，不代表神经网络或多声源算法的性能。它在这四个场景中的实际结果保存在 [foa_baseline_score.json](validation/foa_baseline_score.json)。

## 测什么、应该观察什么

|内容|文件或场景|用途与预期结果|
|---|---|---|
|水平静止方向|s0001–s0024，每隔 15° 一个方向|检查左右、前后、角度单位和环绕边界；相同粉红噪声使频谱不暴露方向|
|仰角与上下方向|s0025–s0038|检查 Z 声道及仰角；正下方 s0038 只有 FOA|
|格式共同原信号|s0039，方位 +30°、仰角 +20°|三个方向分量均不相同，能发现 X/Y/Z 交换|
|窄带声源|s0040–s0044，125/500/1000/4000/8000 Hz|观察方向估计对频带的依赖；纯音不适合无歧义的宽范围时差估计|
|频谱与信号类型|s0045–s0047|40 Hz–18 kHz 对数扫频、带限白噪声、谐波与幅度调制|
|运动|s0048–s0053|顺/逆时针一周、左右经过前方、仰角变化、跨 ±180°、固定声源相对转头的变化|
|多声源与接近声源|s0054–s0059|左右双源、双源交叉、三频带三源，以及 10°/30°/60° 双源间隔|
|干扰强度|s0060–s0062|源信号 SIR 为 −10/0/+10 dB；目标为 a01，干扰为 a02，实际源能量比见检查报告|
|活动时间|s0063、s0079|声源交替、延迟出现和停止，用于活动检测及响应时间检查|
|相干声源|s0064–s0066|同向相加、相反方向同相、相反方向反相；这些输入不适合按独立声源数量评分|
|近似弥散声场|s0067|12 个方向的独立噪声，检查算法是否错误地强行输出一个明确方向|
|离散反射|s0068–s0070|直达声与三个反射分量；分量能量比为 0/6/12 dB，反射延迟为 17/31/53 ms|
|电平变化|s0071–s0074|同一波形依次衰减 0/20/40/60 dB；检查增益不变性、静音阈值及低电平稳定性|
|距离幅度对照|s0075–s0077|只改变 1/r 幅度；用于发现模型是否完全依赖电平推断距离|
|精确时刻脉冲|s0078|源脉冲位于 0.5/1.0/1.75/2.5 秒；用于检查延迟和时间对齐|
|静音|s0080|三种格式均为精确数字零；方向输出应为空|
|声道与格式对照|audio/diagnostics/foa/|W/Y/Z/X 轮流激活、合法 N3D/FuMa、X/Y 交换、左右镜像、Z 反号、Y 丢失、仅 W 增益错误、Y 延迟、全声道反相、+90° 偏航旋转|
|立体声基础关系|audio/diagnostics/stereo/|左独奏、右独奏、同相、反相、互不相关；反相文件在 L/R 平均后应抵消|
|独立双耳线索|audio/diagnostics/binaural/|只有 ITD 的 ±250/±500 μs，以及只有 ILD 的 ±6/±12 dB 对照|
|采样率和位深|audio/compatibility/|三种格式分别经过带抗混叠滤波的共同重采样；16 kHz 版本只保留其 Nyquist 范围内的信息|
|FOA 解码损失|audio/foa_decoded_binaural/|六个场景先经过 FOA，再用一阶 HRIR 拟合解码；与直接双耳渲染分别比较|

不同声源的单声道信号位于 `audio/stems/`。独立噪声、谐波基频和频带可以作为分离实验中的源身份依据，但这些合成声音没有语音内容、自然环境类别或文本语义。

## 三种表示的精确定义

坐标采用右手系：X 指向前方，Y 指向左方，Z 指向上方。方位角 α 从前方开始，朝左为正；仰角 ε 朝上为正。这里的角度表示**听者指向声源的方向**。从上方向下看，方位角增加表示逆时针转动。

对一个单声道源 `s(t)`，FOA 使用 ACN 排序和 SN3D 归一化：

```text
声道 0：W = s
声道 1：Y = s × cos(ε) × sin(α)
声道 2：Z = s × sin(ε)
声道 3：X = s × cos(ε) × cos(α)
```

多声源按声道直接相加。W 的系数是 1，不是 1/√2。转换为 ACN/N3D 时，仅将 Y/Z/X 乘 √3。转换为一阶 FuMa 时，排列改为 W/X/Y/Z，并将 W 除以 √2。对应文件保存了正确的转换结果；把它们直接当作 SN3D/WYZX 输入就是一个格式错误。

这些文件是保存 FOA 样本的普通四声道 PCM WAV，**WAV 头没有自动声明 Ambisonics 的顺序和归一化**。模型读取器必须使用这里的约定及清单信息，不能把四声道自动理解为四个扬声器通道。

立体声使用等功率幅度声像。令 `p = cos(ε) sin(α)`，则 `L = s√((1+p)/2)`，`R = s√((1−p)/2)`。它表示常见的左右幅度分配，并非一对真实麦克风的录音。左右分量相同的方向会得到相同立体声，例如前后方向不能单凭这套声像规则区分。评估前后或仰角时，应当把这种信息缺失与模型失误分开解释。

双耳文件使用 [MIT KEMAR compact 数据](https://sound.media.mit.edu/resources/KEMAR.html)。原始数据为 44.1 kHz、每耳 128 点，经扬声器响应补偿，并从小耳廓测量构造对称双耳。它保留耳间时差，但原测量已经截短，因此不能用其绝对延迟还原 1.4 米的传播时间。原文件的方位角向右为正；本包已转换为向左为正，并检查了左右耳的到达时间和能量关系。

本包重建了 710 个测量方向，将脉冲响应重采样至 48 kHz、140 点，并乘 `44100/48000` 保持卷积增益。静止声源选择球面角距离最近的测量方向；运动声源每 20 ms 选择一次，并对相邻时刻的滤波器权重做线性交叉淡化。权重先乘源样本，再与滤波器卷积。每个控制时刻所选的方向、索引和角度误差都在 `metadata/scenes.json`，本包最大的控制时刻误差为约 4.99°。交叉淡化期间的滤波器是两个测量滤波器的混合，不应被描述成一个新方向的实测 HRTF。

`audio/foa_decoded_binaural/` 使用同一批 HRTF 的一阶球谐最小二乘拟合，按测量方向代表的球面面积加权。拟合范围为现有测量所覆盖的方向，未填补缺失的下半球区域。它用来显示一阶表示及解码带来的变化，不是直接双耳文件的无损转换。

## 电平、时间与标签

生成器对普通源波形先设定活动区间内、淡入淡出前的 RMS 为 0.1，再施加所有场景共用的 0.35 增益、指定的源增益和 20 ms 淡入淡出。脉冲与专用诊断信号另有明确幅度。三种表示之间没有逐文件、逐耳或逐声道归一化，因此方向相关的双耳能量差、SIR 和相对电平都能保留。

同一场景的文件长度完全一致，末尾统一增加 100 ms 静音，容纳 HRTF 卷积尾部。源文件先保存为 PCM，再读取进行场景渲染。全部 PCM 写入不加抖动；位深对照因此能复现量化差异。这里检查的是采样峰值及数值溢出，没有把它当作响度匹配或硬件声压测量。

`metadata/scenes.json` 保存每个源的类型、随机种子、增益、开始和结束时刻、单声道路径及方向轨迹。轨迹节点为 `[秒, 方位角度, 仰角度]`，节点之间对未折返的角度做线性插值。比如一周用 `0→360`，跨越后方用 `150→210`；不要先将节点折到 ±180° 再插值。节点之外保持端点方向。

`metadata/references_100ms.jsonl` 每 100 ms 提供一次活动声源及其名义方向。普通源的活动区间为 `[start,end)`；点击声源按该时间点开始的 100 ms 时间段是否含脉冲标注。标签使用输入源的时间，不补偿 HRTF 方向相关延迟，也不包含最后的卷积尾部。测试自己的算法时，应明确处理窗口位置、输出时间戳和算法延迟。

反射分量标记为 `role="reflection"`，并保留各自的单声道文件；方向评分仅对原声源评分。反射条件中的 dB 值定义为直达声能量与各反射分量能量之和的比值，不是相干反射先相加后的实际波形能量比，也不是房间测量得到的 DRR。

## 接入自己的模型

保持多声道形状为 `[采样点, 声道]`，需要 `[声道, 采样点]` 的模型再显式转置。重采样必须对全部声道使用相同滤波器和时序。FOA 模型可以只取 W 检查普通音频内容，但不能用 W 单声道结果评估其空间输入是否正确。

评分输入每行对应一个场景的一个时间点，例如：

```json
{"scene_id":"s0039","time_s":0.5,"sources":[{"azimuth_deg":30.0,"elevation_deg":20.0}]}
{"scene_id":"s0080","time_s":0.5,"sources":[]}
```

模型每个格式的结果应分别保存和评分。同一时间点可以输出多个声源，评分器用球面角距离做无序匹配，默认阈值为 20°。它报告方向误差、漏检、误检、precision、recall 和 F1；超阈值的匹配同时计为一次漏检和一次误检。这是本包的检测与方向评分定义，不是标准 SELD 分数，也不检查源身份连续性。跟踪 ID 交换、分离 SI-SDR、延迟补偿和语义准确率需要根据具体模型另做评价。

```sh
/usr/bin/python3 scripts/evaluate.py predictions.jsonl \
  --scene-ids s0013,s0039,s0048,s0080 \
  --threshold-deg 20 --output results/my_model.json
```

必须明确输出所有被评时间点，未检出时写 `sources: []`。评分器会拒绝缺帧、重复时间点和无效方向。省略 `--scene-ids` 时，它要求所有可评分场景的全部时间点。相干源、弥散场和距离幅度对照不参与这个默认方向评分；静音参与误检统计。所有格式使用同一套名义方向标签，因此双耳结果含有有限 HRTF 网格和交叉淡化带来的差异；立体声则缺少部分方向信息。

角度误差只统计匹配项，必须与漏检、误检和 F1 一起看。不要在同一份合成材料上训练后再把测试结果当作泛化能力；同一个源种子、波形、场景或其格式变体应当放在同一数据划分里。旋转、镜像或交换左右耳后，应同时变换标签；故障注入文件应与正确文件分组报告。

## 重建或加入自己的素材

重新生成必须指定一个新目录，脚本不会覆盖已有的完整测试包。默认种子是 20260910：

```sh
/usr/bin/python3 scripts/generate.py --output ../spatial_audio_testkit_copy
/usr/bin/python3 scripts/verify.py --root ../spatial_audio_testkit_copy
```

使用 `--seed 20260911` 可以生成不同噪声波形而保持场景设计一致。同环境、同种子整套重建的 WAV 哈希比较结果保存在 [reproducibility.json](validation/reproducibility.json)。NumPy、SciPy 或 libsndfile 版本变化后，不能只凭种子声称字节相同；应当重新检查。

本次已验证 403 个音频的重复生成结果逐文件一致。[评分器检查](validation/evaluator_tests.json) 另外验证了缺帧和重复帧拒绝、声源顺序不影响匹配、空预测受到漏检惩罚以及错误方向受到惩罚。这些检查验证程序行为，不代表学习模型的表现。

下面的命令把你指定的单声道素材转换为同一方向的三种表示。它保留输入幅度，只在需要时对全部输出施加共同衰减，将峰值压到 −6 dBFS 以内；实际增益写入输出元数据。

```sh
/usr/bin/python3 scripts/render_mono.py /absolute/path/source.wav \
  --azimuth 30 --elevation 20 --output ../my_spatial_scene
```

运动素材可用 `--trajectory path/to/trajectory.json`。例如一段至少 8 秒的素材使用 `[[0,0,0],[8,360,0]]` 绕头一周。渲染器会拒绝非单声道输入及超出 KEMAR 仰角覆盖范围的方向，以免隐含混音或替换方向。`render_mono.py` 产生的自定义场景带有自己的元数据；它不会自动加入本包的 100 ms 评分标签，需要按实际任务建立对应参考。

## 这套材料能支持的结论

这里的 FOA 是理想远场平面波的一阶编码；立体声是幅度声像；双耳是单一 KEMAR 数据集的渲染。它们适合确定算法在已知输入下是否保持方向和信号关系。双耳泛化到不同耳廓、实际录音设备、真实房间、自然语音和环境事件的能力，需要另外使用实录数据或更多 HRTF 验证。

离散反射是人工指定的到达路径，不对应具体房间，也不含晚期混响。12 方向噪声只是近似弥散场。距离对照只改变幅度，未加入传播时间、空气吸收、近场球谐或随距离变化的 HRTF。运动渲染没有多普勒效应。保留这些明确条件，才能知道一个分数具体测到了什么。

## 来源与文件

MIT KEMAR 的来源、使用条件与技术说明保存在 `resources/`。原作者允许研究和商业使用，条件是引用 Bill Gardner 与 Keith Martin；双耳衍生信号同样应保留这一说明，详见 [LICENSE.txt](LICENSE.txt)。

|位置|内容|
|---|---|
|[CATALOG.md](CATALOG.md)|逐个场景的用途及音频链接|
|[manifest.json](manifest.json)|每个 WAV 的采样率、声道、位深、峰值、RMS 和 SHA-256|
|[metadata/scenes.json](metadata/scenes.json)|完整声源、轨迹和 HRTF 控制信息|
|[metadata/scene_specs.json](metadata/scene_specs.json)|本次生成所用场景参数快照；生成规则在脚本的 specifications() 中|
|[metadata/references_100ms.jsonl](metadata/references_100ms.jsonl)|活动与方向参考|
|[model_inputs.jsonl](model_inputs.jsonl)|不含方向标签的输入清单|
|[quick_listen/timeline.json](quick_listen/timeline.json)|试听拼接的时间表|
|[scripts/generate.py](scripts/generate.py)|波形生成、三种表示和格式对照|
|[scripts/verify.py](scripts/verify.py)|保存文件的数值检查|
|[scripts/evaluate.py](scripts/evaluate.py)|检测与方向评分|
|[scripts/baseline_foa.py](scripts/baseline_foa.py)|简单的单源 FOA 方向估计示例|
|[scripts/render_mono.py](scripts/render_mono.py)|渲染指定的单声道素材|

MIT 官方入口：[KEMAR measurements](https://sound.media.mit.edu/resources/KEMAR.html)、[技术说明](https://sound.media.mit.edu/resources/KEMAR/hrtfdoc.txt)、[FAQ](https://sound.media.mit.edu/resources/KEMAR/KEMAR-FAQ.txt)。数据和网页下载于 2026-09-10，原始 ZIP 的 SHA-256 保存在 manifest 中。
