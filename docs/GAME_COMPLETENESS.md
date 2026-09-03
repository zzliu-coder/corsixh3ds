# 游戏内容完整性

一句话：**移植层没有裁剪任何游戏内容。**所有关卡、房间、疾病、物件、研究、财务、
存档都是 CorsixTH 0.70.1 上游的 Lua 代码，`tools/integrate_corsixth.py` 只往里注入
平台层，一行游戏逻辑都没改。

「先把第一关跑起来」是**移植的验收步骤**，不是功能范围。第一关能跑，说明地图加载、
房间建造、员工雇佣、病人流程、存档这条主链路全通了；后面 11 关走的是同一套代码。

## 完整的部分

| 内容 | 来源 | 状态 |
|---|---|---|
| 原版 12 关战役 | 用户自己的 Theme Hospital 数据 `LEVELS/Level.L1..L12` | 完整 |
| 关卡间过关/失败判定、下一关衔接 | `Lua/world.lua`，按 `level_number` 推进 | 完整 |
| 23 种房间 | `Lua/rooms/` | 完整 |
| 34 种疾病与诊断 | `Lua/diseases/`、`Lua/diagnosis/` | 完整 |
| 43 类物件（含机器、门） | `Lua/objects/` | 完整 |
| 员工、招聘、培训、加薪 | 上游 | 完整 |
| 研究、药品手册、政策、财务、银行、城镇地图、报表 | 上游全屏对话框 | 完整 |
| 自定义关卡与战役 | `Levels/`、`Campaigns/`（随 SD 包分发） | 完整 |
| 存档与读档 | 上游 + 3DS 原子提交（临时文件 → fsync → 备份轮换 → 替换） | 完整 |
| 音效（招聘、病人、建造、播报） | `SOUND/` 原始采样 | 完整 |

## 缺的部分，以及为什么

### 过场动画

`WITH_MOVIES=OFF`。原版动画是 Smacker 格式，CorsixTH 用 FFmpeg 解码。3DS 上没有可
用的 FFmpeg，且 268 MHz 也放不动。开场、过关、失败动画都不会播，游戏直接进入下一
个界面。**不影响任何玩法。**

### 音乐

`WITH_MIDI_DEVICE=OFF` + SDL_mixer 的 `SDL2MIXER_MIDI=OFF`。原版音乐是 XMI（MIDI
的一种打包格式），播放需要软件合成器和音色库。3DS 上没有硬件音源，软件合成会直接
和游戏抢那 268 MHz。

0.6.0 起 3DS 配置显式写 `play_music = false`。这不只是省 CPU：若不关，CorsixTH 会
对每一条曲目**各起一个加载线程**去试，全部失败，白白拖慢启动。

想要音乐有两条路，都没做：

- SDL_mixer 已经编进了 stb_vorbis，把 OGG 丢进音乐目录并把 `play_music` 改回 true
  就能放。代价是 OGG 解码在 268 MHz 上大约吃 15–30% CPU。
- 开 timidity 软件 MIDI + 在 SD 卡放 GUS 音色库，能放原版曲子，但是三种里最贵的。

### 中文界面

`FETCH_UNICODE_FONT=OFF`、`WITH_FONT=""`。中文需要 Unicode 字体加 FreeType 渲染，
字体本身和字形缓存都占内存，而 Old 3DS 的应用内存本来就是这个移植最紧张的资源。
首轮验收用英文，等真机确认内存水位之后再决定。

游戏内的语言字符串（`Lua/languages/`）是完整的，只差字体。

## 需要用户自备的数据

CorsixTH 不含 Theme Hospital 的美术、音效和关卡数据，本移植也不分发。SD 卡包由
`scripts/package_sd.sh --theme-hospital <路径>` 从用户自己的正版 PC 版数据生成，
`tools/th3ds_pack.py` 会校验目录结构。

需要的目录：`DATA`、`LEVELS`、`QDATA`、`SOUND`、`ANIMS`。
